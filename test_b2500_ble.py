import asyncio
import logging
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# --- Configuration ---
B2500_MAC = "14:80:CC:FA:55:E6"

# --- UUIDs: Using FF06 based on Copilot's successful test ---
CHARACTERISTIC_UUID_RW_NOTIFY = "0000ff06-0000-1000-8000-00805f9b34fb" # Use FF06 for both

# --- Command Code ---
CMD_READ_ALL = 0x04

# --- CRC16 Calculation (CCITT-FALSE - Assume correct for COMMAND frame) ---
def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE calculation."""
    poly = 0x1021; crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8): crc = (crc << 1) ^ poly if (crc & 0x8000) else crc << 1
    return crc & 0xFFFF

# --- Command Frame Builder (Using 01 Len Cmd ... CRC_BE format) ---
def build_hm_cmd(cmd: int, data: bytes = b'') -> bytes:
    """Builds the command frame: 01 len cmd [data] crc_hi crc_lo"""
    frame_header = b'\x01'; frame_len = 1 + len(data)
    frame_cmd = cmd.to_bytes(1, 'big')
    payload_part = frame_cmd + data
    crc_val = crc16(payload_part)
    frame_crc = crc_val.to_bytes(2, 'big') # Big Endian
    full_frame = frame_header + frame_len.to_bytes(1, 'big') + payload_part + frame_crc
    log.debug(f"Built Frame: {full_frame.hex(':')}")
    return full_frame

# --- Response Frame Parser (Checks header, len, CRC for 01...) ---
def parse_b2500_response(data: bytes):
    """Parses a received frame, checking for 01 Len... format and CRC (CCITT)."""
    log.info(f"Attempting to parse frame: {data.hex(':')}") # More visible log

    # 1. Check minimum length and header 0x01
    if not data or len(data) < 5 or data[0] != 0x01:
        log.warning(f"Frame does not match expected 0x01 structure.")
        # Check if it matches the simple response from Copilot's test
        if data == b'\xaa\x01\x02\x03':
            log.warning("Received known simple/error response AA:01:02:03")
        return None # Cannot parse with this structure

    # (Rest of the parsing logic from previous script)
    frame_len = data[1]; expected_total_len = 1 + 1 + frame_len + 2
    if len(data) != expected_total_len: log.warning(f"Invalid 0x01 frame: Length mismatch. Expected {expected_total_len}, Got {len(data)}")
    payload_part = data[2 : 2 + frame_len]; received_crc_bytes = data[2 + frame_len :]
    if len(received_crc_bytes) != 2: log.warning(f"Invalid 0x01 frame: Incorrect CRC length ({len(received_crc_bytes)} bytes)"); return None
    received_crc = int.from_bytes(received_crc_bytes, 'big')
    calculated_crc = crc16(payload_part)
    if received_crc != calculated_crc: log.error(f"CRC mismatch! Calculated: {calculated_crc:04X}, Received: {received_crc:04X}. Frame: {data.hex(':')}"); return None
    if not payload_part: log.warning("Invalid 0x01 frame: Payload part is empty"); return None
    response_cmd = payload_part[0]; response_data = payload_part[1:]
    log.info(f"Valid 0x01 response received! CMD={response_cmd:02X}, Data={response_data.hex(':')}")
    print(f"Successfully parsed 0x01 response: CMD={response_cmd:02X}, Data Len={len(response_data)}")
    return {"cmd": response_cmd, "data": response_data}


# --- Notification Handler ---
def notification_handler(sender: int, data: bytearray):
    """Handles incoming BLE notifications & calls parser."""
    log.info(f"<- Notification Received (Handle: {sender}): {bytes(data).hex(':')}")
    parse_b2500_response(bytes(data))

# --- Main Async Function ---
async def run_test_ff06(device_mac: str):
    """Connects, starts notify on FF06, writes command 0x04 to FF06."""
    log.info(f"--- Starting B2500 Read Test (Using RW/Notify Char: {CHARACTERISTIC_UUID_RW_NOTIFY}) ---")
    log.info(f"Target Device MAC: {device_mac}")

    try:
        log.info("Attempting to connect...")
        async with BleakClient(device_mac, timeout=20.0) as client:
            if not client.is_connected: log.error("Failed to connect."); return
            log.info(f"Connected successfully to {device_mac}!")

            try:
                log.info(f"Starting notifications on characteristic {CHARACTERISTIC_UUID_RW_NOTIFY}...")
                await client.start_notify(CHARACTERISTIC_UUID_RW_NOTIFY, notification_handler)
                log.info("Notifications started.")
            except Exception as e:
                log.error(f"CRITICAL ERROR starting notifications on {CHARACTERISTIC_UUID_RW_NOTIFY}: {e}")
                return

            # Build the CORRECT 0x04 command
            read_command_bytes = build_hm_cmd(CMD_READ_ALL)
            log.info(f"Prepared 'Read All' command: {read_command_bytes.hex(':')}") # Expect 01:01:04:a1:74

            try:
                log.info(f"Sending command to characteristic {CHARACTERISTIC_UUID_RW_NOTIFY}...")
                await client.write_gatt_char(CHARACTERISTIC_UUID_RW_NOTIFY, read_command_bytes, response=False)
                log.info("Command sent successfully.")
            except Exception as e:
                log.error(f"Error writing command: {e}"); await client.stop_notify(CHARACTERISTIC_UUID_RW_NOTIFY); return

            log.info("Waiting for responses... (Press Ctrl+C to stop early)")
            await asyncio.sleep(30)
            log.info("Finished waiting period.")
            try:
                await client.stop_notify(CHARACTERISTIC_UUID_RW_NOTIFY)
            except Exception as e: log.error(f"Error stopping notifications: {e}")

    except Exception as e: log.error(f"Error during test: {e}")
    finally: log.info("--- Test Script Finished ---")

# --- Script Execution ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    log = logging.getLogger("B2500_Test_FF06_RW")
    try: asyncio.run(run_test_ff06(B2500_MAC))
    except KeyboardInterrupt: log.info("Script interrupted by user.")