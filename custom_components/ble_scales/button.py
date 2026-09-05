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
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .assign import Person
from .const import DOMAIN
from .coordinator import ScaleCoordinator
from .sensor import scale_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one claim button per configured person."""
    coordinator: ScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [
        ClaimButton(coordinator, entry, person) for person in coordinator.people
    ]
    # One cancel, not one per person: only a single claim can be active, so a
    # per-person cancel would raise the question of what pressing somebody
    # else's does. This clears whichever claim is standing.
    entities.append(CancelClaimButton(coordinator, entry))
    async_add_entities(entities)


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
        self._attr_device_info = scale_device(entry)
        self._attr_has_entity_name = False
        self._attr_name = f"{person.name} weighing in"

    async def async_press(self) -> None:
        """Claim the next reading for this person."""
        self._coordinator.async_claim(self._person.name)


class CancelClaimButton(ButtonEntity):
    """Clears a pending weigh-in claim.

    Needed because a claim is a five-minute promise about the future, and
    plans change: you press your button, get distracted, and somebody else
    steps on the scale. Without this the only remedy is waiting out the
    window, during which their weight silently lands in your history.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "cancel_claim"
    _attr_icon = "mdi:close-circle-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ScaleCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_cancel_claim"
        self._attr_device_info = scale_device(entry)

    async def async_press(self) -> None:
        self._coordinator.async_clear_claim()
        self._coordinator._notify()
