"""
Test — connect using Windows GATT cache (dangerous_use_bleak_cache=True).

After multiple failed connection attempts Windows may have cached the SP110E's
GATT services.  This test skips live GATT discovery and reads from that cache
instead, which avoids the GetGattServicesAsync timeout.

Usage:
    python tests\test_cache_connect.py CA:AC:02:04:32:24
"""
import asyncio
import sys
from bleak import BleakClient, BleakScanner

WRITE_CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"
HANDSHAKE_1 = bytes([0xD7, 0xF3, 0xA1, 0xD5])
HANDSHAKE_2 = bytes([0x00, 0x00, 0x00, 0x10])
CMD_ON      = bytes([0x00, 0x00, 0x00, 0xAA])
CMD_OFF     = bytes([0x00, 0x00, 0x00, 0xAB])


async def main(address: str) -> None:
    print(f"Scanning for {address}...")
    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if device is None:
        print("✗ Not found — power-cycle the device and try again")
        sys.exit(1)
    print(f"✓ Found\n")

    print("Connecting (dangerous_use_bleak_cache=True — uses Windows GATT cache)...")
    client = BleakClient(device, timeout=20.0, dangerous_use_bleak_cache=True)
    try:
        await client.connect()
    except Exception as e:
        print(f"✗ connect() failed: {type(e).__name__}: {e}")
        sys.exit(1)

    print(f"✓ connect() returned  is_connected={client.is_connected}")
    print(f"  Services discovered: {len(client.services.services)}")
    for svc in client.services.services.values():
        print(f"    Service {svc.uuid}")
        for char in svc.characteristics:
            print(f"      Char {char.uuid}  props={char.properties}")

    if not client.services.services:
        print("\n✗ Services list is empty — Windows cache is empty for this device.")
        print("  Try: open Windows Bluetooth settings, let it scan and discover the device,")
        print("  then run this test again (do NOT pair it).")
        await client.disconnect()
        sys.exit(1)

    # Try handshake
    print(f"\nSending handshake...")
    try:
        await client.write_gatt_char(WRITE_CHAR, HANDSHAKE_1, response=False)
        print("  ✓ Handshake 1 sent")
        await asyncio.sleep(0.1)
        await client.write_gatt_char(WRITE_CHAR, HANDSHAKE_2, response=False)
        print("  ✓ Handshake 2 sent")
    except Exception as e:
        print(f"  ✗ Write failed: {type(e).__name__}: {e}")
        await client.disconnect()
        sys.exit(1)

    print("\nTurning ON...")
    await client.write_gatt_char(WRITE_CHAR, CMD_ON, response=False)
    await asyncio.sleep(2)
    print("Turning OFF...")
    await client.write_gatt_char(WRITE_CHAR, CMD_OFF, response=False)
    await asyncio.sleep(1)

    print("\n✓ All commands sent successfully!")

    await client.disconnect()
    await asyncio.sleep(0.5)
    print("✓ Disconnected")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests\\test_cache_connect.py <BLE_ADDRESS>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
