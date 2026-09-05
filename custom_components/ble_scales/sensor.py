"""Sensor entities.

Every measurement belongs to a person. There is no generic "weight" entity,
deliberately: one shared sensor would interleave everybody who steps on the
scale into a single history, and its long-term statistics would then describe
who weighed in most recently rather than anybody's actual weight.

The scale device carries only what is genuinely about the scale -- when it was
last heard from, how strong its signal is, and why the last reading was or was
not assigned.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ADDRESS,
    PERCENTAGE,
    EntityCategory,
    UnitOfMass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .assign import Person
from .const import DOMAIN
from .coordinator import PersonState, ScaleCoordinator, ScaleState


@dataclass(frozen=True, kw_only=True)
class PersonSensorDescription(SensorEntityDescription):
    """A per-person sensor plus how to read it out of that person's state.

    `label` is the human-readable half of the entity name, combined with the
    person's name at construction. It is separate from `translation_key`
    because these entities do not use has_entity_name, so Home Assistant never
    looks the translation up for them.
    """

    label: str
    value_fn: Callable[[PersonState], float | int | datetime | None]


@dataclass(frozen=True, kw_only=True)
class ScaleSensorDescription(SensorEntityDescription):
    """A scale-level diagnostic."""

    value_fn: Callable[[ScaleState], float | int | str | datetime | None]


def _body(attr: str) -> Callable[[PersonState], float | int | None]:
    def _get(state: PersonState) -> float | int | None:
        return getattr(state.body, attr) if state.body else None

    return _get


# Only what this hardware can actually produce. The BIA-derived sensors -- body
# fat, fat-free mass, skeletal muscle, body water -- are deliberately absent:
# the advertisement carries no impedance (see docs/protocol.md), so they would
# read "unknown" forever and imply a measurement the broadcast never makes.
# body.py still computes them and the parser still decodes an impedance frame,
# so re-adding them is a one-line change once impedance can actually be read.
PERSON_SENSORS: tuple[PersonSensorDescription, ...] = (
    PersonSensorDescription(
        key="weight",
        translation_key="weight",
        label="Weight",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
        value_fn=lambda s: s.weight_kg,
    ),
    PersonSensorDescription(
        key="bmi",
        translation_key="bmi",
        label="BMI",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_body("bmi"),
    ),
    PersonSensorDescription(
        key="basal_metabolic_rate_kcal",
        translation_key="basal_metabolic_rate_kcal",
        label="Basal metabolic rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kcal",
        value_fn=_body("basal_metabolic_rate_kcal"),
    ),
    PersonSensorDescription(
        key="last_measured",
        translation_key="last_measured",
        label="Last measured",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: s.last_measured_at,
    ),
)

SCALE_SENSORS: tuple[ScaleSensorDescription, ...] = (
    ScaleSensorDescription(
        key="last_measurement",
        translation_key="last_measurement",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_measurement_at,
    ),
    ScaleSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.rssi,
    ),
    # When a reading goes nowhere, this is the entity that says why. Enabled by
    # default because "ambiguous between Ananth and Partner" is a far more
    # useful thing to find than a person's sensors quietly not updating.
    ScaleSensorDescription(
        key="assignment_reason",
        translation_key="assignment_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.assignment_reason,
    ),
    ScaleSensorDescription(
        key="claimed_by",
        translation_key="claimed_by",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.claimed_by or "nobody",
    ),
)


def scale_device(entry: ConfigEntry) -> DeviceInfo:
    address = entry.data[CONF_ADDRESS]
    return DeviceInfo(
        connections={(CONNECTION_BLUETOOTH, address)},
        identifiers={(DOMAIN, address)},
        name=entry.title,
        manufacturer="BLE Scales",
    )


def person_device(entry: ConfigEntry, person: Person) -> DeviceInfo:
    """Everything lives on the scale device, including per-person readings.

    An earlier version gave each person their own device. It produced something
    that looked like a second, competing person in the UI, which is misleading:
    Home Assistant already has a person entity for these people, and this
    integration has no business appearing to be another one.

    Attaching the entities to the real person entity is not possible either.
    The person integration owns its entities through its own EntityComponent
    and storage collection, and persons are not devices, so there is no hook
    for another integration to hang anything off one. Scale device it is, with
    the person's name carried in each entity's own name instead.
    """
    return scale_device(entry)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up scale diagnostics and one set of sensors per person."""
    coordinator: ScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        ScaleDiagnosticSensor(coordinator, entry, description)
        for description in SCALE_SENSORS
    ]
    for person in coordinator.people:
        entities.extend(
            PersonSensor(coordinator, entry, person, description)
            for description in PERSON_SENSORS
        )
    async_add_entities(entities)


class _BaseSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(self, coordinator: ScaleCoordinator) -> None:
        self._coordinator = coordinator

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class PersonSensor(_BaseSensor):
    """One measured or derived value, for one person."""

    entity_description: PersonSensorDescription

    def __init__(
        self,
        coordinator: ScaleCoordinator,
        entry: ConfigEntry,
        person: Person,
        description: PersonSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._person = person
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_{person.name}_{description.key}"
        self._attr_device_info = scale_device(entry)
        # has_entity_name is deliberately off here. With it on, Home Assistant
        # prefixes the device name, giving sensor.<scale>_<person>_weight --
        # and if the person's own name already ends in a word like "weight",
        # that word appears twice. An explicit name keeps this readable:
        # "Ananth Weight" -> sensor.ananth_weight.
        self._attr_has_entity_name = False
        self._attr_name = f"{person.name} {description.label}"

    @property
    def available(self) -> bool:
        # A person's last reading stays available indefinitely. Weight is not a
        # live measurement that goes stale -- yesterday's weigh-in is still the
        # most recent true value, and blanking it would break history graphs
        # every time the scale went to sleep.
        return self._coordinator.person_state(self._person.name).has_reading

    @property
    def native_value(self) -> float | int | datetime | None:
        return self.entity_description.value_fn(
            self._coordinator.person_state(self._person.name)
        )


class ScaleDiagnosticSensor(_BaseSensor):
    """Something about the scale itself, never about a body."""

    _attr_has_entity_name = True
    entity_description: ScaleSensorDescription

    def __init__(
        self,
        coordinator: ScaleCoordinator,
        entry: ConfigEntry,
        description: ScaleSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_{description.key}"
        self._attr_device_info = scale_device(entry)

    @property
    def native_value(self) -> float | int | str | datetime | None:
        return self.entity_description.value_fn(self._coordinator.state)
