import asyncio
import logging
import struct
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# --- Manual CRC-16-MODBUS Implementation ---
# (Polynomial=0xA001, Init=0xFFFF, Reflect In=True, Reflect Out=True, XorOut=0x0000)
def crc16_modbus_manual(data: bytes) -> int:
    """Calculates CRC-16-MODBUS manually."""
    crc = 0xFFFF
    poly = 0xA001 # Reversed polynomial 0x8005
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001: # Check if LSB is 1
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return crc & 0xFFFF # Return the final 16-bit CRC

# --- Configuration ---
B2500_MAC = "14:80:CC:FA:55:E6" # Your B2500's MAC address

# --- UUIDs from Gadgetbridge Source ---
MARSTEK_SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
# Characteristic device sends notifications ON (RX)
CHARACTERISTIC_UUID_NOTIFY = "0000ff01-0000-1000-8000-00805f9b34fb"
# Characteristic we send commands TO (TX)
CHARACTERISTIC_UUID_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb"

# --- Protocol Constants from Gadgetbridge Source ---
FRAME_START = 0xAA
FRAME_SECOND = 0x55
FRAME_ADDRESS = 0x01
CMD_GET_STATUS = 0x08 # Command to request status data

# --- Command Frame Builder (AA 55 Addr Cmd Len [Data] CRC_LE) ---
def build_b2500_frame(cmd: int, payload: bytes = b'') -> bytes:
    """Builds the command frame according to Gadgetbridge analysis."""
    frame = bytearray()
    frame.append(FRAME_START)
    frame.append(FRAME_SECOND)
    frame.append(FRAME_ADDRESS)
    frame.append(cmd)
    frame.append(len(payload)) # Length of payload ONLY
    frame.extend(payload)

    # Calculate CRC on Addr, Cmd, Len, Payload
    crc_data = frame[2:]
    crc_val = crc16_modbus_manual(crc_data) # Use the manual function

    # Append CRC as Little Endian
    frame.append(crc_val & 0xFF)       # Low byte
    frame.append((crc_val >> 8) & 0xFF) # High byte

    log.debug(f"Built Frame: {frame.hex(':')}")
    return bytes(frame)

# --- Payload Parser (for CMD_GET_STATUS response) ---
def parse_status_payload(payload: bytes):
    """Parses the data payload of a status response (CMD=0x08)."""
    # (Keep the parsing logic using struct.unpack as before)
    if len(payload) < 14:
        log.warning(f"Status payload too short: {len(payload)} bytes. Payload: {payload.hex(':')}")
        return None
    try:
        status_data = {
            "soc_percent": payload[0],
            "charge_status": payload[1],
            "power_in_w": struct.unpack('>H', payload[2:4])[0],
            "power_out_w": struct.unpack('>H', payload[4:6])[0],
            "battery_voltage_mv": struct.unpack('>H', payload[6:8])[0],
            "output_voltage_mv": struct.unpack('>H', payload[8:10])[0],
            "temp1_c": struct.unpack('>b', payload[10:11])[0],
            "temp2_c": struct.unpack('>b', payload[11:12])[0],
            "remaining_charge_time_min": payload[12],
            "remaining_discharge_time_min": payload[13],
            "raw_payload": payload.hex(':')
        }
        log.info(f"Parsed Status Data: {status_data}")
        return status_data
    except struct.error as e: log.error(f"Error unpacking status payload: {e}. Payload: {payload.hex(':')}"); return None
    except IndexError as e: log.error(f"Index error parsing status payload: {e}. Payload: {payload.hex(':')}"); return None

# --- Response Frame Parser ---
def parse_b2500_response(data: bytes):
    """Parses a received frame (AA 55...), checks CRC (MODBUS), calls payload parser."""
    log.debug(f"Parsing frame: {data.hex(':')}")

    # 1. Check minimum length and header AA 55
    if not data or len(data) < 6 or data[0] != FRAME_START or data[1] != FRAME_SECOND:
        log.warning(f"Invalid frame header or too short. Frame: {data.hex(':')}")
        return None

    # 2. Extract fields based on length byte
    address = data[2]; response_cmd = data[3]; payload_len = data[4]
    expected_total_len = 5 + payload_len + 2
    if len(data) != expected_total_len: log.warning(f"Invalid frame: Length mismatch. Expected {expected_total_len}, Got {len(data)}. Frame: {data.hex(':')}")

    # 3. Extract payload and CRC
    payload = data[5 : 5 + payload_len]; received_crc_bytes = data[5 + payload_len :]
    if len(received_crc_bytes) != 2: log.warning(f"Invalid frame: Incorrect CRC length ({len(received_crc_bytes)} bytes). Frame: {data.hex(':')}"); return None
    received_crc = int.from_bytes(received_crc_bytes, 'little') # CRC is Little Endian

    # 4. Calculate and verify CRC (using MODBUS) on Addr, Cmd, Len, Payload
    crc_check_data = data[2 : 5 + payload_len]
    calculated_crc = crc16_modbus_manual(crc_check_data) # Use manual function

    if received_crc != calculated_crc:
        log.error(f"MODBUS CRC mismatch! Calculated: {calculated_crc:04X}, Received: {received_crc:04X}. Frame: {data.hex(':')}")
        return None

    # 5. CRC is valid, parse the payload based on the command
    log.info(f"Valid MODBUS Frame received! Addr={address:02X}, CMD={response_cmd:02X}, Payload={payload.hex(':')}")

    if response_cmd == CMD_GET_STATUS:
        return parse_status_payload(payload)
    else:
        log.warning(f"No specific parser implemented for response CMD={response_cmd:02X}")
        return {"cmd": response_cmd, "raw_payload": payload.hex(':')}

# --- Notification Handler ---
def notification_handler(sender: int, data: bytearray):
    """Handles incoming BLE notifications & calls parser."""
    log.info(f"<- Notification Received (Handle: {sender}): {bytes(data).hex(':')}")
    parsed_data = parse_b2500_response(bytes(data))
    if parsed_data:
        print("-" * 20); print("Successfully Parsed Data:");
        for key, value in parsed_data.items(): print(f"  {key}: {value}")
        print("-" * 20)

# --- Main Async Function ---
async def run_gadgetbridge_test_manual_crc(device_mac: str):
    """Connects, enables notify on FF01, sends CMD_GET_STATUS (0x08) to FF02 using manual CRC."""
    log.info(f"--- Starting B2500 Gadgetbridge Protocol Test (Manual CRC) ---")
    log.info(f"Target MAC: {device_mac}")
    log.info(f"Write Characteristic (TX): {CHARACTERISTIC_UUID_WRITE}")
    log.info(f"Notify Characteristic (RX): {CHARACTERISTIC_UUID_NOTIFY}")

    try:
        log.info("Attempting to connect...")
        async with BleakClient(device_mac, timeout=20.0) as client:
            if not client.is_connected: log.error("Failed to connect."); return
            log.info(f"Connected successfully!")

            try:
                log.info(f"Starting notifications on RX characteristic {CHARACTERISTIC_UUID_NOTIFY}...")
                await client.start_notify(CHARACTERISTIC_UUID_NOTIFY, notification_handler)
                log.info("Notifications started.")
            except Exception as e:
                log.error(f"CRITICAL ERROR starting notifications: {e}")
                return

            # Build the Get Status command (0x08) using manual MODBUS CRC
            status_command_bytes = build_b2500_frame(CMD_GET_STATUS)
            log.info(f"Prepared 'Get Status (0x08)' command: {status_command_bytes.hex(':')}")
            # Expected frame for CMD=0x08, Payload=empty: AA 55 01 08 00 25 E0

            try:
                log.info(f"Sending command to TX characteristic {CHARACTERISTIC_UUID_WRITE}...")
                await client.write_gatt_char(CHARACTERISTIC_UUID_WRITE, status_command_bytes, response=False)
                log.info("Command sent successfully.")
            except Exception as e:
                log.error(f"Error writing command: {e}"); await client.stop_notify(CHARACTERISTIC_UUID_NOTIFY); return

            log.info("Waiting for responses... (Press Ctrl+C to stop early)")
            await asyncio.sleep(30)
            log.info("Finished waiting period.")
            try: await client.stop_notify(CHARACTERISTIC_UUID_NOTIFY)
            except Exception as e: log.error(f"Error stopping notifications: {e}")

    except BleakError as e: log.error(f"Bluetooth Error: {e}")
    except asyncio.TimeoutError: log.error("Connection timed out.")
    except Exception as e: log.error(f"An unexpected error occurred: {e}")
    finally: log.info("--- Test Script Finished ---")

# --- Script Execution ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    log = logging.getLogger("B2500_GadgetbridgeTestManualCRC")
    try: asyncio.run(run_gadgetbridge_test_manual_crc(B2500_MAC))
    except KeyboardInterrupt: log.info("Script interrupted by user.")