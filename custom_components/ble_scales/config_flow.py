"""Config flow for BLE Scales."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
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

PERSON_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Required(CONF_HEIGHT_CM): selector.NumberSelector(
            selector.NumberSelectorConfig(min=100, max=250, step=1, unit_of_measurement="cm")
        ),
        vol.Required(CONF_AGE_YEARS): selector.NumberSelector(
            selector.NumberSelectorConfig(min=5, max=120, step=1)
        ),
        vol.Required(CONF_SEX): selector.SelectSelector(
            selector.SelectSelectorConfig(options=[SEX_MALE, SEX_FEMALE])
        ),
        vol.Required(CONF_EXPECTED_WEIGHT_KG): selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=250, step=0.1, unit_of_measurement="kg")
        ),
        vol.Optional(
            CONF_WEIGHT_TOLERANCE_KG, default=DEFAULT_WEIGHT_TOLERANCE_KG
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0.5, max=25, step=0.5, unit_of_measurement="kg")
        ),
        vol.Optional(CONF_PERSON_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="person")
        ),
    }
)


class BleScalesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and setup of a scale."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: bluetooth.BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device discovered by the Bluetooth integration.

        The manifest matcher claims the whole FFB0 service, which several
        unrelated scale families also use. Parsing here -- checksum included --
        is what stops this integration adopting a device it would then decode
        into a confident wrong number.
        """
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if parse_service_info(discovery_info) is None:
            return self.async_abort(reason="not_supported")

        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered scale."""
        assert self._discovered is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered.name,
                data={CONF_ADDRESS: self._discovered.address},
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._discovered.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick from scales currently advertising.

        Only devices whose advertisement parses are offered. A scale that is
        asleep does not advertise, so the list is empty until someone steps on
        it -- which the form text says, because an empty list otherwise reads
        as a broken integration.
        """
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"Scale {address}", data={CONF_ADDRESS: address})

        current = self._async_current_ids()
        choices = {
            info.address: f"{info.name} ({info.address})"
            for info in bluetooth.async_discovered_service_info(self.hass, False)
            if info.address not in current and parse_service_info(info) is not None
        }
        if not choices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return BleScalesOptionsFlow()


class BleScalesOptionsFlow(OptionsFlow):
    """Manage the people who use this scale."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the list of people.

        Body composition cannot be computed without height, age and sex, so a
        scale with nobody configured reports weight and impedance only.
        """
        if user_input is not None:
            return self.async_create_entry(data={CONF_PEOPLE: user_input[CONF_PEOPLE]})

        current = self.config_entry.options.get(CONF_PEOPLE, [])
        schema = vol.Schema(
            {
                vol.Optional(CONF_PEOPLE, default=current): selector.ObjectSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
