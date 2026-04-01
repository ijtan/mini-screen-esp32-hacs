"""Mini Screen ESP32 Home Assistant Integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

DOMAIN = "mini_screen_esp32"
PLATFORMS = ["notify", "button"]

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

# All service names — used when removing on last entry unload
_ALL_SERVICES = [
    "send_message",
    "flash",
    "clear",
    "unpin",
    "set_brightness",
    "pin_message",
    "scroll_message",
    "show_progress",
    "pin_sensor",
    "pin_sensor_progress",
    "unpin_sensor",
    "send_image",
]


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
        "sensor_unsub": None,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once — only on the first entry
    if not hass.services.has_service(DOMAIN, "send_message"):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Cancel sensor subscription if active
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is not None:
        unsub = entry_data.get("sensor_unsub")
        if unsub is not None:
            unsub()
            entry_data["sensor_unsub"] = None

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove services only when the last entry is removed
    if not hass.data[DOMAIN]:
        for service_name in _ALL_SERVICES:
            hass.services.async_remove(DOMAIN, service_name)

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register domain-level services."""

    # ── send_message ──────────────────────────────────────────────────────────
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
                _call_device(
                    ip=entry_data["ip_address"],
                    path=STYLE_ENDPOINTS.get(style, "/update"),
                    params=_build_send_params(message, style, font_size, duration, show),
                )
            )

    # ── flash ─────────────────────────────────────────────────────────────────
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
            hass.async_create_task(
                _call_device(ip=entry_data["ip_address"], path="/flashScreenBright5")
            )

    # ── clear ─────────────────────────────────────────────────────────────────
    async def handle_clear(call: ServiceCall) -> None:
        """Handle the clear service call."""
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "clear: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            # Cancel any active sensor subscription for this entry
            unsub = entry_data.get("sensor_unsub")
            if unsub is not None:
                unsub()
                entry_data["sensor_unsub"] = None
            hass.async_create_task(
                _call_device(ip=entry_data["ip_address"], path="/clear")
            )

    # ── unpin ─────────────────────────────────────────────────────────────────
    async def handle_unpin(call: ServiceCall) -> None:
        """Handle the unpin service call."""
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "unpin: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            hass.async_create_task(
                _call_device(ip=entry_data["ip_address"], path="/unpin")
            )

    # ── set_brightness ────────────────────────────────────────────────────────
    async def handle_set_brightness(call: ServiceCall) -> None:
        """Handle the set_brightness service call."""
        level: int = int(call.data["level"])
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "set_brightness: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            hass.async_create_task(
                _call_device(
                    ip=entry_data["ip_address"],
                    path="/setBrightness",
                    params={"level": level},
                )
            )

    # ── pin_message ───────────────────────────────────────────────────────────
    async def handle_pin_message(call: ServiceCall) -> None:
        """Handle the pin_message service call."""
        message: str = call.data["message"]
        font_size: int = int(call.data.get("font_size", 2))
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "pin_message: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            hass.async_create_task(
                _call_device(
                    ip=entry_data["ip_address"],
                    path="/pin",
                    params={"message": message, "font_size": font_size},
                )
            )

    # ── scroll_message ────────────────────────────────────────────────────────
    async def handle_scroll_message(call: ServiceCall) -> None:
        """Handle the scroll_message service call."""
        message: str = call.data["message"]
        font_size: int = int(call.data.get("font_size", 2))
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "scroll_message: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            hass.async_create_task(
                _call_device(
                    ip=entry_data["ip_address"],
                    path="/scroll",
                    params={"message": message, "font_size": font_size},
                )
            )

    # ── show_progress ─────────────────────────────────────────────────────────
    async def handle_show_progress(call: ServiceCall) -> None:
        """Handle the show_progress service call."""
        from homeassistant.helpers.template import Template

        value: int = int(call.data["value"])
        device_name: str | None = call.data.get("device_name")

        # Render label template if provided
        raw_label: str = call.data.get("label", "")
        label = Template(raw_label, hass).async_render(parse_result=False) if raw_label else ""

        # value_text: None = not provided (use default %), " " = hide, else custom/template
        raw_value_text: str | None = call.data.get("value_text")
        if raw_value_text is None:
            value_text = ""  # firmware default: show X%
        elif raw_value_text.strip() == "":
            value_text = "__hide__"  # hide entirely
        else:
            value_text = Template(raw_value_text, hass).async_render(parse_result=False)

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "show_progress: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        params: dict[str, Any] = {"value": value, "label": label}
        if value_text:
            params["value_text"] = value_text

        for entry_data in entries:
            hass.async_create_task(
                _call_device(
                    ip=entry_data["ip_address"],
                    path="/showProgress",
                    params=params,
                )
            )

    # ── pin_sensor ────────────────────────────────────────────────────────────
    async def handle_pin_sensor(call: ServiceCall) -> None:
        """
        Track a sensor entity and pin its formatted value to the screen.

        Fields:
          entity_id  – entity to track
          template   – Jinja-like placeholder; use {{ value }} for the state
          font_size  – 1-3 (default 2)
          device_name – optional target device
        """
        entity_id: str = call.data["entity_id"]
        template: str = call.data.get("template", "{{ value }}")
        font_size: int = int(call.data.get("font_size", 2))
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "pin_sensor: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        def _format_message(state_value: str, tmpl: str) -> str:
            return tmpl.replace("{{ value }}", state_value).replace("{{value}}", state_value)

        for entry_data in entries:
            # Cancel existing subscription
            existing_unsub = entry_data.get("sensor_unsub")
            if existing_unsub is not None:
                existing_unsub()
                entry_data["sensor_unsub"] = None

            # Send the current state immediately
            current_state = hass.states.get(entity_id)
            if current_state is not None:
                msg = _format_message(current_state.state, template)
                hass.async_create_task(
                    _call_device(
                        ip=entry_data["ip_address"],
                        path="/pin",
                        params={"message": msg, "font_size": font_size},
                    )
                )

            # Set up listener — use default args to capture loop variables correctly
            @callback
            def _on_state_change(
                event: Event,
                _entry_data: dict = entry_data,
                _template: str = template,
                _font_size: int = font_size,
            ) -> None:
                new_state = event.data.get("new_state")
                if new_state is None:
                    return
                msg = _format_message(new_state.state, _template)
                hass.async_create_task(
                    _call_device(
                        ip=_entry_data["ip_address"],
                        path="/pin",
                        params={"message": msg, "font_size": _font_size},
                    )
                )

            unsub = async_track_state_change_event(hass, [entity_id], _on_state_change)
            entry_data["sensor_unsub"] = unsub

    # ── pin_sensor_progress ───────────────────────────────────────────────────
    async def handle_pin_sensor_progress(call: ServiceCall) -> None:
        """
        Track a sensor and show its value as a progress bar.

        Fields:
          entity_id   – entity to track
          min_value   – value that maps to 0 % (default 0)
          max_value   – value that maps to 100 % (default 100)
          label       – bar label (default: derived from entity_id)
          device_name – optional target device
        """
        entity_id: str = call.data["entity_id"]
        min_value: float = float(call.data.get("min_value", 0))
        max_value: float = float(call.data.get("max_value", 100))
        device_name: str | None = call.data.get("device_name")

        from homeassistant.helpers.template import Template

        # Default label: last part of entity_id, underscores → spaces, title case
        default_label = entity_id.split(".")[-1].replace("_", " ").title()
        raw_label: str = call.data.get("label", default_label)
        raw_value_text: str | None = call.data.get("value_text")

        def _render_label() -> str:
            return Template(raw_label, hass).async_render(parse_result=False) if raw_label else ""

        def _render_value_text() -> str:
            if raw_value_text is None:
                return ""
            if raw_value_text.strip() == "":
                return "__hide__"
            return Template(raw_value_text, hass).async_render(parse_result=False)

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "pin_sensor_progress: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

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

        for entry_data in entries:
            # Cancel existing subscription
            existing_unsub = entry_data.get("sensor_unsub")
            if existing_unsub is not None:
                existing_unsub()
                entry_data["sensor_unsub"] = None

            def _build_progress_params(pct: int) -> dict:
                params: dict = {"value": pct, "label": _render_label()}
                vt = _render_value_text()
                if vt:
                    params["value_text"] = vt
                return params

            # Send current state immediately
            current_state = hass.states.get(entity_id)
            if current_state is not None:
                pct = _to_percent(current_state.state)
                hass.async_create_task(
                    _call_device(
                        ip=entry_data["ip_address"],
                        path="/showProgress",
                        params=_build_progress_params(pct),
                    )
                )

            # Set up listener — capture loop variables via default args
            @callback
            def _on_state_change_progress(
                event: Event,
                _entry_data: dict = entry_data,
            ) -> None:
                new_state = event.data.get("new_state")
                if new_state is None:
                    return
                pct = _to_percent(new_state.state)
                hass.async_create_task(
                    _call_device(
                        ip=_entry_data["ip_address"],
                        path="/showProgress",
                        params=_build_progress_params(pct),
                    )
                )

            unsub = async_track_state_change_event(
                hass, [entity_id], _on_state_change_progress
            )
            entry_data["sensor_unsub"] = unsub

    # ── unpin_sensor ──────────────────────────────────────────────────────────
    async def handle_unpin_sensor(call: ServiceCall) -> None:
        """Cancel sensor tracking and unpin the display."""
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "unpin_sensor: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            unsub = entry_data.get("sensor_unsub")
            if unsub is not None:
                unsub()
                entry_data["sensor_unsub"] = None
            hass.async_create_task(
                _call_device(ip=entry_data["ip_address"], path="/unpin")
            )

    # ── send_image ────────────────────────────────────────────────────────────
    async def handle_send_image(call: ServiceCall) -> None:
        """Convert an image to a 1-bit bitmap and send to the display."""
        import io
        from PIL import Image

        image_path: str = call.data["image_path"]
        dither: bool = bool(call.data.get("dither", True))
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "send_image: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)", device_name,
            )
            return

        # Load and convert image in executor to avoid blocking the event loop
        def convert_image() -> bytes:
            img = Image.open(image_path).convert("RGB")
            img = img.resize((128, 64), Image.LANCZOS)
            dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
            img = img.convert("1", dither=dither_mode)
            # Pack into raw bytes: each byte = 8 horizontal pixels, MSB first
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
            bitmap_bytes = await hass.async_add_executor_job(convert_image)
        except Exception as err:
            raise HomeAssistantError(f"Failed to convert image: {err}") from err

        timeout = aiohttp.ClientTimeout(total=15)
        for entry_data in entries:
            async def _post(ip: str = entry_data["ip_address"]) -> None:
                try:
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
                except aiohttp.ClientError as err:
                    _LOGGER.warning("Cannot connect to Mini Screen ESP32 at %s: %s", ip, err)
            hass.async_create_task(_post())

    # ── Register all services ─────────────────────────────────────────────────
    hass.services.async_register(DOMAIN, "send_message",        handle_send_message)
    hass.services.async_register(DOMAIN, "flash",               handle_flash)
    hass.services.async_register(DOMAIN, "clear",               handle_clear)
    hass.services.async_register(DOMAIN, "unpin",               handle_unpin)
    hass.services.async_register(DOMAIN, "set_brightness",      handle_set_brightness)
    hass.services.async_register(DOMAIN, "pin_message",         handle_pin_message)
    hass.services.async_register(DOMAIN, "scroll_message",      handle_scroll_message)
    hass.services.async_register(DOMAIN, "show_progress",       handle_show_progress)
    hass.services.async_register(DOMAIN, "pin_sensor",          handle_pin_sensor)
    hass.services.async_register(DOMAIN, "pin_sensor_progress", handle_pin_sensor_progress)
    hass.services.async_register(DOMAIN, "unpin_sensor",        handle_unpin_sensor)
    hass.services.async_register(DOMAIN, "send_image",          handle_send_image)


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


def _build_send_params(
    message: str,
    style: str,
    font_size: int,
    duration: int,
    show: bool,
) -> dict[str, Any]:
    """Build query-param dict for a send-message request."""
    params: dict[str, Any] = {"message": message}
    if style == "updateable":
        params["t"] = duration
        params["font_size"] = font_size
        params["show"] = str(show).lower()
    return params


async def _call_device(
    ip: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> None:
    """Make a GET request to the device at the given path with optional params."""
    url = f"http://{ip}{path}"
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params or {}) as response:
                if response.status >= 400:
                    _LOGGER.warning(
                        "Mini Screen ESP32 at %s returned HTTP %s for %s",
                        ip,
                        response.status,
                        path,
                    )
    except asyncio.CancelledError:
        _LOGGER.debug("Request to Mini Screen ESP32 at %s was cancelled", ip)
    except aiohttp.ClientError as err:
        _LOGGER.warning("Cannot connect to Mini Screen ESP32 at %s: %s", ip, err)


# ---------------------------------------------------------------------------
# Backward-compat shims used by device_action.py (import these by name)
# ---------------------------------------------------------------------------

async def _send_message_to_device(
    ip_address: str,
    message: str,
    style: str = "normal",
    font_size: int = 2,
    duration: int = 5,
    show: bool = True,
) -> None:
    """Send a message to a single device (legacy shim)."""
    endpoint = STYLE_ENDPOINTS.get(style, "/update")
    params = _build_send_params(message, style, font_size, duration, show)
    await _call_device(ip=ip_address, path=endpoint, params=params)


async def _flash_device(ip_address: str) -> None:
    """Flash the screen on a single device (legacy shim)."""
    await _call_device(ip=ip_address, path="/flashScreenBright5")
