# /// script
# requires-python = ">=3.11"
# dependencies = ["bleak>=0.22"]
# ///
"""Probe-Tool für die Beurer WL75 über BLE (Protokoll siehe docs/wl75-protocol.md).

Verwendung:
    uv run tools/wl75_probe.py scan
    uv run tools/wl75_probe.py probe <adresse> [--listen 10]
    uv run tools/wl75_probe.py send <adresse> 12 01 [--listen 3] [--no-handshake]

Auf macOS ist <adresse> eine CoreBluetooth-UUID, keine MAC-Adresse.
"""

import argparse
import asyncio
from datetime import datetime

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

WRITE_UUID = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
NOTIFY_UUID = "0734594a-a8e7-4b1a-a6b1-cd5243059a57"

HANDSHAKE = [0x00, 0x75]

# Nur lesende Abfragen
QUERIES = {
    "Settings": [0x01],
    "Alarm 1": [0x04, 0x01],
    "Alarm 2": [0x04, 0x02],
    "Radio": [0x06],
    "Radio-Presets 1-5": [0x07],
    "Radio-Presets 6-10": [0x08],
    "Licht": [0x11],
    "Stimmungslicht": [0x16],
    "Sleep": [0x1D],
}


def hexstr(data: bytes | list[int]) -> str:
    return " ".join(f"{b:02x}" for b in data)


def build_frame(payload: list[int]) -> bytes:
    """FE EF LEN <payload> CHK, LEN = len(payload) + 1, CHK = LEN ^ alle Payload-Bytes."""
    length = len(payload) + 1
    checksum = length
    for b in payload:
        checksum ^= b
    return bytes([0xFE, 0xEF, length, *payload, checksum])


def on_notify(char: BleakGATTCharacteristic, data: bytearray) -> None:
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] NOTIFY ({len(data)} B): {hexstr(data)}")


async def scan(timeout: float) -> None:
    print(f"Scanne {timeout:.0f}s ...")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    rows = sorted(found.values(), key=lambda x: x[1].rssi, reverse=True)
    for device, adv in rows:
        name = adv.local_name or device.name
        if not name:
            continue
        print(f"{device.address}  rssi={adv.rssi:4d}  name={name!r}")
        if adv.service_uuids:
            print(f"    services: {', '.join(adv.service_uuids)}")
        for company, payload in adv.manufacturer_data.items():
            print(f"    manufacturer 0x{company:04x}: {hexstr(payload)}")
        for uuid, payload in adv.service_data.items():
            print(f"    service_data {uuid}: {hexstr(payload)}")


async def send(client: BleakClient, payload: list[int]) -> None:
    frame = build_frame(payload)
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] WRITE  ({len(frame)} B): {hexstr(frame)}")
    await client.write_gatt_char(WRITE_UUID, frame, response=False)


async def connect(address: str, handshake: bool = True) -> BleakClient:
    device = await BleakScanner.find_device_by_address(address, timeout=15)
    if device is None:
        raise SystemExit(f"Gerät {address} nicht gefunden (App noch verbunden?)")
    client = BleakClient(
        device, disconnected_callback=lambda _: print(f"[{datetime.now():%H:%M:%S.%f}] !! getrennt")
    )
    await client.connect(timeout=20)
    print(f"Verbunden mit {device.name} ({device.address})")
    await client.start_notify(NOTIFY_UUID, on_notify)
    if handshake:
        await send(client, HANDSHAKE)
        await asyncio.sleep(1)
    return client


async def probe(address: str, listen: float) -> None:
    client = await connect(address)
    try:
        for name, payload in QUERIES.items():
            print(f"-- {name}")
            await send(client, payload)
            await asyncio.sleep(1)
        print(
            f"\nHöre {listen:.0f}s auf Notifications – jetzt gerne Tasten an der Lampe drücken ..."
        )
        await asyncio.sleep(listen)
    finally:
        await client.disconnect()


async def send_cmd(address: str, payload: list[int], listen: float, handshake: bool) -> None:
    client = await connect(address, handshake)
    try:
        await send(client, payload)
        await asyncio.sleep(listen)
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--timeout", type=float, default=10)

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("address")
    p_probe.add_argument("--listen", type=float, default=10)

    p_send = sub.add_parser("send", help="Payload in Hex, z.B. '12 01' (Rahmen wird ergänzt)")
    p_send.add_argument("address")
    p_send.add_argument("payload", nargs="+")
    p_send.add_argument("--listen", type=float, default=3)
    p_send.add_argument("--no-handshake", action="store_true")

    args = parser.parse_args()
    if args.cmd == "scan":
        asyncio.run(scan(args.timeout))
    elif args.cmd == "probe":
        asyncio.run(probe(args.address, args.listen))
    elif args.cmd == "send":
        payload = [int(b, 16) for b in args.payload]
        asyncio.run(send_cmd(args.address, payload, args.listen, not args.no_handshake))


if __name__ == "__main__":
    main()
