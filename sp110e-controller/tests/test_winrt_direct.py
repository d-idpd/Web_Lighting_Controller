"""
Test — raw WinRT BLE write, bypassing bleak's connect/GATT-session management.

Bleak's connect() creates a GattSession which times out on SP110E.
This test goes directly through the Windows BLE WinRT API:
  BluetoothLEDevice -> GetGattServicesAsync -> GetCharacteristicsAsync -> WriteValue

Usage:
    python tests\test_winrt_direct.py CA:AC:02:04:32:24
"""
import asyncio
import sys
from bleak import BleakScanner

from winrt.windows.devices.bluetooth import (
    BluetoothCacheMode,
    BluetoothLEDevice,
)
from winrt.windows.devices.bluetooth.genericattributeprofile import (
    GattCommunicationStatus,
    GattWriteOption,
)
from winrt.windows.storage.streams import DataWriter

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID    = "0000ffe1-0000-1000-8000-00805f9b34fb"

HANDSHAKE_1 = bytes([0xD7, 0xF3, 0xA1, 0xD5])
HANDSHAKE_2 = bytes([0x00, 0x00, 0x00, 0x10])
CMD_ON      = bytes([0x00, 0x00, 0x00, 0xAA])
CMD_OFF     = bytes([0x00, 0x00, 0x00, 0xAB])


def _bytes_to_ibuffer(data: bytes):
    writer = DataWriter()
    writer.write_bytes(list(data))
    return writer.detach_buffer()


async def winrt_write(char, data: bytes, label: str):
    buf = _bytes_to_ibuffer(data)
    result = await wrap_IAsyncOperation(
        char.write_value_with_result_async(buf, GattWriteOption.WRITE_WITHOUT_RESPONSE)
    )
    if result.status == GattCommunicationStatus.SUCCESS:
        print(f"  ✓ {label}")
        return True
    else:
        print(f"  ✗ {label}  status={result.status}")
        return False


async def main(address: str) -> None:
    print(f"Scanning for {address}...")
    found = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if found is None:
        print("✗ Not found — power-cycle and retry")
        sys.exit(1)
    print("✓ Found\n")

    addr_int = int(address.replace(":", ""), 16)

    print("Getting BluetoothLEDevice from WinRT...")
    ble_device = await wrap_IAsyncOperation(
        BluetoothLEDevice.from_bluetooth_address_async(addr_int)
    )
    if ble_device is None:
        print("✗ from_bluetooth_address_async returned None")
        sys.exit(1)
    print(f"✓ Got device: {ble_device.name or '(no name)'}\n")

    # Try cached first (instant), fall back to uncached
    for cache_mode, label in [
        (BluetoothCacheMode.CACHED,   "CACHED"),
        (BluetoothCacheMode.UNCACHED, "UNCACHED"),
    ]:
        print(f"GetGattServicesAsync({label})...")
        try:
            svc_result = await asyncio.wait_for(
                wrap_IAsyncOperation(
                    ble_device.get_gatt_services_async(cache_mode)
                ),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            print(f"  timed out after 10s")
            continue
        except Exception as e:
            print(f"  failed: {type(e).__name__}: {e}")
            continue

        if svc_result.status != GattCommunicationStatus.SUCCESS:
            print(f"  status={svc_result.status} (not SUCCESS)")
            continue

        services = list(svc_result.services)
        print(f"  ✓ {len(services)} service(s) found")
        for s in services:
            print(f"    {s.uuid}")

        # Find our FFE0 service
        target_svc = None
        for s in services:
            if str(s.uuid).lower() == SERVICE_UUID:
                target_svc = s
                break

        if target_svc is None:
            print(f"  ✗ Service {SERVICE_UUID} not in results")
            continue

        # Get characteristic
        print(f"\nGetCharacteristicsAsync({CHAR_UUID})...")
        try:
            char_result = await asyncio.wait_for(
                wrap_IAsyncOperation(
                    target_svc.get_characteristics_async(cache_mode)
                ),
                timeout=5.0,
            )
        except Exception as e:
            print(f"  failed: {type(e).__name__}: {e}")
            continue

        chars = [c for c in char_result.characteristics
                 if str(c.uuid).lower() == CHAR_UUID]
        if not chars:
            print(f"  ✗ Characteristic {CHAR_UUID} not found")
            continue

        char = chars[0]
        print(f"  ✓ Got characteristic\n")

        # Send handshake + test commands
        print("Sending handshake...")
        if not await winrt_write(char, HANDSHAKE_1, "Handshake 1"):
            break
        await asyncio.sleep(0.1)
        if not await winrt_write(char, HANDSHAKE_2, "Handshake 2"):
            break
        await asyncio.sleep(0.3)

        print("\nTurning ON...")
        await winrt_write(char, CMD_ON, "ON")
        await asyncio.sleep(2)
        print("Turning OFF...")
        await winrt_write(char, CMD_OFF, "OFF")
        await asyncio.sleep(0.5)

        print("\n✓ Done!")
        ble_device.close()
        return

    print("\n✗ Could not get GATT services via either cache mode")
    ble_device.close()
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests\\test_winrt_direct.py <ADDRESS>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
