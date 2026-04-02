"""Switch platform for Mini Screen ESP32 — Monitoring Enabled toggle."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MONITOR_ENABLED, CONF_NAME
from .helpers import device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Monitoring Enabled switch."""
    async_add_entities([MiniScreenMonitorSwitch(entry)])


class MiniScreenMonitorSwitch(SwitchEntity):
    """Switch that enables/disables sensor monitoring for one Mini Screen device."""

    _attr_has_entity_name = True
    _attr_name = "Monitoring"
    _attr_icon = "mdi:monitor-eye"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_monitor_switch"
        self._attr_device_info = device_info(entry.entry_id, entry.data[CONF_NAME])

    @property
    def is_on(self) -> bool:
        return bool(self._entry.options.get(CONF_MONITOR_ENABLED, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_MONITOR_ENABLED: True},
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_MONITOR_ENABLED: False},
        )
        self.async_write_ha_state()
