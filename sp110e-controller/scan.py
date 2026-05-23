"""
Scan for nearby BLE devices and identify SP110E controllers.
Run this to find the MAC addresses to put in config.json.

Usage:
    python scan.py
    python scan.py --timeout 15   (scan for 15 seconds instead of 10)

NOTE: Do NOT pair SP110E devices in Windows Bluetooth settings.
      bleak connects directly by address without OS pairing.
"""

import asyncio
import argparse
from bleak import BleakScanner

SP110E_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"


async def scan(timeout: float) -> None:
    print(f"Scanning for BLE devices ({int(timeout)} seconds)...\n")

    raw = await BleakScanner.discover(timeout=timeout, return_adv=True)

    # return_adv=True gives dict[address, (device, adv)] on newer bleak,
    # older versions may return a plain list[BLEDevice]
    if isinstance(raw, dict):
        entries = [(dev, adv) for dev, adv in raw.values()]
    else:
        entries = [(dev, None) for dev in raw]

    sp110e = []
    others = []

    for device, adv in entries:
        name = device.name or "(unknown)"
        uuids = [str(u).lower() for u in ((adv.service_uuids if adv else None) or [])]
        is_sp110e = (
            "sp110" in name.lower()
            or "0000ffe0" in " ".join(uuids)
            or "ffe0" in " ".join(uuids)
        )
        if is_sp110e:
            sp110e.append((name, device.address))
        else:
            others.append((name, device.address))

    if sp110e:
        print(f"{'─'*48}")
        print(f"  SP110E / Likely matches  ({len(sp110e)} found)")
        print(f"{'─'*48}")
        for name, addr in sp110e:
            print(f"  {name:24s}  {addr}")
        print()
    else:
        print("No devices matched SP110E heuristics (name or FFE0 service).")
        print("They may appear in the full list below with a generic name.\n")

    if others:
        print(f"{'─'*48}")
        print(f"  All other BLE devices  ({len(others)} found)")
        print(f"{'─'*48}")
        for name, addr in others:
            print(f"  {name:24s}  {addr}")
        print()

    total = len(entries)
    print(f"Total devices found: {total}")

    if sp110e:
        print("\nNext step: copy the addresses above into config.json.")
    else:
        print(
            "\nTip: If you see devices named 'BT-4.0', 'LEDnet', or similar,")
        print("     try those addresses in config.json — SP110E names vary by firmware.")
        print("     You can also run:  python tests/test_ble_connect.py <ADDRESS>")
        print("     to test a specific address and see the handshake response.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan for SP110E BLE devices")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help="Scan duration in seconds (default: 10)")
    args = parser.parse_args()
    asyncio.run(scan(args.timeout))


if __name__ == "__main__":
    main()
