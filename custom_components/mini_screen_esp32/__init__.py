"""Mini Screen ESP32 Home Assistant Integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

DOMAIN = "mini_screen_esp32"
PLATFORMS = ["notify"]

CONF_IP_ADDRESS = "ip_address"
CONF_NAME = "name"

# Style -> endpoint mapping
STYLE_ENDPOINTS: dict[str, str] = {
    "normal": "/update",
    "big": "/updateBig",
    "important": "/updateImportant",
    "critical": "/updateCritical",
    "inverted": "/updateInverted",
    "inverted_big": "/updateInvertedBig",
    "updateable": "/updateBigChangeable",
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Mini Screen ESP32 component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Mini Screen ESP32 from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    ip_address: str = entry.data[CONF_IP_ADDRESS]
    name: str = entry.data[CONF_NAME]

    hass.data[DOMAIN][entry.entry_id] = {
        "ip_address": ip_address,
        "name": name,
        "entry": entry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once — only on the first entry
    if not hass.services.has_service(DOMAIN, "send_message"):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove services only when the last entry is removed
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, "send_message")
        hass.services.async_remove(DOMAIN, "flash")

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register domain-level services."""

    async def handle_send_message(call: ServiceCall) -> None:
        """Handle the send_message service call."""
        message: str = call.data["message"]
        style: str = call.data.get("style", "normal")
        font_size: int = int(call.data.get("font_size", 2))
        duration: int = int(call.data.get("duration", 5))
        show: bool = bool(call.data.get("show", True))
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "send_message: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            hass.async_create_task(
                _send_message_to_device(
                    ip_address=entry_data["ip_address"],
                    message=message,
                    style=style,
                    font_size=font_size,
                    duration=duration,
                    show=show,
                )
            )

    async def handle_flash(call: ServiceCall) -> None:
        """Handle the flash service call."""
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "flash: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            hass.async_create_task(_flash_device(ip_address=entry_data["ip_address"]))

    hass.services.async_register(DOMAIN, "send_message", handle_send_message)
    hass.services.async_register(DOMAIN, "flash", handle_flash)


def _get_matching_entries(
    hass: HomeAssistant, device_name: str | None
) -> list[dict[str, Any]]:
    """Return entries matching device_name, or all entries if device_name is None."""
    all_entries: dict[str, dict[str, Any]] = hass.data.get(DOMAIN, {})
    if device_name is None:
        return list(all_entries.values())
    return [
        entry_data
        for entry_data in all_entries.values()
        if entry_data["name"] == device_name
    ]


async def _send_message_to_device(
    ip_address: str,
    message: str,
    style: str = "normal",
    font_size: int = 2,
    duration: int = 5,
    show: bool = True,
) -> None:
    """Send a message to a single device."""
    endpoint = STYLE_ENDPOINTS.get(style, "/update")
    url = f"http://{ip_address}{endpoint}"

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
                        ip_address,
                        response.status,
                        endpoint,
                    )
    except asyncio.CancelledError:
        _LOGGER.debug("Request to Mini Screen ESP32 at %s was cancelled", ip_address)
    except aiohttp.ClientError as err:
        _LOGGER.warning("Cannot connect to Mini Screen ESP32 at %s: %s", ip_address, err)


async def _flash_device(ip_address: str) -> None:
    """Flash the screen on a single device."""
    url = f"http://{ip_address}/flashScreenBright5"
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status >= 400:
                    _LOGGER.warning(
                        "Mini Screen ESP32 at %s returned HTTP %s for /flashScreenBright5",
                        ip_address,
                        response.status,
                    )
    except asyncio.CancelledError:
        _LOGGER.debug("Flash request to Mini Screen ESP32 at %s was cancelled", ip_address)
    except aiohttp.ClientError as err:
        _LOGGER.warning("Cannot connect to Mini Screen ESP32 at %s: %s", ip_address, err)
