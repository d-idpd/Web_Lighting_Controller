# SP110E Cabinet Lighting Controller — Project Requirements

## Project Overview

A locally-hosted web application that controls 6 SP110E Bluetooth LED strip controllers across two sides of a kitchen, each side having three lighting zones (top accent, middle under-cabinet, bottom toe-kick). A **Raspberry Pi Zero W** acts as the Bluetooth bridge and web server. Any device on the same WiFi network can access the web UI — primary use case is a phone in the kitchen.

A static demo is hosted publicly at [idpd.us](https://idpd.us/Web_Lighting_Controller/sp110e-controller/templates/index.html) — the page auto-detects it's not running on the local Flask server and enters demo mode.

---

## System Architecture

```
Mobile/Desktop Browser (phone in kitchen)
        ↓ HTTP (local WiFi)
Python Flask Web Server (Raspberry Pi Zero W, port 5000)
        ↓ Bluetooth LE × 6 simultaneous connections
6× SP110E Controllers
        ↓ SPI/signal
LED Strips (2 sides × 3 zones)
```

---

## Hardware Layout

### Zone Map

| Zone ID | Label | Side | Position | LED Type | Control Mode |
|---|---|---|---|---|---|
| `left-top` | Left Top | Left | Above cabinets (accent) | RGB | Color picker + effects |
| `left-mid` | Left Mid | Left | Under-cabinet | Tunable (cool/amber) | Temperature slider |
| `left-bot` | Left Bottom | Left | Toe kick | Tunable (cool/amber) | Temperature slider |
| `right-top` | Right Top | Right | Above cabinets (accent) | RGB | Color picker + effects |
| `right-mid` | Right Mid | Right | Under-cabinet | Tunable (cool/amber) | Temperature slider |
| `right-bot` | Right Bottom | Right | Toe kick | Tunable (cool/amber) | Temperature slider |

### LED Types

**RGB zones** (`left-top`, `right-top`):
- Full color control via RGB values
- Support effects/presets (1–120)
- SP110E configured for RGB pixel type

**Tunable zones** (`left-mid`, `left-bot`, `right-mid`, `right-bot`):
- SK6812_RGBW or similar strips with **2 usable channels: cool white + amber**
- Channel mapping confirmed by hardware test: **R byte → cool white LED, G byte → amber LED, B byte → unused**
- Temperature range: 2000K (full amber) → 6500K (full cool white)
- Conversion formula:
  ```python
  t = (kelvin - 2000) / 4500   # 0.0 = full amber, 1.0 = full cool
  cool  = int(t * 255)          # R channel
  amber = int((1 - t) * 255)    # G channel
  _cmd_color(cool, amber, 0)
  ```
- Effect commands (e.g. party mode) are sent to tunable zones too — the device cycles through its channels

---

## SP110E Bluetooth Protocol Reference

- **Service UUID:** `ffe0`
- **Write characteristic:** `ffe1`
- **Read characteristic:** `ffe2`
- Upon connection, send the handshake or the connection drops
- Handshake: write `D7 F3 A1 D5` to `ffe1`, then `00 00 00 10` to request device info
- Send handshake immediately after connect; wait 100ms between the two bytes

### Key Commands (4-byte hex, written to `ffe1`)

**Command byte format: `[data0, data1, data2, command_byte]`**
The value always goes in **byte 0**. Bytes 1–2 are unused (send 0x00).

| Action | Command |
|---|---|
| Turn ON | `00 00 00 AA` |
| Turn OFF | `00 00 00 AB` |
| Get device info | `00 00 00 10` |
| Set brightness | `{value} 00 00 2A` (value: 0–255) |
| Set speed | `{value} 00 00 03` (value: 0–255) |
| Set static color | `{R} {G} {B} 1E` |
| Set preset/effect | `{preset} 00 00 2C` (preset: 1–120) |

> **Note:** The command byte is the last byte (index 3), not byte 2. Getting this wrong sends garbage to the device.

### Reading Device Config

Send `00 00 00 10` after `start_notify` on `ffe1`. The device responds with a 12-byte packet:

| Bytes | Field |
|---|---|
| 0 | Power state (1=ON) |
| 1 | Mode/effect |
| 2 | Speed |
| 3 | Brightness |
| 4 | IC model index |
| 5 | Sequence index (RGB/GRB/etc.) |
| 6–7 | Pixel count (big-endian) |
| 8–10 | Current color (R, G, B) |
| 11 | White channel value |

---

## Backend Requirements

### 1. Configuration File (`config.json`)

```json
{
  "zones": {
    "left-top":  { "address": "AA:BB:CC:DD:EE:01", "type": "rgb",     "label": "Left Top" },
    "left-mid":  { "address": "AA:BB:CC:DD:EE:02", "type": "tunable", "label": "Left Mid" },
    "left-bot":  { "address": "AA:BB:CC:DD:EE:03", "type": "tunable", "label": "Left Bottom" },
    "right-top": { "address": "AA:BB:CC:DD:EE:04", "type": "rgb",     "label": "Right Top" },
    "right-mid": { "address": "AA:BB:CC:DD:EE:05", "type": "tunable", "label": "Right Mid" },
    "right-bot": { "address": "AA:BB:CC:DD:EE:06", "type": "tunable", "label": "Right Bottom" }
  }
}
```

### 2. BLE Connection Manager

- **Single scan pass** on startup: one `BleakScanner.discover()` call finds all target devices, then connects in parallel. Multiple concurrent scanners conflict in BlueZ — never run more than one scanner at a time.
- On Linux/BlueZ, devices must appear in a scan before connecting by address (BlueZ needs to learn the address type). Direct connect-by-address fails for random-address devices.
- Send handshake immediately upon connection; wait 500ms before allowing write queue to process
- Each zone has its own `asyncio.Queue` for sequential writes — no concurrent writes to the same `ffe1`
- Write worker coalesces same-type commands: if the queue has multiple brightness commands, only the latest is sent. Different command types (ON, brightness, color) are all sent in order.
- Inter-command delay: 100ms minimum to prevent ATT 0x0e "Unlikely Error" disconnects

#### Offline / Reconnect Behavior

Three zone statuses: `"connected"`, `"reconnecting"`, `"offline"`

- **On disconnect** (write error or BLE callback): status → `"reconnecting"`, signal reconnect event
- **Reconnect loop**: event-driven — fires ~4s after a disconnect signal (grace period to accumulate multiple drops into one scan), plus a 30s fallback poll. One scan for all pending zones.
- **Not found in scan**: status → `"offline"`
- API calls reject with offline response for any status other than `"connected"`
- `"reconnecting"` zones keep their last-known state in the UI canvas — no visual flicker

### 3. REST API Endpoints

All return JSON. Base URL: `http://<pi-ip>:5000`

#### Per-zone endpoints

| Method | Endpoint | Body | Description |
|---|---|---|---|
| GET | `/status` | — | All 6 zones: status + current state |
| POST | `/zone/{zone}/power` | `{"on": true\|false}` | Power on/off |
| POST | `/zone/{zone}/brightness` | `{"value": 0–255}` | Set brightness |
| POST | `/zone/{zone}/color` | `{"r", "g", "b": 0–255}` | Set RGB color (rgb zones) |
| POST | `/zone/{zone}/temperature` | `{"kelvin": 2000–6500}` | Set temperature (tunable zones) |
| POST | `/zone/{zone}/effect` | `{"preset": 1–120}` | Set effect (rgb zones) |
| POST | `/zone/{zone}/speed` | `{"value": 0–255}` | Set speed |

#### Group endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/group/all/power` | All 6 zones on/off |
| POST | `/group/all/brightness` | All 6 zones brightness |
| POST | `/group/top/power` | Both top zones |
| POST | `/group/top/brightness` | Both top zones brightness |
| POST | `/group/mid/power` | Both mid zones |
| POST | `/group/mid/brightness` | Both mid zones brightness |
| POST | `/group/bot/power` | Both bottom zones |
| POST | `/group/bot/brightness` | Both bottom zones brightness |
| POST | `/group/all/defaults` | RGB → purple 40%, tunable → 4250K 60% |
| POST | `/group/all/party` | All zones → effect 4 at 60% speed |

### 4. State Tracking

```json
{
  "left-top": {
    "status": "connected",
    "on": true,
    "brightness": 102,
    "color": { "r": 128, "g": 0, "b": 128 },
    "effect": null,
    "speed": 128
  },
  "left-mid": {
    "status": "connected",
    "on": true,
    "brightness": 153,
    "kelvin": 4250,
    "effect": null
  }
}
```

Note: tunable zones include `"effect"` in state so party mode can be tracked and the UI can animate them.

### 5. Startup

- BLE loop runs in a background thread; Flask bridges into it via `asyncio.run_coroutine_threadsafe`
- No state is pushed to devices on connect — server state starts at defaults (off), user uses the Defaults button to sync
- Print local IP on startup

---

## Frontend Requirements

### General
- Single `index.html` served by Flask at `/`
- Mobile-first, responsive
- Plain HTML + CSS + vanilla JS, no build tools
- All API calls via `fetch()` to relative URLs
- Polls `/status` every 3 seconds

### Demo Mode Detection

```javascript
const IS_DEMO = window.location.port !== '5000' ||
                new URLSearchParams(window.location.search).has('demo');
```

When `IS_DEMO` is true: API calls are no-ops, `initDemoState()` populates the UI with mock state. Automatically active on any host that isn't the local Flask server.

### Visual Design
- **Aesthetic:** Premium smart home app — dark, minimal
- **Background:** Near-black (`#0a0a0a`)
- **Accent:** Warm amber/gold
- **Touch targets:** Minimum 44px
- **Canvas crossfade:** 150ms on state change

---

## UI Layout

### Section 1 — Kitchen Visualizer

Canvas compositing per side:
1. Draw base image
2. Apply constant 30% black overlay (day) or `0.30 + (slider/100 × 0.70)` (night)
3. For each active zone: fill canvas with zone color × brightness, multiply by grayscale mask, screen onto base

**Default state:** Night mode at 75% (actual darkness = 82.5%). Day mode uses 30% fixed overlay.

**Effect animation:** When any zone has `effect != null`, a `setInterval` at 40ms drives canvas re-renders:
- RGB zones: hue cycles via `Date.now() / 30`
- Tunable zones: kelvin oscillates between 2000K and 6500K via sine wave

**Zone card swatch:** Rainbow gradient CSS when effect active, solid color otherwise.

### Section 2 — Global Controls

- Master power toggle
- **Defaults button** — RGB zones to purple 40%, tunable to 4250K 60%
- **Party button** — all zones to rainbow strobe at 60% speed (canvas animates)
- Brightness sliders: All / Top / Mid / Bottom (debounced 300ms)

### Section 3 — Zone Cards

One card per zone: power toggle, brightness slider, color swatch/hue slider (RGB) or temperature slider (tunable).

### Zone Control Popup

**RGB zones:** power, brightness, color wheel, 120 named effects, speed slider (visible when effect active)

**Tunable zones:** power, brightness, temperature slider (2000K amber → 6500K cool white)

---

## Connection Status Indicators

| Status | Dot color | Canvas | Controls |
|---|---|---|---|
| `connected` | Green | Shows current color | Active |
| `reconnecting` | Amber | Keeps last color | Disabled (offline response) |
| `offline` | Grey | Dark (no overlay) | Disabled |

---

## Named Effect Presets (1–120)

```
1: Rainbow       2: Rainbow Fade    3: Rainbow Strobe   4: RGB Fade
5: Red Fade      6: Green Fade      7: Blue Fade         8: Yellow Fade
9: Cyan Fade     10: Purple Fade    11: White Fade       12: Red Strobe
13: Green Strobe 14: Blue Strobe    15: Yellow Strobe    16: Cyan Strobe
17: Purple Strobe 18: White Strobe  19: Red Chase        20: Green Chase
21: Blue Chase   22: Yellow Chase   23: Cyan Chase       24: Purple Chase
25: White Chase  26: Rainbow Chase  27: Fire             28: Twinkle
29: Meteor       30: Comet          (31–120: unnamed)
```

---

## File Structure

```
sp110e-controller/
├── app.py                  Flask server + BLE manager
├── config.json             BLE addresses per zone
├── scan.py                 Scan for nearby SP110E devices
├── get_config.py           Read current config from a device via BLE
├── split_masks.py          Auto-split combined masks into zone masks
├── setup.sh                Pi first-time setup (deps, BLE caps, systemd)
├── requirements.txt        flask, flask-cors, bleak
├── static/
│   └── images/             Base photos + 6 zone masks (PNG)
├── templates/
│   └── index.html          Full web UI
└── tests/
    ├── test_ble_connect.py
    └── test_ble_control.py
```

---

## Pi Setup Notes

- Platform: Raspberry Pi Zero W (BCM43430A1 Bluetooth chip)
- Requires `pi-bluetooth` package and `hciuart` service
- Python packages installed with `--break-system-packages` (no venv — too slow on Pi Zero W)
- BLE without sudo: `sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))`
- Systemd service: `sp110e.service` — auto-starts on boot, restarts on failure
- SFTP sync from VS Code via `sftp.json` using OpenSSH agent auth
