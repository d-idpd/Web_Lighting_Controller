"""
Test 2 — BLE Connection + RGB Control

Runs an automated command sequence against a single SP110E, or drops into
an interactive REPL if --interactive is passed. No Flask, no web UI.

Usage:
    python tests/test_ble_control.py AA:BB:CC:DD:EE:01
    python tests/test_ble_control.py AA:BB:CC:DD:EE:01 --interactive
"""

import asyncio
import sys
import argparse
import traceback
from bleak import BleakClient, BleakScanner

WRITE_CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"

HANDSHAKE_1 = bytes([0xD7, 0xF3, 0xA1, 0xD5])
HANDSHAKE_2 = bytes([0x00, 0x00, 0x00, 0x10])

CMD_ON         = bytes([0x00, 0x00, 0x00, 0xAA])
CMD_OFF        = bytes([0x00, 0x00, 0x00, 0xAB])


def cmd_brightness(value: int) -> bytes:
    return bytes([value & 0xFF, 0x00, 0x00, 0x2A])

def cmd_color(r: int, g: int, b: int) -> bytes:
    return bytes([r & 0xFF, g & 0xFF, b & 0xFF, 0x1E])

def cmd_effect(preset: int) -> bytes:
    return bytes([preset & 0xFF, 0x00, 0x00, 0x2C])

def cmd_speed(value: int) -> bytes:
    return bytes([value & 0xFF, 0x00, 0x00, 0x03])


async def send(client: BleakClient, data: bytes, label: str) -> bool:
    try:
        await client.write_gatt_char(WRITE_CHAR, data, response=False)
        print(f"  ✓ {label}")
        return True
    except Exception as e:
        print(f"  ✗ {label}  ERROR: {e}")
        return False


async def handshake(client: BleakClient) -> bool:
    print("Sending handshake...")
    ok1 = await send(client, HANDSHAKE_1, "Handshake part 1")
    await asyncio.sleep(0.1)
    ok2 = await send(client, HANDSHAKE_2, "Handshake part 2 (get device info)")
    await asyncio.sleep(0.3)
    return ok1 and ok2


async def run_automated(client: BleakClient) -> tuple[int, int]:
    passed = 0
    total = 0

    async def step(data: bytes, label: str, delay: float = 1.0) -> None:
        nonlocal passed, total
        total += 1
        if await send(client, data, label):
            passed += 1
        await asyncio.sleep(delay)

    print("\n--- Automated sequence ---\n")
    await step(CMD_ON,                           "Turn ON")
    await step(cmd_brightness(128),              "Set brightness 50%")
    await step(cmd_color(255, 0, 0),             "Set color RED",   delay=2.0)
    await step(cmd_color(0, 255, 0),             "Set color GREEN", delay=2.0)
    await step(cmd_color(0, 0, 255),             "Set color BLUE",  delay=2.0)
    await step(cmd_color(255, 255, 255),         "Set color WHITE", delay=2.0)
    await step(cmd_brightness(255),              "Set brightness 100%")
    await step(cmd_effect(1),                    "Set effect Rainbow (preset 1)", delay=3.0)
    await step(CMD_OFF,                          "Turn OFF")

    return passed, total


INTERACTIVE_HELP = """
Commands:
  on                  Turn on
  off                 Turn off
  color R G B         Set color (0-255 each)   e.g. color 255 0 128
  brightness N        Set brightness (0-255)    e.g. brightness 128
  effect N            Set effect preset (1-120) e.g. effect 27
  speed N             Set speed (0-255)         e.g. speed 200
  help                Show this help
  quit / exit         Disconnect and exit
"""

async def run_interactive(client: BleakClient) -> None:
    print("\n--- Interactive mode ---")
    print(INTERACTIVE_HELP)
    loop = asyncio.get_event_loop()

    while True:
        try:
            raw = await loop.run_in_executor(None, lambda: input("SP110E Control > "))
        except (EOFError, KeyboardInterrupt):
            break

        parts = raw.strip().split()
        if not parts:
            continue

        cmd = parts[0].lower()

        if cmd in ("quit", "exit", "q"):
            break
        elif cmd == "help":
            print(INTERACTIVE_HELP)
        elif cmd == "on":
            await send(client, CMD_ON, "Turn ON")
        elif cmd == "off":
            await send(client, CMD_OFF, "Turn OFF")
        elif cmd == "color":
            if len(parts) != 4:
                print("  Usage: color R G B  (e.g. color 255 0 128)")
                continue
            try:
                r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
            except ValueError:
                print("  Values must be integers 0-255")
                continue
            await send(client, cmd_color(r, g, b), f"Set color R={r} G={g} B={b}")
        elif cmd == "brightness":
            if len(parts) != 2:
                print("  Usage: brightness N  (0-255)")
                continue
            try:
                v = int(parts[1])
            except ValueError:
                print("  Value must be an integer 0-255")
                continue
            await send(client, cmd_brightness(v), f"Set brightness {v}")
        elif cmd == "effect":
            if len(parts) != 2:
                print("  Usage: effect N  (1-120)")
                continue
            try:
                n = int(parts[1])
            except ValueError:
                print("  Value must be an integer 1-120")
                continue
            await send(client, cmd_effect(n), f"Set effect preset {n}")
        elif cmd == "speed":
            if len(parts) != 2:
                print("  Usage: speed N  (0-255)")
                continue
            try:
                v = int(parts[1])
            except ValueError:
                print("  Value must be an integer 0-255")
                continue
            await send(client, cmd_speed(v), f"Set speed {v}")
        else:
            print(f"  Unknown command: {cmd}  (type 'help' for a list)")

    print("Exiting interactive mode.")


async def main(address: str, interactive: bool) -> None:
    # Scan first — Windows WinRT needs the device in its BLE cache before
    # GATT service discovery will succeed on a direct address connect.
    print(f"Scanning for {address}...")
    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if device is None:
        print(f"✗ Device {address} not found — make sure it is powered on and advertising")
        sys.exit(1)
    print(f"✓ Found: {device.name or '(no name)'}\n")

    client = None
    for attempt in range(1, 4):
        use_cache = attempt > 1  # first attempt populates Windows cache; retries use it
        print(f"Connecting (attempt {attempt}/3, cache={'yes' if use_cache else 'no'})...")
        client = BleakClient(device, timeout=20.0, dangerous_use_bleak_cache=use_cache)
        try:
            await client.connect()
            break  # success
        except TimeoutError:
            print(f"  timed out, disconnecting...")
            try:
                await client.disconnect()
            except Exception:
                pass
            if attempt < 3:
                # Device stops advertising while connected; give Windows time to
                # release the connection and let the SP110E start advertising again
                print(f"  waiting for device to re-advertise (up to 20s)...")
                device = await BleakScanner.find_device_by_address(address, timeout=20.0)
                if device is None:
                    print(f"  still not visible — waiting another 15s...")
                    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
                if device is None:
                    print(f"✗ Device not found after disconnect — power-cycle and retry")
                    sys.exit(1)
            else:
                raise
    try:
        if not client.is_connected:
            print("✗ Connection failed")
            sys.exit(1)
        print("✓ Connected\n")

        if not await handshake(client):
            print("✗ Handshake failed — aborting")
        else:
            print("✓ Handshake complete\n")
            if interactive:
                await run_interactive(client)
            else:
                passed, total = await run_automated(client)
                print(f"\n{'─'*30}")
                print(f"Result: {passed}/{total} commands succeeded")
                if passed == total:
                    print("✓ All passed")
                else:
                    print(f"✗ {total - passed} command(s) failed")

    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
        traceback.print_exc()

    finally:
        print("\nDisconnecting...")
        try:
            await client.disconnect()
            await asyncio.sleep(0.5)   # give WinRT time to signal the device
            print("✓ Disconnected")
        except Exception as e:
            print(f"  (disconnect error: {type(e).__name__}: {e})")

    print("✓ Done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SP110E BLE control test")
    parser.add_argument("address", help="BLE MAC address of the SP110E")
    parser.add_argument("--interactive", action="store_true",
                        help="Drop into interactive REPL instead of automated sequence")
    args = parser.parse_args()
    asyncio.run(main(args.address, args.interactive))
