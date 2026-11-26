"""Pre-AP pedal FULL capture edge (selfdrive/car/card.py -> VCruiseHelper.capture_preap_full): SetSpeedLimit on and fresh gives limit +
offset; off or stale gives the exact vEgo (NAP preap/engagement.py:142,243-246 @ e99f4dc75). Never 40 (V_CRUISE_INITIAL) and never
the 8 (V_CRUISE_MIN) floor; the old set speed is never restored."""
import unittest
from types import SimpleNamespace as NS

from opendbc.car.common.conversions import Conversions as CV
from openpilot.selfdrive.car import cruise
from openpilot.selfdrive.car.cruise import V_CRUISE_INITIAL, V_CRUISE_MIN, VCruiseHelper
from openpilot.selfdrive.controls.tests.test_preap_set_speed_limit import MPH, engage

RELEASED = dict(standstill=False, gasPressed=False)


class TestPreapFullCapture(unittest.TestCase):
  def _h(self):
    h = VCruiseHelper(NS(pcmCruise=False))
    h.v_cruise_kph = h.v_cruise_kph_last = 100.0      # an old set speed that must not come back
    return h

  def test_ssl_fresh_gives_limit_plus_offset(self):
    cs = NS(vEgo=3.0, **RELEASED)
    lim = engage(Offset3="3").kph(cs, 40 * MPH)
    h = self._h()
    h.capture_preap_full(cs.vEgo, lim)
    self.assertEqual(h.v_cruise_kph, int(round((40 + 3) * MPH * CV.MS_TO_KPH)))

  def test_ssl_off_or_stale_gives_exact_vego(self):
    cs = NS(vEgo=3.0, **RELEASED)
    for lim in (engage(SetSpeedLimit="0").kph(cs, 40 * MPH), engage().kph(cs, 0.0), engage().kph(cs, None)):
      h = self._h()
      h.capture_preap_full(cs.vEgo, lim)
      self.assertAlmostEqual(h.v_cruise_kph, 3.0 * CV.MS_TO_KPH, places=6)

  def test_never_40_never_the_8_floor(self):
    for v in (0.1, 0.5, 2.0):
      h = self._h()
      h.capture_preap_full(v, 0.0)
      self.assertAlmostEqual(h.v_cruise_kph, v * CV.MS_TO_KPH, places=6)
      self.assertNotEqual(h.v_cruise_kph, V_CRUISE_INITIAL)
      self.assertLess(h.v_cruise_kph, V_CRUISE_MIN)

  def test_q6_constant_named_and_default_on(self):
    self.assertTrue(cruise.PREAP_FULL_USE_SET_SPEED_LIMIT)


if __name__ == "__main__":
  unittest.main()
