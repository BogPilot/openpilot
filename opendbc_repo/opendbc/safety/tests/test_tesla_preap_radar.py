#!/usr/bin/env python3
"""Pre-AP Bosch radar GTW: NAP-style bus-0 to bus-1 rewrite, flags 256 / 128.

Flag off and flag 128 alone must not emit any bus-1 GTW frames. Flag 256 on Pre-AP
emits the NAP map and synthetics on bus 1 only, once the host 0x560 donor config is
complete (NAP 604b9c49). 128/256 are ignored without PREAP. Host TX adds only 0x560
(consumed, never sent) and the bus-1 0x641 F190 read allow-list; both are covered in
test_tesla_preap_radar_donor.py / test_tesla_preap_radar_f190.py. No bus-0 0x2B9. Raw-wire tests, no DBC.
"""
import unittest

from opendbc.car.tesla_ap1.safety_flags import (
  FLAG_TESLA_PREAP,
  FLAG_TESLA_PREAP_PEDAL,
  FLAG_TESLA_PREAP_RADAR_BEHIND_NOSECONE,
  FLAG_TESLA_PREAP_RADAR_EMULATION,
  flags_for_preap,
)
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_preap import (
  AP1,
  LONG,
  PEDAL,
  PREAP,
  SAFETY_TESLA,
  pedal_cmd,
  pkt,
  steer,
)

l = libsafety_py.libsafety

RADAR = FLAG_TESLA_PREAP_RADAR_EMULATION
NOSE = FLAG_TESLA_PREAP_RADAR_BEHIND_NOSECONE

# NAP tesla_preap.h:223-230, 233-247, 250-267, 270-314 @ cc39c7fa
SIMPLE = {
  0x45: 0x219,
  0x108: 0x109,
  0x145: 0x149,
  0x20A: 0x159,
  0x308: 0x209,
  0x30A: 0x2D9,
  0x405: 0x2B9,
}

CRC_LOOKUP = [
  0x00, 0x1D, 0x3A, 0x27, 0x74, 0x69, 0x4E, 0x53, 0xE8, 0xF5, 0xD2, 0xCF, 0x9C, 0x81, 0xA6, 0xBB,
  0xCD, 0xD0, 0xF7, 0xEA, 0xB9, 0xA4, 0x83, 0x9E, 0x25, 0x38, 0x1F, 0x02, 0x51, 0x4C, 0x6B, 0x76,
  0x87, 0x9A, 0xBD, 0xA0, 0xF3, 0xEE, 0xC9, 0xD4, 0x6F, 0x72, 0x55, 0x48, 0x1B, 0x06, 0x21, 0x3C,
  0x4A, 0x57, 0x70, 0x6D, 0x3E, 0x23, 0x04, 0x19, 0xA2, 0xBF, 0x98, 0x85, 0xD6, 0xCB, 0xEC, 0xF1,
  0x13, 0x0E, 0x29, 0x34, 0x67, 0x7A, 0x5D, 0x40, 0xFB, 0xE6, 0xC1, 0xDC, 0x8F, 0x92, 0xB5, 0xA8,
  0xDE, 0xC3, 0xE4, 0xF9, 0xAA, 0xB7, 0x90, 0x8D, 0x36, 0x2B, 0x0C, 0x11, 0x42, 0x5F, 0x78, 0x65,
  0x94, 0x89, 0xAE, 0xB3, 0xE0, 0xFD, 0xDA, 0xC7, 0x7C, 0x61, 0x46, 0x5B, 0x08, 0x15, 0x32, 0x2F,
  0x59, 0x44, 0x63, 0x7E, 0x2D, 0x30, 0x17, 0x0A, 0xB1, 0xAC, 0x8B, 0x96, 0xC5, 0xD8, 0xFF, 0xE2,
  0x26, 0x3B, 0x1C, 0x01, 0x52, 0x4F, 0x68, 0x75, 0xCE, 0xD3, 0xF4, 0xE9, 0xBA, 0xA7, 0x80, 0x9D,
  0xEB, 0xF6, 0xD1, 0xCC, 0x9F, 0x82, 0xA5, 0xB8, 0x03, 0x1E, 0x39, 0x24, 0x77, 0x6A, 0x4D, 0x50,
  0xA1, 0xBC, 0x9B, 0x86, 0xD5, 0xC8, 0xEF, 0xF2, 0x49, 0x54, 0x73, 0x6E, 0x3D, 0x20, 0x07, 0x1A,
  0x6C, 0x71, 0x56, 0x4B, 0x18, 0x05, 0x22, 0x3F, 0x84, 0x99, 0xBE, 0xA3, 0xF0, 0xED, 0xCA, 0xD7,
  0x35, 0x28, 0x0F, 0x12, 0x41, 0x5C, 0x7B, 0x66, 0xDD, 0xC0, 0xE7, 0xFA, 0xA9, 0xB4, 0x93, 0x8E,
  0xF8, 0xE5, 0xC2, 0xDF, 0x8C, 0x91, 0xB6, 0xAB, 0x10, 0x0D, 0x2A, 0x37, 0x64, 0x79, 0x5E, 0x43,
  0xB2, 0xAF, 0x88, 0x95, 0xC6, 0xDB, 0xFC, 0xE1, 0x5A, 0x47, 0x60, 0x7D, 0x2E, 0x33, 0x14, 0x09,
  0x7F, 0x62, 0x45, 0x58, 0x0B, 0x16, 0x31, 0x2C, 0x97, 0x8A, 0xAD, 0xB0, 0xE3, 0xFE, 0xD9, 0xC4,
]


def crc8(lo, hi, msg_len):
  crc = 0xFF
  for x in range(msg_len):
    v = ((lo >> (x * 8)) & 0xFF) if x <= 3 else ((hi >> ((x - 4) * 8)) & 0xFF)
    crc = CRC_LOOKUP[crc ^ v]
  return crc ^ 0xFF


def u32_le(n):
  return bytes((n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF, (n >> 24) & 0xFF))


def expected_2a9(src, position=0, epas_type=0):
  lo = int.from_bytes(src[0:4], "little")
  hi = int.from_bytes(src[4:8], "little")
  lo = (lo & 0xFFFFF33F) | 0x100 | 0x440
  hi = (hi & 0xCFFF0F0F) | 0x10000000 | (position << 4) | (epas_type << 12)
  # No byte-7 checksum: Bosch BO_681 has none, byte 7 = (src & 0xCF) | 0x10 (NAP a2cdda8e,
  # test_tesla_preap_radar_carconfig.py:22-50 @ opendbc 5dbe36d37 / openpilot 7eb09d2a7).
  return u32_le(lo) + u32_le(hi)


def expected_199_sna(src):
  lo = int.from_bytes(src[0:4], "little")
  hi = int.from_bytes(src[4:8], "little")
  if ((lo >> 16) & 0xFF3F) == 0xFF3F:
    lo = (lo & 0x00C0FFFF) | (0x0020 << 16)
    hi = (hi & 0x00FFFFF0) | 0x00000004
    hi = hi | (crc8(lo, hi, 7) << 24)
  return u32_le(lo) + u32_le(hi)


def expected_1a9(src):
  hi_src = int.from_bytes(src[4:8].ljust(8, b"\x00"), "little")
  counter = ((hi_src & 0xF0) >> 4) & 0x0F
  syn_lo = 0x000C0000 | (counter << 28)
  cksm = (0x38 + 0x0C + (counter << 4)) & 0xFF
  return (u32_le(syn_lo) + bytes((cksm,)))[:5]


def expected_169(src):
  lo = int.from_bytes(src[0:4], "little")
  ws_counter = int.from_bytes(src[4:8].ljust(8, b"\x00"), "little") & 0x0F
  raw_speed = (0xFFF0000 & lo) >> 16
  if raw_speed == 0xFFF:
    speed = 0x1FFF
  else:
    mph_x100 = raw_speed * 5 - 2500
    kph_x100 = mph_x100 * 1609 // 1000
    speed = 0 if kph_x100 < 0 else ((kph_x100 // 4) & 0x1FFF)
  ws_lo = (speed | (speed << 13) | (speed << 26)) & 0xFFFFFFFF
  ws_hi = ((speed >> 6) | (speed << 7) | (ws_counter << 20)) & 0x00FFFFFF
  ws_cksm = 0x76
  ws_cksm = (ws_cksm + (ws_lo & 0xFF) + ((ws_lo >> 8) & 0xFF) + ((ws_lo >> 16) & 0xFF) + ((ws_lo >> 24) & 0xFF)) & 0xFF
  ws_cksm = (ws_cksm + (ws_hi & 0xFF) + ((ws_hi >> 8) & 0xFF) + ((ws_hi >> 16) & 0xFF)) & 0xFF
  ws_hi = ws_hi | (ws_cksm << 24)
  return u32_le(ws_lo) + u32_le(ws_hi)


def sent():
  out = []
  n = l.safety_can_send_log_count()
  for i in range(n):
    length = l.safety_can_send_log_len(i)
    data = bytes(l.safety_can_send_log_byte(i, b) for b in range(length))
    out.append((l.safety_can_send_log_addr(i), l.safety_can_send_log_bus(i), length, data))
  return out


def raw(addr, data, bus=0):
  return pkt(addr, bytearray(data), bus)


def donor_config(vin="", use_radar=True, position=0, epas_type=0):
  """The three host 0x560 records (NAP teslacan.py:84-97 layout). Empty VIN = 17 spaces = this car."""
  padded = (vin + " " * 17)[:17]
  flags = (1 if use_radar else 0) | ((position & 0x03) << 1) | ((epas_type & 0x07) << 3)
  return [
    bytes((0, 1, flags, 0, 0, *padded[0:3].encode())),
    bytes((1, *padded[3:10].encode())),
    bytes((2, *padded[10:17].encode())),
  ]


def send_donor_config(vin="", use_radar=True, position=0, epas_type=0):
  results = [bool(l.safety_tx_hook(pkt(0x560, d, 0))) for d in donor_config(vin, use_radar, position, epas_type)]
  assert results == [False, False, False]  # consumed, never sent


class RadarCase(unittest.TestCase):
  PARAM = PREAP | RADAR

  def setUp(self):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, self.PARAM), 0)
    l.init_tests()
    l.set_timer(1_000_000)
    # blank VIN: GTW opens, no substitution (ignored when flag 256 is off). Position as the host sends it: 1 with flag 128.
    send_donor_config(position=1 if (self.PARAM & NOSE) else 0)
    l.safety_can_send_log_reset()

  def rx(self, addr, data, bus=0):
    l.safety_can_send_log_reset()
    l.safety_rx_hook(raw(addr, data, bus))
    return sent()

  def tx(self, m):
    return bool(l.safety_tx_hook(m))


class TestFlagsForPreap(unittest.TestCase):
  def test_defaults_match_today(self):
    self.assertEqual(flags_for_preap(pedal=False), PREAP)
    self.assertEqual(flags_for_preap(pedal=True), PREAP | PEDAL)
    self.assertEqual(flags_for_preap(False, radar=False, behind_nosecone=True), PREAP)
    self.assertEqual(FLAG_TESLA_PREAP, 32)
    self.assertEqual(FLAG_TESLA_PREAP_PEDAL, 64)
    self.assertEqual(NOSE, 128)
    self.assertEqual(RADAR, 256)

  def test_radar_and_nosecone_or(self):
    self.assertEqual(flags_for_preap(False, radar=True), PREAP | RADAR)
    self.assertEqual(flags_for_preap(True, radar=True, behind_nosecone=True), PREAP | PEDAL | RADAR | NOSE)
    self.assertEqual((PREAP | RADAR | NOSE), 32 + 256 + 128)


class TestRadarFlagOff(RadarCase):
  PARAM = PREAP

  def test_no_bus1_tx_for_any_mapped_source(self):
    sources = list(SIMPLE) + [0x398, 0x0E, 0x115, 0x118, 0x32E]
    for addr in sources:
      frames = self.rx(addr, bytes(range(8)))
      self.assertEqual(frames, [], hex(addr))

  def test_tx_allowlist_unchanged(self):
    # 0x560 / 0x641 are on the TX list now but always refused without flag 256.
    allowed = {(0x488, 0), (0x214, 0), (0x45, 0)}
    for addr in (0x488, 0x214, 0x45, 0x551, 0x2B9, 0x399, 0x560, 0x641, 0x219, 0x109, 0x2A9, 0x1A9, 0x169):
      for bus in range(4):
        d = bytearray(8)
        if addr == 0x45:
          d[0] = 1
        l.set_controls_allowed(False)
        ok = self.tx(pkt(addr, d, bus))
        if (addr, bus) not in allowed:
          self.assertFalse(ok, (hex(addr), bus))

  def test_fwd_still_blocks(self):
    for bus in (0, 1, 2):
      for addr in (0x45, 0x108, 0x2B9, 0x32E):
        self.assertEqual(l.safety_fwd_hook(bus, addr), -1)


class TestRadarNoseconeAloneIsNoop(TestRadarFlagOff):
  """Flag 128 without 256 must behave like today (flag off)."""
  PARAM = PREAP | NOSE


class TestRadarGtwOn(RadarCase):
  PARAM = PREAP | RADAR

  def test_simple_readdr_copies_payload_to_bus1(self):
    data = bytes((0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88))
    for src, dest in SIMPLE.items():
      payload = data[:8]
      frames = self.rx(src, payload)
      self.assertEqual(len(frames), 1, hex(src))
      addr, bus, ln, body = frames[0]
      self.assertEqual(addr, dest)
      self.assertEqual(bus, 1)
      self.assertEqual(ln, 8)
      self.assertEqual(body, payload)
      self.assertTrue(all(bus == 1 for _, bus, _, _ in frames))

  def test_mapped_source_on_bus1_or_2_is_ignored(self):
    for bus in (1, 2):
      self.assertEqual(self.rx(0x108, bytes(range(8)), bus=bus), [])

  def test_unmapped_ids_including_park_clash_are_not_copied(self):
    for addr in (0x32E, 0x33E, 0x370, 0x155, 0x551):
      self.assertEqual(self.rx(addr, bytes(range(8))), [], hex(addr))

  def test_carconfig_patch_no_byte7_checksum(self):
    # zeros + the two NAP a2cdda8e vectors (test_tesla_preap_radar_carconfig.py:23-26 @ opendbc 5dbe36d37)
    cases = (
      ("0000000000000000", "4005000000000010"),
      ("0290555300001700", "4295555300001710"),
      ("0281555300000000", "4285555300000010"),
    )
    for src_hex, want_hex in cases:
      src = bytes.fromhex(src_hex)
      frames = self.rx(0x398, src)
      self.assertEqual(len(frames), 1)
      addr, bus, ln, body = frames[0]
      self.assertEqual((addr, bus, ln), (0x2A9, 1, 8))
      self.assertEqual(body.hex(), want_hex)
      self.assertEqual(body, expected_2a9(src, position=0))
      self.assertEqual(body[7] & 0x30, 0x10)  # GTW_autopilot = 1
      self.assertEqual(body[7] & 0xCF, src[7] & 0xCF)

  def test_anglhp_sna_replacement(self):
    # lo bits 16.. have 0xFF3F in the masked field: bytes 2-3 of little-endian lo
    # lo = byte0 | byte1<<8 | byte2<<16 | byte3<<24; (lo>>16)&0xFF3F == 0xFF3F
    # so byte2=0x3F, byte3=0xFF (and maybe low bits of the mask already in byte2)
    src = bytes((0x01, 0x02, 0x3F, 0xFF, 0x10, 0x20, 0x30, 0x40))
    frames = self.rx(0x0E, src)
    self.assertEqual(len(frames), 1)
    addr, bus, ln, body = frames[0]
    self.assertEqual((addr, bus, ln), (0x199, 1, 8))
    self.assertEqual(body, expected_199_sna(src))

  def test_anglhp_non_sna_is_copied(self):
    src = bytes((0x01, 0x02, 0x00, 0x00, 0x10, 0x20, 0x30, 0x40))
    frames = self.rx(0x0E, src)
    self.assertEqual(frames, [(0x199, 1, 8, src)])

  def test_esp115_readdr_and_synthetic_1a9_on_bus1_only(self):
    # counter lives in hi byte0 bits 7:4, i.e. data[4]
    src = bytes((0, 0, 0, 0, 0xA0, 0, 0, 0))  # counter = 0xA
    frames = self.rx(0x115, src)
    self.assertEqual(len(frames), 2)
    self.assertEqual(frames[0], (0x129, 1, 8, src))
    self.assertEqual(frames[1][0], 0x1A9)
    self.assertEqual(frames[1][1], 1)
    self.assertEqual(frames[1][2], 5)
    self.assertEqual(frames[1][3], expected_1a9(src))
    self.assertFalse(any(bus == 0 for _, bus, _, _ in frames))

  def test_torque2_readdr_and_synthetic_169_on_bus1_only(self):
    # raw_speed in lo bits 16..27: put 0x100 in that field (not SNA)
    # lo = raw_speed << 16
    raw_speed = 0x200
    lo = raw_speed << 16
    src = u32_le(lo) + bytes((0x03, 0, 0, 0))  # counter 3, len will be 8 in this test
    frames = self.rx(0x118, src)
    self.assertEqual(len(frames), 2)
    self.assertEqual(frames[0][:3], (0x119, 1, 8))
    self.assertEqual(frames[0][3], src)
    self.assertEqual(frames[1][0], 0x169)
    self.assertEqual(frames[1][1], 1)
    self.assertEqual(frames[1][2], 8)
    self.assertEqual(frames[1][3], expected_169(src))
    self.assertFalse(any(bus == 0 for _, bus, _, _ in frames))

  def test_host_tx_allowlist_unchanged_and_bus0_2b9_blocked(self):
    # 0x560 is on the TX list but is consumed and never sent; 0x641 with this all-zero payload is not on the F190
    # allow-list, and it is never allowed on bus 0/2 or while engaged (test_tesla_preap_radar_f190.py).
    allowed = {(0x488, 0), (0x214, 0), (0x45, 0)}
    for addr in (0x488, 0x214, 0x45, 0x551, 0x2B9, 0x219, 0x2A9, 0x1A9, 0x169, 0x560, 0x641):
      for bus in range(4):
        d = bytearray(8)
        if addr == 0x45:
          d[0] = 1
        l.set_controls_allowed(True)
        ok = self.tx(pkt(addr, d, bus))
        if (addr, bus) not in allowed:
          self.assertFalse(ok, (hex(addr), bus))

  def test_fwd_still_blocks(self):
    for bus in (0, 1, 2):
      for addr in (0x45, 0x108, 0x2B9, 0x32E, 0x219):
        self.assertEqual(l.safety_fwd_hook(bus, addr), -1)

  def test_existing_checks_still_apply(self):
    # cancel-only stalk TX, 0x551 still blocked without pedal flag, steering still gated
    d = bytearray(8)
    d[0] = 2
    self.assertFalse(self.tx(pkt(0x45, d, 0)))
    d[0] = 1
    self.assertTrue(self.tx(pkt(0x45, d, 0)))
    self.assertFalse(self.tx(pedal_cmd(0, False)))
    l.set_controls_allowed(True)
    self.assertTrue(self.tx(steer(0, ctype=0)))

  def test_one_gateway_tx_per_source_frame(self):
    data = bytes(range(8))
    l.safety_can_send_log_reset()
    for _ in range(3):
      l.safety_rx_hook(raw(0x108, data))
    frames = sent()
    self.assertEqual(len(frames), 3)
    self.assertTrue(all(f[0] == 0x109 and f[1] == 1 for f in frames))
    l.safety_can_send_log_reset()
    l.safety_rx_hook(raw(0x118, data))
    l.safety_rx_hook(raw(0x118, data))
    frames = sent()
    self.assertEqual(len(frames), 4)  # two synthetics + two readdrs
    dests = [f[0] for f in frames]
    self.assertEqual(dests, [0x119, 0x169, 0x119, 0x169])
    l.safety_can_send_log_reset()
    l.safety_rx_hook(raw(0x115, data))
    self.assertEqual([f[0] for f in sent()], [0x129, 0x1A9])


class TestRadarNosecone(RadarCase):
  PARAM = PREAP | RADAR | NOSE

  def test_carconfig_position_bit_differs(self):
    src = bytes((0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00))
    frames = self.rx(0x398, src)
    self.assertEqual(len(frames), 1)
    self.assertEqual(frames[0][3], expected_2a9(src, position=1))
    self.assertEqual(frames[0][3].hex(), "4005000010000010")  # position 1 = byte 4 bit 4 (tesla_preap.h:276 flag 128)
    self.assertNotEqual(frames[0][3], expected_2a9(src, position=0))

  def test_simple_readdr_unchanged(self):
    data = bytes(range(8))
    frames = self.rx(0x45, data)
    self.assertEqual(frames, [(0x219, 1, 8, data)])


class TestRadarFlagsIgnoredWithoutPreap(unittest.TestCase):
  def init(self, param):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.init_tests()
    l.set_timer(1000)
    l.safety_can_send_log_reset()

  def test_ap1_with_radar_bits_does_not_gateway(self):
    for param in (AP1, AP1 | LONG, AP1 | RADAR, AP1 | RADAR | NOSE, AP1 | PREAP | RADAR):
      self.init(param)
      l.safety_rx_hook(raw(0x108, bytes(range(8))))
      self.assertEqual(sent(), [], param)

  def test_stock_tesla_with_radar_bits_does_not_gateway(self):
    for param in (0, LONG, RADAR, NOSE, RADAR | NOSE):
      self.init(param)
      l.safety_rx_hook(raw(0x108, bytes(range(8))))
      self.assertEqual(sent(), [], param)


class TestRadarFlagCollision(unittest.TestCase):
  def test_bits_do_not_collide(self):
    used = PREAP | PEDAL | AP1 | 16 | LONG
    self.assertEqual(RADAR & used, 0)
    self.assertEqual(NOSE & used, 0)
    self.assertEqual(RADAR & NOSE, 0)


if __name__ == "__main__":
  unittest.main()
