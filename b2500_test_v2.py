import asyncio
from bleak import BleakClient

B2500_MAC = "14:80:CC:FA:55:E6"
WRITE_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
NOTIFY_UUIDS = [
    "0000ff01-0000-1000-8000-00805f9b34fb",
    "0000ff02-0000-1000-8000-00805f9b34fb",
]

def notification_handler(sender, data):
    print(f"Notification from {sender}: {data.hex()}")

async def main():
    async with BleakClient(B2500_MAC) as client:
        if await client.is_connected():
            print("✅ Connected")

            # Enable all known notify channels
            for uuid in NOTIFY_UUIDS:
                try:
                    await client.start_notify(uuid, notification_handler)
                    print(f"🔔 Subscribed to {uuid}")
                except Exception as e:
                    print(f"⚠️ Could not subscribe to {uuid}: {e}")

            # Send command that should trigger a response
            try:
                command = bytes.fromhex("01 03 00 00 00 0A 05 CD")  # Read command
                await client.write_gatt_char(WRITE_UUID, command, response=False)
                print("📤 Command sent")
            except Exception as e:
                print(f"⚠️ Failed to write: {e}")

            # Wait for data
            await asyncio.sleep(10)

            # Cleanup
            for uuid in NOTIFY_UUIDS:
                try:
                    await client.stop_notify(uuid)
                except:
                    pass

asyncio.run(main())
