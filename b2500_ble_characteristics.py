# Test BLE connectivity and read battery status from B2500
# This script uses the Bleak library to connect to the B2500 and read its battery status.
import asyncio
import logging
from bleak import BleakClient
from bleak.exc import BleakError

# --- Configuration ---
B2500_MAC = "14:80:CC:FA:55:E6"  # Your B2500's MAC address

# --- Main Async Function ---
async def discover_characteristics(device_mac: str):
    """Connects to the device and lists all services and characteristics."""
    log.info(f"--- Discovering B2500 Services/Characteristics ---")
    log.info(f"Target Device MAC: {device_mac}")

    try:
        # 1. Connect to the device
        log.info("Attempting to connect...")
        async with BleakClient(device_mac, timeout=20.0) as client:
            if not client.is_connected:
                log.error("Failed to connect.")
                return
            log.info(f"Connected successfully to {device_mac}!")
            log.info(f"MTU size: {client.mtu_size}") # Good info to know

            # 2. Get and print services and characteristics
            log.info("Discovering services and characteristics...")
            for service in client.services:
                log.info(f"\n[Service] UUID: {service.uuid}")
                log.info(f"          Description: {service.description}")
                log.info(f"          Handle: {service.handle}")

                try:
                    for char in service.characteristics:
                        log.info(f"  [Characteristic] UUID: {char.uuid}")
                        log.info(f"                   Description: {char.description}")
                        log.info(f"                   Handle: {char.handle}")
                        # CRITICAL: Print the properties!
                        log.info(f"                   Properties: {', '.join(char.properties)}")
                        # Properties tell us if it supports: 'read', 'write', 'write-without-response',
                        # 'notify', 'indicate', 'broadcast', 'authenticated-signed-writes', 'extended-properties'

                        # Optionally, list descriptors if needed for debugging deeper issues
                        # log.info("    [Descriptors]")
                        # for descriptor in char.descriptors:
                        #     try:
                        #         desc_value = await client.read_gatt_descriptor(descriptor.handle)
                        #         log.info(f"      {descriptor.uuid}: {bytes(desc_value).hex(':')} ({bytes(desc_value)})")
                        #     except Exception as e_desc:
                        #         log.warning(f"      Could not read descriptor {descriptor.uuid}: {e_desc}")

                except BleakError as e_char:
                     log.warning(f"    Could not access characteristics for service {service.uuid}: {e_char}")


            log.info("\n--- Service Discovery Complete ---")

    except BleakError as e:
        log.error(f"Bluetooth Error: {e}")
    except asyncio.TimeoutError:
        log.error("Connection timed out.")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")
    finally:
        log.info("--- Discovery Script Finished ---")

# --- Script Execution ---
if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    log = logging.getLogger("B2500_Discover")

    # Run the asynchronous discovery function
    try:
        asyncio.run(discover_characteristics(B2500_MAC))
    except KeyboardInterrupt:
        log.info("Script interrupted by user.")