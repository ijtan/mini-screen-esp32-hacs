"""Mini Screen ESP32 notify platform (NotifyEntity — HA 2024.8+)."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import STYLE_ENDPOINTS
from .const import CONF_IP_ADDRESS, CONF_NAME
from .helpers import device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mini Screen ESP32 notify entity from a config entry."""
    ip_address: str = entry.data[CONF_IP_ADDRESS]
    name: str = entry.data[CONF_NAME]
    async_add_entities([MiniScreenNotifyEntity(entry.entry_id, ip_address, name)])


class MiniScreenNotifyEntity(NotifyEntity):
    """Notify entity for a single Mini Screen ESP32 device."""

    _attr_has_entity_name = True

    def __init__(self, entry_id: str, ip_address: str, name: str) -> None:
        self._ip_address = ip_address
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_notify"
        self._attr_device_info = device_info(entry_id, name)

    async def async_send_message(
        self, message: str, title: str | None = None, **kwargs: Any
    ) -> None:
        """
        Send a message to the Mini Screen device.

        Extra keys supported in the ``data`` dict when calling notify.send_message:
          - ``style``     : normal | big | important | critical |
                            inverted | inverted_big | updateable  (default: normal)
          - ``font_size`` : 1 | 2 | 3  (updateable only, default 2)
          - ``duration``  : seconds to show (updateable only, default 5)
          - ``show``      : bool — false logs without displaying (updateable only)
        """
        data: dict[str, Any] = kwargs.get("data") or {}

        style: str = str(data.get("style", "normal"))
        font_size: int = int(data.get("font_size", 2))
        duration: int = int(data.get("duration", 5))
        show: bool = bool(data.get("show", True))

        endpoint = STYLE_ENDPOINTS.get(style, "/update")
        url = f"http://{self._ip_address}{endpoint}"

        params: dict[str, Any] = {"message": message}
        if style == "updateable":
            params["t"] = duration
            params["font_size"] = font_size
            params["show"] = str(show).lower()

        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status >= 400:
                        _LOGGER.warning(
                            "Mini Screen ESP32 at %s returned HTTP %s for %s",
                            self._ip_address,
                            response.status,
                            endpoint,
                        )
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Cannot connect to Mini Screen ESP32 at {self._ip_address}: {err}"
            ) from err
