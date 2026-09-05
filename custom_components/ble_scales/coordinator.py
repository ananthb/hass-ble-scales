"""Turns advertisements into per-person readings.

Passive throughout: this registers a Home Assistant Bluetooth callback and
never opens a connection. Not merely simpler -- a GATT connect would occupy one
of an ESPHome proxy's three connection slots, and a proxy that loses its slots
takes every other device on it offline.

State is held PER PERSON, not per scale. A single shared "weight" entity would
interleave everyone who steps on the scale into one history, which makes its
long-term statistics meaningless: the trend it draws is an artefact of who
weighed in most recently, not of anybody's actual weight. So a reading is only
ever recorded against the person it was assigned to, and a reading nobody can
be assigned is recorded against nobody.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .assign import Assignment, Person, assign_reading
from .body import BodyComposition, Profile, compute
from .const import ADVERTISEMENT_TIMEOUT_SECONDS, CLAIM_WINDOW_SECONDS
from .parser import PARSERS, SERVICE_FAMILIES, ScaleReading

_LOGGER = logging.getLogger(__name__)


def identify_family(service_uuids: list[str]) -> str | None:
    """Return the parser family for an advertisement, or None if unrecognised."""
    for uuid in service_uuids:
        family = SERVICE_FAMILIES.get(uuid.lower())
        if family is not None:
            return family
    return None


def parse_service_info(
    service_info: bluetooth.BluetoothServiceInfoBleak,
) -> ScaleReading | None:
    """Decode an advertisement, or None if it is not one of ours.

    Claiming on the service UUID alone is too loose -- other scales sit on
    FFB0 with entirely different frames -- so the manufacturer payload must
    also parse and pass its checksum before we believe it.
    """
    family = identify_family(list(service_info.service_uuids or []))
    if family is None:
        return None
    parser = PARSERS.get(family)
    if parser is None:
        return None

    for company_id, data in (service_info.manufacturer_data or {}).items():
        reading = parser(company_id, bytes(data))
        if reading is not None and not reading.is_empty:
            return reading
    return None


@dataclass
class PersonState:
    """One person's most recent measurement."""

    weight_kg: float | None = None
    impedance: int | None = None
    stable: bool = False
    body: BodyComposition | None = None
    #: Monotonic, for availability logic -- unaffected by clock changes.
    last_update: float = 0.0
    #: Wall clock, for display. Monotonic time is meaningless to a user and
    #: cannot be rendered as a timestamp.
    last_measured_at: datetime | None = None

    @property
    def has_reading(self) -> bool:
        return self.last_update > 0.0


@dataclass
class ScaleState:
    """Scale-level diagnostics. Deliberately holds no body measurements --
    every measured or derived value belongs to a person."""

    assignment_reason: str = "no reading yet"
    claimed_by: str | None = None
    last_seen: float = 0.0
    last_measurement_at: datetime | None = None
    rssi: int | None = None
    people: dict[str, PersonState] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        if self.last_seen == 0.0:
            return False
        return (time.monotonic() - self.last_seen) < ADVERTISEMENT_TIMEOUT_SECONDS


class ScaleCoordinator:
    """Owns the advertisement subscription and per-person state."""

    def __init__(self, hass: HomeAssistant, address: str, people: list[Person]) -> None:
        self.hass = hass
        self.address = address
        self.people = people
        self.state = ScaleState(people={p.name: PersonState() for p in people})
        self._listeners: list[callback] = []
        self._unsub: callback | None = None
        #: Weight and impedance arrive in SEPARATE advertisements, so the
        #: person a weight was assigned to is remembered until the matching
        #: impedance turns up. Without this, composition could never be
        #: computed: neither frame carries both numbers.
        self._pending_person: str | None = None
        #: Set by a person's "weighing in next" button: their name and the
        #: monotonic deadline after which it is ignored.
        self._claim: tuple[str, float] | None = None

    def person(self, name: str) -> Person | None:
        return next((p for p in self.people if p.name == name), None)

    def person_state(self, name: str) -> PersonState:
        return self.state.people.setdefault(name, PersonState())

    # -- explicit claims ---------------------------------------------------

    @callback
    def async_claim(self, person_name: str) -> None:
        """Record that `person_name` is about to weigh in.

        Replaces any existing claim rather than queueing: two people cannot
        both be next, and the most recent press reflects reality.
        """
        self._claim = (person_name, time.monotonic() + CLAIM_WINDOW_SECONDS)
        self.state.claimed_by = person_name
        self._notify()

    @property
    def active_claim(self) -> str | None:
        """The unexpired claim, if any. Expiry is evaluated on read, so no
        timer is needed and a stale claim can never fire late."""
        if self._claim is None:
            return None
        name, deadline = self._claim
        if time.monotonic() >= deadline:
            self._claim = None
            return None
        return name

    @callback
    def async_clear_claim(self) -> None:
        self._claim = None
        self.state.claimed_by = None

    # -- lifecycle ---------------------------------------------------------

    async def async_start(self) -> None:
        self._unsub = bluetooth.async_register_callback(
            self.hass,
            self._handle_advertisement,
            {"address": self.address, "connectable": False},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )

    @callback
    def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def async_add_listener(self, listener) -> callback:
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _is_home(self) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for person in self.people:
            if not person.person_entity:
                continue
            state = self.hass.states.get(person.person_entity)
            if state is not None:
                result[person.person_entity] = state.state == "home"
        return result

    @callback
    def _handle_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        reading = parse_service_info(service_info)
        if reading is None:
            return
        # RSSI comes from the advertisement rather than the payload, so it is
        # recorded here and not in apply_reading, which is transport-agnostic
        # and unit-tested without Home Assistant.
        self.state.rssi = service_info.rssi
        self.apply_reading(reading)
        self._notify()

    # -- the actual work ---------------------------------------------------

    def apply_reading(self, reading: ScaleReading) -> None:
        """Fold one decoded frame into the right person's state.

        Split out from the callback so it can be tested without a running
        Home Assistant.
        """
        now = time.monotonic()
        self.state.last_seen = now
        self.state.last_measurement_at = dt_util.utcnow()
        self.state.claimed_by = self.active_claim

        if reading.weight_kg is not None:
            claimed = self.active_claim
            assignment = assign_reading(
                reading.weight_kg, self.people, self._is_home(), claimed
            )
            self.state.assignment_reason = assignment.reason
            if assignment.person is None:
                # Nobody owns this reading, so nobody's history is touched.
                # Dropping it is the point: a wrong attribution corrupts two
                # people's histories at once and cannot be detected later.
                self._pending_person = None
                _LOGGER.debug("Reading unassigned: %s", assignment.reason)
            else:
                self._pending_person = assignment.person.name
                ps = self.person_state(assignment.person.name)
                ps.weight_kg = reading.weight_kg
                ps.stable = reading.stable
                ps.last_update = now
                ps.last_measured_at = self.state.last_measurement_at
                # A new weigh-in invalidates the previous impedance: it belongs
                # to the last measurement, not this one.
                ps.impedance = None
                self._recompute(assignment.person.name)
                # Consume the claim only once it has actually assigned a stable
                # reading, so it is not burnt by a 2 kg frame captured while
                # the scale is still settling underfoot.
                if claimed is not None and reading.stable:
                    self.async_clear_claim()

        if reading.impedance is not None and self._pending_person is not None:
            ps = self.person_state(self._pending_person)
            ps.impedance = reading.impedance
            ps.last_update = now
            ps.last_measured_at = self.state.last_measurement_at
            self._recompute(self._pending_person)

    def _recompute(self, name: str) -> None:
        """Derive composition for one person from what is currently known."""
        person = self.person(name)
        ps = self.person_state(name)
        if person is None or ps.weight_kg is None:
            ps.body = None
            return
        # No height/age/sex means this person was added the quick way. Weight,
        # assignment and history all still work; composition simply has no
        # inputs, so leave it empty rather than inventing a default body.
        if not person.can_derive_composition:
            ps.body = None
            return
        profile = Profile(
            height_cm=person.height_cm,
            age_years=person.age_years,
            sex=person.sex,
        )
        ps.body = compute(ps.weight_kg, ps.impedance, profile)
