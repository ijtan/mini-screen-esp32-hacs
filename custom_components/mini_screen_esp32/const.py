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
CONF_CLAUDE_ENABLED = "claude_enabled"
CONF_CLAUDE_ROTATE  = "claude_rotate"

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

# When the session is active (>0 %) show it primarily; show the Week frame
# only once every N rotations.
CLAUDE_WEEK_EVERY = 4
