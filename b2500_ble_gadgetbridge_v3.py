import asyncio
from bleak import BleakClient
from typing import Optional

# Device MAC (replace with yours)
B2500_MAC = "14:80:CC:FA:55:E6"

# UUIDs from GadgetBridge Java code
SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
CHAR_WRITE_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"  # Control characteristic
CHAR_NOTIFY_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"  # Notify characteristic

# Protocol constants from Java code
HEADER = bytes.fromhex("AA55")
FOOTER = bytes.fromhex("55AA")
COMMAND_GET_DATA = 0x03  # Example command to fetch battery/solar data

def build_command(command: int, payload: bytes = b"") -> bytes:
    """
    Constructs a B2500 protocol message with header, checksum, and footer.
    Replicates the Java code's logic.
    """
    length = len(payload) + 1  # Length includes command byte
    
    # Calculate checksum (Java: sum of command + length + payload bytes)
    checksum = (command + length + sum(payload)) & 0xFF
    
    return (
        HEADER +
        bytes([command, length]) +
        payload +
        bytes([checksum]) +
        FOOTER
    )

def parse_response(data: bytes) -> Optional[dict]:
    """
    Parses B2500 response data into usable values.
    Based on GadgetBridge's handleResponse() logic.
    """
    if not data.startswith(HEADER) or not data.endswith(FOOTER):
        return None

    payload = data[4:-3]  # Strip header, command, length, checksum, footer
    
    try:
        # Example: Extract voltage/current (adjust positions based on your device)
        voltage = int.from_bytes(payload[0:2], byteorder="little") / 100.0  # e.g., 24.5V
        current = int.from_bytes(payload[2:4], byteorder="little") / 100.0  # e.g., 5.0A
        return {"voltage": voltage, "current": current}
    except Exception as e:
        print(f"Parse error: {e}")
        return None

async def main():
    async with BleakClient(B2500_MAC) as client:
        print(f"Connected: {client.is_connected}")

        # Notification handler
        def notification_handler(sender: str, data: bytes):
            print(f"Raw response: {data.hex()}")
            if parsed := parse_response(data):
                print(f"Battery: {parsed['voltage']}V | Solar Input: {parsed['current']}A")

        await client.start_notify(CHAR_NOTIFY_UUID, notification_handler)

        # Send "get data" command (0x03) - replicates Java code's COMMAND_GET_DATA
        command = build_command(COMMAND_GET_DATA)
        print(f"Sending command: {command.hex()}")
        await client.write_gatt_char(CHAR_WRITE_UUID, command, response=False)

        # Keep connection alive
        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())