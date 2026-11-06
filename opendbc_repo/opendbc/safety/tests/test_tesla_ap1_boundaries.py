#!/usr/bin/env python3
"""Independent raw-wire AP1 boundary tests; no Tesla DBC or car flags imported.

Both release bases use LONG=1, AP1=8, STANDSTILL=16. Old BogPilot
LONG=2 is deliberately not accepted as AP1 longitudinal permission.
Ruling 6: no Pre-AP/pedal actuation exists in this mode.
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety


def packet(addr, data, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(data))


def acceleration(lo=375, hi=375, aeb=0):
  # Independently encode only the two 9-bit acceleration fields and AEB bits.
  raw = (lo << 35) | (hi << 44) | (aeb << 16)
  return raw.to_bytes(8, "little")


class TestTeslaAp1Boundaries(unittest.TestCase):
  TX_MSGS = [[0x488, 0], [0x45, 0], [0x45, 2], [0x2b9, 0], [0x349, 0], [0x399, 0], [0x389, 0], [0x239, 0]]
  def init(self, param=9):
    self.assertEqual(l.set_safety_hooks(10, param), 0)
    l.init_tests()
    l.set_timer(1000)

  def tx(self, addr, data, bus=0):
    return bool(l.safety_tx_hook(packet(addr, data, bus)))

  def rx(self, addr, data, bus=0):
    return bool(l.safety_rx_hook(packet(addr, data, bus)))

  def test_cancel_only_stalk_all_lever_values(self):
    for param in (8, 9, 25):
      self.init(param)
      for allowed in (False, True):
        l.set_controls_allowed(allowed)
        for bus in (0, 2):
          for lever in range(64):
            self.assertEqual(self.tx(0x45, [lever] + [0] * 7, bus), lever == 1)
        self.assertFalse(self.tx(0x45, [1] + [0] * 7, 1))
        self.assertFalse(self.tx(0x45, [1] + [0] * 6))

  def test_no_pedal_or_preap_actuation(self):
    for param in (0, 1, 8, 9, 10, 25):
      self.init(param)
      l.set_controls_allowed(True)
      for addr in (0x551, 0x552, 0x2bf):
        for bus in range(4):
          for data in (bytes(6), bytes(8), bytes([255]) * 6, bytes([255]) * 8):
            self.assertFalse(self.tx(addr, data, bus), (param, addr, bus))

  def test_new_long_bit_not_legacy_bit(self):
    for param, allowed in ((8, False), (10, False), (9, True), (25, True)):
      self.init(param)
      l.set_controls_allowed(True)
      self.assertEqual(self.tx(0x2b9, acceleration(375, 400)), allowed)

  def test_accel_boundaries_and_aeb(self):
    for param in (9, 25):
      for lo, hi, expected in ((287, 375, True), (375, 425, True),
                                (286, 375, False), (375, 426, False)):
        self.init(param)
        l.set_controls_allowed(True)
        self.assertEqual(self.tx(0x2b9, acceleration(lo, hi)), expected)
      for aeb in (1, 2, 3):
        self.init(param)
        l.set_controls_allowed(True)
        self.assertFalse(self.tx(0x2b9, acceleration(aeb=aeb)))
      self.init(param)
      l.set_controls_allowed(False)
      self.assertFalse(self.tx(0x2b9, acceleration(375, 376)))

  def test_real_brake_disengages_and_gas_inhibits_longitudinal(self):
    for addr, released, pressed in ((0x20a, [4] + [0] * 7, [8] + [0] * 7),
                                    (0x108, [0] * 8, [0] * 6 + [1, 0])):
      self.init()
      # Vehicle speed above zero; no dependency on car parser/DBC helpers.
      self.assertTrue(self.rx(0x118, [0, 0, 188, 2, 0, 0]))
      self.assertTrue(self.rx(addr, released))
      l.set_controls_allowed(True)
      self.assertTrue(self.rx(addr, pressed))
      if addr == 0x20a:
        self.assertFalse(l.get_controls_allowed())
      # New-base shared safety inhibits longitudinal on gas; userspace owns disengage.
      self.assertFalse(self.tx(0x2b9, acceleration(375, 400)), hex(addr))

  def test_stalk_pull_does_not_arm_ap1(self):
    self.init()
    self.rx(0x45, [2] + [0] * 7)
    self.assertFalse(l.get_controls_allowed())
    self.assertTrue(self.rx(0x368, [0, 0x20] + [0] * 6))
    self.assertTrue(l.get_controls_allowed())
    self.assertTrue(self.rx(0x368, [0, 0x10] + [0] * 6))
    self.assertFalse(l.get_controls_allowed())

  def test_wrong_bus_cannot_arm_or_set_brake(self):
    self.init()
    self.rx(0x368, [0, 0x20] + [0] * 6, 2)
    self.assertFalse(l.get_controls_allowed())
    l.set_controls_allowed(True)
    self.rx(0x20a, [8] + [0] * 7, 2)
    self.assertTrue(l.get_controls_allowed())

  def test_stock_aeb_passes_through_and_blocks_op(self):
    self.init()
    l.set_controls_allowed(True)
    self.assertTrue(self.tx(0x2b9, acceleration()))
    self.assertEqual(l.safety_fwd_hook(2, 0x2b9), -1)
    self.assertTrue(self.rx(0x2b9, acceleration(aeb=1), 2))
    self.assertFalse(self.tx(0x2b9, acceleration()))
    self.assertEqual(l.safety_fwd_hook(2, 0x2b9), 0)

  def test_forward_timer_wrap_and_reinit(self):
    self.init()
    l.set_timer(0xFFFFFF00)
    self.assertTrue(self.tx(0x239, bytes(8)))
    l.set_timer(0x100)
    self.assertEqual(l.safety_fwd_hook(2, 0x239), -1)
    l.set_timer((0xFFFFFF00 + 150000) & 0xFFFFFFFF)
    self.assertEqual(l.safety_fwd_hook(2, 0x239), 0)
    self.init()
    self.assertEqual(l.safety_fwd_hook(2, 0x239), 0)

  def test_switching_back_to_stock_removes_ap1_permissions(self):
    self.init(25)
    l.set_controls_allowed(True)
    self.assertTrue(self.tx(0x399, bytes(8)))
    self.assertEqual(l.safety_fwd_hook(2, 0x399), -1)
    for param in (0, 1, 16, 17):
      self.init(param)
      l.set_controls_allowed(True)
      self.assertFalse(self.tx(0x399, bytes(8)))
      self.assertFalse(self.tx(0x349, bytes(8)))
      self.assertFalse(self.tx(0x45, [1] + [0] * 7))
      self.assertEqual(l.safety_fwd_hook(2, 0x399), 0)


  def test_switching_to_stock_without_long_clears_long_permission(self):
    self.init(9)
    l.set_controls_allowed(True)
    self.assertTrue(self.tx(0x2b9, acceleration(375, 400)))
    self.init(0)
    l.set_controls_allowed(True)
    # init_tests clears stock autopark; rejection must come from stock long gating.
    self.assertFalse(self.tx(0x2b9, acceleration(375, 400)))

  def test_exhaustive_standard_id_allowlist(self):
    allowed = {(0x488, 0, 4), (0x45, 0, 8), (0x45, 2, 8), (0x2b9, 0, 8),
               (0x349, 0, 8), (0x399, 0, 8), (0x389, 0, 8), (0x239, 0, 8)}
    self.init()
    l.set_controls_allowed(True)
    for addr in range(0x800):
      for bus in range(4):
        for size in (4, 6, 8):
          if (addr, bus, size) not in allowed:
            self.assertFalse(self.tx(addr, bytes(size), bus), (addr, bus, size))

  def test_relay_fault_blocks_all_ap1_tx(self):
    self.init()
    l.set_controls_allowed(True)
    self.rx(0x488, bytes(4))
    self.assertTrue(l.get_relay_malfunction())
    self.assertFalse(self.tx(0x45, [1] + [0] * 7))
    self.assertFalse(self.tx(0x399, bytes(8)))
    self.assertFalse(self.tx(0x2b9, acceleration()))


if __name__ == "__main__":
  unittest.main()
