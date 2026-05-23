import asyncio
from bleak import BleakScanner, BleakClient

TARGET_NAME = "RightMid"
TARGET_ADDR = "CA:AC:02:04:32:24"

# Common SP110E / LED Hue BLE characteristic
WRITE_CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"

async def main():
    print("Scanning...")
    devices = await BleakScanner.discover(timeout=10)

    target = None
    for d in devices:
        print(d.name, d.address)
        if d.name == TARGET_NAME or d.address.upper() == TARGET_ADDR:
            target = d

    if not target:
        print("Could not find RightMid")
        return

    print("Connecting...")
    async with BleakClient(target, timeout=45.0, services=["0000ffe0-0000-1000-8000-00805f9b34fb"]) as client:
        print("Connected:", client.is_connected)

        # Turn on / basic test packet
        command = bytearray([0xAA, 0x22, 0x01, 0x55])

        print("Writing command...")
        await client.write_gatt_char(WRITE_CHAR, command, response=False)

        print("Done")

asyncio.run(main())