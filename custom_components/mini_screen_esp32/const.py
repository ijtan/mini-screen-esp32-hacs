"""Constants for the Mini Screen ESP32 integration."""

DOMAIN = "mini_screen_esp32"

CONF_IP_ADDRESS = "ip_address"
CONF_NAME = "name"

# Options keys — dim schedule
CONF_DIM_ENABLED  = "dim_enabled"
CONF_DIM_START    = "dim_start"
CONF_DIM_END      = "dim_end"
CONF_DIM_LEVEL    = "dim_level"
CONF_DIM_RESTORE  = "dim_restore_level"

# Options keys — monitor
CONF_MONITOR_ENABLED  = "monitor_enabled"
CONF_MONITOR_INTERVAL = "monitor_interval"

# Options keys — Claude usage mode
CONF_CLAUDE_ENABLED      = "claude_enabled"
# Value (%) placement on the multi-bar view: "right" | "inside" | "below"
CONF_CLAUDE_BAR_STYLE    = "claude_bar_style"
# Optional: seconds a sticky takeover (pin/scroll/image) holds before the screen
# returns to the Claude "home" display. Default 0 = off, i.e. pins stay until
# explicitly cleared/unpinned (the monitor→Claude return is handled separately
# by the display precedence, not this timeout).
CONF_CLAUDE_HOME_TIMEOUT = "claude_home_timeout"

# Subentry type key
SUBENTRY_TYPE_MONITOR = "monitored_sensor"

# ── hass-claude-usage integration (https://github.com/trickv/hass-claude-usage) ──
CLAUDE_DOMAIN = "hass_claude_usage"

# Sensor "keys" (suffix of the integration's unique_id: "{entry_id}_{key}")
CLAUDE_KEYS = {
    "session_usage_percent",
    "session_reset_time",
    "week_usage_percent",
    "week_reset_time",
    "extra_usage_enabled",
    "extra_usage_percent",
    "extra_usage_credits",
    "extra_usage_limit",
}

# Force a re-push at least this often (seconds) even when the rendered frame is
# unchanged, so a rebooted/desynced device recovers the Claude display instead
# of sitting on the clock (the dedupe would otherwise keep skipping).
CLAUDE_REPUSH_HEARTBEAT = 10
