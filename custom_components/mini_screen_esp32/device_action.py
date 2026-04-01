"""Mini Screen ESP32 device actions for the HA automation editor."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import DOMAIN, STYLE_ENDPOINTS, _build_send_params, _call_device

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
    (ACTION_SHOW_PROGRESS,     "Show progress bar"),
    (ACTION_SEND_IMAGE,        "Send image"),
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
    if action_type in (ACTION_FLASH, ACTION_CLEAR, ACTION_UNPIN):
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
    """Execute a device action."""
    entry_data = _get_entry_data_for_device(hass, config[CONF_DEVICE_ID])
    if entry_data is None:
        return

    ip: str = entry_data["ip_address"]
    action_type: str = config[CONF_TYPE]

    # ── No-extra-field actions ────────────────────────────────────────────────
    if action_type == ACTION_FLASH:
        hass.async_create_task(_call_device(ip=ip, path="/flashScreenBright5"))
        return

    if action_type == ACTION_CLEAR:
        hass.async_create_task(_call_device(ip=ip, path="/clear"))
        return

    if action_type == ACTION_UNPIN:
        hass.async_create_task(_call_device(ip=ip, path="/unpin"))
        return

    # ── Send-message family ───────────────────────────────────────────────────
    if action_type in _STYLE_MAP:
        style = _STYLE_MAP[action_type]
        params = _build_send_params(
            message=config.get("message", ""),
            style=style,
            font_size=config.get("font_size", 2),
            duration=config.get("duration", 5),
            show=config.get("show", True),
        )
        hass.async_create_task(
            _call_device(ip=ip, path=STYLE_ENDPOINTS.get(style, "/update"), params=params)
        )
        return

    # ── New actions ───────────────────────────────────────────────────────────
    if action_type == ACTION_SET_BRIGHTNESS:
        hass.async_create_task(
            _call_device(
                ip=ip,
                path="/setBrightness",
                params={"level": config.get("level", 128)},
            )
        )
        return

    if action_type == ACTION_PIN_MESSAGE:
        hass.async_create_task(
            _call_device(
                ip=ip,
                path="/pin",
                params={
                    "message": config.get("message", ""),
                    "font_size": config.get("font_size", 2),
                },
            )
        )
        return

    if action_type == ACTION_SCROLL_MESSAGE:
        hass.async_create_task(
            _call_device(
                ip=ip,
                path="/scroll",
                params={
                    "message": config.get("message", ""),
                    "font_size": config.get("font_size", 2),
                },
            )
        )
        return

    if action_type == ACTION_SHOW_PROGRESS:
        hass.async_create_task(
            _call_device(
                ip=ip,
                path="/showProgress",
                params={
                    "value": config.get("value", 0),
                    "label": config.get("label", ""),
                },
            )
        )
        return

    if action_type == ACTION_SEND_IMAGE:
        image_url: str = config.get("image_url", "")
        dither: bool = config.get("dither", True)
        if not image_url:
            return

        async def _send_image_action() -> None:
            import io
            import urllib.request
            from PIL import Image

            def load_and_convert() -> bytes:
                with urllib.request.urlopen(image_url, timeout=15) as resp:
                    img = Image.open(io.BytesIO(resp.read())).convert("RGB")
                img = img.resize((128, 64), Image.LANCZOS)
                dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
                img = img.convert("1", dither=dither_mode)
                raw = bytearray(1024)
                for y in range(64):
                    for x in range(128):
                        pixel = img.getpixel((x, y))
                        if pixel:
                            byte_idx = (y * 128 + x) // 8
                            bit_idx  = 7 - ((y * 128 + x) % 8)
                            raw[byte_idx] |= (1 << bit_idx)
                return bytes(raw)

            try:
                import aiohttp
                bitmap_bytes = await hass.async_add_executor_job(load_and_convert)
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"http://{ip}/drawBitmap",
                        data=bitmap_bytes,
                        headers={"Content-Type": "application/octet-stream"},
                    ) as response:
                        if response.status >= 400:
                            _LOGGER.warning(
                                "Mini Screen ESP32 at %s returned HTTP %s for /drawBitmap",
                                ip, response.status,
                            )
            except Exception as err:
                _LOGGER.warning("send_image action failed for %s: %s", ip, err)

        hass.async_create_task(_send_image_action())
        return


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
