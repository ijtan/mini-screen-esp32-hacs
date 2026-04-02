"""Config flow for Mini Screen ESP32 integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, ConfigSubentryFlow, OptionsFlow, SubentryFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    CONF_IP_ADDRESS, CONF_NAME, DOMAIN,
    CONF_DIM_ENABLED, CONF_DIM_START, CONF_DIM_END, CONF_DIM_LEVEL, CONF_DIM_RESTORE,
    CONF_MONITOR_ENABLED, CONF_MONITOR_INTERVAL, SUBENTRY_TYPE_MONITOR,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Mini Screen"
REACHABILITY_TIMEOUT = 5


async def _validate_device_reachable(ip_address: str) -> bool:
    """
    Attempt a GET to /updatePage on the device.

    Returns True if any HTTP response is received (even 404), meaning the
    device is reachable.  Returns False on a connection error / timeout.
    """
    url = f"http://{ip_address}/updatePage"
    timeout = aiohttp.ClientTimeout(total=REACHABILITY_TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url):
                return True
    except aiohttp.ClientError:
        return False


class MiniScreenESP32ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mini Screen ESP32."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ip_address: str = user_input[CONF_IP_ADDRESS].strip()
            name: str = user_input[CONF_NAME].strip()

            # Use IP as the unique identifier to prevent duplicates
            await self.async_set_unique_id(ip_address)
            self._abort_if_unique_id_configured()

            reachable = await _validate_device_reachable(ip_address)
            if not reachable:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_NAME: name,
                        CONF_IP_ADDRESS: ip_address,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_IP_ADDRESS): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MiniScreenESP32OptionsFlow:
        """Return the options flow handler."""
        return MiniScreenESP32OptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported subentry types."""
        return {SUBENTRY_TYPE_MONITOR: MiniScreenMonitorSubentryFlow}


class MiniScreenESP32OptionsFlow(OptionsFlow):
    """Handle options flow for Mini Screen ESP32 (edit IP after setup)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options step."""
        errors: dict[str, str] = {}

        current_ip: str = self.config_entry.data.get(CONF_IP_ADDRESS, "")
        opts = self.config_entry.options

        if user_input is not None:
            new_ip: str = user_input[CONF_IP_ADDRESS].strip()

            reachable = await _validate_device_reachable(new_ip)
            if not reachable:
                errors["base"] = "cannot_connect"
            else:
                # Update IP in config entry data
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_IP_ADDRESS: new_ip},
                )
                return self.async_create_entry(title="", data={
                    CONF_DIM_ENABLED:      user_input.get(CONF_DIM_ENABLED, False),
                    CONF_DIM_START:        user_input.get(CONF_DIM_START, "22:00"),
                    CONF_DIM_END:          user_input.get(CONF_DIM_END, "07:00"),
                    CONF_DIM_LEVEL:        user_input.get(CONF_DIM_LEVEL, 5),
                    CONF_DIM_RESTORE:      user_input.get(CONF_DIM_RESTORE, 255),
                    CONF_MONITOR_ENABLED:  user_input.get(CONF_MONITOR_ENABLED, False),
                    CONF_MONITOR_INTERVAL: user_input.get(CONF_MONITOR_INTERVAL, 10),
                })

        schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS, default=current_ip): str,
                vol.Optional(CONF_DIM_ENABLED, default=opts.get(CONF_DIM_ENABLED, False)): bool,
                vol.Optional(CONF_DIM_START,   default=opts.get(CONF_DIM_START, "22:00")): str,
                vol.Optional(CONF_DIM_END,     default=opts.get(CONF_DIM_END, "07:00")): str,
                vol.Optional(CONF_DIM_LEVEL,   default=opts.get(CONF_DIM_LEVEL, 5)):
                    vol.All(int, vol.Range(min=0, max=255)),
                vol.Optional(CONF_DIM_RESTORE, default=opts.get(CONF_DIM_RESTORE, 255)):
                    vol.All(int, vol.Range(min=0, max=255)),
                vol.Optional(CONF_MONITOR_ENABLED,  default=opts.get(CONF_MONITOR_ENABLED, False)): bool,
                vol.Optional(CONF_MONITOR_INTERVAL, default=opts.get(CONF_MONITOR_INTERVAL, 10)):
                    vol.All(int, vol.Range(min=1, max=300)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )


class MiniScreenMonitorSubentryFlow(ConfigSubentryFlow):
    """Flow for adding / editing a monitored sensor subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle adding a new monitored sensor."""
        return await self._show_form(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle editing an existing monitored sensor."""
        return await self._show_form(user_input, reconfigure=True)

    async def _show_form(
        self,
        user_input: dict[str, Any] | None,
        reconfigure: bool = False,
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        existing: dict[str, Any] = {}
        if reconfigure:
            existing = dict(self._get_reconfigure_subentry().data)

        if user_input is not None:
            try:
                entity_id = str(user_input["entity_id"]).strip()
                label = str(user_input.get("label", "")).strip()
                min_value = float(user_input.get("min_value", 0))
                max_value = float(user_input.get("max_value", 100))
                value_type = str(user_input.get("value_type", "percentage"))
                unit = str(user_input.get("unit", "")).strip()
                threshold = float(user_input.get("threshold", 0))
                value_font_size = int(user_input.get("value_font_size", "1"))
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_monitor_config"
            else:
                if not entity_id or value_type not in {"percentage", "raw"}:
                    errors["base"] = "invalid_monitor_config"
                elif max_value <= min_value:
                    errors["base"] = "invalid_range"
                elif value_type == "percentage" and not 0 <= threshold <= 100:
                    errors["base"] = "threshold_range"
                elif value_font_size not in {1, 2}:
                    errors["base"] = "invalid_monitor_config"
                else:
                    title = label or entity_id.split(".")[-1].replace("_", " ").title()
                    data = {
                        "entity_id": entity_id,
                        "label": label,
                        "min_value": min_value,
                        "max_value": max_value,
                        "value_type": value_type,
                        "unit": unit,
                        "threshold": threshold,
                        "value_font_size": value_font_size,
                    }
                    if reconfigure:
                        return self.async_update_and_abort(
                            self._get_entry(),
                            self._get_reconfigure_subentry(),
                            title=title,
                            data=data,
                        )
                    return self.async_create_entry(title=title, data=data)

        schema = vol.Schema({
            vol.Required("entity_id", default=existing.get("entity_id", "")): EntitySelector(),
            vol.Optional("label", default=existing.get("label", "")): str,
            vol.Optional("min_value", default=existing.get("min_value", 0)): vol.Coerce(float),
            vol.Optional("max_value", default=existing.get("max_value", 100)): vol.Coerce(float),
            vol.Optional("value_type", default=existing.get("value_type", "percentage")): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="percentage", label="Percentage"),
                        SelectOptionDict(value="raw", label="Raw value"),
                    ]
                )
            ),
            vol.Optional("unit", default=existing.get("unit", "")): str,
            vol.Optional("threshold", default=existing.get("threshold", 0)): vol.Coerce(float),
            vol.Optional(
                "value_font_size",
                default=str(existing.get("value_font_size", 1)),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="1", label="Small (10 px)"),
                        SelectOptionDict(value="2", label="Medium (16 px)"),
                    ]
                )
            ),
        })

        step_id = "reconfigure" if reconfigure else "user"
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)
