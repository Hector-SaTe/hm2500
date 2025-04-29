import asyncio
from bleak import BleakClient

ADDRESS = "14:80:CC:FA:55:E6"  # Replace with your device's address
CHARACTERISTIC_UUID = "0000ff06-0000-1000-8000-00805f9b34fb"  # Example UUID

async def main():
    async with BleakClient(ADDRESS) as client:
        if await client.is_connected():
            print("Connected!")

            # Writing data
            await client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x01]))

            # Subscribing to notifications
            def notification_handler(sender, data):
                print(f"Notification from {sender}: {data}")

            await client.start_notify(CHARACTERISTIC_UUID, notification_handler)
            await asyncio.sleep(10)  # Keep listening for notifications
            await client.stop_notify(CHARACTERISTIC_UUID)

asyncio.run(main())
