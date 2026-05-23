"""
Test 1 — BLE Connection Only

Scans for nearby BLE devices and optionally connects to a specific SP110E
to verify the handshake works. No Flask, no config.json, no other zones.

Usage:
    python tests/test_ble_connect.py                        # scan only
    python tests/test_ble_connect.py AA:BB:CC:DD:EE:01      # scan + connect

NOTE: Do NOT pair the SP110E in Windows Bluetooth settings first.
      bleak connects directly by address without OS pairing.
"""

import asyncio
import sys
from bleak import BleakScanner, BleakClient

WRITE_CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"
READ_CHAR  = "0000ffe2-0000-1000-8000-00805f9b34fb"

HANDSHAKE_1 = bytes([0xD7, 0xF3, 0xA1, 0xD5])
HANDSHAKE_2 = bytes([0x00, 0x00, 0x00, 0x10])


async def do_scan() -> list[tuple[str, str]]:
    print("Scanning for BLE devices (10 seconds)...\n")
    devices = await BleakScanner.discover(timeout=10.0)

    found = []
    for d in sorted(devices, key=lambda x: x.name or ""):
        name = d.name or "(unknown)"
        found.append((name, d.address))
        marker = " ← likely SP110E" if "sp110" in name.lower() or "ffe0" in name.lower() else ""
        print(f"  {name:30s}  {d.address}{marker}")

    print(f"\nTotal: {len(found)} device(s) found.")
    return found


async def do_connect(address: str) -> bool:
    print(f"\nConnecting to {address}...")
    received_data: list[bytes] = []

    def notification_handler(_sender: int, data: bytes) -> None:
        received_data.append(data)
        print(f"  Notification from device: {data.hex(' ').upper()}")

    try:
        async with BleakClient(address, timeout=10.0) as client:
            if not client.is_connected:
                print("✗ Connection failed (client reports not connected)")
                return False
            print("✓ Connected")

            # Subscribe to notifications on read char if available
            try:
                await client.start_notify(READ_CHAR, notification_handler)
            except Exception:
                pass  # read char may not support notifications on all firmware

            print("Sending handshake...")
            await client.write_gatt_char(WRITE_CHAR, HANDSHAKE_1, response=False)
            await asyncio.sleep(0.1)
            await client.write_gatt_char(WRITE_CHAR, HANDSHAKE_2, response=False)
            print("✓ Handshake sent")

            # Wait briefly for any response
            await asyncio.sleep(0.5)

            # Try to read device info directly
            try:
                info = await client.read_gatt_char(READ_CHAR)
                print(f"Device info response: {info.hex(' ').upper()}")
            except Exception as e:
                print(f"  (Read char not directly readable: {e})")

            if received_data:
                print(f"Notification data received: {len(received_data)} packet(s)")
            else:
                print("  (No notification data — device may not push on connect)")

            print("\n✓ Test passed — BLE connection working")
            print("Disconnecting...")

        print("✓ Done")
        return True

    except Exception as e:
        print(f"✗ Connection error: {e}")
        return False


async def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else None

    found = await do_scan()

    if target is None:
        if found:
            print("\nTo test a specific device, run:")
            print(f"  python tests/test_ble_connect.py <ADDRESS>")
        return

    success = await do_connect(target)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
