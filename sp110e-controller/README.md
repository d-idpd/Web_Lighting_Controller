# SP110E Kitchen Cabinet Lighting Controller

A locally-hosted web app that controls 6 SP110E Bluetooth LED strip controllers across two sides of a kitchen. A Raspberry Pi Zero W bridges Bluetooth to the lights; any device on the same WiFi can use the web UI.

**Live demo:** [idpd.us/Web_Lighting_Controller/sp110e-controller/templates/index.html](https://idpd.us/Web_Lighting_Controller/sp110e-controller/templates/index.html)

---

## Prerequisites

- Raspberry Pi Zero W (or any Pi with Bluetooth)
- Python 3.9 or newer
- 6× SP110E controllers installed and powered on

---

## Pi Setup (first time)

```bash
chmod +x setup.sh && ./setup.sh
```

This installs all dependencies, sets Bluetooth permissions, and registers a systemd service so the server starts automatically on boot.

---

## Quick Start

### 1. Find your SP110E Bluetooth addresses

```bash
python3 scan.py
```

Look for devices named `SP110E` (or anything with the `FFE0` BLE service). Note each address.

> **Important:** Do NOT pair the SP110E in OS Bluetooth settings. bleak connects directly by MAC address without OS pairing.

### 2. Read current device config (optional)

```bash
python3 get_config.py AA:BB:CC:DD:EE:01
```

Reads and prints the IC model, pixel count, sequence, and current state from a device. Useful for confirming the LED type before setting `type` in `config.json`.

### 3. Edit config.json with your actual BLE addresses

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

Set `"type"` to `"rgb"` for full-color zones and `"tunable"` for white-temperature zones.

### 4. Generate zone mask images

Run on your PC (requires Pillow):

```bash
python split_masks.py
```

This reads `../LeftMask.png` and `../RightMask.png`, auto-detects the three brightness bands per side, and writes 8 files to `static/images/`. Sync the `static/images/` folder to the Pi after running.

### 5. Run the server

```bash
python3 app.py
```

```
════════════════════════════════════════════════
  SP110E Controller
  Server running at http://192.168.1.30:5000
  Open this URL on your phone
════════════════════════════════════════════════
```

Open that URL on any device on the same WiFi network.

### 6. Run as a background service (auto-start on boot)

```bash
sudo systemctl start sp110e
sudo journalctl -u sp110e -f   # view logs
```

---

## LED Types

### RGB zones (`type: "rgb"`)
Full color control — color wheel, 120 effect presets, speed slider.

### Tunable white zones (`type: "tunable"`)
SK6812_RGBW or similar 2-channel cool/amber strips. The temperature slider maps:
- **2000K** → full amber (R=0, G=255, B=0 on device)
- **6500K** → full cool white (R=255, G=0, B=0 on device)

The exact R/G/B → LED channel mapping depends on your device's sequence setting. Use `get_config.py` to read the sequence, then test with `python3 tests/test_ble_control.py <address> --interactive` to confirm which channel is which.

---

## Image Assets

The visualizer overlays colored light onto photos of your kitchen. Required files in `static/images/`:

| File | Description |
|---|---|
| `left-base.png` | Left side, lights off |
| `left-mask-top.png` | Grayscale mask — left top accent zone |
| `left-mask-mid.png` | Grayscale mask — left under-cabinet zone |
| `left-mask-bot.png` | Grayscale mask — left toe-kick zone |
| `right-base.png` | Right side, lights off |
| `right-mask-top.png` | Grayscale mask — right top accent zone |
| `right-mask-mid.png` | Grayscale mask — right under-cabinet zone |
| `right-mask-bot.png` | Grayscale mask — right toe-kick zone |

`split_masks.py` generates all of these automatically from combined `LeftMask.png` / `RightMask.png` source photos.

### Making masks manually (optional)

1. Photograph the kitchen with **only one zone lit** at a time
2. Desaturate to grayscale
3. Use Levels/Curves to push dark areas to pure black (0) — lit areas stay bright (near 255)
4. Export as PNG

---

## Features

### Day / Night Toggle
Defaults to Night at 75% darkness. Day mode keeps a 30% base darkening so the light overlays stay readable. The slider adds darkness on top of that floor.

### Global Controls
- **Master power** — all zones on/off
- **Defaults** — sets RGB zones to purple at 40% brightness, tunable zones to 4250K at 60% brightness
- **Party** — sets all zones to rainbow strobe (effect 4) at 60% speed
- **Brightness sliders** — All / Top / Mid / Bottom independently

### Zone Cards
Each zone has a power toggle, brightness slider, and a color swatch (RGB) or temperature slider (tunable). Tap to open the full zone popup.

### Zone Popup
- **RGB zones:** color wheel, 120 named effects, speed slider
- **Tunable zones:** warm↔cool temperature slider (2000K–6500K)

### Connection Stability
Zones that drop show an amber dot and keep their last-known color on the canvas — the visualizer doesn't go dark on a brief disconnect. Reconnect is event-driven: a scan fires ~4 seconds after any disconnect rather than waiting a fixed interval.

### Demo Mode
The site auto-detects when it's not running on the local Flask server (port 5000) and enters demo mode — all API calls are no-ops, the UI animates fully. Visiting the live link above shows the demo automatically.

---

## Testing

```bash
# Scan for nearby SP110E devices
python3 scan.py

# Read device config
python3 get_config.py AA:BB:CC:DD:EE:01

# BLE control test — automated sequence
python3 tests/test_ble_control.py AA:BB:CC:DD:EE:01

# BLE control test — interactive REPL
python3 tests/test_ble_control.py AA:BB:CC:DD:EE:01 --interactive
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No Bluetooth adapter found | Run `sudo hciconfig hci0 up`. Install `pi-bluetooth` if missing. |
| Zone shows as offline at startup | SP110E may be off or out of range. Reconnect scan fires automatically after ~4s. |
| Zone keeps disconnecting | The device can't handle rapid BLE writes. The write worker rate-limits to 100ms/command and coalesces same-type commands. |
| Visualizer shows black canvas | Run `split_masks.py` on PC, then sync `static/images/` to the Pi. |
| Colors look wrong | Check sequence setting with `get_config.py` and adjust `type` in `config.json`. |
| "Address already in use" on port 5000 | Another process holds port 5000. `sudo systemctl stop sp110e` or change the port in `app.py`. |

---

## File Structure

```
sp110e-controller/
├── app.py                  Flask server + BLE manager
├── config.json             BLE addresses per zone (edit once)
├── scan.py                 Scan for nearby SP110E devices
├── get_config.py           Read current config from a device
├── split_masks.py          Auto-split combined masks into zone masks
├── setup.sh                Pi first-time setup script
├── requirements.txt
├── static/
│   └── images/             Zone masks + base images
├── templates/
│   └── index.html          Full web UI (single file, no build tools)
└── tests/
    ├── test_ble_connect.py
    └── test_ble_control.py
```
