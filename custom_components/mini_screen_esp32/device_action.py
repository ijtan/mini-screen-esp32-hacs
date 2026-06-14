"""Mini Screen ESP32 device actions for the HA automation editor.

Each device action simply builds the data for, and delegates to, the matching
domain service registered in ``__init__.py``. This keeps a single source of
truth for behaviour (display-ownership / pause handling, templating, etc.) so
the automation-editor path and the service path can never drift apart.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# ── Action type constants ─────────────────────────────────────────────────────
ACTION_SEND_NORMAL      = "send_normal"
ACTION_SEND_BIG         = "send_big"
ACTION_SEND_IMPORTANT   = "send_important"
ACTION_SEND_CRITICAL    = "send_critical"
ACTION_SEND_INVERTED    = "send_inverted"
ACTION_SEND_INVERTED_BIG = "send_inverted_big"
ACTION_SEND_UPDATEABLE  = "send_updateable"
ACTION_FLASH            = "flash"
ACTION_CLEAR            = "clear"
ACTION_UNPIN            = "unpin"
ACTION_SET_BRIGHTNESS   = "set_brightness"
ACTION_PIN_MESSAGE      = "pin_message"
ACTION_SCROLL_MESSAGE   = "scroll_message"
ACTION_SHOW_PROGRESS    = "show_progress"
ACTION_PIN_SENSOR_PROGRESS = "pin_sensor_progress"
ACTION_PIN_SENSOR       = "pin_sensor"
ACTION_UNPIN_SENSOR     = "unpin_sensor"
ACTION_SEND_IMAGE       = "send_image"

_STYLE_MAP = {
    ACTION_SEND_NORMAL:      "normal",
    ACTION_SEND_BIG:         "big",
    ACTION_SEND_IMPORTANT:   "important",
    ACTION_SEND_CRITICAL:    "critical",
    ACTION_SEND_INVERTED:    "inverted",
    ACTION_SEND_INVERTED_BIG: "inverted_big",
    ACTION_SEND_UPDATEABLE:  "updateable",
}

_ALL_ACTIONS: list[tuple[str, str]] = [
    (ACTION_SEND_NORMAL,       "Send normal message"),
    (ACTION_SEND_BIG,          "Send big message"),
    (ACTION_SEND_IMPORTANT,    "Send important message (flashes 15×)"),
    (ACTION_SEND_CRITICAL,     "Send critical message (flashes 25×)"),
    (ACTION_SEND_INVERTED,     "Send inverted message"),
    (ACTION_SEND_INVERTED_BIG, "Send inverted big message"),
    (ACTION_SEND_UPDATEABLE,   "Send updateable message"),
    (ACTION_FLASH,             "Flash screen"),
    (ACTION_CLEAR,             "Clear display"),
    (ACTION_UNPIN,             "Unpin display"),
    (ACTION_SET_BRIGHTNESS,    "Set brightness"),
    (ACTION_PIN_MESSAGE,       "Pin message"),
    (ACTION_SCROLL_MESSAGE,    "Scroll message"),
    (ACTION_SHOW_PROGRESS,          "Show progress bar"),
    (ACTION_PIN_SENSOR_PROGRESS,    "Track sensor as progress bar"),
    (ACTION_PIN_SENSOR,             "Track sensor (pin value)"),
    (ACTION_UNPIN_SENSOR,           "Unpin sensor"),
    (ACTION_SEND_IMAGE,             "Send image"),
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
        vol.Optional("level", default=128): vol.All(int, vol.Range(min=0, max=255)),
        vol.Optional("value", default=0): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("label", default=""): str,
        vol.Optional("entity_id", default=""): str,
        vol.Optional("template", default="{{ value }}"): str,
        vol.Optional("min_value", default=0): vol.Coerce(float),
        vol.Optional("max_value", default=100): vol.Coerce(float),
        vol.Optional("value_text", default=""): str,
        vol.Optional("image_url", default=""): str,
        vol.Optional("dither", default=True): bool,
        vol.Optional("auto_clear_delay", default=0): vol.All(int, vol.Range(min=0, max=300)),
        vol.Optional("value_font_size", default=1): vol.All(int, vol.Range(min=1, max=2)),
        vol.Optional("unit", default=""): str,
        vol.Optional("value_type", default="percentage"): vol.In(["percentage", "raw"]),
        vol.Optional("crit_threshold", default=0): vol.Coerce(float),
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

    # Actions with no extra fields
    if action_type in (ACTION_FLASH, ACTION_CLEAR, ACTION_UNPIN, ACTION_UNPIN_SENSOR):
        return {}

    fields: dict = {}

    if action_type in _STYLE_MAP:
        # All send_* actions require a message
        fields[vol.Required("message")] = str
        if action_type == ACTION_SEND_UPDATEABLE:
            fields[vol.Optional("font_size", default=2)] = vol.All(
                int, vol.Range(min=1, max=3)
            )
            fields[vol.Optional("duration", default=5)] = vol.All(
                int, vol.Range(min=1, max=300)
            )
            fields[vol.Optional("show", default=True)] = bool

    elif action_type == ACTION_SET_BRIGHTNESS:
        fields[vol.Required("level")] = vol.All(int, vol.Range(min=0, max=255))

    elif action_type == ACTION_PIN_MESSAGE:
        fields[vol.Required("message")] = str
        fields[vol.Optional("font_size", default=2)] = vol.All(
            int, vol.Range(min=1, max=3)
        )

    elif action_type == ACTION_SCROLL_MESSAGE:
        fields[vol.Required("message")] = str
        fields[vol.Optional("font_size", default=2)] = vol.All(
            int, vol.Range(min=1, max=3)
        )

    elif action_type == ACTION_SHOW_PROGRESS:
        fields[vol.Required("value")] = vol.All(int, vol.Range(min=0, max=100))
        fields[vol.Optional("label", default="")] = str
        fields[vol.Optional("auto_clear_delay", default=0)] = vol.All(int, vol.Range(min=0, max=300))
        fields[vol.Optional("value_font_size", default=1)] = vol.All(int, vol.Range(min=1, max=2))
        fields[vol.Optional("crit_threshold", default=0)] = vol.All(int, vol.Range(min=0, max=100))

    elif action_type == ACTION_PIN_SENSOR_PROGRESS:
        fields[vol.Required("entity_id")] = str
        fields[vol.Optional("min_value", default=0)] = vol.Coerce(float)
        fields[vol.Optional("max_value", default=100)] = vol.Coerce(float)
        fields[vol.Optional("label", default="")] = str
        fields[vol.Optional("value_type", default="percentage")] = vol.In(["percentage", "raw"])
        fields[vol.Optional("value_text", default="")] = str
        fields[vol.Optional("unit", default="")] = str
        fields[vol.Optional("auto_clear_delay", default=0)] = vol.All(int, vol.Range(min=0, max=300))
        fields[vol.Optional("value_font_size", default=1)] = vol.All(int, vol.Range(min=1, max=2))
        fields[vol.Optional("crit_threshold", default=0)] = vol.Coerce(float)

    elif action_type == ACTION_PIN_SENSOR:
        fields[vol.Required("entity_id")] = str
        fields[vol.Optional("template", default="{{ value }}")] = str
        fields[vol.Optional("font_size", default=2)] = vol.All(
            int, vol.Range(min=1, max=3)
        )

    elif action_type == ACTION_SEND_IMAGE:
        fields[vol.Required("image_url")] = str
        fields[vol.Optional("dither", default=True)] = bool

    return {"extra_fields": vol.Schema(fields)}


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: dict[str, Any],
    variables: dict[str, Any],
    context: Context | None,
) -> None:
    """Execute a device action by delegating to the matching domain service."""
    entry_data = _get_entry_data_for_device(hass, config[CONF_DEVICE_ID])
    if entry_data is None:
        return

    action_type: str = config[CONF_TYPE]
    # Target this device specifically; services match on the device name.
    data: dict[str, Any] = {"device_name": entry_data["name"]}

    if action_type in _STYLE_MAP:
        service = "send_message"
        data["message"] = config.get("message", "")
        data["style"] = _STYLE_MAP[action_type]
        if action_type == ACTION_SEND_UPDATEABLE:
            data["font_size"] = config.get("font_size", 2)
            data["duration"] = config.get("duration", 5)
            data["show"] = config.get("show", True)
    elif action_type == ACTION_FLASH:
        service = "flash"
    elif action_type == ACTION_CLEAR:
        service = "clear"
    elif action_type == ACTION_UNPIN:
        service = "unpin"
    elif action_type == ACTION_UNPIN_SENSOR:
        service = "unpin_sensor"
    elif action_type == ACTION_SET_BRIGHTNESS:
        service = "set_brightness"
        data["level"] = config.get("level", 128)
    elif action_type == ACTION_PIN_MESSAGE:
        service = "pin_message"
        data["message"] = config.get("message", "")
        data["font_size"] = config.get("font_size", 2)
    elif action_type == ACTION_SCROLL_MESSAGE:
        service = "scroll_message"
        data["message"] = config.get("message", "")
        data["font_size"] = config.get("font_size", 2)
    elif action_type == ACTION_SHOW_PROGRESS:
        service = "show_progress"
        data["value"] = config.get("value", 0)
        if config.get("label"):
            data["label"] = config["label"]
        if int(config.get("auto_clear_delay", 0)) > 0:
            data["auto_clear_delay"] = int(config["auto_clear_delay"])
        if int(config.get("value_font_size", 1)) == 2:
            data["value_font_size"] = 2
        if int(config.get("crit_threshold", 0)) > 0:
            data["crit_threshold"] = int(config["crit_threshold"])
    elif action_type == ACTION_PIN_SENSOR:
        service = "pin_sensor"
        data["entity_id"] = config.get("entity_id", "")
        data["template"] = config.get("template", "{{ value }}")
        data["font_size"] = config.get("font_size", 2)
    elif action_type == ACTION_PIN_SENSOR_PROGRESS:
        service = "pin_sensor_progress"
        data["entity_id"] = config.get("entity_id", "")
        data["min_value"] = float(config.get("min_value", 0))
        data["max_value"] = float(config.get("max_value", 100))
        if config.get("label"):
            data["label"] = config["label"]
        data["value_type"] = config.get("value_type", "percentage")
        if config.get("unit"):
            data["unit"] = config["unit"]
        if config.get("value_text"):
            data["value_text"] = config["value_text"]
        if int(config.get("auto_clear_delay", 0)) > 0:
            data["auto_clear_delay"] = int(config["auto_clear_delay"])
        if int(config.get("value_font_size", 1)) == 2:
            data["value_font_size"] = 2
        if float(config.get("crit_threshold", 0)) != 0:
            data["crit_threshold"] = float(config["crit_threshold"])
    elif action_type == ACTION_SEND_IMAGE:
        if not config.get("image_url"):
            return
        service = "send_image"
        data["image_url"] = config["image_url"]
        data["dither"] = config.get("dither", True)
    else:
        return

    await hass.services.async_call(
        DOMAIN, service, data, blocking=False, context=context
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
