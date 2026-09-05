"""Sensor entities for the BLE Scales integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, PERCENTAGE, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ScaleCoordinator, ScaleState


@dataclass(frozen=True, kw_only=True)
class ScaleSensorDescription(SensorEntityDescription):
    """A sensor plus how to pull its value out of the state."""

    value_fn: Callable[[ScaleState], float | int | str | None]


def _body(attr: str) -> Callable[[ScaleState], float | int | None]:
    def _get(state: ScaleState) -> float | int | None:
        return getattr(state.body, attr) if state.body else None

    return _get


SENSORS: tuple[ScaleSensorDescription, ...] = (
    ScaleSensorDescription(
        key="weight",
        translation_key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
        value_fn=lambda s: s.weight_kg,
    ),
    # Raw impedance is exposed deliberately. Every derived value below is a
    # regression over this number, so when an estimate looks wrong this is the
    # only field that says whether the scale or the equation is at fault.
    ScaleSensorDescription(
        key="impedance",
        translation_key="impedance",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="Ω",
        value_fn=lambda s: s.impedance,
    ),
    ScaleSensorDescription(
        key="person",
        translation_key="person",
        value_fn=lambda s: s.person_name,
    ),
    # Enabled by default on purpose. When every derived sensor reads unknown,
    # this is the entity that says why -- "no people configured" is a far more
    # useful thing to see than eight blanks.
    ScaleSensorDescription(
        key="assignment_reason",
        translation_key="assignment_reason",
        value_fn=lambda s: s.assignment_reason,
    ),
    ScaleSensorDescription(
        key="claimed_by",
        translation_key="claimed_by",
        value_fn=lambda s: s.claimed_by or "nobody",
    ),
    ScaleSensorDescription(
        key="bmi",
        translation_key="bmi",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_body("bmi"),
    ),
    ScaleSensorDescription(
        key="body_fat_percent",
        translation_key="body_fat_percent",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=_body("body_fat_percent"),
    ),
    ScaleSensorDescription(
        key="body_fat_kg",
        translation_key="body_fat_kg",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=2,
        value_fn=_body("body_fat_kg"),
    ),
    ScaleSensorDescription(
        key="fat_free_mass_kg",
        translation_key="fat_free_mass_kg",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=2,
        value_fn=_body("fat_free_mass_kg"),
    ),
    ScaleSensorDescription(
        key="skeletal_muscle_kg",
        translation_key="skeletal_muscle_kg",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=2,
        value_fn=_body("skeletal_muscle_kg"),
    ),
    ScaleSensorDescription(
        key="total_body_water_percent",
        translation_key="total_body_water_percent",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=_body("total_body_water_percent"),
    ),
    ScaleSensorDescription(
        key="basal_metabolic_rate_kcal",
        translation_key="basal_metabolic_rate_kcal",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kcal",
        value_fn=_body("basal_metabolic_rate_kcal"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for a configured scale."""
    coordinator: ScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ScaleSensor(coordinator, entry, description) for description in SENSORS
    )


class ScaleSensor(SensorEntity):
    """One reading from the scale."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: ScaleSensorDescription

    def __init__(
        self,
        coordinator: ScaleCoordinator,
        entry: ConfigEntry,
        description: ScaleSensorDescription,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            identifiers={(DOMAIN, address)},
            name=entry.title,
            manufacturer="BLE Scales",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        # The person and reason sensors stay available so an unassigned reading
        # can explain itself; a stale weight would just be misleading.
        if self.entity_description.key in (
            "person",
            "assignment_reason",
            "claimed_by",
        ):
            return True
        return self._coordinator.state.available

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self._coordinator.state)
