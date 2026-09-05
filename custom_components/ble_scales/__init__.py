"""The BLE Scales integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .assign import Person
from .const import (
    CONF_AGE_YEARS,
    CONF_EXPECTED_WEIGHT_KG,
    CONF_HEIGHT_CM,
    CONF_NAME,
    CONF_PEOPLE,
    CONF_PERSON_ENTITY,
    CONF_SEX,
    CONF_WEIGHT_TOLERANCE_KG,
    DEFAULT_WEIGHT_TOLERANCE_KG,
    DOMAIN,
)
from .coordinator import ScaleCoordinator

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]


def people_from_options(options: dict) -> list[Person]:
    """Build Person records from a config entry's options."""
    people: list[Person] = []
    for raw in options.get(CONF_PEOPLE, []):
        people.append(
            Person(
                name=raw[CONF_NAME],
                height_cm=(
                    float(raw[CONF_HEIGHT_CM]) if raw.get(CONF_HEIGHT_CM) else None
                ),
                age_years=(
                    int(raw[CONF_AGE_YEARS]) if raw.get(CONF_AGE_YEARS) else None
                ),
                sex=raw.get(CONF_SEX) or None,
                expected_weight_kg=float(raw[CONF_EXPECTED_WEIGHT_KG]),
                weight_tolerance_kg=float(
                    raw.get(CONF_WEIGHT_TOLERANCE_KG, DEFAULT_WEIGHT_TOLERANCE_KG)
                ),
                person_entity=raw.get(CONF_PERSON_ENTITY) or None,
            )
        )
    return people


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a scale from a config entry."""
    coordinator = ScaleCoordinator(
        hass, entry.data[CONF_ADDRESS], people_from_options(dict(entry.options))
    )
    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload so edited people take effect immediately."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: ScaleCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_stop()
    return unloaded
