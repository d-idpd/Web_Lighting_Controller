# SP110E Cabinet Lighting Controller — Project Requirements

## Project Overview

A locally-hosted web application that controls 6 SP110E Bluetooth LED strip controllers across two sides of a kitchen, each side having three lighting zones (top accent, middle under-cabinet, bottom toe-kick). The PC acts as the Bluetooth bridge. Any device on the same WiFi network can access the web UI — primary use case is a phone in the kitchen.

---

## System Architecture

```
Mobile/Desktop Browser (phone in kitchen)
        ↓ HTTP (local WiFi)
Python Flask Web Server (Windows PC)
        ↓ Bluetooth LE × 6 simultaneous connections
6× SP110E Controllers
        ↓ SPI signal
LED Strips (2 sides × 3 zones)
```

---

## Hardware Layout

### Zone Map

| Zone ID | Label | Side | Position | LED Type | Control Mode |
|---|---|---|---|---|---|
| `left-top` | Left Top | Left | Above cabinets (accent) | RGB | Color picker + effects |
| `left-mid` | Left Mid | Left | Under-cabinet | Tunable White (WW+CW) | Warm/Cool slider |
| `left-bot` | Left Bottom | Left | Toe kick | Tunable White (WW+CW) | Warm/Cool slider |
| `right-top` | Right Top | Right | Above cabinets (accent) | RGB | Color picker + effects |
| `right-mid` | Right Mid | Right | Under-cabinet | Tunable White (WW+CW) | Warm/Cool slider |
| `right-bot` | Right Bottom | Right | Toe kick | Tunable White (WW+CW) | Warm/Cool slider |

### LED Types

**RGB zones** (`left-top`, `right-top`):
- Full color control via RGB values
- Support effects/presets
- SP110E configured for RGB pixel type

**Tunable White zones** (`left-mid`, `left-bot`, `right-mid`, `right-bot`):
- WS2811 COB LEDs with 3 white channels: warm white, neutral, cool white
- Color temperature range: 3000K (warm) → 6000K (cool)
- Controlled via the SP110E `Set static color` command using R=warm, G=0, B=cool mapping
  - Full warm: `FF 00 00 1E`
  - Full cool: `00 00 FF 1E`
  - Midpoint neutral: `7F 00 7F 1E`
- No effects/presets for tunable white zones — color temperature slider only

### Controller Configuration

Each SP110E must be configured (via the app or manually via the iOS app first) with the correct pixel IC type and channel count to match the installed LED strip. The backend `config.json` stores the Bluetooth device address for each zone so the server knows which BLE device maps to which zone.

---

## SP110E Bluetooth Protocol Reference

- **Service UUID:** `ffe0`
- **Write characteristic:** `ffe1`
- **Read characteristic:** `ffe2`
- Upon connection, send the handshake immediately or the connection drops
- Handshake: write `D7 F3 A1 D5` to `ffe1`, then `00 00 00 10` to get device info

### Key Commands (4-byte hex, written to `ffe1`)

| Action | Command |
|---|---|
| Turn ON | `00 00 00 AA` |
| Turn OFF | `00 00 00 AB` |
| Get device info | `00 00 00 10` |
| Set brightness | `00 00 {value} 2A` (value: 0–255) |
| Set speed | `00 00 {value} 03` (value: 0–255) |
| Set static color | `{R} {G} {B} 1E` |
| Set preset/effect | `00 00 {preset_num} 2C` (preset: 1–120) |

---

## Backend Requirements

### 1. Configuration File (`config.json`)

Stores the BLE MAC address and zone metadata for each controller. Example:

```json
{
  "zones": {
    "left-top":  { "address": "AA:BB:CC:DD:EE:01", "type": "rgb",   "label": "Left Top" },
    "left-mid":  { "address": "AA:BB:CC:DD:EE:02", "type": "tunable", "label": "Left Mid" },
    "left-bot":  { "address": "AA:BB:CC:DD:EE:03", "type": "tunable", "label": "Left Bottom" },
    "right-top": { "address": "AA:BB:CC:DD:EE:04", "type": "rgb",   "label": "Right Top" },
    "right-mid": { "address": "AA:BB:CC:DD:EE:05", "type": "tunable", "label": "Right Mid" },
    "right-bot": { "address": "AA:BB:CC:DD:EE:06", "type": "tunable", "label": "Right Bottom" }
  }
}
```

The user edits this file once with their actual BLE addresses. A helper script `scan.py` should be included that scans for nearby SP110E devices and prints their addresses to help the user populate `config.json`.

### 2. BLE Connection Manager

- On startup, attempt to connect to all 6 controllers concurrently using `asyncio`
- Send handshake to each immediately upon connection
- Each zone gets its own async BLE client instance
- BLE writes per zone are sequential (queued) — no concurrent writes to the same `ffe1`
- Log connect/disconnect events per zone to console

#### Offline / Powered-Off Behavior

If a controller cannot be reached — whether at startup or during operation — it is treated as **intentionally powered off**, not as an error:

- Zone status is set to `"offline"` (distinct from `"connected"` or `"error"`)
- No error is shown in the UI — the zone card simply appears dimmed with a neutral "Off" indicator
- The visualizer shows that zone's canvas region as dark (no color overlay)
- No reconnection attempts are made automatically — the app does not poll or retry in the background
- Once per minute, the server does a single quiet background scan to check if any offline zones have come back online. If one is found, it connects, handshakes, and updates zone status to `"connected"` without any user action required
- API calls targeting an offline zone return `{"status": "offline", "message": "Device not reachable — assumed powered off"}` with HTTP 200 (not an error code), and the UI silently ignores it

### 3. REST API Endpoints

All return JSON. Base URL: `http://<local-ip>:5000`

#### Per-zone endpoints (replace `{zone}` with zone ID, e.g. `left-top`)

| Method | Endpoint | Body | Description |
|---|---|---|---|
| GET | `/status` | — | Returns all 6 zones: connection status + current state |
| POST | `/zone/{zone}/power` | `{"on": true\|false}` | Power on/off one zone |
| POST | `/zone/{zone}/brightness` | `{"value": 0–255}` | Set brightness for one zone |
| POST | `/zone/{zone}/color` | `{"r": 0–255, "g": 0–255, "b": 0–255}` | Set RGB color (RGB zones only) |
| POST | `/zone/{zone}/temperature` | `{"kelvin": 3000–6000}` | Set color temperature (tunable zones only) — converts to R/B mix |
| POST | `/zone/{zone}/effect` | `{"preset": 1–120}` | Set effect (RGB zones only) |
| POST | `/zone/{zone}/speed` | `{"value": 0–255}` | Set speed (RGB zones with effect active) |

#### Group endpoints

| Method | Endpoint | Body | Description |
|---|---|---|---|
| POST | `/group/all/power` | `{"on": true\|false}` | All 6 zones on/off |
| POST | `/group/all/brightness` | `{"value": 0–255}` | Set brightness on all 6 zones |
| POST | `/group/top/power` | `{"on": true\|false}` | Both top zones |
| POST | `/group/top/brightness` | `{"value": 0–255}` | Both top zones brightness |
| POST | `/group/mid/power` | `{"on": true\|false}` | Both mid zones |
| POST | `/group/mid/brightness` | `{"value": 0–255}` | Both mid zones brightness |
| POST | `/group/bot/power` | `{"on": true\|false}` | Both bottom zones |
| POST | `/group/bot/brightness` | `{"value": 0–255}` | Both bottom zones brightness |

### 4. State Tracking

The server maintains an in-memory state dict per zone:

```json
{
  "left-top": {
    "connected": true,
    "on": true,
    "brightness": 200,
    "color": { "r": 128, "g": 0, "b": 255 },
    "effect": null,
    "speed": 128
  },
  "left-mid": {
    "connected": true,
    "on": true,
    "brightness": 180,
    "kelvin": 4000
  }
}
```

Every API response returns the full current state of the affected zone(s).

### 5. Startup & CORS
- Enable CORS on all routes
- Print local IP on startup: `Server running at http://192.168.x.x:5000`
- Attempt all 6 BLE connections on startup; UI shows which are connected vs pending

---

## Frontend Requirements

### General
- Single `index.html` served by Flask at `/`
- Mobile-first, responsive — primary use on phone in kitchen
- Plain HTML + CSS + vanilla JS, no build tools, no npm
- All API calls via `fetch()` to relative URLs

### Visual Design Direction
- **Aesthetic:** Premium smart home app — dark, minimal, confident
- **Background:** Near-black (`#0a0a0a`)
- **Accent:** Warm amber/gold for interactive elements
- **Typography:** Distinctive Google Font — not Inter, not Roboto
- **Layout:** Full-width on mobile, centered max-width on desktop
- **Touch targets:** Minimum 44px for all interactive elements
- **Animations:** Subtle glow effects that respond to the current light color state

---

## UI Layout & Sections

### Section 1 — Kitchen Visualizer (top of page)

This is the hero section. It shows a live visual representation of the kitchen with colored light overlays matching the current state of each zone.

#### How it works — Layered Image Compositing

For each side of the kitchen (left and right), three image layers are stacked using CSS `position: absolute` and canvas `globalCompositeOperation`:

```
Layer 1 (bottom): Base photo — kitchen with lights off / neutral
Layer 2 (middle): Grayscale light mask — black=no light, white=full light, gray=falloff
Layer 3 (top):    Color overlay — user's current color, multiplied by mask brightness
```

**Blend mode:** Use `screen` or `lighter` compositing on a `<canvas>` element so the color only appears where the mask is bright, creating a realistic glow effect.

**Implementation:**
- Each side has its own `<canvas>` element
- On state change, re-render the canvas:
  1. Draw base image
  2. For each active zone on that side, draw the grayscale mask tinted with the zone's current color using `globalCompositeOperation = 'screen'`
  3. Stack all three zone masks (top/mid/bot) for that side in one render pass
- Poll `/status` every 3 seconds and re-render if state changed
- Canvas updates are animated with a short crossfade (150ms) so color changes feel smooth

**Image assets required (user-provided, placed in `static/images/`):**

| Filename | Description |
|---|---|
| `left-base.jpg` | Left side of kitchen, lights off |
| `left-mask-top.png` | Grayscale mask for left top accent zone |
| `left-mask-mid.png` | Grayscale mask for left under-cabinet zone |
| `left-mask-bot.png` | Grayscale mask for left toe-kick zone |
| `right-base.jpg` | Right side of kitchen, lights off |
| `right-mask-top.png` | Grayscale mask for right top accent zone |
| `right-mask-mid.png` | Grayscale mask for right under-cabinet zone |
| `right-mask-bot.png` | Grayscale mask for right toe-kick zone |

The user's provided photos are the source for these assets. Claude Code should include a note in the README on how to create the grayscale masks (e.g. in Photoshop or GIMP: desaturate the lit photo, then use Levels to push black areas to pure black).

**Tap interaction:**
- Tapping a zone area on the visualizer opens the zone control popup for that zone
- Each canvas zone has a defined tap region (percentage-based coordinates relative to canvas size, defined in a JS config object so they're easy to adjust)

### Section 2 — Global Controls

A card below the visualizer with controls that affect multiple zones at once:

- **Master power toggle** — all 6 zones on/off
- **"All" brightness slider** — sets all 6 zones to same brightness (0–100%)
- **"Top" brightness slider** — both top zones
- **"Mid" brightness slider** — both mid zones  
- **"Bottom" brightness slider** — both bottom zones
- All sliders debounced 300ms

### Section 3 — Zone Cards (fallback / detail view)

Below global controls, a scrollable list of 6 zone cards (one per zone), each showing:
- Zone label + connection status dot
- Power toggle
- Brightness slider
- For RGB zones: color swatch showing current color (tapping opens zone popup)
- For tunable zones: color temperature indicator showing warm→cool position

Tapping a zone card also opens the zone popup.

---

## Zone Control Popup

A bottom sheet / modal that slides up when a zone is tapped (either on the visualizer or the zone card). Contains zone-specific controls based on LED type.

### For RGB zones (`left-top`, `right-top`):

- **Power toggle**
- **Brightness slider** (0–100%)
- **Color picker** — a full hue/saturation/brightness wheel or grid in vanilla JS (not native `<input type="color">` — it looks out of place on mobile). Show current color as a large swatch.
- **Effects grid** — scrollable grid of named effect buttons. Currently active effect is highlighted. Include "Static Color" as the first option to exit effect mode.
- **Speed slider** — visible only when an effect is active
- All changes sent immediately (debounced 300ms for sliders)

### For Tunable White zones (`left-mid`, `left-bot`, `right-mid`, `right-bot`):

- **Power toggle**
- **Brightness slider** (0–100%)
- **Color temperature slider** — a single horizontal slider styled with a warm-to-cool gradient (3000K amber on left → 6000K blue-white on right). Shows current Kelvin value. Translates to R/B mix and sends `POST /zone/{zone}/temperature`.
- No effects, no color picker

### Popup behavior:
- Slides up from bottom (CSS transform animation)
- Tap outside or swipe down to dismiss
- Shows zone label and LED type in the popup header

---

## Tunable White — Color Temperature Conversion

When the user sets a Kelvin value K (3000–6000), convert to R/B channel mix:

```python
def kelvin_to_rgb_mix(kelvin):
    # Map 3000K=full warm, 6000K=full cool
    t = (kelvin - 3000) / 3000  # 0.0 = warmest, 1.0 = coolest
    warm = int((1 - t) * 255)
    cool = int(t * 255)
    return warm, 0, cool  # R=warm, G=0, B=cool
```

Send as `POST /zone/{zone}/color` with `{"r": warm, "g": 0, "b": cool}`.

---

## Named Effect Presets (RGB zones only)

```
1: Rainbow       2: Rainbow Fade    3: Rainbow Strobe   4: RGB Fade
5: Red Fade      6: Green Fade      7: Blue Fade         8: Yellow Fade
9: Cyan Fade     10: Purple Fade    11: White Fade       12: Red Strobe
13: Green Strobe 14: Blue Strobe    15: Yellow Strobe    16: Cyan Strobe
17: Purple Strobe 18: White Strobe  19: Red Chase        20: Green Chase
21: Blue Chase   22: Yellow Chase   23: Cyan Chase       24: Purple Chase
25: White Chase  26: Rainbow Chase  27: Fire             28: Twinkle
29: Meteor       30: Comet          (31–120: Effect 31–120)
```

---

## File Structure

```
sp110e-controller/
├── app.py                  # Flask server + BLE manager
├── config.json             # BLE addresses per zone (user edits once)
├── scan.py                 # Helper: scan for nearby SP110E devices
├── requirements.txt        # Python dependencies
├── static/
│   └── images/
│       ├── left-base.jpg
│       ├── left-mask-top.png
│       ├── left-mask-mid.png
│       ├── left-mask-bot.png
│       ├── right-base.jpg
│       ├── right-mask-top.png
│       ├── right-mask-mid.png
│       └── right-mask-bot.png
├── templates/
│   └── index.html          # Full web UI
└── README.md
```

---

## Python Dependencies (`requirements.txt`)

```
flask
flask-cors
bleak
```

---

## README Requirements

1. **Prerequisites** — Python 3.9+, Windows with BLE support
2. **Install** — `pip install -r requirements.txt`
3. **Find BLE addresses** — Run `python scan.py`, note the address of each SP110E
4. **Configure** — Edit `config.json` with each zone's BLE address
5. **Add images** — Place base photos and grayscale masks in `static/images/`
6. **How to make masks** — Desaturate the lit kitchen photo in any image editor; use Levels/Curves to push dark areas to black and keep lit areas white/gray. Export as PNG.
7. **Run** — `python app.py`
8. **Access** — Open the printed URL on any device on the same WiFi
9. **Troubleshooting** — Do NOT pair SP110E in Windows Bluetooth settings; bleak uses direct BLE without OS pairing

---

## Notes for Claude Code

- Use `asyncio` + `bleak` for all BLE. Run Flask in a thread alongside the asyncio event loop (use `asyncio.run_coroutine_threadsafe` to bridge Flask route handlers into the async loop).
- All 6 BLE clients run concurrently in the same asyncio event loop.
- Each zone has its own write queue (asyncio.Queue) to ensure sequential writes to `ffe1`.
- SP110E must NOT be OS-paired — bleak connects directly by MAC address.
- Handshake on connect: write `D7 F3 A1 D5` then `00 00 00 10` to `ffe1`.
- Frontend canvas compositing: use `globalCompositeOperation = 'screen'` for additive light blending. Draw base image first, then each active zone's mask tinted with the zone color.
- Tap regions on the canvas visualizer should be defined as percentage-based bounding boxes in a JS config object (easy for the user to tweak if needed).
- Debounce all sliders 300ms on the frontend before sending API requests.
- The color temperature slider background should be a CSS linear-gradient from `#ffb347` (3000K warm) to `#cce8ff` (6000K cool).

---

## Testing Requirements

Three independent test modes, each runnable without the others. All test scripts live in a `tests/` folder.

### File Structure Addition

```
sp110e-controller/
├── tests/
│   ├── test_ble_connect.py       # Test 1: BLE connection only
│   ├── test_ble_control.py       # Test 2: BLE connection + RGB control
│   └── test_ui_mock.py           # Test 3: Flask server in mock mode (no BLE)
```

---

### Test 1 — BLE Connection Only (`test_ble_connect.py`)

**Purpose:** Verify a single SP110E can be found and connected to over Bluetooth, completely independent of the rest of the app.

**What it does:**
1. Scans for BLE devices for 10 seconds and lists all found devices (name + address)
2. Accepts a target address as a command-line argument: `python test_ble_connect.py AA:BB:CC:DD:EE:01`
3. Attempts to connect to that address
4. Sends the handshake (`D7 F3 A1 D5` then `00 00 00 10`)
5. Reads and prints the device info response from `ffe2`
6. Prints `✓ Connected and handshake successful` or a clear error message
7. Disconnects cleanly

**No Flask, no config.json, no other zones involved.**

**Example output:**
```
Scanning for BLE devices...
Found: SP110E  AA:BB:CC:DD:EE:01
Found: SP110E  AA:BB:CC:DD:EE:02
...
Connecting to AA:BB:CC:DD:EE:01...
✓ Connected
Sending handshake...
✓ Handshake sent
Device info response: [raw bytes]
✓ Test passed — BLE connection working
Disconnecting...
✓ Done
```

---

### Test 2 — BLE Connection + RGB Control (`test_ble_control.py`)

**Purpose:** Verify full send/receive control of a single SP110E via command line, without the web UI.

**Usage:**
```
python test_ble_control.py AA:BB:CC:DD:EE:01
```

**What it does after connecting:**
1. Runs through an automated sequence of commands with a 1-second pause between each, printing what it's doing:
   - Turn ON
   - Set brightness to 50%
   - Set color RED (`FF 00 00 1E`)
   - Wait 2 seconds
   - Set color GREEN (`00 FF 00 1E`)
   - Wait 2 seconds
   - Set color BLUE (`00 00 FF 1E`)
   - Wait 2 seconds
   - Set color WHITE (`FF FF FF 1E`)
   - Wait 2 seconds
   - Set brightness to 100%
   - Set effect preset 1 (Rainbow)
   - Wait 3 seconds
   - Turn OFF
2. Prints `✓ Pass` or `✗ Fail` after each command
3. Prints a final summary: `X/Y commands succeeded`

**Optional interactive mode:** If run with `--interactive` flag, instead of the automated sequence it drops into a simple REPL:
```
SP110E Control > on
SP110E Control > color 255 0 128
SP110E Control > brightness 75
SP110E Control > effect 27
SP110E Control > off
SP110E Control > quit
```

**No Flask, no web UI, no other zones involved.**

---

### Test 3 — UI + Visualizer Mock Mode (`test_ui_mock.py`)

**Purpose:** Run the full Flask web server and web UI with simulated zone state — no Bluetooth hardware required. Lets you develop and test the frontend, canvas compositing, popups, and API responses without any SP110E controllers powered on.

**How it works:**
- Starts the Flask server normally on port 5000
- Replaces the BLE connection manager with a mock that:
  - Immediately marks all 6 zones as "connected"
  - Accepts all API commands and updates in-memory state as normal
  - Never attempts any actual Bluetooth calls
  - Logs `[MOCK] Zone left-top: color set to R=255 G=0 B=128` etc. to console
- The web UI behaves identically to production — all controls, sliders, popups, and canvas compositing work normally
- State changes reflect immediately in the visualizer

**Usage:**
```
python tests/test_ui_mock.py
```

**What to verify in this test:**
- Kitchen visualizer renders correctly on load
- Color changes on a zone update the canvas overlay in real time
- Tunable white slider moves warm→cool gradient correctly
- Tapping zone areas on the visualizer opens the correct popup
- Global brightness sliders affect all relevant zones
- Master power toggle reflects across all zone cards
- Polling (`/status` every 3 seconds) keeps UI in sync

**Acceptance criteria:** All UI interactions work identically to what the production app would show, with zero BLE hardware present.

---

### Running Tests

```bash
# Test 1 — scan and connect
python tests/test_ble_connect.py

# Test 1 — connect to specific device
python tests/test_ble_connect.py AA:BB:CC:DD:EE:01

# Test 2 — automated RGB sequence
python tests/test_ble_control.py AA:BB:CC:DD:EE:01

# Test 2 — interactive REPL
python tests/test_ble_control.py AA:BB:CC:DD:EE:01 --interactive

# Test 3 — full UI with mock BLE
python tests/test_ui_mock.py
```

No additional dependencies beyond the main `requirements.txt` are needed for any test.
