import asyncio
import struct
from bleak import BleakClient

# ── HARD-CODED ADDRESS ─────────────────────────────────────────────────────────
B2500_MAC = "14:80:CC:FA:55:E6"  # Your B2500's MAC

# ── UUIDs (main service + two possible notify/write chars) ────────────────────
SERVICE_UUID   = "0000ff00-0000-1000-8000-00805f9b34fb"  # from Java :contentReference[oaicite:6]{index=6}
CHAR_WRITE     = "0000ff02-0000-1000-8000-00805f9b34fb"  # main R/W/Notify :contentReference[oaicite:7]{index=7}
CHAR_NOTIFY2   = "0000ff01-0000-1000-8000-00805f9b34fb"  # alternate notify :contentReference[oaicite:8]{index=8}

# ── Commands & opcodes from Java :contentReference[oaicite:9]{index=9}
CP = 0x73; CMD = 0x23
OP1 = 0x03; OP2 = 0x13

CMD_INFOS1 = bytes([CP, 0x06, CMD, OP1, 0x01, 0x54])
CMD_INFOS2 = bytes([CP, 0x06, CMD, OP2, 0x00, 0x45])

def xor_checksum(data: bytes) -> int:
    cs = 0
    for b in data: cs ^= b
    return cs

def encode_set_time() -> bytes:
    """Build same 0x14 packet as Java’s encodeSetCurrentTime()” :contentReference[oaicite:10]{index=10}."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    year = now.year - 1900
    buf = bytearray(13)
    struct.pack_into("<B B B B B B B B h", buf, 0,
                     CP, 13, CMD, 0x14,
                     year, now.month - 1, now.day,
                     now.hour, now.minute)
    struct.pack_into("<B h", buf, 9, now.second,
                     int(now.utcoffset().total_seconds() / 60))
    buf[-1] = xor_checksum(buf[:-1])
    return bytes(buf)

class B2500:
    def __init__(self, addr): 
        self.client = BleakClient(addr)
        self.inited = False

    async def run(self):
        await self.client.connect()
        print("Connected:", await self.client.is_connected())

        # subscribe both possible notify characteristics
        for uuid in (CHAR_WRITE, CHAR_NOTIFY2):
            try:
                await self.client.start_notify(uuid, self._cb)
                print(f"Subscribed to {uuid}")
            except Exception as e:
                print(f"❌ cannot sub {uuid}: {e}")

        # wait 3.5 s as in Java builder.wait(3500) :contentReference[oaicite:11]{index=11}
        await asyncio.sleep(3.5)

        # send first infos1
        await self.client.write_gatt_char(CHAR_WRITE, CMD_INFOS1, response=False)
        print("Sent CMD_INFOS1")

        # keep alive to receive both infos
        await asyncio.sleep(15)

        # cleanup
        for uuid in (CHAR_WRITE, CHAR_NOTIFY2):
            try: await self.client.stop_notify(uuid)
            except: pass
        await self.client.disconnect()

    def _cb(self, handle, data: bytearray):
        if data[0] != CP: return
        code = data[3]
        if code == OP1:
            print("→ INFO1:", data.hex())
            self._decode_infos(data)
            # ask for second infos
            asyncio.create_task(self.client.write_gatt_char(CHAR_WRITE, CMD_INFOS2, response=False))
            print("Sent CMD_INFOS2")
        elif code == OP2:
            print("→ INFO2:", data.hex())
            self._decode_intervals(data)
            if not self.inited:
                pkt = encode_set_time()
                asyncio.create_task(self.client.write_gatt_char(CHAR_WRITE, pkt, response=False))
                print("Sent SET_TIME")
                self.inited = True

    def _decode_infos(self, d: bytes):
        # match Java decodeInfos() ByteBuffer positions :contentReference[oaicite:12]{index=12}
        p1a, p2a = struct.unpack_from("<??", d, 4)
        p1w, p2w = struct.unpack_from("<hh", d, 6)
        fw = d[12]
        bat_kwh = struct.unpack_from("<h", d, 14)[0]
        bat_pct = int((bat_kwh / 2240.0) * 100)
        print(f"Panel1 {p1w}W (active={p1a}), Panel2 {p2w}W (active={p2a})")
        print(f"Battery {bat_kwh}kWh → {bat_pct}%  FW V{fw}")

    def _decode_intervals(self, d: bytes):
        off = 5
        for i in range(5):
            en = d[off] != 0
            sh, sm, eh, em = struct.unpack_from("<BBBB", d, off+1)
            w = struct.unpack_from("<h", d, off+5)[0]
            print(f"Interval{i+1}: {en}, {sh:02d}:{sm:02d}–{eh:02d}:{em:02d}, {w}W")
            off += 7

async def main():
    b = B2500(B2500_MAC)
    await b.run()

if __name__ == "__main__":
    asyncio.run(main())
