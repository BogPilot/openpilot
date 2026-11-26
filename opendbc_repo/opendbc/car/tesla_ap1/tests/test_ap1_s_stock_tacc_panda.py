#!/usr/bin/env python3
"""AP1 Model S with Disable openpilot Longitudinal Control on, panda side: the host now passes the lateral only AP1 param 8 (the
same as the AP1 Model X) instead of 9. With 8 the panda refuses every DAS_control (0x2b9) from openpilot and always forwards the
stock DAS_control from the camera bus, so stock TACC keeps working with openpilot steering. With openpilot longitudinal the Model S
param is unchanged (9, or 25 with engage from a stop).
Kept with the car tests, outside opendbc/safety, so the panda firmware source identity (panda/build_identity.py) is unchanged."""
import unittest

from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.safety_flags import flags_for_candidate
from opendbc.car.tesla_ap1.values import CAR
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_ap1_x_long_flag import das_control

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
S = CAR.TESLA_AP1_MODELS
S_STOCK_TACC = flags_for_candidate(S, standstill=True, s_long=False)[0]
S_LONG = flags_for_candidate(S, s_long=True)[0]
S_LONG_STANDSTILL = flags_for_candidate(S, standstill=True, s_long=True)[0]


class TestTeslaAp1ModelSStockTaccFlag(unittest.TestCase):
  def init(self, param, allowed=True):
    l.set_timer(1000)
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.set_controls_allowed(allowed)

  def tx(self, dat):
    return l.safety_tx_hook(libsafety_py.make_CANPacket(0x2b9, 0, dat))

  def test_params(self):
    self.assertEqual(S_STOCK_TACC, 8)                     # lateral only, even with engage from a stop on
    self.assertEqual(flags_for_candidate(S, s_long=False), (8,))
    self.assertEqual((S_LONG, S_LONG_STANDSTILL), (9, 25))
    self.assertEqual(S_STOCK_TACC, flags_for_candidate(CAR.TESLA_AP1_MODELX, standstill=True)[0])

  def test_openpilot_das_control_refused_with_disable_on(self):
    frames = (das_control(), das_control(accel_min=0.0, accel_max=0.0), das_control(accel_min=-3.5, accel_max=0.0),
              das_control(set_speed_kph=0.0, acc_state=0), das_control(set_speed_kph=0.0, accel_min=-1.4, accel_max=0.0))
    for allowed in (True, False):
      self.init(S_STOCK_TACC, allowed)
      for d in frames:
        self.assertFalse(self.tx(d), (allowed, d.hex()))

  def test_stock_das_control_always_forwarded_with_disable_on(self):
    for allowed in (True, False):
      self.init(S_STOCK_TACC, allowed)
      self.assertFalse(self.tx(das_control()))            # a refused frame never starts the substitution window
      for aeb in (0, 1):
        l.safety_rx_hook(libsafety_py.make_CANPacket(0x2b9, 2, das_control(aeb=aeb)))
        self.assertEqual(l.safety_fwd_hook(2, 0x2b9), 0)

  def test_openpilot_long_param_unchanged(self):
    self.init(S_LONG)
    self.assertTrue(self.tx(das_control()))
    self.assertNotEqual(l.safety_fwd_hook(2, 0x2b9), 0)    # openpilot substitutes the stock frame while it sends
    self.init(S_LONG_STANDSTILL)
    self.assertTrue(self.tx(das_control(accel_min=-3.5, accel_max=0.0)))


if __name__ == "__main__":
  unittest.main()
