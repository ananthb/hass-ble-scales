"""A 'weighing in next' button per configured person.

Weight matching is the primary mechanism and handles most weigh-ins with nobody
pressing anything. This is the escape hatch for the case it cannot solve: two
people close enough in weight that the band matches both, where inference
correctly refuses to guess and would otherwise leave the reading unassigned.

One button per person, so they can go straight on a dashboard or a wall tablet
next to the scale.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .assign import Person
from .const import DOMAIN
from .coordinator import ScaleCoordinator
from .sensor import person_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one claim button per configured person."""
    coordinator: ScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ClaimButton(coordinator, entry, person) for person in coordinator.people
    )


class ClaimButton(ButtonEntity):
    """Claims the next weigh-in for one person."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:scale-bathroom"

    def __init__(
        self,
        coordinator: ScaleCoordinator,
        entry: ConfigEntry,
        person: Person,
    ) -> None:
        self._coordinator = coordinator
        self._person = person
        address = entry.data[CONF_ADDRESS]
        # Keyed by name, so renaming a person makes a new button rather than
        # silently retargeting an existing one that a dashboard still points at.
        self._attr_unique_id = f"{address}_claim_{person.name}"
        self._attr_translation_key = "claim"
        # Lives on the person's own device, next to their measurements, rather
        # than on the scale -- pressing it is a statement about a person.
        self._attr_device_info = person_device(entry, person)

    async def async_press(self) -> None:
        """Claim the next reading for this person."""
        self._coordinator.async_claim(self._person.name)
