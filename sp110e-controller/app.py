"""
SP110E Cabinet Lighting Controller — Flask + BLE backend

Architecture:
  - One asyncio event loop runs in a background thread
  - Flask routes bridge into that loop via asyncio.run_coroutine_threadsafe()
  - Each zone has its own BleakClient + asyncio.Queue for sequential writes
  - A background reconnect task checks offline zones once per minute

Run:
    python app.py
"""

import asyncio
import json
import logging
import os
import socket
import threading
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.json"

WRITE_CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"
READ_CHAR  = "0000ffe2-0000-1000-8000-00805f9b34fb"

HANDSHAKE_1 = bytes([0xD7, 0xF3, 0xA1, 0xD5])
HANDSHAKE_2 = bytes([0x00, 0x00, 0x00, 0x10])

ZONE_ORDER = ["left-top", "left-mid", "left-bot", "right-top", "right-mid", "right-bot"]

# ──────────────────────────────────────────────────────────────────────────────
# Config loading
# ──────────────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)

config = load_config()

# ──────────────────────────────────────────────────────────────────────────────
# In-memory state
# ──────────────────────────────────────────────────────────────────────────────
def _default_state(zone_id: str) -> dict:
    z = config["zones"][zone_id]
    base = {
        "status": "offline",   # "connected" | "offline"
        "on": False,
        "brightness": 200,
    }
    if z["type"] == "rgb":
        base.update({"color": {"r": 255, "g": 140, "b": 0}, "effect": None, "speed": 128})
    else:
        base.update({"kelvin": 4000, "effect": None})
    return base

state: dict[str, dict] = {zid: _default_state(zid) for zid in config["zones"]}

# ──────────────────────────────────────────────────────────────────────────────
# BLE manager
# ──────────────────────────────────────────────────────────────────────────────
clients: dict[str, BleakClient | None] = {zid: None for zid in config["zones"]}
write_queues: dict[str, asyncio.Queue] = {}
ble_loop: asyncio.AbstractEventLoop | None = None
_reconnect_pending: asyncio.Event | None = None


def _cmd_brightness(value: int) -> bytes:
    return bytes([value & 0xFF, 0x00, 0x00, 0x2A])

def _cmd_color(r: int, g: int, b: int) -> bytes:
    return bytes([r & 0xFF, g & 0xFF, b & 0xFF, 0x1E])

def _cmd_effect(preset: int) -> bytes:
    return bytes([preset & 0xFF, 0x00, 0x00, 0x2C])

def _cmd_speed(value: int) -> bytes:
    return bytes([value & 0xFF, 0x00, 0x00, 0x03])

CMD_ON  = bytes([0x00, 0x00, 0x00, 0xAA])
CMD_OFF = bytes([0x00, 0x00, 0x00, 0xAB])


async def _write_worker(zone_id: str) -> None:
    """Drains the write queue for a zone, sending one command at a time."""
    q = write_queues[zone_id]
    while True:
        data = await q.get()
        # Coalesce rapid same-type commands (e.g. slider dragging).
        # Only skip ahead while the next item is the same command type (same last byte).
        # Different command types (ON vs brightness vs color) must all be sent.
        while not q.empty():
            nxt = q.get_nowait()
            q.task_done()
            if nxt[3] == data[3]:
                data = nxt       # newer value, same type — discard older
            else:
                q.put_nowait(nxt)  # different type — put back and stop
                break
        client = clients[zone_id]
        if client and client.is_connected:
            try:
                await client.write_gatt_char(WRITE_CHAR, data, response=False)
                await asyncio.sleep(0.1)
            except Exception as e:
                log.warning("Write failed for %s: %s", zone_id, e)
                state[zone_id]["status"] = "reconnecting"
                clients[zone_id] = None
                if _reconnect_pending is not None:
                    _reconnect_pending.set()
        q.task_done()


def _enqueue(zone_id: str, data: bytes) -> None:
    if ble_loop and zone_id in write_queues:
        ble_loop.call_soon_threadsafe(write_queues[zone_id].put_nowait, data)


def _make_disconnect_callback(zone_id: str):
    def callback(client):
        log.info("%s disconnected", zone_id)
        state[zone_id]["status"] = "reconnecting"
        clients[zone_id] = None
        if _reconnect_pending is not None:
            _reconnect_pending.set()
    return callback


async def _connect_zone(zone_id: str, device) -> bool:
    """Connect to a zone given an already-discovered BLEDevice object."""
    addr = config["zones"][zone_id]["address"]
    try:
        client = BleakClient(
            device,
            timeout=20.0,
            disconnected_callback=_make_disconnect_callback(zone_id),
        )
        await client.connect()
        if not client.is_connected:
            log.warning("%s: connect returned but not connected", zone_id)
            return False
        clients[zone_id] = client
        await client.write_gatt_char(WRITE_CHAR, HANDSHAKE_1, response=False)
        await asyncio.sleep(0.1)
        await client.write_gatt_char(WRITE_CHAR, HANDSHAKE_2, response=False)
        await asyncio.sleep(0.5)
        state[zone_id]["status"] = "connected"
        log.info("✓ %s connected", zone_id)
        return True
    except Exception as e:
        log.info("%s offline (%s: %s)", zone_id, type(e).__name__, e)
        state[zone_id]["status"] = "offline"
        clients[zone_id] = None
        return False


async def _scan_and_connect(zone_ids: list) -> None:
    """Single scan pass to find all target devices, then connect in parallel."""
    targets = {config["zones"][zid]["address"].upper(): zid for zid in zone_ids}
    found = {}

    log.info("Scanning for %d zone(s)...", len(zone_ids))
    discovered = await BleakScanner.discover(timeout=10.0)
    for device in discovered:
        zid = targets.get(device.address.upper())
        if zid:
            found[zid] = device
            log.info("  found %s (%s)", zid, device.address)

    for zid in zone_ids:
        if zid not in found:
            log.info("%s not found in scan — offline", zid)
            state[zid]["status"] = "offline"

    if found:
        await asyncio.gather(*[_connect_zone(zid, dev) for zid, dev in found.items()])


async def _connect_all() -> None:
    await _scan_and_connect(list(config["zones"].keys()))


async def _reconnect_loop() -> None:
    """Reconnects on disconnect event or every 30s for persistent offline zones."""
    while True:
        try:
            await asyncio.wait_for(_reconnect_pending.wait(), timeout=30)
            _reconnect_pending.clear()
            await asyncio.sleep(4)  # grace period — accumulate multiple disconnects
        except asyncio.TimeoutError:
            pass
        pending = [zid for zid, s in state.items() if s["status"] in ("offline", "reconnecting")]
        if pending:
            log.info("Reconnect scan for %d zone(s)...", len(pending))
            await _scan_and_connect(pending)


async def _ble_main() -> None:
    global _reconnect_pending
    _reconnect_pending = asyncio.Event()
    for zone_id in config["zones"]:
        write_queues[zone_id] = asyncio.Queue()
        asyncio.ensure_future(_write_worker(zone_id))

    await _connect_all()
    asyncio.ensure_future(_reconnect_loop())

    # Keep loop alive
    while True:
        await asyncio.sleep(3600)


def _start_ble_thread() -> None:
    global ble_loop
    loop = asyncio.new_event_loop()
    ble_loop = loop
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_ble_main())


# ──────────────────────────────────────────────────────────────────────────────
# Flask app
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)


def _run_ble(coro):
    """Run a coroutine on the BLE event loop from a Flask thread. Returns result."""
    future = asyncio.run_coroutine_threadsafe(coro, ble_loop)
    return future.result(timeout=8)


def _zone_response(zone_id: str) -> dict:
    return {
        "zone": zone_id,
        "label": config["zones"][zone_id]["label"],
        "type": config["zones"][zone_id]["type"],
        **state[zone_id],
    }


def _offline_response(zone_id: str):
    return jsonify({
        "status": "offline",
        "zone": zone_id,
        "message": "Device not reachable — assumed powered off",
    }), 200


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/status")
def get_status():
    result = {}
    for zid in ZONE_ORDER:
        result[zid] = {
            "label": config["zones"][zid]["label"],
            "type": config["zones"][zid]["type"],
            **state[zid],
        }
    return jsonify(result)


# ── Per-zone: power ──────────────────────────────────────────────────────────
@app.route("/zone/<zone_id>/power", methods=["POST"])
def zone_power(zone_id: str):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    if state[zone_id]["status"] != "connected":
        return _offline_response(zone_id)

    on = request.json.get("on", True)
    _enqueue(zone_id, CMD_ON if on else CMD_OFF)
    state[zone_id]["on"] = on
    return jsonify(_zone_response(zone_id))


# ── Per-zone: brightness ─────────────────────────────────────────────────────
@app.route("/zone/<zone_id>/brightness", methods=["POST"])
def zone_brightness(zone_id: str):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    if state[zone_id]["status"] != "connected":
        return _offline_response(zone_id)

    value = max(0, min(255, int(request.json.get("value", 200))))
    _enqueue(zone_id, _cmd_brightness(value))
    state[zone_id]["brightness"] = value
    return jsonify(_zone_response(zone_id))


# ── Per-zone: color (RGB zones) ───────────────────────────────────────────────
@app.route("/zone/<zone_id>/color", methods=["POST"])
def zone_color(zone_id: str):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    if state[zone_id]["status"] != "connected":
        return _offline_response(zone_id)

    data = request.json
    r = max(0, min(255, int(data.get("r", 255))))
    g = max(0, min(255, int(data.get("g", 255))))
    b = max(0, min(255, int(data.get("b", 255))))
    _enqueue(zone_id, _cmd_color(r, g, b))
    if config["zones"][zone_id]["type"] == "rgb":
        state[zone_id]["color"] = {"r": r, "g": g, "b": b}
        state[zone_id]["effect"] = None
    return jsonify(_zone_response(zone_id))


# ── Per-zone: temperature (tunable white) ────────────────────────────────────
@app.route("/zone/<zone_id>/temperature", methods=["POST"])
def zone_temperature(zone_id: str):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    if config["zones"][zone_id]["type"] != "tunable":
        return jsonify({"error": "Temperature only applies to tunable white zones"}), 400
    if state[zone_id]["status"] != "connected":
        return _offline_response(zone_id)

    kelvin = max(2000, min(6500, int(request.json.get("kelvin", 4000))))
    t = (kelvin - 2000) / 4500  # 0 = full amber, 1 = full cool
    cool  = int(t * 255)        # R channel
    amber = int((1 - t) * 255)  # G channel
    _enqueue(zone_id, _cmd_color(cool, amber, 0))
    state[zone_id]["kelvin"] = kelvin
    return jsonify(_zone_response(zone_id))


# ── Per-zone: effect (RGB zones) ─────────────────────────────────────────────
@app.route("/zone/<zone_id>/effect", methods=["POST"])
def zone_effect(zone_id: str):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    if config["zones"][zone_id]["type"] != "rgb":
        return jsonify({"error": "Effects only available on RGB zones"}), 400
    if state[zone_id]["status"] != "connected":
        return _offline_response(zone_id)

    preset = max(1, min(120, int(request.json.get("preset", 1))))
    _enqueue(zone_id, _cmd_effect(preset))
    state[zone_id]["effect"] = preset
    return jsonify(_zone_response(zone_id))


# ── Per-zone: speed ───────────────────────────────────────────────────────────
@app.route("/zone/<zone_id>/speed", methods=["POST"])
def zone_speed(zone_id: str):
    if zone_id not in config["zones"]:
        return jsonify({"error": "Unknown zone"}), 404
    if state[zone_id]["status"] != "connected":
        return _offline_response(zone_id)

    value = max(0, min(255, int(request.json.get("value", 128))))
    _enqueue(zone_id, _cmd_speed(value))
    if "speed" in state[zone_id]:
        state[zone_id]["speed"] = value
    return jsonify(_zone_response(zone_id))


# ── Group endpoints ──────────────────────────────────────────────────────────
GROUP_ZONES = {
    "all": ZONE_ORDER,
    "top": ["left-top", "right-top"],
    "mid": ["left-mid", "right-mid"],
    "bot": ["left-bot", "right-bot"],
}


@app.route("/group/<group>/power", methods=["POST"])
def group_power(group: str):
    if group not in GROUP_ZONES:
        return jsonify({"error": "Unknown group"}), 404
    on = request.json.get("on", True)
    for zid in GROUP_ZONES[group]:
        if state[zid]["status"] == "connected":
            _enqueue(zid, CMD_ON if on else CMD_OFF)
            state[zid]["on"] = on
    return jsonify({zid: _zone_response(zid) for zid in GROUP_ZONES[group]})


@app.route("/group/<group>/brightness", methods=["POST"])
def group_brightness(group: str):
    if group not in GROUP_ZONES:
        return jsonify({"error": "Unknown group"}), 404
    value = max(0, min(255, int(request.json.get("value", 200))))
    for zid in GROUP_ZONES[group]:
        if state[zid]["status"] == "connected":
            _enqueue(zid, _cmd_brightness(value))
            state[zid]["brightness"] = value
    return jsonify({zid: _zone_response(zid) for zid in GROUP_ZONES[group]})


@app.route("/group/all/defaults", methods=["POST"])
def group_defaults():
    for zid in ZONE_ORDER:
        if state[zid]["status"] != "connected":
            continue
        z = config["zones"][zid]
        if z["type"] == "rgb":
            _enqueue(zid, CMD_ON)
            _enqueue(zid, _cmd_brightness(102))
            _enqueue(zid, _cmd_color(128, 0, 128))
            state[zid].update({"on": True, "brightness": 102, "color": {"r": 128, "g": 0, "b": 128}, "effect": None})
        else:
            _enqueue(zid, CMD_ON)
            _enqueue(zid, _cmd_brightness(153))
            _enqueue(zid, _cmd_color(127, 127, 0))
            state[zid].update({"on": True, "brightness": 153, "kelvin": 4250, "effect": None})
    return jsonify({zid: _zone_response(zid) for zid in ZONE_ORDER})


@app.route("/group/all/party", methods=["POST"])
def group_party():
    speed = int(0.6 * 255)  # 60%
    for zid in ZONE_ORDER:
        if state[zid]["status"] != "connected":
            continue
        _enqueue(zid, CMD_ON)
        _enqueue(zid, _cmd_effect(4))
        _enqueue(zid, _cmd_speed(speed))
        state[zid].update({"on": True, "effect": 4})
        if config["zones"][zid]["type"] == "rgb":
            state[zid]["speed"] = speed
    return jsonify({zid: _zone_response(zid) for zid in ZONE_ORDER})


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


async def _disconnect_all() -> None:
    tasks = []
    for zone_id, client in clients.items():
        if client and client.is_connected:
            tasks.append(client.disconnect())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    log.info("All BLE connections closed.")


def _shutdown() -> None:
    if ble_loop and ble_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_disconnect_all(), ble_loop)
        try:
            future.result(timeout=5)
        except Exception:
            pass


if __name__ == "__main__":
    ble_thread = threading.Thread(target=_start_ble_thread, daemon=True)
    ble_thread.start()

    # Wait for loop to be ready
    while ble_loop is None:
        time.sleep(0.05)

    ip = _local_ip()
    print(f"\n{'═'*48}")
    print(f"  SP110E Controller")
    print(f"  Server running at http://{ip}:5000")
    print(f"  Open this URL on your phone")
    print(f"{'═'*48}\n")

    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    finally:
        _shutdown()
