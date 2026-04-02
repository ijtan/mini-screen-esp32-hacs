"""Mini Screen ESP32 device actions for the HA automation editor."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_state_change_event

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
        fields[vol.Optional("warn_enabled", default=False)] = bool
        fields[vol.Optional("warn_threshold", default=80)] = vol.Coerce(float)
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
        params: dict = {
            "value": config.get("value", 0),
            "label": config.get("label", ""),
        }
        acd = int(config.get("auto_clear_delay", 0))
        if acd > 0:
            params["auto_clear_delay"] = acd
        vfs = int(config.get("value_font_size", 1))
        if vfs == 2:
            params["value_font_size"] = 2
        crit = max(0, min(100, int(config.get("crit_threshold", 0))))
        if crit > 0:
            params["crit"] = crit
        hass.async_create_task(_call_device(ip=ip, path="/showProgress", params=params))
        return

    if action_type == ACTION_PIN_SENSOR_PROGRESS:
        from homeassistant.helpers.template import Template

        entity_id: str = config.get("entity_id", "")
        min_value: float = float(config.get("min_value", 0))
        max_value: float = float(config.get("max_value", 100))
        raw_label: str = config.get("label", entity_id.split(".")[-1].replace("_", " ").title())
        raw_value_text: str = config.get("value_text", "")
        unit: str = config.get("unit", "").strip()
        value_type: str = config.get("value_type", "percentage")
        auto_clear_delay: int = int(config.get("auto_clear_delay", 0))
        value_font_size: int = int(config.get("value_font_size", 1))
        crit_threshold_raw: float = float(config.get("crit_threshold", 0))

        def _threshold_to_pct(raw: float) -> int:
            if value_type == "raw":
                span = max_value - min_value
                if span == 0:
                    return 0
                return max(0, min(100, int(round((raw - min_value) / span * 100))))
            return max(0, min(100, int(round(raw))))

        def _to_percent(state_value: str) -> int:
            try:
                raw = float(state_value)
            except ValueError:
                return 0
            span = max_value - min_value
            if span == 0:
                return 0
            pct = (raw - min_value) / span * 100.0
            return max(0, min(100, int(round(pct))))

        def _build_progress_params(pct: int, raw_sensor: str) -> dict:
            label = Template(raw_label, hass).async_render(parse_result=False) if raw_label else ""
            params: dict = {"value": pct, "label": label}
            if value_type == "raw":
                if raw_value_text.strip():
                    vt = Template(raw_value_text, hass).async_render(
                        variables={"value": raw_sensor}, parse_result=False
                    )
                    params["value_text"] = vt
                else:
                    suffix = unit
                    if not suffix:
                        state = hass.states.get(entity_id)
                        suffix = (state.attributes.get("unit_of_measurement", "") if state else "")
                    params["value_text"] = f"{raw_sensor} {suffix}".strip()
            if auto_clear_delay > 0:
                params["auto_clear_delay"] = auto_clear_delay
            if value_font_size == 2:
                params["value_font_size"] = 2
            crit_pct = _threshold_to_pct(crit_threshold_raw)
            if crit_pct > 0:
                params["crit"] = crit_pct
            return params

        # Cancel existing subscription
        existing_unsub = entry_data.get("sensor_unsub")
        if existing_unsub is not None:
            existing_unsub()
            entry_data["sensor_unsub"] = None

        # Send current state immediately
        current_state = hass.states.get(entity_id)
        if current_state is not None:
            hass.async_create_task(
                _call_device(ip=ip, path="/showProgress",
                             params=_build_progress_params(
                                 _to_percent(current_state.state), current_state.state))
            )

        @callback
        def _on_progress_change(event: Event, _entry_data: dict = entry_data) -> None:
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            hass.async_create_task(
                _call_device(ip=_entry_data["ip_address"], path="/showProgress",
                             params=_build_progress_params(
                                 _to_percent(new_state.state), new_state.state))
            )

        entry_data["sensor_unsub"] = async_track_state_change_event(
            hass, [entity_id], _on_progress_change
        )
        return

    if action_type == ACTION_PIN_SENSOR:
        from homeassistant.helpers.template import Template

        entity_id = config.get("entity_id", "")
        template: str = config.get("template", "{{ value }}")
        font_size: int = int(config.get("font_size", 2))

        def _format_message(state_value: str) -> str:
            return Template(template, hass).async_render(
                variables={"value": state_value}, parse_result=False
            )

        # Cancel existing subscription
        existing_unsub = entry_data.get("sensor_unsub")
        if existing_unsub is not None:
            existing_unsub()
            entry_data["sensor_unsub"] = None

        # Send current state immediately
        current_state = hass.states.get(entity_id)
        if current_state is not None:
            hass.async_create_task(
                _call_device(ip=ip, path="/pin",
                             params={"message": _format_message(current_state.state),
                                     "font_size": font_size})
            )

        @callback
        def _on_sensor_change(event: Event, _entry_data: dict = entry_data) -> None:
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            hass.async_create_task(
                _call_device(ip=_entry_data["ip_address"], path="/pin",
                             params={"message": _format_message(new_state.state),
                                     "font_size": font_size})
            )

        entry_data["sensor_unsub"] = async_track_state_change_event(
            hass, [entity_id], _on_sensor_change
        )
        return

    if action_type == ACTION_UNPIN_SENSOR:
        unsub = entry_data.get("sensor_unsub")
        if unsub is not None:
            unsub()
            entry_data["sensor_unsub"] = None
        hass.async_create_task(_call_device(ip=ip, path="/unpin"))
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
