import asyncio
from sp110e.controller import Controller as SP110E
from bleak import BleakScanner

async def find_sp110e():
    """Scan for SP110E device and return its MAC address."""
    print("Scanning for SP110E...")
    devices = await BleakScanner.discover(timeout=5.0)
    for d in devices:
        if d.name and "SP110E" in d.name.upper():
            print(f"Found SP110E: {d.name} - {d.address}")
            return d.address
    print("No SP110E device found. Make sure it is powered on and in range.")
    return None

async def main():
    mac_address = "CA:AC:02:04:32:24"
    # mac_address = await find_sp110e()
    # if not mac_address:
    #     return

    led = SP110E(mac_address)
    print("Connecting...")
    await led.connect()
    print("Connected!")

    colors = [
        (255, 0, 0),   # Red
        (0, 255, 0),   # Green
        (0, 0, 255)    # Blue
    ]

    for r, g, b in colors:
        print(f"Setting color to RGB({r}, {g}, {b})...")
        await led.set_color(r, g, b)
        await asyncio.sleep(2)

    print("Disconnecting...")
    await led.disconnect()
    print("Done.")

if __name__ == "__main__":
    asyncio.run(main())