"""Mini Screen ESP32 button platform."""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CONF_IP_ADDRESS, CONF_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mini Screen ESP32 button entities."""
    ip_address: str = entry.data[CONF_IP_ADDRESS]
    name: str = entry.data[CONF_NAME]
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=name,
        manufacturer="ESP8266",
        model="Mini Screen OLED",
    )
    async_add_entities([
        MiniScreenRestartButton(entry.entry_id, ip_address, name, device_info),
        MiniScreenClearButton(entry.entry_id, ip_address, name, device_info),
    ])


class _MiniScreenButton(ButtonEntity):
    """Base class for Mini Screen buttons."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry_id: str,
        ip_address: str,
        device_name: str,
        device_info: DeviceInfo,
        label: str,
        unique_suffix: str,
        path: str,
    ) -> None:
        self._ip_address = ip_address
        self._path = path
        self._attr_name = label
        self._attr_unique_id = f"{entry_id}_{unique_suffix}"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        self.hass.async_create_task(self._fire())

    async def _fire(self) -> None:
        timeout = aiohttp.ClientTimeout(total=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"http://{self._ip_address}{self._path}"
                ) as response:
                    if response.status >= 400:
                        _LOGGER.warning(
                            "Mini Screen ESP32 at %s returned HTTP %s for %s",
                            self._ip_address, response.status, self._path,
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass  # Expected on restart — device reboots before responding
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(
                f"Cannot connect to Mini Screen ESP32 at {self._ip_address}: {err}"
            ) from err


class MiniScreenRestartButton(_MiniScreenButton):
    _attr_icon = "mdi:restart"

    def __init__(self, entry_id, ip_address, device_name, device_info):
        super().__init__(entry_id, ip_address, device_name, device_info,
                         "Restart", "restart", "/restart")


class MiniScreenClearButton(_MiniScreenButton):
    _attr_icon = "mdi:monitor-off"

    def __init__(self, entry_id, ip_address, device_name, device_info):
        super().__init__(entry_id, ip_address, device_name, device_info,
                         "Clear display", "clear", "/clear")
