"""Mini Screen ESP32 Home Assistant Integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)

from .const import (
    CONF_DIM_ENABLED, CONF_DIM_END, CONF_DIM_LEVEL, CONF_DIM_RESTORE, CONF_DIM_START,
    CONF_IP_ADDRESS, CONF_MONITOR_ENABLED, CONF_MONITOR_INTERVAL, CONF_NAME,
    DOMAIN, SUBENTRY_TYPE_MONITOR,
)
from .helpers import build_progress_params, render_value_text, state_to_percent, threshold_to_pct

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["notify", "button", "switch"]

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
    "set_dim_schedule",
    "pin_message",
    "scroll_message",
    "show_progress",
    "pin_sensor",
    "pin_sensor_progress",
    "unpin_sensor",
    "send_image",
]


def _cancel_monitor_resume(entry_data: dict[str, Any]) -> None:
    """Cancel any pending automatic monitor resume."""
    unsub = entry_data.get("monitor_resume_unsub")
    if unsub is not None:
        unsub()
        entry_data["monitor_resume_unsub"] = None


def _set_monitor_paused(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    paused: bool,
    *,
    resume_after: float | None = None,
) -> None:
    """Pause or resume monitored sensor rotation, optionally auto-resuming later."""
    _cancel_monitor_resume(entry_data)
    entry_data["monitor_paused"] = paused

    if not paused or resume_after is None or resume_after <= 0:
        return

    @callback
    def _resume_monitor(_now: Any) -> None:
        entry_data["monitor_paused"] = False
        entry_data["monitor_resume_unsub"] = None

    entry_data["monitor_resume_unsub"] = async_call_later(
        hass, resume_after, _resume_monitor
    )


def _set_display_owner(entry_data: dict[str, Any], owner: str | None) -> None:
    """Track which feature most recently took over the display."""
    entry_data["display_owner"] = owner


def _apply_dim_schedule(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    enabled: bool,
    start_str: str,
    end_str: str,
    dim_level: int,
    restore_level: int,
) -> None:
    """Set up (or cancel) daily dim/restore time listeners for one entry."""
    # Cancel existing listeners
    for key in ("dim_unsub_start", "dim_unsub_end"):
        unsub = entry_data.get(key)
        if unsub is not None:
            unsub()
            entry_data[key] = None

    if not enabled:
        return

    try:
        start_h, start_m = (int(x) for x in start_str.split(":"))
        end_h, end_m = (int(x) for x in end_str.split(":"))
    except (ValueError, AttributeError):
        _LOGGER.error(
            "Mini Screen ESP32: invalid dim schedule time format (expected HH:MM), "
            "got start=%s end=%s",
            start_str, end_str,
        )
        return

    ip = entry_data["ip_address"]

    @callback
    def _on_dim_start(_now: Any, _ip: str = ip, _level: int = dim_level) -> None:
        hass.async_create_task(
            _call_device(ip=_ip, path="/setBrightness", params={"level": _level})
        )

    @callback
    def _on_dim_end(_now: Any, _ip: str = ip, _level: int = restore_level) -> None:
        hass.async_create_task(
            _call_device(ip=_ip, path="/setBrightness", params={"level": _level})
        )

    entry_data["dim_unsub_start"] = async_track_time_change(
        hass, _on_dim_start, hour=start_h, minute=start_m, second=0
    )
    entry_data["dim_unsub_end"] = async_track_time_change(
        hass, _on_dim_end, hour=end_h, minute=end_m, second=0
    )
    _LOGGER.debug(
        "Mini Screen ESP32 dim schedule applied for %s: dim=%d at %02d:%02d, "
        "restore=%d at %02d:%02d",
        ip, dim_level, start_h, start_m, restore_level, end_h, end_m,
    )


def _apply_monitor(
    hass: HomeAssistant,
    entry: ConfigEntry,
    entry_data: dict[str, Any],
) -> None:
    """Set up (or restart) the sensor monitor rotation for one entry."""
    # Cancel existing monitor timer/listener
    for key in ("monitor_unsub", "monitor_state_unsub"):
        unsub = entry_data.get(key)
        if unsub is not None:
            unsub()
            entry_data[key] = None

    opts = entry.options
    if not opts.get(CONF_MONITOR_ENABLED, False):
        if entry_data.get("display_owner") == "monitor":
            _set_display_owner(entry_data, None)
            hass.async_create_task(_call_device(ip=entry_data["ip_address"], path="/unpin"))
        entry_data["monitor_had_active"] = False
        return

    interval = max(1, int(opts.get(CONF_MONITOR_INTERVAL, 10)))
    ip: str = entry_data["ip_address"]

    entry_data["monitor_index"] = 0

    @callback
    def _refresh_monitor(*, advance_index: bool) -> None:
        if entry_data.get("monitor_paused"):
            return

        # Re-read subentries each tick so additions/removals are picked up
        sensors = [
            s.data
            for s in entry.subentries.values()
            if s.subentry_type == SUBENTRY_TYPE_MONITOR
        ]
        if not sensors:
            if entry_data.get("monitor_had_active") and entry_data.get("display_owner") == "monitor":
                _set_display_owner(entry_data, None)
                hass.async_create_task(_call_device(ip=ip, path="/unpin"))
            entry_data["monitor_had_active"] = False
            return

        active = []
        for cfg in sensors:
            entity_id: str = cfg.get("entity_id", "")
            state = hass.states.get(entity_id)
            if state is None:
                continue
            threshold_raw = float(cfg.get("threshold", 0))
            if threshold_raw <= 0:
                active.append(cfg)  # no threshold → always shown
                continue
            min_v = float(cfg.get("min_value", 0))
            max_v = float(cfg.get("max_value", 100))
            value_type = cfg.get("value_type", "percentage")
            pct = state_to_percent(state.state, min_v, max_v)
            trigger_pct = threshold_to_pct(threshold_raw, value_type, min_v, max_v)
            if pct >= trigger_pct:
                active.append(cfg)

        if not active:
            if entry_data.get("monitor_had_active") and entry_data.get("display_owner") == "monitor":
                _set_display_owner(entry_data, None)
                hass.async_create_task(_call_device(ip=ip, path="/unpin"))
            entry_data["monitor_had_active"] = False
            return

        entry_data["monitor_had_active"] = True

        idx = entry_data.get("monitor_index", 0) % len(active)
        if advance_index:
            entry_data["monitor_index"] = (idx + 1) % len(active)
        cfg = active[idx]

        entity_id = cfg.get("entity_id", "")
        state = hass.states.get(entity_id)
        if state is None:
            return

        min_v = float(cfg.get("min_value", 0))
        max_v = float(cfg.get("max_value", 100))
        bar_val = state_to_percent(state.state, min_v, max_v)
        default_label = entity_id.split(".")[-1].replace("_", " ").title()
        label = cfg.get("label", "").strip() or default_label
        value_type: str = cfg.get("value_type", "percentage")
        vt = render_value_text(hass, state.state, entity_id, value_type, cfg.get("unit", ""), None)
        threshold_raw = float(cfg.get("threshold", 0))
        crit_pct = (
            threshold_to_pct(threshold_raw, value_type, min_v, max_v)
            if threshold_raw > 0
            else 0
        )

        params = build_progress_params(
            pct=bar_val,
            label=label,
            value_text=vt,
            auto_clear_delay=0,
            value_font_size=int(cfg.get("value_font_size", 1)),
            crit_pct=crit_pct,
        )
        _set_display_owner(entry_data, "monitor")
        hass.async_create_task(_call_device(ip=ip, path="/showProgress", params=params))

    @callback
    def _monitor_tick(_now: Any) -> None:
        _refresh_monitor(advance_index=True)

    monitor_entity_ids = list(
        {
            s.data.get("entity_id", "")
            for s in entry.subentries.values()
            if s.subentry_type == SUBENTRY_TYPE_MONITOR and s.data.get("entity_id", "")
        }
    )

    @callback
    def _on_monitor_state_change(event: Event) -> None:
        if event.data.get("new_state") is None:
            return
        _refresh_monitor(advance_index=False)

    entry_data["monitor_unsub"] = async_track_time_interval(
        hass, _monitor_tick, timedelta(seconds=interval)
    )
    if monitor_entity_ids:
        entry_data["monitor_state_unsub"] = async_track_state_change_event(
            hass, monitor_entity_ids, _on_monitor_state_change
        )
        _refresh_monitor(advance_index=False)
    _LOGGER.debug("Mini Screen ESP32 monitor started for %s (%ds interval)", ip, interval)


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
        "dim_unsub_start": None,
        "dim_unsub_end": None,
        "monitor_unsub": None,
        "monitor_state_unsub": None,
        "monitor_resume_unsub": None,
        "monitor_index": 0,
        "monitor_had_active": False,
        "monitor_paused": False,
        "display_owner": None,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once — only on the first entry
    if not hass.services.has_service(DOMAIN, "send_message"):
        _register_services(hass)

    # Re-apply dim schedule from saved options (survives restarts)
    opts = entry.options
    entry_data = hass.data[DOMAIN][entry.entry_id]
    dim_enabled = opts.get(CONF_DIM_ENABLED, False)
    dim_start   = opts.get(CONF_DIM_START, "22:00")
    dim_end     = opts.get(CONF_DIM_END, "07:00")
    dim_level   = int(opts.get(CONF_DIM_LEVEL, 5))
    dim_restore = int(opts.get(CONF_DIM_RESTORE, 255))

    _apply_dim_schedule(
        hass, entry_data,
        enabled=dim_enabled,
        start_str=dim_start,
        end_str=dim_end,
        dim_level=dim_level,
        restore_level=dim_restore,
    )

    # Always push current schedule to firmware on startup so device flash stays in sync
    hass.async_create_task(
        _call_device(
            ip=ip_address,
            path="/setDimSchedule",
            params={
                "enabled": "1" if dim_enabled else "0",
                "start":   dim_start,
                "end":     dim_end,
                "level":   dim_level,
                "restore": dim_restore,
            },
        )
    )

    # Start sensor monitor if enabled
    _apply_monitor(hass, entry, entry_data)

    # Re-apply dim schedule and monitor when options are updated via the UI
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called by HA when the options flow saves new settings."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return
    opts = entry.options
    enabled     = opts.get(CONF_DIM_ENABLED, False)
    start_str   = opts.get(CONF_DIM_START, "22:00")
    end_str     = opts.get(CONF_DIM_END, "07:00")
    dim_level   = int(opts.get(CONF_DIM_LEVEL, 5))
    restore     = int(opts.get(CONF_DIM_RESTORE, 255))

    # Update HA-side time listeners
    _apply_dim_schedule(hass, entry_data, enabled, start_str, end_str, dim_level, restore)

    # Restart monitor with new settings
    _apply_monitor(hass, entry, entry_data)

    # Also push to firmware so it persists on device (survives HA being down)
    ip = entry_data["ip_address"]
    hass.async_create_task(
        _call_device(
            ip=ip,
            path="/setDimSchedule",
            params={
                "enabled": "1" if enabled else "0",
                "start":   start_str,
                "end":     end_str,
                "level":   dim_level,
                "restore": restore,
            },
        )
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Cancel sensor and dim subscriptions if active
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is not None:
        for key in (
            "sensor_unsub",
            "dim_unsub_start",
            "dim_unsub_end",
            "monitor_unsub",
            "monitor_state_unsub",
            "monitor_resume_unsub",
        ):
            unsub = entry_data.get(key)
            if unsub is not None:
                unsub()
                entry_data[key] = None

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
        from homeassistant.helpers.template import Template
        message: str = Template(call.data["message"], hass).async_render(parse_result=False)
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
            # Non-updateable styles take over the display — pause monitor
            if style != "updateable":
                resume_after = duration if style in {"normal", "big", "inverted", "inverted_big"} else 5
                _set_monitor_paused(hass, entry_data, True, resume_after=resume_after)
            _set_display_owner(entry_data, "send_message")
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
            _set_monitor_paused(hass, entry_data, False)
            _set_display_owner(entry_data, None)
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
            _set_monitor_paused(hass, entry_data, False)
            _set_display_owner(entry_data, None)
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
        from homeassistant.helpers.template import Template
        message: str = Template(call.data["message"], hass).async_render(parse_result=False)
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
            _set_monitor_paused(hass, entry_data, True)
            _set_display_owner(entry_data, "pin_message")
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
        from homeassistant.helpers.template import Template
        message: str = Template(call.data["message"], hass).async_render(parse_result=False)
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
            _set_monitor_paused(hass, entry_data, True)
            _set_display_owner(entry_data, "scroll_message")
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

        auto_clear_delay: int = int(call.data.get("auto_clear_delay", 0))
        value_font_size: int = int(call.data.get("value_font_size", 1))
        crit_threshold: int = max(0, min(100, int(call.data.get("crit_threshold", 0))))

        params: dict[str, Any] = {"value": value, "label": label}
        if value_text:
            params["value_text"] = value_text
        if auto_clear_delay > 0:
            params["auto_clear_delay"] = auto_clear_delay
        if value_font_size == 2:
            params["value_font_size"] = 2
        if crit_threshold > 0:
            params["crit"] = crit_threshold

        for entry_data in entries:
            _set_display_owner(entry_data, "show_progress")
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
            from homeassistant.helpers.template import Template
            return Template(tmpl, hass).async_render(
                variables={"value": state_value}, parse_result=False
            )

        for entry_data in entries:
            # Cancel existing subscription
            existing_unsub = entry_data.get("sensor_unsub")
            if existing_unsub is not None:
                existing_unsub()
                entry_data["sensor_unsub"] = None
            _set_monitor_paused(hass, entry_data, True)

            # Send the current state immediately
            current_state = hass.states.get(entity_id)
            if current_state is not None:
                msg = _format_message(current_state.state, template)
                _set_display_owner(entry_data, "pin_sensor")
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
                _set_display_owner(_entry_data, "pin_sensor")
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
        unit: str = call.data.get("unit", "").strip()
        value_type: str = call.data.get("value_type", "percentage")
        auto_clear_delay: int = int(call.data.get("auto_clear_delay", 0))
        value_font_size: int = int(call.data.get("value_font_size", 1))
        crit_threshold_raw: float = float(call.data.get("crit_threshold", 0))

        def _render_label() -> str:
            return Template(raw_label, hass).async_render(parse_result=False) if raw_label else ""

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "pin_sensor_progress: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        crit_pct = threshold_to_pct(crit_threshold_raw, value_type, min_value, max_value)

        def _make_params(raw_sensor: str) -> dict:
            pct = state_to_percent(raw_sensor, min_value, max_value)
            vt = render_value_text(hass, raw_sensor, entity_id, value_type, unit, raw_value_text)
            return build_progress_params(
                pct=pct,
                label=_render_label(),
                value_text=vt,
                auto_clear_delay=auto_clear_delay,
                value_font_size=value_font_size,
                crit_pct=crit_pct,
            )

        for entry_data in entries:
            # Cancel existing subscription
            existing_unsub = entry_data.get("sensor_unsub")
            if existing_unsub is not None:
                existing_unsub()
                entry_data["sensor_unsub"] = None
            _set_monitor_paused(hass, entry_data, True)

            # Send current state immediately
            current_state = hass.states.get(entity_id)
            if current_state is not None:
                _set_display_owner(entry_data, "pin_sensor_progress")
                hass.async_create_task(
                    _call_device(
                        ip=entry_data["ip_address"],
                        path="/showProgress",
                        params=_make_params(current_state.state),
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
                _set_display_owner(_entry_data, "pin_sensor_progress")
                hass.async_create_task(
                    _call_device(
                        ip=_entry_data["ip_address"],
                        path="/showProgress",
                        params=_make_params(new_state.state),
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
            _set_monitor_paused(hass, entry_data, False)
            _set_display_owner(entry_data, None)
            hass.async_create_task(
                _call_device(ip=entry_data["ip_address"], path="/unpin")
            )

    # ── send_image ────────────────────────────────────────────────────────────
    async def handle_send_image(call: ServiceCall) -> None:
        """Convert an image (file path or URL) to a 1-bit bitmap and send to the display."""
        import io
        from PIL import Image

        image_source: str = call.data.get("image_url") or call.data.get("image_path", "")
        dither: bool = bool(call.data.get("dither", True))
        device_name: str | None = call.data.get("device_name")

        if not image_source:
            raise HomeAssistantError("Either image_url or image_path must be provided")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "send_image: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)", device_name,
            )
            return

        # Fetch URL or load file — done in executor to avoid blocking
        def load_and_convert() -> bytes:
            if image_source.startswith("http://") or image_source.startswith("https://"):
                import urllib.request
                with urllib.request.urlopen(image_source, timeout=15) as resp:
                    img = Image.open(io.BytesIO(resp.read())).convert("RGB")
            else:
                img = Image.open(image_source).convert("RGB")
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
            bitmap_bytes = await hass.async_add_executor_job(load_and_convert)
        except Exception as err:
            raise HomeAssistantError(f"Failed to load/convert image: {err}") from err

        timeout = aiohttp.ClientTimeout(total=15)
        for entry_data in entries:
            _set_monitor_paused(hass, entry_data, True)
            _set_display_owner(entry_data, "send_image")
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

    # ── set_dim_schedule ──────────────────────────────────────────────────────
    async def handle_set_dim_schedule(call: ServiceCall) -> None:
        """Set up (or cancel) a daily auto-dim schedule for one or all devices."""
        enabled: bool = bool(call.data.get("enabled", True))
        device_name: str | None = call.data.get("device_name")

        entries = _get_matching_entries(hass, device_name)
        if not entries:
            _LOGGER.warning(
                "set_dim_schedule: no matching Mini Screen ESP32 entries found "
                "(device_name=%s)",
                device_name,
            )
            return

        for entry_data in entries:
            _apply_dim_schedule(
                hass, entry_data,
                enabled=enabled,
                start_str=call.data.get("start_time", "22:00"),
                end_str=call.data.get("end_time", "07:00"),
                dim_level=int(call.data.get("dim_level", 5)),
                restore_level=int(call.data.get("restore_level", 255)),
            )

    # ── Register all services ─────────────────────────────────────────────────
    hass.services.async_register(DOMAIN, "send_message",        handle_send_message)
    hass.services.async_register(DOMAIN, "flash",               handle_flash)
    hass.services.async_register(DOMAIN, "clear",               handle_clear)
    hass.services.async_register(DOMAIN, "unpin",               handle_unpin)
    hass.services.async_register(DOMAIN, "set_brightness",      handle_set_brightness)
    hass.services.async_register(DOMAIN, "set_dim_schedule",    handle_set_dim_schedule)
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
