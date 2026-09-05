"""Config flow for BLE Scales.

Two things shape this flow, both learned from the first real install:

  * A scale that is not being stood on does not advertise, so a flow that only
    offers discovered devices is unusable most of the time. Entering an address
    by hand is always available.
  * With nobody configured, every sensor except weight reads "unknown", because
    height, age and sex are what turn a weight into anything else. People are
    therefore part of INITIAL setup rather than an options page found later.
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
from homeassistant.core import callback
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

CONF_ADD_ANOTHER = "add_another"

#: Only used to pre-fill the "expected weight" box. A person's own last reading
#: is a far better starting point than a made-up number, and getting this field
#: wrong is precisely what leaves readings unassigned.
FALLBACK_EXPECTED_WEIGHT_KG = 70.0


def person_schema(
    defaults: dict[str, Any] | None = None, *, offer_add_another: bool = True
) -> vol.Schema:
    """Schema for one person. `defaults` pre-fills it when editing."""
    d = defaults or {}
    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=d.get(CONF_NAME, vol.UNDEFINED)): (
            selector.TextSelector()
        ),
        vol.Required(CONF_HEIGHT_CM, default=d.get(CONF_HEIGHT_CM, 170)): (
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=100, max=250, step=1, unit_of_measurement="cm"
                )
            )
        ),
        vol.Required(CONF_AGE_YEARS, default=d.get(CONF_AGE_YEARS, 30)): (
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=120, step=1)
            )
        ),
        vol.Required(CONF_SEX, default=d.get(CONF_SEX, SEX_MALE)): (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SEX_MALE, SEX_FEMALE], translation_key="sex"
                )
            )
        ),
        vol.Required(
            CONF_EXPECTED_WEIGHT_KG,
            default=d.get(CONF_EXPECTED_WEIGHT_KG, FALLBACK_EXPECTED_WEIGHT_KG),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=250, step=0.1, unit_of_measurement="kg"
            )
        ),
        vol.Optional(
            CONF_WEIGHT_TOLERANCE_KG,
            default=d.get(CONF_WEIGHT_TOLERANCE_KG, DEFAULT_WEIGHT_TOLERANCE_KG),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.5, max=25, step=0.5, unit_of_measurement="kg"
            )
        ),
        vol.Optional(
            CONF_PERSON_ENTITY, default=d.get(CONF_PERSON_ENTITY, vol.UNDEFINED)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="person")),
    }
    if offer_add_another:
        fields[vol.Optional(CONF_ADD_ANOTHER, default=False)] = (
            selector.BooleanSelector()
        )
    return vol.Schema(fields)


def _clean(person: dict[str, Any]) -> dict[str, Any]:
    """Strip flow-control keys and normalise types before storing."""
    out = {k: v for k, v in person.items() if k != CONF_ADD_ANOTHER}
    out[CONF_HEIGHT_CM] = float(out[CONF_HEIGHT_CM])
    out[CONF_AGE_YEARS] = int(out[CONF_AGE_YEARS])
    out[CONF_EXPECTED_WEIGHT_KG] = float(out[CONF_EXPECTED_WEIGHT_KG])
    out[CONF_WEIGHT_TOLERANCE_KG] = float(
        out.get(CONF_WEIGHT_TOLERANCE_KG, DEFAULT_WEIGHT_TOLERANCE_KG)
    )
    return out


def _last_seen_weight(hass, address: str) -> float | None:
    """Best-effort current weight, used only to pre-fill the setup form."""
    for info in bluetooth.async_discovered_service_info(hass, False):
        if info.address.upper() != address.upper():
            continue
        reading = parse_service_info(info)
        if reading is not None and reading.weight_kg:
            return round(reading.weight_kg, 1)
    return None


class BleScalesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and setup of a scale."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: bluetooth.BluetoothServiceInfoBleak | None = None
        self._address: str | None = None
        self._title: str | None = None
        self._people: list[dict[str, Any]] = []

    # -- entry points ------------------------------------------------------

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
        """Confirm adding a discovered scale, then collect people."""
        assert self._discovered is not None
        if user_input is not None:
            return await self.async_step_person()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._discovered.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a scale that is advertising, or go enter an address by hand."""
        current = self._async_current_ids()
        choices = {
            info.address: f"{info.name} ({info.address})"
            for info in bluetooth.async_discovered_service_info(self.hass, False)
            if info.address not in current and parse_service_info(info) is not None
        }

        # Nothing advertising is the NORMAL case: these scales sleep between
        # weigh-ins. Aborting here would make setup possible only while
        # standing on the scale, so fall straight through to manual entry.
        if not choices:
            return await self.async_step_manual()

        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            self._title = choices[self._address].split(" (")[0]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_person()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)}),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter a scale's Bluetooth address by hand.

        Always reachable, so the scale never has to be awake to set this up.
        The address is not verified here -- the scale may well be asleep -- so
        entities stay unavailable until the first advertisement arrives.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if len(address.split(":")) != 6 or not all(
                len(p) == 2 and all(c in "0123456789ABCDEF" for c in p)
                for p in address.split(":")
            ):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                self._address = address
                self._title = f"Scale {address}"
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return await self.async_step_person()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): selector.TextSelector()}),
            errors=errors,
        )

    # -- people ------------------------------------------------------------

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect people, one per pass, until 'add another' is left unticked."""
        if user_input is not None:
            add_another = user_input.get(CONF_ADD_ANOTHER, False)
            self._people.append(_clean(user_input))
            if add_another:
                return await self.async_step_person()
            return self._create()

        assert self._address is not None
        seen = _last_seen_weight(self.hass, self._address)
        defaults: dict[str, Any] = {}
        if seen is not None and not self._people:
            # Pre-fill from the live reading: whoever is setting this up is
            # very often the person standing on the scale, and a wrong expected
            # weight is the single most common reason a reading goes unassigned.
            defaults[CONF_EXPECTED_WEIGHT_KG] = seen

        return self.async_show_form(
            step_id="person",
            data_schema=person_schema(defaults),
            description_placeholders={
                "count": str(len(self._people)),
                "seen": f"{seen:.1f} kg" if seen is not None else "nothing right now",
            },
        )

    def _create(self) -> ConfigFlowResult:
        assert self._address is not None
        return self.async_create_entry(
            title=self._title or f"Scale {self._address}",
            data={CONF_ADDRESS: self._address},
            options={CONF_PEOPLE: self._people},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return BleScalesOptionsFlow()


class BleScalesOptionsFlow(OptionsFlow):
    """Add, edit and remove the people who use this scale."""

    def __init__(self) -> None:
        self._editing: int | None = None

    @property
    def _people(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_PEOPLE, []))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Menu of what can be done with the configured people."""
        people = self._people
        options = ["add"]
        if people:
            options += ["edit", "remove"]
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(self._people + [_clean(user_input)])
        return self.async_show_form(
            step_id="add", data_schema=person_schema(offer_add_another=False)
        )

    async def async_step_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick someone to edit, then show their details pre-filled."""
        people = self._people
        if self._editing is None:
            if user_input is not None:
                self._editing = int(user_input[CONF_NAME])
                return await self.async_step_edit()
            choices = {str(i): p[CONF_NAME] for i, p in enumerate(people)}
            return self.async_show_form(
                step_id="edit",
                data_schema=vol.Schema({vol.Required(CONF_NAME): vol.In(choices)}),
            )

        if user_input is not None:
            updated = people[:]
            updated[self._editing] = _clean(user_input)
            return self._save(updated)

        return self.async_show_form(
            step_id="edit",
            data_schema=person_schema(people[self._editing], offer_add_another=False),
        )

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        people = self._people
        if user_input is not None:
            keep = [p for p in people if p[CONF_NAME] not in user_input[CONF_PEOPLE]]
            return self._save(keep)
        choices = {p[CONF_NAME]: p[CONF_NAME] for p in people}
        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PEOPLE, default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(choices), multiple=True
                        )
                    )
                }
            ),
        )

    def _save(self, people: list[dict[str, Any]]) -> ConfigFlowResult:
        return self.async_create_entry(data={CONF_PEOPLE: people})
