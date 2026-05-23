"""
Test 3 — UI + Visualizer Mock Mode

Runs the full Flask server with a mock BLE backend so the web UI can be
tested without any SP110E hardware. All controls, sliders, canvas compositing,
and popups behave identically to production.

Usage (from the sp110e-controller/ directory):
    python tests/test_ui_mock.py

Then open the printed URL in your browser (or phone on the same WiFi).
"""

import json
import logging
import os
import socket
import sys

# Allow importing app.py from the parent directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [MOCK]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")
with open(CONFIG_PATH) as f:
    config = json.load(f)

ZONE_ORDER = ["left-top", "left-mid", "left-bot", "right-top", "right-mid", "right-bot"]
GROUP_ZONES = {
    "all": ZONE_ORDER,
    "top": ["left-top", "right-top"],
    "mid": ["left-mid", "right-mid"],
    "bot": ["left-bot", "right-bot"],
}

# ──────────────────────────────────────────────────────────────────────────────
# Mock state — all zones start "connected"
# ──────────────────────────────────────────────────────────────────────────────
def _default_state(zone_id: str) -> dict:
    z = config["zones"][zone_id]
    base = {"status": "connected", "on": True, "brightness": 200}
    if z["type"] == "rgb":
        base.update({"color": {"r": 138, "g": 43, "b": 226}, "effect": None, "speed": 128})
    else:
        base.update({"kelvin": 3200})
    return base

state: dict = {zid: _default_state(zid) for zid in config["zones"]}


def _log_cmd(zone_id: str, action: str, **kwargs) -> None:
    parts = " ".join(f"{k}={v}" for k, v in kwargs.items())
    log.info("Zone %-12s  %-16s  %s", zone_id, action, parts)


# ──────────────────────────────────────────────────────────────────────────────
# Flask
# ──────────────────────────────────────────────────────────────────────────────
# Point Flask to the real templates and static folders in the parent directory
template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
static_dir   = os.path.join(os.path.dirname(__file__), "..", "static")

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
CORS(app)


def _zone_response(zone_id: str) -> dict:
    return {
        "zone": zone_id,
        "label": config["zones"][zone_id]["label"],
        "type":  config["zones"][zone_id]["type"],
        **state[zone_id],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/status")
def get_status():
    result = {}
    for zid in ZONE_ORDER:
        result[zid] = {
            "label": config["zones"][zid]["label"],
            "type":  config["zones"][zid]["type"],
            **state[zid],
        }
    return jsonify(result)


@app.route("/zone/<zone_id>/power", methods=["POST"])
def zone_power(zone_id):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    on = request.json.get("on", True)
    state[zone_id]["on"] = on
    _log_cmd(zone_id, "power", on=on)
    return jsonify(_zone_response(zone_id))


@app.route("/zone/<zone_id>/brightness", methods=["POST"])
def zone_brightness(zone_id):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    value = max(0, min(255, int(request.json.get("value", 200))))
    state[zone_id]["brightness"] = value
    _log_cmd(zone_id, "brightness", value=value)
    return jsonify(_zone_response(zone_id))


@app.route("/zone/<zone_id>/color", methods=["POST"])
def zone_color(zone_id):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    data = request.json
    r = max(0, min(255, int(data.get("r", 255))))
    g = max(0, min(255, int(data.get("g", 255))))
    b = max(0, min(255, int(data.get("b", 255))))
    if config["zones"][zone_id]["type"] == "rgb":
        state[zone_id]["color"] = {"r": r, "g": g, "b": b}
        state[zone_id]["effect"] = None
    _log_cmd(zone_id, "color", r=r, g=g, b=b)
    return jsonify(_zone_response(zone_id))


@app.route("/zone/<zone_id>/temperature", methods=["POST"])
def zone_temperature(zone_id):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    if config["zones"][zone_id]["type"] != "tunable":
        return jsonify({"error": "Tunable zones only"}), 400
    kelvin = max(3000, min(6000, int(request.json.get("kelvin", 4000))))
    state[zone_id]["kelvin"] = kelvin
    t = (kelvin - 3000) / 3000
    warm, cool = int((1 - t) * 255), int(t * 255)
    _log_cmd(zone_id, "temperature", kelvin=kelvin, warm=warm, cool=cool)
    return jsonify(_zone_response(zone_id))


@app.route("/zone/<zone_id>/effect", methods=["POST"])
def zone_effect(zone_id):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    preset = max(1, min(120, int(request.json.get("preset", 1))))
    state[zone_id]["effect"] = preset
    _log_cmd(zone_id, "effect", preset=preset)
    return jsonify(_zone_response(zone_id))


@app.route("/zone/<zone_id>/speed", methods=["POST"])
def zone_speed(zone_id):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    value = max(0, min(255, int(request.json.get("value", 128))))
    if "speed" in state[zone_id]:
        state[zone_id]["speed"] = value
    _log_cmd(zone_id, "speed", value=value)
    return jsonify(_zone_response(zone_id))


@app.route("/group/<group>/power", methods=["POST"])
def group_power(group):
    if group not in GROUP_ZONES:
        return jsonify({"error": "Unknown group"}), 404
    on = request.json.get("on", True)
    for zid in GROUP_ZONES[group]:
        state[zid]["on"] = on
        _log_cmd(zid, "group-power", on=on)
    return jsonify({zid: _zone_response(zid) for zid in GROUP_ZONES[group]})


@app.route("/group/<group>/brightness", methods=["POST"])
def group_brightness(group):
    if group not in GROUP_ZONES:
        return jsonify({"error": "Unknown group"}), 404
    value = max(0, min(255, int(request.json.get("value", 200))))
    for zid in GROUP_ZONES[group]:
        state[zid]["brightness"] = value
        _log_cmd(zid, "group-brightness", value=value)
    return jsonify({zid: _zone_response(zid) for zid in GROUP_ZONES[group]})


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    ip = _local_ip()
    print(f"\n{'═'*52}")
    print(f"  SP110E Controller — MOCK MODE (no BLE)")
    print(f"  All 6 zones simulated as connected")
    print(f"  Server: http://{ip}:5000")
    print(f"  UI:     http://{ip}:5000")
    print(f"{'═'*52}")
    print()
    print("  What to verify:")
    print("  ✓ Visualizer renders base image + light overlays")
    print("  ✓ Color changes update canvas in real time")
    print("  ✓ Tunable slider moves warm→cool gradient")
    print("  ✓ Tapping visualizer opens correct zone popup")
    print("  ✓ Global sliders affect all relevant zones")
    print("  ✓ Master power toggle reflects on all cards")
    print("  ✓ Day/Night toggle darkens the base image")
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
