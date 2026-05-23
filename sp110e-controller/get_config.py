"""
Read current configuration from an SP110E device.
Usage:  python get_config.py CA:AC:02:04:32:24
"""
import asyncio, sys
from bleak import BleakClient, BleakScanner

CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"

IC_MODELS = (
    'SM16703','TM1804','UCS1903','WS2811','WS2801','SK6812','LPD6803',
    'LPD8806','APA102','APA105','DMX512','TM1914','TM1913','P9813',
    'INK1003','P943S','P9411','P9413','TX1812','TX1813','GS8206','GS8208',
    'SK9822','TM1814','SK6812_RGBW','P9414','PG412',
)
SEQUENCES = ('RGB','RBG','GRB','GBR','BRG','BGR')

async def main(address):
    print(f"Scanning for {address}...")
    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if not device:
        print("Not found"); sys.exit(1)
    print(f"Found: {device.name}\n")

    received = asyncio.Event()
    params = {}

    def on_notify(sender, data: bytearray):
        if len(data) >= 12:
            params['state']      = 'ON' if data[0] == 1 else 'OFF'
            params['mode']       = data[1]
            params['speed']      = data[2]
            params['brightness'] = data[3]
            params['ic_model']   = IC_MODELS[data[4]] if data[4] < len(IC_MODELS) else f"unknown({data[4]})"
            params['sequence']   = SEQUENCES[data[5]] if data[5] < len(SEQUENCES) else f"unknown({data[5]})"
            params['pixels']     = int.from_bytes(data[6:8], 'big')
            params['color']      = (data[8], data[9], data[10])
            params['white']      = data[11]
            received.set()

    client = BleakClient(device, timeout=20.0)
    try:
        await client.connect()
        await client.start_notify(CHAR, on_notify)
        await client.write_gatt_char(CHAR, bytes([0x00, 0x00, 0x00, 0x10]), response=False)
        try:
            await asyncio.wait_for(received.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            print("No response to read command — device may need power cycle")
            return

        print("── SP110E Configuration ──────────────────")
        for k, v in params.items():
            print(f"  {k:12s}: {v}")
        print("──────────────────────────────────────────")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_config.py <ADDRESS>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
