#!/usr/bin/env python3
"""AP1 Model X openpilot long opt-in, panda side: 0x2b9 TX with the X flag (AP1 = 8) is blocked without LONG_CONTROL (1) and
allowed with it. The AP1 safety mode keys only on the flag bits, never on the car model, so enabling Model X long needs no
firmware change: the host just adds bit 1. The Model X never gets the standstill bit (16)."""
import unittest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
X_LATERAL_ONLY = 8            # flags_for_candidate(TESLA_AP1_MODELX)
X_LONG = 8 | 1                # flags_for_candidate(TESLA_AP1_MODELX, x_long=True)


def das_control(set_speed_kph=50.0, acc_state=4, aeb=0, accel_min=-1.0, accel_max=1.0, jerk_min=-0.46, jerk_max=0.476, counter=0):
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


class TestTeslaAp1ModelXLongFlag(unittest.TestCase):
  def init(self, param, allowed=True):
    l.set_timer(1000)
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.set_controls_allowed(allowed)

  def tx(self, dat):
    return l.safety_tx_hook(libsafety_py.make_CANPacket(0x2b9, 0, dat))

  def test_0x2b9_blocked_with_x_flag_without_long_control(self):
    for allowed in (True, False):
      self.init(X_LATERAL_ONLY, allowed)
      for d in (das_control(), das_control(accel_min=0.0, accel_max=0.0), das_control(set_speed_kph=0.0, acc_state=0)):
        self.assertFalse(self.tx(d), (allowed, d.hex()))

  def test_0x2b9_allowed_with_x_flag_and_long_control(self):
    self.init(X_LONG)
    self.assertTrue(self.tx(das_control()))
    self.assertTrue(self.tx(das_control(accel_min=-3.5, accel_max=0.0)))
    self.assertTrue(self.tx(das_control(accel_min=0.0, accel_max=1.9)))

  def test_x_long_still_needs_controls_allowed_and_keeps_limits(self):
    self.init(X_LONG)
    self.assertFalse(self.tx(das_control(accel_min=0.0, accel_max=2.2)))      # above +2.0
    self.assertFalse(self.tx(das_control(accel_min=-4.0, accel_max=0.0)))     # below the minimum
    self.init(X_LONG, allowed=False)
    self.assertFalse(self.tx(das_control(accel_min=0.0, accel_max=1.5)))

  def test_x_long_never_sends_aeb_and_stock_aeb_passes_through(self):
    self.init(X_LONG)
    self.assertFalse(self.tx(das_control(aeb=1)))
    self.assertFalse(self.tx(das_control(aeb=2)))
    aeb = bytearray(8); aeb[2] = 1
    l.safety_rx_hook(libsafety_py.make_CANPacket(0x2b9, 2, bytes(aeb)))
    self.assertEqual(l.safety_fwd_hook(2, 0x2b9), 0)                          # stock AEB frame is forwarded, not blocked

  def test_stock_das_control_forwarded_without_long_control(self):
    # Disable openpilot Longitudinal Control on the X (flag 8 only): openpilot never sends 0x2b9, and the stock DAS_control from
    # the camera bus always reaches the car, so stock TACC keeps working with openpilot steering.
    for allowed in (True, False):
      self.init(X_LATERAL_ONLY, allowed)
      self.assertFalse(self.tx(das_control()))
      l.safety_rx_hook(libsafety_py.make_CANPacket(0x2b9, 2, das_control()))
      self.assertEqual(l.safety_fwd_hook(2, 0x2b9), 0)

  def test_standstill_standby_frame_stays_blocked_without_standstill_bit(self):
    self.init(X_LONG, allowed=False)
    self.assertFalse(self.tx(das_control(set_speed_kph=0.0, accel_min=-1.4, accel_max=0.0, jerk_min=-0.46, jerk_max=0.476)))


if __name__ == "__main__":
  unittest.main()
