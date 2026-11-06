#!/usr/bin/env python3
"""BogPilot AP1 cluster frames (0x399, 0x389, 0x239) and forward substitution."""
import unittest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
AP1 = (8 | 1)
CLUSTER = {0x399: 750000, 0x389: 750000, 0x239: 150000}
OTHER_DAS = (0x309, 0x3a9, 0x3e9, 0x329, 0x369)


def pkt(addr, dat, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(dat))


def status(state):
  dat = bytearray(8)
  dat[0] = state & 0x0F
  return dat


class TestTeslaAp1Cluster(unittest.TestCase):
  TX_MSGS = [[0x488, 0], [0x45, 0], [0x45, 2], [0x2b9, 0], [0x349, 0], [0x399, 0], [0x389, 0], [0x239, 0]]
  def init(self, param):
    l.set_timer(1000)
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.set_controls_allowed(False)

  def tx(self, addr, dat=None):
    return l.safety_tx_hook(pkt(addr, dat if dat is not None else bytes(8)))

  def test_cluster_tx_only_with_ap1_flag(self):
    for param in (0, 1):
      self.init(param)
      for addr in CLUSTER:
        self.assertFalse(self.tx(addr, status(2)), (param, hex(addr)))
    self.init(AP1)
    for addr in CLUSTER:
      self.assertTrue(self.tx(addr, status(2)), hex(addr))

  def test_cluster_tx_wrong_bus_or_length_rejected(self):
    self.init(AP1)
    for addr in CLUSTER:
      self.assertFalse(l.safety_tx_hook(pkt(addr, bytes(8), bus=2)))
      self.assertFalse(l.safety_tx_hook(pkt(addr, bytes(7))))

  def test_other_das_frames_still_not_allowed(self):
    self.init(AP1)
    for addr in OTHER_DAS:
      self.assertFalse(self.tx(addr), hex(addr))

  def test_active_autopilot_state_needs_controls_allowed(self):
    self.init(AP1)
    for state in range(16):
      l.set_controls_allowed(False)
      self.assertEqual(self.tx(0x399, status(state)), state not in (3, 4, 5), state)
      l.set_controls_allowed(True)
      self.assertTrue(self.tx(0x399, status(state)), state)
    l.set_controls_allowed(False)
    self.assertTrue(self.tx(0x389, status(5)))
    self.assertTrue(self.tx(0x239, status(5)))

  def test_blocked_cluster_tx_does_not_change_controls_allowed(self):
    self.init(AP1)
    l.set_controls_allowed(True)
    self.assertTrue(self.tx(0x399, status(5)))
    self.assertTrue(l.get_controls_allowed())

  def test_stock_cluster_forwarded_without_op_tx(self):
    for param in (0, AP1):
      self.init(param)
      for addr in list(CLUSTER) + list(OTHER_DAS):
        # Without AP1, cluster addrs are not in TX list; fwd still returns dest bus
        # unless statically blocked. AP1 without recent OP TX forwards.
        self.assertEqual(l.safety_fwd_hook(2, addr), 0, (param, hex(addr)))

  def test_stock_cluster_dropped_only_while_op_recently_sent(self):
    for addr, timeout in CLUSTER.items():
      self.init(AP1)
      t = 5_000_000
      l.set_timer(t)
      self.assertTrue(self.tx(addr, status(2)))
      self.assertEqual(l.safety_fwd_hook(2, addr), -1, hex(addr))
      l.set_timer(t + timeout - 1)
      self.assertEqual(l.safety_fwd_hook(2, addr), -1, hex(addr))
      l.set_timer(t + timeout)
      self.assertEqual(l.safety_fwd_hook(2, addr), 0, hex(addr))
      l.set_timer(t)
      self.tx(addr, status(2))
      for other in CLUSTER:
        if other != addr:
          self.assertEqual(l.safety_fwd_hook(2, other), 0, (hex(addr), hex(other)))
      self.assertEqual(l.safety_fwd_hook(0, addr), 2)

  def test_rejected_tx_does_not_start_substitution(self):
    self.init(AP1)
    l.set_controls_allowed(False)
    self.assertFalse(self.tx(0x399, status(5)))
    self.assertEqual(l.safety_fwd_hook(2, 0x399), 0)

  def test_no_drop_without_ap1_even_after_tx_attempt(self):
    self.init(1)
    for addr in CLUSTER:
      self.assertFalse(self.tx(addr, status(2)))
      self.assertEqual(l.safety_fwd_hook(2, addr), 0)

  def test_init_clears_substitution(self):
    self.init(AP1)
    self.tx(0x239)
    self.assertEqual(l.safety_fwd_hook(2, 0x239), -1)
    self.init(AP1)
    self.assertEqual(l.safety_fwd_hook(2, 0x239), 0)

  def test_existing_steer_forward_rule_unchanged(self):
    self.init(AP1)
    self.assertEqual(l.safety_fwd_hook(2, 0x488), 0)
    self.tx(0x399, status(2))
    self.assertEqual(l.safety_fwd_hook(2, 0x488), 0)
    self.assertEqual(l.safety_fwd_hook(2, 0x2b9), 0)

  def test_hold_clear_rule_unchanged(self):
    self.init(AP1)
    self.assertTrue(self.tx(0x349, bytes(8)))
    self.assertFalse(self.tx(0x349, bytes([2, 0, 0, 0, 0, 0, 0, 0])))
    self.assertEqual(l.safety_fwd_hook(2, 0x349), 0)


if __name__ == "__main__":
  unittest.main()
