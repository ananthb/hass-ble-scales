"""Config flow for BLE Scales.

The shape of this flow is set by three facts learned from real installs:

  * A scale that nobody is standing on does not advertise, so a flow that only
    offers discovered devices is unusable most of the time. Entering an address
    by hand is always reachable.
  * With nobody configured, every sensor but weight reads "unknown", because
    height, age and sex are what turn a weight into anything else. People are
    therefore part of INITIAL setup, not an options page found later.
  * Typing a person's details is the slowest possible way to do this. The
    default path is: pick yourself from the people Home Assistant already
    knows, stand on the scale, done. Manual entry stays for people who are not
    in Home Assistant at all -- a guest, a child without an account.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .body import SEX_FEMALE, SEX_MALE
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
from .coordinator import parse_service_info

#: Only used when someone is added manually and the scale is not advertising.
FALLBACK_EXPECTED_WEIGHT_KG = 70.0


def live_weight(hass: HomeAssistant, address: str) -> float | None:
    """The weight the scale is broadcasting right now, if it is awake."""
    for info in bluetooth.async_discovered_service_info(hass, False):
        if info.address.upper() != address.upper():
            continue
        reading = parse_service_info(info)
        if reading is not None and reading.weight_kg:
            return round(reading.weight_kg, 1)
    return None


def person_name(hass: HomeAssistant, entity_id: str) -> str:
    """Display name for a Home Assistant person entity."""
    state = hass.states.get(entity_id)
    if state is not None and state.attributes.get("friendly_name"):
        return str(state.attributes["friendly_name"])
    # The entity may not exist yet during a restore; the object id still reads
    # better than an empty name.
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


def available_people(hass: HomeAssistant, taken: list[str]) -> dict[str, str]:
    """Home Assistant person entities not already attached to this scale."""
    return {
        state.entity_id: person_name(hass, state.entity_id)
        for state in hass.states.async_all("person")
        if state.entity_id not in taken
    }


def body_detail_schema(defaults: dict[str, Any] | None = None) -> dict[Any, Any]:
    """Height, age and sex. Optional everywhere: without them a person still
    gets assignment, a button and a weight history, just no composition."""
    d = defaults or {}
    return {
        vol.Optional(CONF_HEIGHT_CM, default=d.get(CONF_HEIGHT_CM, vol.UNDEFINED)): (
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=100, max=250, step=1, unit_of_measurement="cm"
                )
            )
        ),
        vol.Optional(CONF_AGE_YEARS, default=d.get(CONF_AGE_YEARS, vol.UNDEFINED)): (
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=120, step=1)
            )
        ),
        vol.Optional(CONF_SEX, default=d.get(CONF_SEX, vol.UNDEFINED)): (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SEX_MALE, SEX_FEMALE], translation_key="sex"
                )
            )
        ),
    }


def manual_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Everything typed by hand, for someone with no Home Assistant person."""
    d = defaults or {}
    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=d.get(CONF_NAME, vol.UNDEFINED)): (
            selector.TextSelector()
        ),
        vol.Required(
            CONF_EXPECTED_WEIGHT_KG,
            default=d.get(CONF_EXPECTED_WEIGHT_KG, FALLBACK_EXPECTED_WEIGHT_KG),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=250, step=0.1, unit_of_measurement="kg"
            )
        ),
    }
    fields.update(body_detail_schema(d))
    fields[
        vol.Optional(
            CONF_WEIGHT_TOLERANCE_KG,
            default=d.get(CONF_WEIGHT_TOLERANCE_KG, DEFAULT_WEIGHT_TOLERANCE_KG),
        )
    ] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.5, max=25, step=0.5, unit_of_measurement="kg"
        )
    )
    return vol.Schema(fields)


def clean_person(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a person record before storing it."""
    out: dict[str, Any] = {
        CONF_NAME: raw[CONF_NAME],
        CONF_EXPECTED_WEIGHT_KG: float(raw[CONF_EXPECTED_WEIGHT_KG]),
        CONF_WEIGHT_TOLERANCE_KG: float(
            raw.get(CONF_WEIGHT_TOLERANCE_KG) or DEFAULT_WEIGHT_TOLERANCE_KG
        ),
    }
    if raw.get(CONF_HEIGHT_CM):
        out[CONF_HEIGHT_CM] = float(raw[CONF_HEIGHT_CM])
    if raw.get(CONF_AGE_YEARS):
        out[CONF_AGE_YEARS] = int(raw[CONF_AGE_YEARS])
    if raw.get(CONF_SEX):
        out[CONF_SEX] = raw[CONF_SEX]
    if raw.get(CONF_PERSON_ENTITY):
        out[CONF_PERSON_ENTITY] = raw[CONF_PERSON_ENTITY]
    return out


class PeopleMixin:
    """The add-a-person steps, shared by initial setup and options."""

    hass: HomeAssistant
    _address: str
    _people: list[dict[str, Any]]
    _pending_entity: str | None = None

    def _menu_options(self) -> list[str]:
        return ["from_ha", "manual", "finish"]

    async def async_step_people(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to add someone, or stop."""
        return self.async_show_menu(
            step_id="people",
            menu_options=self._menu_options(),
            description_placeholders={"count": str(len(self._people))},
        )

    async def async_step_from_ha(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick someone Home Assistant already knows about."""
        taken = [p[CONF_PERSON_ENTITY] for p in self._people if p.get(CONF_PERSON_ENTITY)]
        choices = available_people(self.hass, taken)
        if not choices:
            return await self.async_step_manual()

        if user_input is not None:
            self._pending_entity = user_input[CONF_PERSON_ENTITY]
            return await self.async_step_weigh()

        return self.async_show_form(
            step_id="from_ha",
            data_schema=vol.Schema(
                {vol.Required(CONF_PERSON_ENTITY): vol.In(choices)}
            ),
        )

    async def async_step_weigh(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Read the person's usual weight off the scale instead of asking.

        Submitting samples whatever the scale is broadcasting at that moment,
        which is why the form says to stand on it first. Getting this number
        wrong is the single most common reason a later reading goes unassigned,
        and measuring it is strictly better than asking someone to recall it.

        Height, age and sex are offered here too, all optional. They are the
        only things the scale cannot measure for itself, and while you are
        already standing there is the one moment you are certain to be thinking
        about it. Skipping them costs only the composition sensors.
        """
        assert self._pending_entity is not None
        name = person_name(self.hass, self._pending_entity)
        seen = live_weight(self.hass, self._address)
        errors: dict[str, str] = {}

        if user_input is not None:
            if seen is None:
                # Not an error in the device sense -- the scale is simply not
                # broadcasting yet. Say so and let them try again rather than
                # dropping them out of the flow.
                errors["base"] = "no_reading"
            else:
                self._people.append(
                    clean_person(
                        {
                            **user_input,
                            CONF_NAME: name,
                            CONF_PERSON_ENTITY: self._pending_entity,
                            CONF_EXPECTED_WEIGHT_KG: seen,
                        }
                    )
                )
                self._pending_entity = None
                return await self.async_step_people()

        return self.async_show_form(
            step_id="weigh",
            data_schema=vol.Schema(body_detail_schema(user_input)),
            errors=errors,
            description_placeholders={
                "name": name,
                "seen": f"{seen:.1f} kg" if seen is not None else "nothing yet",
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add someone who is not a Home Assistant person -- a guest, a child."""
        if user_input is not None:
            self._people.append(clean_person(user_input))
            return await self.async_step_people()

        seen = live_weight(self.hass, self._address)
        defaults = {CONF_EXPECTED_WEIGHT_KG: seen} if seen is not None else {}
        return self.async_show_form(
            step_id="manual",
            data_schema=manual_schema(defaults),
            description_placeholders={
                "seen": f"{seen:.1f} kg" if seen is not None else "nothing right now"
            },
        )


class BleScalesConfigFlow(PeopleMixin, ConfigFlow, domain=DOMAIN):
    """Handle discovery and setup of a scale."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: bluetooth.BluetoothServiceInfoBleak | None = None
        self._address: str = ""
        self._title: str | None = None
        self._people: list[dict[str, Any]] = []
        self._pending_entity: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device discovered by the Bluetooth integration.

        The manifest matcher claims the whole FFB0 service, which unrelated
        scale families also use. Parsing here -- checksum included -- is what
        stops this integration adopting a device it would then decode into a
        confident wrong number.
        """
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if parse_service_info(discovery_info) is None:
            return self.async_abort(reason="not_supported")

        self._discovered = discovery_info
        self._address = discovery_info.address
        self._title = discovery_info.name
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovered is not None
        if user_input is not None:
            return await self.async_step_people()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._discovered.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a scale that is advertising, or enter an address by hand."""
        current = self._async_current_ids()
        choices = {
            info.address: f"{info.name} ({info.address})"
            for info in bluetooth.async_discovered_service_info(self.hass, False)
            if info.address not in current and parse_service_info(info) is not None
        }
        # Nothing advertising is the NORMAL case: these scales sleep between
        # weigh-ins. Fall through to manual entry rather than aborting, which
        # would make setup possible only while standing on the scale.
        if not choices:
            return await self.async_step_address()

        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            self._title = choices[self._address].split(" (")[0]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_people()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)}),
        )

    async def async_step_address(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the scale's Bluetooth address by hand."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            parts = address.split(":")
            if len(parts) != 6 or not all(
                len(p) == 2 and all(c in "0123456789ABCDEF" for c in p) for p in parts
            ):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                self._address = address
                self._title = f"Scale {address}"
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return await self.async_step_people()

        return self.async_show_form(
            step_id="address",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): selector.TextSelector()}
            ),
            errors=errors,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._title or f"Scale {self._address}",
            data={CONF_ADDRESS: self._address},
            options={CONF_PEOPLE: self._people},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return BleScalesOptionsFlow()


class BleScalesOptionsFlow(PeopleMixin, OptionsFlow):
    """Add, edit and remove the people who use this scale."""

    def __init__(self) -> None:
        self._people: list[dict[str, Any]] = []
        self._pending_entity: str | None = None
        self._editing: int | None = None
        self._loaded = False

    @property
    def _address(self) -> str:
        return self.config_entry.data[CONF_ADDRESS]

    def _load(self) -> None:
        if not self._loaded:
            self._people = [dict(p) for p in self.config_entry.options.get(CONF_PEOPLE, [])]
            self._loaded = True

    def _menu_options(self) -> list[str]:
        options = ["from_ha", "manual"]
        if self._people:
            options += ["details", "remove"]
        return options + ["finish"]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        return await self.async_step_people()

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Fill in height, age and sex -- the only things needed for body
        composition, and the only things the quick path cannot measure."""
        self._load()
        if self._editing is None:
            if user_input is not None:
                self._editing = int(user_input[CONF_NAME])
                return await self.async_step_details()
            choices = {str(i): p[CONF_NAME] for i, p in enumerate(self._people)}
            return self.async_show_form(
                step_id="details",
                data_schema=vol.Schema({vol.Required(CONF_NAME): vol.In(choices)}),
            )

        person = self._people[self._editing]
        if user_input is not None:
            self._people[self._editing] = clean_person({**person, **user_input})
            self._editing = None
            return await self.async_step_people()

        fields = dict(body_detail_schema(person))
        fields[
            vol.Optional(
                CONF_EXPECTED_WEIGHT_KG, default=person[CONF_EXPECTED_WEIGHT_KG]
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=250, step=0.1, unit_of_measurement="kg"
            )
        )
        return self.async_show_form(
            step_id="details",
            data_schema=vol.Schema(fields),
            description_placeholders={"name": person[CONF_NAME]},
        )

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load()
        if user_input is not None:
            drop = set(user_input[CONF_PEOPLE])
            self._people = [p for p in self._people if p[CONF_NAME] not in drop]
            return await self.async_step_people()
        names = [p[CONF_NAME] for p in self._people]
        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PEOPLE, default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=names, multiple=True)
                    )
                }
            ),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(data={CONF_PEOPLE: self._people})
