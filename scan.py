import asyncio
from bleak import BleakScanner

async def run():
    print("Scanning for BLE devices...")
    devices = await BleakScanner.discover()
    print("Scan complete. Found devices:")
    for d in devices:
        print(f"  Address: {d.address}, Name: {d.name or 'Unknown'}, RSSI: {d.rssi}, Metadata: {d.metadata}")

if __name__ == "__main__":
    asyncio.run(run())


# Address: 14:80:CC:FA:55:E6, Name: HM_B2500_55e6, RSSI: -87, Metadata: {'uuids': [], 'manufacturer_data': {}}