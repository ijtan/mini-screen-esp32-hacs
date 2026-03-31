"""Mini Screen ESP32 device actions for the HA automation editor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import DOMAIN, _flash_device, _send_message_to_device

ACTION_SEND_NORMAL = "send_normal"
ACTION_SEND_BIG = "send_big"
ACTION_SEND_IMPORTANT = "send_important"
ACTION_SEND_CRITICAL = "send_critical"
ACTION_SEND_INVERTED = "send_inverted"
ACTION_SEND_INVERTED_BIG = "send_inverted_big"
ACTION_SEND_UPDATEABLE = "send_updateable"
ACTION_FLASH = "flash"

_STYLE_MAP = {
    ACTION_SEND_NORMAL: "normal",
    ACTION_SEND_BIG: "big",
    ACTION_SEND_IMPORTANT: "important",
    ACTION_SEND_CRITICAL: "critical",
    ACTION_SEND_INVERTED: "inverted",
    ACTION_SEND_INVERTED_BIG: "inverted_big",
    ACTION_SEND_UPDATEABLE: "updateable",
}

_ALL_ACTIONS = [
    (ACTION_SEND_NORMAL,      "Send normal message"),
    (ACTION_SEND_BIG,         "Send big message"),
    (ACTION_SEND_IMPORTANT,   "Send important message (flashes 15×)"),
    (ACTION_SEND_CRITICAL,    "Send critical message (flashes 25×)"),
    (ACTION_SEND_INVERTED,    "Send inverted message"),
    (ACTION_SEND_INVERTED_BIG,"Send inverted big message"),
    (ACTION_SEND_UPDATEABLE,  "Send updateable message"),
    (ACTION_FLASH,            "Flash screen"),
]

ACTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_DOMAIN): DOMAIN,
        vol.Required(CONF_TYPE): vol.In([a[0] for a in _ALL_ACTIONS]),
        vol.Optional("message", default=""): str,
        vol.Optional("font_size", default=2): vol.All(int, vol.Range(min=1, max=3)),
        vol.Optional("duration", default=5): vol.All(int, vol.Range(min=1, max=300)),
        vol.Optional("show", default=True): bool,
    }
)


async def async_get_actions(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """Return device actions for a Mini Screen ESP32 device."""
    if _get_entry_data_for_device(hass, device_id) is None:
        return []
    base = {CONF_DEVICE_ID: device_id, CONF_DOMAIN: DOMAIN}
    return [{**base, CONF_TYPE: action_type} for action_type, _ in _ALL_ACTIONS]


async def async_get_action_capabilities(
    hass: HomeAssistant, config: dict[str, Any]
) -> dict[str, vol.Schema]:
    """Return extra fields shown in the automation editor for each action type."""
    action_type = config[CONF_TYPE]

    if action_type == ACTION_FLASH:
        return {}

    fields: dict = {vol.Required("message"): str}

    if action_type == ACTION_SEND_UPDATEABLE:
        fields[vol.Optional("font_size", default=2)] = vol.All(
            int, vol.Range(min=1, max=3)
        )
        fields[vol.Optional("duration", default=5)] = vol.All(
            int, vol.Range(min=1, max=300)
        )
        fields[vol.Optional("show", default=True)] = bool

    return {"extra_fields": vol.Schema(fields)}


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: dict[str, Any],
    variables: dict[str, Any],
    context: Context | None,
) -> None:
    """Execute a device action."""
    entry_data = _get_entry_data_for_device(hass, config[CONF_DEVICE_ID])
    if entry_data is None:
        return

    ip_address: str = entry_data["ip_address"]
    action_type: str = config[CONF_TYPE]

    if action_type == ACTION_FLASH:
        hass.async_create_task(_flash_device(ip_address))
        return

    hass.async_create_task(
        _send_message_to_device(
            ip_address=ip_address,
            message=config.get("message", ""),
            style=_STYLE_MAP[action_type],
            font_size=config.get("font_size", 2),
            duration=config.get("duration", 5),
            show=config.get("show", True),
        )
    )


def _get_entry_data_for_device(
    hass: HomeAssistant, device_id: str
) -> dict[str, Any] | None:
    """Find the config entry data for a given device_id."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is not None:
            return entry_data
    return None
