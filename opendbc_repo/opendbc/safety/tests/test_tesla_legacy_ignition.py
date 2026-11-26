#!/usr/bin/env python3
"""Legacy Tesla Model S/X (AP1, AP2, Pre-AP) CAN ignition: GTW_status 0x348, bus 0, 8 bytes."""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety


def gtw_status(counter, drive_rail_req, bus=0, length=8, byte0_other=0x00, byte6_high=0x50, addr=0x348):
  dat = bytearray(length)
  if length > 0:
    dat[0] = byte0_other | (1 if drive_rail_req else 0)
  if length > 6:
    dat[6] = byte6_high | (counter & 0xF)
  if length > 7:
    dat[7] = ((addr & 0xFF) + (addr >> 8) + sum(dat[:7])) & 0xFF
  return libsafety_py.make_CANPacket(addr, bus, bytes(dat))


def feed(counters, drive_rail_req=True, **kw):
  for c in counters:
    l.ignition_can_hook(gtw_status(c, drive_rail_req, **kw))


class TestTeslaLegacyIgnition(unittest.TestCase):
  def setUp(self):
    l.init_tests()
    # The hook keeps its previous counter in a static; park it on a known value, then clear the result.
    feed([0])
    l.init_tests()

  def test_ignition_on(self):
    feed([1])
    self.assertTrue(l.get_ignition_can())

  def test_ignition_on_every_counter_start(self):
    for start in range(16):
      l.init_tests()
      feed([start])
      l.init_tests()
      feed([(start + 1) % 16])
      self.assertTrue(l.get_ignition_can(), start)

  def test_first_frame_alone_does_not_set(self):
    # A lone frame cannot satisfy continuity against the parked counter (0) unless it is 1.
    feed([5])
    self.assertFalse(l.get_ignition_can())

  def test_ignition_stays_on_through_counter_wrap(self):
    feed(list(range(1, 16)) + list(range(0, 16)))
    self.assertTrue(l.get_ignition_can())

  def test_ignition_off(self):
    feed([1, 2])
    self.assertTrue(l.get_ignition_can())
    feed([3], drive_rail_req=False)
    self.assertFalse(l.get_ignition_can())
    feed([4], drive_rail_req=True)
    self.assertTrue(l.get_ignition_can())

  def test_only_byte0_bit0_matters(self):
    feed([1], drive_rail_req=False, byte0_other=0xFE)
    self.assertFalse(l.get_ignition_can())
    feed([2], drive_rail_req=True, byte0_other=0xFE)
    self.assertTrue(l.get_ignition_can())
    feed([3], drive_rail_req=False, byte0_other=0xFE)
    self.assertFalse(l.get_ignition_can())

  def test_counter_high_nibble_ignored(self):
    feed([1], byte6_high=0xF0)
    self.assertTrue(l.get_ignition_can())
    feed([2], byte6_high=0x00)
    self.assertTrue(l.get_ignition_can())

  def test_counter_skip_is_rejected(self):
    feed([1])
    l.init_tests()
    feed([3])  # skipped 2
    self.assertFalse(l.get_ignition_can())
    feed([4])  # continuity is re-established from the last seen counter
    self.assertTrue(l.get_ignition_can())

  def test_counter_repeat_is_rejected(self):
    feed([1])
    l.init_tests()
    feed([1, 1, 1])  # stuck or replayed message
    self.assertFalse(l.get_ignition_can())

  def test_counter_backwards_is_rejected(self):
    feed([1, 2])
    l.init_tests()
    feed([1])
    self.assertFalse(l.get_ignition_can())

  def test_bad_counter_does_not_clear_ignition(self):
    feed([1, 2])
    self.assertTrue(l.get_ignition_can())
    feed([9], drive_rail_req=False)  # bad counter: ignored, not treated as off
    self.assertTrue(l.get_ignition_can())

  def test_wrong_bus_ignored(self):
    for bus in (1, 2, 3):
      feed([0])
      l.init_tests()
      feed([0], bus=bus)
      feed([1], bus=bus)
      feed([2], bus=bus)
      self.assertFalse(l.get_ignition_can(), bus)
      # and it does not disturb the bus 0 counter chain
      feed([1])
      self.assertTrue(l.get_ignition_can(), bus)

  def test_wrong_length_ignored(self):
    for length in (3, 7):
      l.init_tests()
      for c in (0, 1, 2):
        l.ignition_can_hook(gtw_status(c, True, length=length))
      self.assertFalse(l.get_ignition_can(), length)

  def test_other_address_ignored(self):
    for addr in (0x347, 0x349, 0x248):
      l.init_tests()
      for c in (0, 1, 2):
        l.ignition_can_hook(gtw_status(c, True, addr=addr))
      self.assertFalse(l.get_ignition_can(), addr)

  def test_overlapping_non_counter_traffic_cannot_set_ignition(self):
    # 0x348 on PSA carries engine data, not a counter; a constant or random byte 6 must not turn ignition on.
    for b6 in (0x00, 0x05, 0xFF):
      l.init_tests()
      for _ in range(40):
        l.ignition_can_hook(gtw_status(b6 & 0xF, True, byte6_high=b6 & 0xF0))
      self.assertFalse(l.get_ignition_can(), b6)

  def test_does_not_disturb_model_3_ignition(self):
    # Model 3/Y 0x221 uses its own counter in byte 6 high nibble and its own static state
    dat = bytes([0x60, 0, 0, 0, 0, 0, 0x10, 0])
    l.ignition_can_hook(libsafety_py.make_CANPacket(0x221, 0, dat))
    dat = bytes([0x60, 0, 0, 0, 0, 0, 0x20, 0])
    l.ignition_can_hook(libsafety_py.make_CANPacket(0x221, 0, dat))
    self.assertTrue(l.get_ignition_can())
    feed([1], drive_rail_req=False)
    self.assertFalse(l.get_ignition_can())


if __name__ == "__main__":
  unittest.main()
