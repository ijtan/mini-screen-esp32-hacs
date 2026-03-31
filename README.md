# Mini Screen ESP32 — Home Assistant Integration

A HACS custom integration for the ESP8266/ESP32 mini OLED screen running the [MiniScreenESP32](https://github.com/ijtan/PRIVATE-MiniScreenESP32) firmware.

## Features

- Configure your device by IP address (editable after setup)
- Send messages via the `mini_screen_esp32.send_message` service or the `notify` entity
- Flash the screen with `mini_screen_esp32.flash`
- Use in automations with all display styles

## Installation

1. Add this repo to HACS as a custom repository (Category: Integration)
2. Install "Mini Screen ESP32" from HACS
3. Restart Home Assistant
4. Go to Settings → Integrations → Add Integration → search "Mini Screen ESP32"
5. Enter your device name and IP address

## Services

### `mini_screen_esp32.send_message`

| Field | Required | Description |
|---|---|---|
| `message` | yes | Text to display |
| `style` | no | `normal` (default), `big`, `important`, `critical`, `inverted`, `inverted_big`, `updateable` |
| `font_size` | no | `1` (small), `2` (medium, default), `3` (large) — `updateable` style only |
| `duration` | no | Seconds to show message (default 5) — `updateable` style only |
| `show` | no | `false` to log without displaying — `updateable` style only |
| `device_name` | no | Target a specific device by name (omit to send to all) |

**Styles:**
- `normal` — small font, shows 5s
- `big` — large font, shows 5s
- `important` — large font, flashes screen 15×
- `critical` — large font, flashes screen 25×
- `inverted` — small font, inverted display 5s
- `inverted_big` — large font, inverted display 5s
- `updateable` — non-blocking, configurable font & duration, saves to device log

### `mini_screen_esp32.flash`

Flashes the screen bright 5 times. Optional `device_name` field.

### Notify entity

Each configured device registers as a `notify` entity. Use it in automations:

```yaml
service: notify.send_message
target:
  entity_id: notify.mini_screen
data:
  message: "Hello!"
  data:
    style: critical
```

## Automation example

```yaml
automation:
  - alias: "Doorbell alert on screen"
    trigger:
      - platform: state
        entity_id: binary_sensor.doorbell
        to: "on"
    action:
      - service: mini_screen_esp32.send_message
        data:
          message: "Door!"
          style: critical
```
