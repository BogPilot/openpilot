#!/usr/bin/env python3
"""BogPilot AP1 standstill experiment (TESLA_FLAG_AP1_STANDSTILL, 16)."""
import unittest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
AP1 = (8 | 1)
AP1_SS = AP1 | 16


def das_control(set_speed_kph=0.0, acc_state=4, aeb=0, accel_min=-1.4, accel_max=0.0, jerk_min=-0.46, jerk_max=0.476, counter=0):
  v = 0
  v |= int(round(set_speed_kph / 0.1)) & 0xFFF
  v |= (acc_state & 0xF) << 12
  v |= (aeb & 0x3) << 16
  v |= (int(round((jerk_min + 15.232) / 0.03)) & 0x1FF) << 18
  v |= (int(round(jerk_max / 0.059)) & 0xFF) << 27
  v |= (int(round((accel_min + 15) / 0.04)) & 0x1FF) << 35
  v |= (int(round((accel_max + 15) / 0.04)) & 0x1FF) << 44
  v |= (counter & 0x7) << 53
  dat = bytearray(v.to_bytes(8, "little"))
  dat[7] = (0xb9 + 0x02 + sum(dat[:7])) & 0xFF
  return bytes(dat)


class TestTeslaAp1Standstill(unittest.TestCase):
  TX_MSGS = [[0x488, 0], [0x45, 0], [0x45, 2], [0x2b9, 0], [0x349, 0], [0x399, 0], [0x389, 0], [0x239, 0]]
  def init(self, param, allowed=False):
    l.set_timer(1000)
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.set_controls_allowed(allowed)

  def tx(self, dat):
    return l.safety_tx_hook(libsafety_py.make_CANPacket(0x2b9, 0, dat))

  def test_standby_accepted_only_with_flag(self):
    self.init(AP1)
    self.assertFalse(self.tx(das_control()))
    self.init(AP1_SS)
    self.assertTrue(self.tx(das_control()))
    self.assertTrue(self.tx(das_control(acc_state=0)))

  def test_flag_needs_ap1_and_long(self):
    for p in (16,
              (16 | 1),
              (16 | 8)):
      self.init(p)
      self.assertFalse(self.tx(das_control()), p)

  def test_only_standby_values(self):
    self.init(AP1_SS)
    bad = [
      das_control(set_speed_kph=1.0),
      das_control(set_speed_kph=409.5),
      das_control(acc_state=3), das_control(acc_state=5), das_control(acc_state=15),
      das_control(aeb=1), das_control(aeb=2),
      das_control(accel_max=0.04), das_control(accel_max=1.8),
      das_control(accel_min=0.04, accel_max=0.04),
      das_control(accel_min=-4.0),
      das_control(accel_min=0.0, accel_max=-0.4),
    ]
    for d in bad:
      self.assertFalse(self.tx(d), d.hex())
    for d in (das_control(accel_min=-3.5), das_control(accel_min=0.0, accel_max=0.0),
              das_control(accel_min=-1.4, accel_max=-0.2)):
      self.assertTrue(self.tx(d), d.hex())

  def test_standby_rejected_during_stock_aeb(self):
    self.init(AP1_SS)
    aeb = bytearray(8); aeb[2] = 1
    l.safety_rx_hook(libsafety_py.make_CANPacket(0x2b9, 2, bytes(aeb)))
    self.assertFalse(self.tx(das_control()))

  def test_engaged_path_unchanged(self):
    for p in (AP1, AP1_SS):
      self.init(p, allowed=True)
      self.assertTrue(self.tx(das_control(set_speed_kph=50, accel_min=0.0, accel_max=1.5)), p)
      self.assertTrue(self.tx(das_control(set_speed_kph=50, accel_min=-3.5, accel_max=0.0)), p)
      self.assertFalse(self.tx(das_control(set_speed_kph=50, accel_min=0.0, accel_max=2.2)), p)
      self.assertFalse(self.tx(das_control(set_speed_kph=50, aeb=1, accel_min=0.0, accel_max=1.0)), p)
      l.set_controls_allowed(False)
      self.assertFalse(self.tx(das_control(set_speed_kph=50, accel_min=0.0, accel_max=1.5)), p)
      self.assertTrue(self.tx(das_control(set_speed_kph=50, accel_min=0.0, accel_max=0.0)), p)

  def test_standby_tx_arms_recent_drop_like_any_op_2b9(self):
    self.init(AP1_SS)
    self.assertEqual(l.safety_fwd_hook(2, 0x2b9), 0)
    self.assertTrue(self.tx(das_control()))
    self.assertEqual(l.safety_fwd_hook(2, 0x2b9), -1)
    l.set_timer(1000 + 60000)
    self.assertEqual(l.safety_fwd_hook(2, 0x2b9), 0)


if __name__ == "__main__":
  unittest.main()
