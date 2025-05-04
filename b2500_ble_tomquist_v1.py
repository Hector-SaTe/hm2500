import asyncio
import logging
import struct
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# --- Configuration ---
B2500_MAC = "63AE965F-4F66-9C3A-3731-B03BD08E6F7C"
#B2500_MAC = "14:80:CC:FA:55:E6" # Your B2500's MAC address

# --- UUIDs from b2500_base.h ---
CHARACTERISTIC_UUID_WRITE = "0000ff01-0000-1000-8000-00805f9b34fb" # Write FF01
CHARACTERISTIC_UUID_NOTIFY = "0000ff02-0000-1000-8000-00805f9b34fb" # Notify FF02

# --- Protocol Constants based on b2500_codec.h/cpp ---
FRAME_HEADER = 0x73
FRAME_CNTL = 0x23
# Try CMD_GET_RUNTIME_INFO (used by polling in cpp)
CMD_GET_RUNTIME_INFO = 0x02

# --- Checksum Calculation (Simple 8-bit XOR) ---
def calculate_xor_checksum(data: bytes) -> int:
    """Calculates the simple XOR checksum used by the ESPHome component."""
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum

# --- Command Frame Builder (73 TotalLen 23 Cmd [Payload] Checksum) ---
def build_73_frame_xor(cmd: int, payload_data: bytes = b'') -> bytes:
    """Builds the command frame with XOR checksum."""
    header_part = bytearray([FRAME_HEADER]) # 0x73
    # Temp frame without len for calculation: Cntl(1) + Cmd(1) + Payload Length
    temp_frame_for_len = bytearray([FRAME_CNTL, cmd])
    temp_frame_for_len.extend(payload_data)
    
    # Total Length = Header(1) + LenByte(1) + Cntl(1) + Cmd(1) + PayloadLen + Checksum(1)
    total_len = 1 + 1 + len(temp_frame_for_len) + 1
    
    # Build final frame prefix (Header + Len + Cntl + Cmd + Payload)
    frame = header_part + total_len.to_bytes(1, 'big') + temp_frame_for_len
    
    # Calculate checksum on ALL bytes before the checksum byte itself
    checksum = calculate_xor_checksum(frame)
    
    # Append checksum
    frame.append(checksum)
    
    log.debug(f"Built 73 Frame (XOR Checksum): {frame.hex(':')}")
    return bytes(frame)

# --- Payload Parser (for CMD_GET_RUNTIME_INFO response - ASSUMES LITTLE ENDIAN) ---
def parse_runtime_info_payload(payload: bytes):
    """Parses the data payload of a runtime info response (CMD=0x02)."""
    expected_len = 52 # Based on RuntimeInfoPacket size estimate (adjust if needed)
    if len(payload) < expected_len:
        log.warning(f"Runtime Info payload too short: {len(payload)} bytes. Expected at least {expected_len}. Payload: {payload.hex(':')}")
        # Attempt partial parsing if needed, or return None
        return None

    try:
        # Using struct.unpack with '<' for Little Endian
        # Offsets derived from RuntimeInfoPacket struct definition
        status_data = {
            "in1_active_byte": payload[0], # offset 0
            "in2_active_byte": payload[1], # offset 1
            "in1_power_w": struct.unpack('<H', payload[2:4])[0], # offset 2-3
            "in2_power_w": struct.unpack('<H', payload[4:6])[0], # offset 4-5
            "soc_percent16": struct.unpack('<H', payload[6:8])[0], # offset 6-8 (SoC from struct)
            "dev_version": payload[8], # offset 8
            "charge_mode_byte": payload[9], # offset 9
            "discharge_setting_byte": payload[10], # offset 10
            "wifi_mqtt_state_byte": payload[11], # offset 11
            "out1_active": payload[12], # offset 12
            "out2_active": payload[13], # offset 13
            "dod": payload[14], # offset 14
            "discharge_threshold16": struct.unpack('<H', payload[15:17])[0], # offset 15-16
            "device_scene": payload[17], # offset 17
            "remaining_capacity_wh?": struct.unpack('<H', payload[18:20])[0], # offset 18-19
            "out1_power_w": struct.unpack('<H', payload[20:22])[0], # offset 20-21
            "out2_power_w": struct.unpack('<H', payload[22:24])[0], # offset 22-23
            "extern1_connected": payload[24], # offset 24
            "extern2_connected": payload[25], # offset 25
            "device_region": payload[26], # offset 26
            "time_hour": payload[27], # offset 27
            "time_minute": payload[28], # offset 28
            "temp_low_c": struct.unpack('<h', payload[29:31])[0] / 10.0, # offset 29-30, signed short / 10?
            "temp_high_c": struct.unpack('<h', payload[31:33])[0] / 10.0, # offset 31-32, signed short / 10?
            # Skipping reserved1 (33-34)
            "device_sub_version": payload[35], # offset 35
            "daily_charge_wh?": struct.unpack('<I', payload[36:40])[0], # offset 36-39, uint32
            "daily_discharge_wh?": struct.unpack('<I', payload[40:44])[0], # offset 40-43, uint32
            "daily_load_charge_wh?": struct.unpack('<I', payload[44:48])[0], # offset 44-47, uint32
            "daily_load_discharge_wh?": struct.unpack('<I', payload[48:52])[0], # offset 48-51, uint32
            "raw_payload": payload.hex(':')
        }
        # Extract bits from bytes where needed (example)
        status_data["in1_active"] = bool(status_data["in1_active_byte"] & 0x01)
        status_data["in1_transparent"] = bool(status_data["in1_active_byte"] & 0x02)
        # ... do similar for other bit fields ...
        log.info(f"Parsed Runtime Data: {status_data}")
        return status_data
    except struct.error as e: log.error(f"Error unpacking runtime payload: {e}. Payload: {payload.hex(':')}"); return None
    except IndexError as e: log.error(f"Index error parsing runtime payload: {e}. Payload: {payload.hex(':')}"); return None


# --- Response Frame Parser (Checks for 73... frame and XOR checksum) ---
def parse_73_response_xor(data: bytes):
    """Parses a received frame, checking for 73... format and XOR checksum."""
    log.info(f"Attempting to parse 73 frame (XOR Checksum): {data.hex(':')}")

    # Min length: 73(1) + Len(1) + 23(1) + Cmd(1) + Checksum(1) = 5
    if not data or len(data) < 5: log.warning(f"Invalid frame: Too short ({len(data)} bytes)"); return None
    if data[0] != FRAME_HEADER: log.warning(f"Invalid frame: Incorrect header {data[0]:#04x}"); return None

    # Check Total Length field consistency
    total_len_from_frame = data[1]
    if total_len_from_frame != len(data):
        log.warning(f"Frame length field mismatch. Header says {total_len_from_frame}, actual is {len(data)}.")
        # Continue parsing but be cautious

    # Check Cntl byte
    if data[2] != FRAME_CNTL: log.warning(f"Invalid frame: Incorrect Cntl byte {data[2]:#04x}"); return None

    # Calculate and Verify XOR Checksum (on all bytes except the last one)
    checksum_data = data[:-1]
    calculated_checksum = calculate_xor_checksum(checksum_data)
    received_checksum = data[-1]

    if received_checksum != calculated_checksum:
        log.error(f"XOR CHECKSUM mismatch! Calculated: {calculated_checksum:02X}, Received: {received_checksum:02X}. Frame: {data.hex(':')}")
        return None

    # Extract Cmd and Payload
    cmd_byte = data[3]
    # Payload is between header (4 bytes) and checksum (1 byte)
    payload = data[4:-1]

    log.info(f"Valid 73 XOR Frame received! Cntl={data[2]:02X}, CMD={cmd_byte:02X}, Payload={payload.hex(':')}")

    # Call specific payload parser based on command
    if cmd_byte == CMD_GET_RUNTIME_INFO:
        return parse_runtime_info_payload(payload)
    # Add elif for other command responses (like CMD_DEVICE_INFO = 0x01, etc.)
    else:
        log.warning(f"No specific parser implemented for response CMD={cmd_byte:02X}")
        return {"cmd": cmd_byte, "payload": payload.hex(':')}


# --- Notification Handler ---
def notification_handler(sender: int, data: bytearray):
    log.info(f"<- Notification Received (Handle: {sender}): {bytes(data).hex(':')}")
    parsed_data = parse_73_response_xor(bytes(data)) # Use the new parser
    if parsed_data:
        print("-" * 20); print("Successfully Parsed Data:");
        # Basic print, enhance as needed
        print(parsed_data)
        print("-" * 20)

# --- Main Async Function ---
async def run_test_esphome_protocol(device_mac: str):
    """Connects, uses W:ff01 N:ff02, sends command 0x02 in 73... frame format with XOR checksum."""
    log.info(f"--- Starting B2500 Read Test (ESPHome Protocol | Write: {CHARACTERISTIC_UUID_WRITE}, Notify: {CHARACTERISTIC_UUID_NOTIFY}) ---")
    log.info(f"Target Device MAC: {device_mac}")
    try:
        log.info("Attempting to connect...")
        async with BleakClient(device_mac, timeout=20.0) as client:
            if not client.is_connected: log.error("Failed to connect."); return
            log.info(f"Connected successfully!")
            try:
                log.info(f"Starting notifications on characteristic {CHARACTERISTIC_UUID_NOTIFY}...")
                await client.start_notify(CHARACTERISTIC_UUID_NOTIFY, notification_handler)
                log.info("Notifications started.")
            except Exception as e: log.error(f"CRITICAL ERROR starting notifications on {CHARACTERISTIC_UUID_NOTIFY}: {e}"); return

            # Build command 0x02 using 73... frame format and XOR checksum
            # Send 0x01 as payload based on encode_simple_command
            command_bytes = build_73_frame_xor(CMD_GET_RUNTIME_INFO, payload_data=b'\x01')
            log.info(f"Prepared 'Get Runtime Info (0x02)' command: {command_bytes.hex(':')}")

            try:
                log.info(f"Sending command to characteristic {CHARACTERISTIC_UUID_WRITE}...")
                await client.write_gatt_char(CHARACTERISTIC_UUID_WRITE, command_bytes, response=False)
                log.info("Command sent successfully.")
            except Exception as e: log.error(f"Error writing command: {e}"); await client.stop_notify(CHARACTERISTIC_UUID_NOTIFY); return

            log.info("Waiting for responses on FF02... (Press Ctrl+C to stop early)")
            await asyncio.sleep(30)
            log.info("Finished waiting period.")
            try: await client.stop_notify(CHARACTERISTIC_UUID_NOTIFY)
            except Exception as e: log.error(f"Error stopping notifications: {e}")
    except Exception as e: log.error(f"Error during test: {e}")
    finally: log.info("--- Test Script Finished ---")

# --- Script Execution ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    log = logging.getLogger("B2500_Test_ESPHomeProto")
    try: asyncio.run(run_test_esphome_protocol(B2500_MAC))
    except KeyboardInterrupt: log.info("Script interrupted by user.")
