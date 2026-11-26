#!/usr/bin/env python3
"""Pre-AP radar UDS: the only 0x641 frames allowed are NAP's read-only F190 sequence, bus 1, flag 256, disengaged.

Ported from NAP opendbc/safety/tests/test_tesla_preap_radar_f190.py (6 tests) @ opendbc 5dbe36d37
(openpilot naponsp-alpha-prebuilt 7eb09d2a7). The host-side reader is a dormant library: nothing in this build sends these.
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_preap import PREAP, SAFETY_TESLA, pkt
from opendbc.safety.tests.test_tesla_preap_radar import NOSE, RADAR

l = libsafety_py.libsafety

F190 = bytes([0x03, 0x22, 0xF1, 0x90, 0x00, 0x00, 0x00, 0x00])
TESTER = bytes([0x02, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
ALLOWED = [
  TESTER,
  bytes([0x02, 0x10, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]),
  bytes([0x02, 0x10, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00]),
  F190,
  bytes([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
  bytes([0x02, 0x3E, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00]),
]
OTHER_DID = bytes([0x03, 0x22, 0xF0, 0x14, 0x00, 0x00, 0x00, 0x00])
SECURITY = bytes([0x02, 0x27, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00])
ROUTINE = bytes([0x04, 0x31, 0x01, 0x0A, 0x03, 0x00, 0x00, 0x00])
WRITE_VIN = bytes([0x10, 0x14, 0x2E, 0xF1, 0x90, 0x41, 0x41, 0x41])


class TestPreapRadarF190(unittest.TestCase):
  PARAM = PREAP | RADAR

  def setUp(self):
    self.init(self.PARAM)

  def init(self, param):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.init_tests()
    l.set_timer(1_000_000)
    l.set_controls_allowed(False)

  def tx(self, addr, dat, bus):
    return bool(l.safety_tx_hook(pkt(addr, dat, bus)))

  def test_allows_f190_read_while_disengaged(self):
    for d in ALLOWED:
      self.assertTrue(self.tx(0x641, d, 1), d.hex())

  def test_rejects_f190_when_controls_allowed(self):
    l.set_controls_allowed(True)
    for d in ALLOWED:
      self.assertFalse(self.tx(0x641, d, 1), d.hex())

  def test_rejects_f190_without_radar(self):
    for param in (PREAP, PREAP | NOSE):
      self.init(param)
      self.assertFalse(self.tx(0x641, F190, 1))
      self.assertFalse(self.tx(0x641, TESTER, 1))

  def test_rejects_writes_routines_and_other_dids(self):
    for d in (OTHER_DID, SECURITY, ROUTINE, WRITE_VIN, bytes(8), F190[:7] + b"\x01"):
      self.assertFalse(self.tx(0x641, d, 1), d.hex())
    self.assertFalse(self.tx(0x641, F190[:4], 1))  # DLC must be 8

  def test_rejects_uds_on_chassis_bus(self):
    for bus in (0, 2, 3):
      self.assertFalse(self.tx(0x641, F190, bus), bus)
    for addr in (0x7DF, 0x7E0, 0x651):
      for bus in range(4):
        self.assertFalse(self.tx(addr, F190, bus), (hex(addr), bus))

  def test_560_still_never_leaves_host(self):
    for bus in range(4):
      for d in (bytes([0, 1, 1, 0, 0, 0x20, 0x20, 0x20]), bytes([1]) + b" " * 7, bytes([2]) + b" " * 7):
        self.assertFalse(self.tx(0x560, d, bus), bus)


if __name__ == "__main__":
  unittest.main()
