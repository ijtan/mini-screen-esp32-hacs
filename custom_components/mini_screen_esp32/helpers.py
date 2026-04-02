"""Shared helpers for the Mini Screen ESP32 integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


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
