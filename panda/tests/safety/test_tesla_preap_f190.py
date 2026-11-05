#!/usr/bin/env python3
"""SAFETY_TESLA_PREAP narrow F190 UDS allow (bus 1, addr 0x641).

Only the exact NAP read-conversation payloads may TX while radar emulation is
on and controls are not allowed. WriteDataByIdentifier, routines, wrong bus,
wrong address, and engaged state must stay blocked.

No real VINs. Not a driving validation.
"""
import unittest

from panda import Panda
from panda.tests.libpanda import libpanda_py

l = libpanda_py.libpanda

PREAP = Panda.SAFETY_TESLA_PREAP
RADAR = Panda.FLAG_TESLA_PREAP_RADAR_EMULATION  # 2
PEDAL = Panda.FLAG_TESLA_PREAP_ENABLE_PEDAL     # 1

F190_OK = [
  bytes([0x02, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
  bytes([0x02, 0x10, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]),
  bytes([0x02, 0x10, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00]),
  bytes([0x03, 0x22, 0xF1, 0x90, 0x00, 0x00, 0x00, 0x00]),
  bytes([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
  bytes([0x02, 0x3E, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00]),
]

# Other diagnostic payloads that must remain blocked.
F190_BLOCKED = [
  bytes([0x04, 0x2E, 0xF1, 0x90, 0x00, 0x00, 0x00, 0x00]),  # WriteDataByIdentifier F190
  bytes([0x04, 0x31, 0x01, 0x0A, 0x03, 0x00, 0x00, 0x00]),  # Routine 0x0A03
  bytes([0x02, 0x3E, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]),  # tester present variant
  bytes([0x02, 0x10, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00]),  # programming session
  bytes([0x03, 0x22, 0xF1, 0x91, 0x00, 0x00, 0x00, 0x00]),  # wrong DID
  bytes([0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # wrong ISO-TP length
  bytes([0x03, 0x27, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]),  # security access
]


def pkt(addr, dat, bus=1):
  return libpanda_py.make_CANPacket(addr, bus, bytes(dat))


class TestTeslaPreapF190(unittest.TestCase):
  def init(self, param=RADAR):
    l.set_timer(1000)
    self.assertEqual(l.set_safety_hooks(PREAP, param), 0)
    l.set_controls_allowed(False)

  def tx(self, addr, dat, bus=1):
    return l.safety_tx_hook(pkt(addr, dat, bus=bus))

  def test_exact_f190_frames_allowed_disengaged_with_radar(self):
    self.init(RADAR)
    for dat in F190_OK:
      self.assertTrue(self.tx(0x641, dat), dat.hex())

  def test_other_diag_frames_blocked(self):
    self.init(RADAR)
    for dat in F190_BLOCKED:
      self.assertFalse(self.tx(0x641, dat), dat.hex())

  def test_f190_blocked_when_engaged(self):
    self.init(RADAR)
    l.set_controls_allowed(True)
    for dat in F190_OK:
      self.assertFalse(self.tx(0x641, dat), dat.hex())

  def test_f190_blocked_without_radar_flag(self):
    self.init(0)
    for dat in F190_OK:
      self.assertFalse(self.tx(0x641, dat), dat.hex())
    self.init(PEDAL)
    for dat in F190_OK:
      self.assertFalse(self.tx(0x641, dat), dat.hex())

  def test_f190_wrong_bus_blocked(self):
    self.init(RADAR)
    for dat in F190_OK:
      self.assertFalse(self.tx(0x641, dat, bus=0), dat.hex())
      self.assertFalse(self.tx(0x641, dat, bus=2), dat.hex())

  def test_f190_wrong_addr_blocked(self):
    self.init(RADAR)
    # Nearby UDS / radar addrs must not inherit the allow.
    for addr in (0x640, 0x642, 0x651, 0x560):
      self.assertFalse(self.tx(addr, F190_OK[3]), hex(addr))

  def test_dummy_vin_still_allowed_with_radar(self):
    self.init(RADAR)
    self.assertTrue(self.tx(0x560, b"TESTDUMM"))


if __name__ == "__main__":
  unittest.main()
