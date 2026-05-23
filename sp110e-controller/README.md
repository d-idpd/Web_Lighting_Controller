# SP110E Kitchen Cabinet Lighting Controller

A locally-hosted web app that controls 6 SP110E Bluetooth LED strip controllers across two sides of a kitchen. Your PC bridges Bluetooth to the lights; any device on the same WiFi can use the web UI.

---

## Prerequisites

- Windows PC with Bluetooth LE support
- Python 3.9 or newer
- 6× SP110E controllers installed and powered on

---

## Quick Start

### 1. Install dependencies

```
pip install -r requirements.txt
```

### 2. Find your SP110E Bluetooth addresses

```
python scan.py
```

Look for devices named `SP110E` (or anything with the `FFE0` BLE service). Note each address.

> **Important:** Do NOT pair the SP110E in Windows Bluetooth settings. bleak connects directly by MAC address without OS pairing. If you already paired them, unpair first.

### 3. Split your kitchen mask images into zone masks

Place your source images in the parent folder (already done if you cloned this repo), then run:

```
python split_masks.py
```

This reads `../LeftMask.png` and `../RightMask.png`, auto-detects the three brightness bands (top accent / under-cabinet / toe-kick), and writes 6 zone mask files to `static/images/`. It also copies the base images.

Review the output masks. If any zone is missing or merged with another, re-shoot your mask photo with stronger contrast between zones.

### 4. Edit config.json with your actual BLE addresses

```json
{
  "zones": {
    "left-top":  { "address": "AA:BB:CC:DD:EE:01", "type": "rgb",     "label": "Left Top" },
    "left-mid":  { "address": "AA:BB:CC:DD:EE:02", "type": "tunable", "label": "Left Mid" },
    ...
  }
}
```

Replace each `AA:BB:CC:DD:EE:XX` with the real address from step 2.

### 5. Run the server

```
python app.py
```

The console prints the local URL, e.g.:

```
════════════════════════════════════════════════
  SP110E Controller
  Server running at http://192.168.1.42:5000
  Open this URL on your phone
════════════════════════════════════════════════
```

Open that URL on any device on the same WiFi network.

---

## Image Assets

The visualizer overlays colored light onto photos of your kitchen. You need:

| File | Description |
|---|---|
| `static/images/left-base.png`    | Left side, lights off |
| `static/images/left-mask-top.png`  | Grayscale mask — left top accent zone |
| `static/images/left-mask-mid.png`  | Grayscale mask — left under-cabinet zone |
| `static/images/left-mask-bot.png`  | Grayscale mask — left toe-kick zone |
| `static/images/right-base.png`   | Right side, lights off |
| `static/images/right-mask-top.png` | Grayscale mask — right top accent zone |
| `static/images/right-mask-mid.png` | Grayscale mask — right under-cabinet zone |
| `static/images/right-mask-bot.png` | Grayscale mask — right toe-kick zone |

`split_masks.py` generates all of these automatically from your combined `LeftMask.png` / `RightMask.png` source photos.

### How to make better masks manually (optional)

If the auto-split result doesn't look right, create masks manually in any image editor:

1. Start with a photo taken with **only one zone lit** at a time (e.g. only the top accent strip on)
2. Desaturate to grayscale
3. Use Levels/Curves to push dark/unlit areas to pure black (0) and keep the lit area bright (near 255)
4. Export as PNG — the brighter the lit region, the more the color overlay will show there

---

## Features

### Day / Night Toggle
The toggle in the top-right corner darkens the base kitchen image so the colored light overlays look more vivid (simulating low ambient light). Drag the darkness slider to your preference.

### Zone Popup
Tap any zone on the visualizer or any zone card to open the popup:
- **RGB zones** (top accent): full color wheel, 120 effect presets, speed slider
- **Tunable white zones** (under-cabinet, toe-kick): warm↔cool color temperature slider (3000K–6000K)

### Global Controls
- Master power button (all zones on/off)
- Brightness sliders for all zones, top zones, mid zones, bottom zones independently

### GitHub Pages / Demo Mode
Add `?demo=true` to the URL to enable demo mode — a red banner appears at the top and all API calls are no-ops (the UI still animates fully). Useful for portfolio links.

---

## Testing

### Test 1 — BLE scan & connect (no hardware required for scan)

```bash
python tests/test_ble_connect.py
python tests/test_ble_connect.py AA:BB:CC:DD:EE:01
```

### Test 2 — RGB control sequence

```bash
python tests/test_ble_control.py AA:BB:CC:DD:EE:01
python tests/test_ble_control.py AA:BB:CC:DD:EE:01 --interactive
```

### Test 3 — Full UI with mock BLE (no hardware needed)

```bash
python tests/test_ui_mock.py
```

All controls work; BLE commands are logged to console instead of sent.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `bleak` can't find devices | Make sure SP110E is powered on. Do NOT pair in Windows Bluetooth settings. |
| Zone shows as offline | The SP110E may be off or out of range. The server retries once per minute automatically. |
| Visualizer shows black canvas | Run `split_masks.py` to generate the zone mask images into `static/images/`. |
| "Address already in use" on port 5000 | Another process is using port 5000. Kill it or change the port in `app.py`. |
| Colors look wrong on canvas | Adjust tap regions in the JS `TAP_REGIONS` config in `index.html` if zones don't line up with your image. |

---

## File Structure

```
sp110e-controller/
├── app.py                  Flask server + BLE manager
├── config.json             BLE addresses per zone (edit once)
├── scan.py                 Scan for nearby SP110E devices
├── split_masks.py          Auto-split combined masks into zone masks
├── requirements.txt
├── static/
│   └── images/             Zone masks + base images go here
├── templates/
│   └── index.html          Full web UI (single file, no build tools)
└── tests/
    ├── test_ble_connect.py
    ├── test_ble_control.py
    └── test_ui_mock.py
```
