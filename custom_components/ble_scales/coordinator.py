"""Turns advertisements into assigned, derived readings.

Passive throughout: this registers a Home Assistant Bluetooth callback and
never opens a connection. That is not just simplicity -- a GATT connect would
occupy one of an ESPHome proxy's three connection slots, and a proxy that
loses its slots (or its advertisement subscription) takes every other device
on it offline. Nothing here can do that.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

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
class ScaleState:
    """Everything the sensors render, and when it last changed."""

    weight_kg: float | None = None
    impedance: int | None = None
    stable: bool = False
    person_name: str | None = None
    assignment_reason: str = "no reading yet"
    claimed_by: str | None = None
    body: BodyComposition | None = None
    last_update: float = 0.0

    @property
    def available(self) -> bool:
        if self.last_update == 0.0:
            return False
        return (time.monotonic() - self.last_update) < ADVERTISEMENT_TIMEOUT_SECONDS


class ScaleCoordinator:
    """Owns the advertisement subscription and the current state."""

    def __init__(self, hass: HomeAssistant, address: str, people: list[Person]) -> None:
        self.hass = hass
        self.address = address
        self.people = people
        self.state = ScaleState()
        self._listeners: list[callback] = []
        self._unsub: callback | None = None
        #: Weight and impedance arrive in SEPARATE advertisements, so a weight
        #: is held here until its impedance turns up (or the next weigh-in
        #: replaces it). Without this, composition could never be computed:
        #: neither frame carries both numbers.
        self._pending_weight_kg: float | None = None
        #: Set by a person's "weighing in next" button. Holds their name and the
        #: monotonic deadline after which it is ignored.
        self._claim: tuple[str, float] | None = None

    # -- explicit claims ---------------------------------------------------

    @callback
    def async_claim(self, person_name: str) -> None:
        """Record that `person_name` is about to weigh in.

        Replaces any existing claim rather than queueing: two people cannot be
        next, and the most recent press is the one that reflects reality.
        """
        self._claim = (person_name, time.monotonic() + CLAIM_WINDOW_SECONDS)
        self._notify()

    @property
    def active_claim(self) -> str | None:
        """The unexpired claim, if any. Expiry is evaluated on read so no timer
        is needed and a stale claim can never fire late."""
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
        self.apply_reading(reading)
        self._notify()

    def apply_reading(self, reading: ScaleReading) -> None:
        """Fold one decoded frame into the current state.

        Split out from the callback so it can be tested without a running
        Home Assistant.
        """
        self.state.last_update = time.monotonic()
        self.state.stable = reading.stable

        if reading.weight_kg is not None:
            self.state.weight_kg = reading.weight_kg
            self._pending_weight_kg = reading.weight_kg
            claimed = self.active_claim
            assignment = assign_reading(
                reading.weight_kg, self.people, self._is_home(), claimed
            )
            self._apply_assignment(assignment)
            # Consume the claim only once it has actually assigned something.
            # Clearing it on any frame would burn the claim on a 2 kg reading
            # taken while the scale was still settling underfoot.
            if claimed is not None and assignment.assigned and reading.stable:
                self.async_clear_claim()

        if reading.impedance is not None:
            self.state.impedance = reading.impedance

        self._recompute_body()

    def _refresh_claim_state(self) -> None:
        self.state.claimed_by = self.active_claim

    def _apply_assignment(self, assignment: Assignment) -> None:
        self.state.person_name = assignment.person.name if assignment.person else None
        self.state.assignment_reason = assignment.reason
        if not assignment.assigned:
            _LOGGER.debug("Reading unassigned: %s", assignment.reason)

    def _recompute_body(self) -> None:
        """Derive composition once both halves and a person are known."""
        weight = self._pending_weight_kg
        if weight is None or self.state.impedance is None or self.state.person_name is None:
            self.state.body = None
            return
        person = next((p for p in self.people if p.name == self.state.person_name), None)
        if person is None:
            self.state.body = None
            return
        profile = Profile(
            height_cm=person.height_cm,
            age_years=person.age_years,
            sex=person.sex,
        )
        self.state.body = compute(weight, self.state.impedance, profile)
