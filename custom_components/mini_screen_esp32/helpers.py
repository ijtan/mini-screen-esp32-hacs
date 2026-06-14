"""Shared helpers for the Mini Screen ESP32 integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import CLAUDE_DOMAIN, CLAUDE_KEYS, DOMAIN


def device_info(entry_id: str, name: str) -> DeviceInfo:
    """Return a DeviceInfo block for a Mini Screen ESP32 config entry."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=name,
        manufacturer="ESP8266",
        model="Mini Screen OLED",
    )


def state_to_percent(state_value: str, min_value: float, max_value: float) -> int:
    """Convert a raw sensor state string to a 0-100 percentage."""
    try:
        raw = float(state_value)
    except (ValueError, TypeError):
        return 0
    span = max_value - min_value
    if span == 0:
        return 0
    return max(0, min(100, int(round((raw - min_value) / span * 100.0))))


def threshold_to_pct(
    raw: float, value_type: str, min_value: float, max_value: float
) -> int:
    """Convert a threshold (raw or %) to a firmware percentage value (0-100)."""
    if value_type == "raw":
        return state_to_percent(str(raw), min_value, max_value)
    return max(0, min(100, int(round(raw))))


def render_value_text(
    hass: HomeAssistant,
    raw_sensor: str,
    entity_id: str,
    value_type: str,
    unit: str,
    raw_value_text: str | None,
) -> str:
    """
    Build the value_text string to send to the firmware.

    Returns:
      ""         — percentage mode, let firmware show "X%"
      "__hide__" — hide the value line entirely
      "<text>"   — custom formatted string
    """
    if value_type != "raw":
        return ""

    if raw_value_text and raw_value_text.strip():
        from homeassistant.helpers.template import Template
        return Template(raw_value_text, hass).async_render(
            variables={"value": raw_sensor}, parse_result=False
        )

    suffix = unit.strip()
    if not suffix:
        state = hass.states.get(entity_id)
        suffix = (state.attributes.get("unit_of_measurement", "") if state else "")
    return f"{raw_sensor} {suffix}".strip()


def build_progress_params(
    pct: int,
    label: str,
    value_text: str,
    auto_clear_delay: int,
    value_font_size: int,
    crit_pct: int,
) -> dict[str, Any]:
    """Build the query-param dict for a /showProgress request."""
    params: dict[str, Any] = {"value": pct, "label": label}
    if value_text:
        params["value_text"] = value_text
    if auto_clear_delay > 0:
        params["auto_clear_delay"] = auto_clear_delay
    if value_font_size == 2:
        params["value_font_size"] = 2
    if crit_pct > 0:
        params["crit"] = crit_pct
    return params


# ── Claude usage mode helpers ─────────────────────────────────────────────────

def parse_float(state_value: Any) -> float | None:
    """Parse a sensor state into a float, or None if not numeric."""
    try:
        return float(state_value)
    except (TypeError, ValueError):
        return None


def is_truthy_state(state_value: Any) -> bool:
    """Return True for the various ways an 'on' / enabled state is rendered."""
    return str(state_value).strip().lower() in {"true", "on", "1", "yes", "enabled"}


def find_claude_entities(hass: HomeAssistant) -> dict[str, str]:
    """
    Locate the hass-claude-usage sensors via the entity registry.

    Returns a dict mapping each known sensor key (see CLAUDE_KEYS) to its
    current entity_id. Matching is done on the unique_id suffix
    ("{config_entry_id}_{key}"), so it survives the user renaming entities.
    """
    registry = er.async_get(hass)
    found: dict[str, str] = {}
    for ent in registry.entities.values():
        if ent.platform != CLAUDE_DOMAIN:
            continue
        uid = ent.unique_id or ""
        ce = ent.config_entry_id or ""
        key = uid[len(ce) + 1:] if ce and uid.startswith(ce + "_") else uid
        if key in CLAUDE_KEYS:
            found[key] = ent.entity_id
    return found


def format_reset_countdown(state_value: Any) -> str:
    """
    Format a timestamp sensor state as a compact countdown.

    The countdown is computed live from the absolute reset timestamp minus the
    current time, so it ticks down between the integration's slow (~5 min)
    sensor refreshes and reconciles whenever a new reset time arrives.

    Granularity adapts to how far away the reset is:
      • under 1 hour → "M:SS"  (e.g. "38:12", "0:45")   — seconds tick
      • under 1 day  → "3h05m"
      • else         → "2d4h"
    Returns "now" if already past, or "" if unparseable.
    """
    if not state_value or str(state_value).lower() in {"unknown", "unavailable", "none"}:
        return ""
    target = dt_util.parse_datetime(str(state_value))
    if target is None:
        return ""
    now = dt_util.utcnow()
    if target.tzinfo is None:
        target = target.replace(tzinfo=now.tzinfo)
    delta = int((target - now).total_seconds())
    if delta <= 0:
        return "now"
    if delta < 3600:
        minutes, seconds = divmod(delta, 60)
        return f"{minutes}:{seconds:02d}"
    minutes = delta // 60
    hours, rem_m = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{rem_m:02d}m"
    days, rem_h = divmod(hours, 24)
    return f"{days}d{rem_h}h"
