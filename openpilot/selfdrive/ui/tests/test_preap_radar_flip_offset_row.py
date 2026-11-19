"""Pre-AP Flip Radar toggle and Radar Offset row (TeslaRadarUpsideDown / TeslaRadarOffset), offroad only, next to Radar Donor Type."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import (AP1, LONG, PREAP, RADAR, RADAR_FLIP, RADAR_OFFSET, RADAR_OFFSET_MINUS,
                                                            RADAR_OFFSET_PLUS, TITLES, VehicleSettings)
from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP


class TestPreApRadarFlipOffset(unittest.TestCase):
  def setUp(self):
    self.temp = TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    root = Path(self.temp.name)
    self.pdir = root / "params_bogpilot"
    self.pdir.mkdir()
    old = preap_params._params_dir
    preap_params._params_dir = self.pdir
    self.addCleanup(setattr, preap_params, "_params_dir", old)
    (root / "bogpilot").mkdir()
    self.cp = SimpleNamespace(carFingerprint=PREAP, dashcamOnly=False, openpilotLongitudinalControl=True, alphaLongitudinalAvailable=False)
    self.offroad = True
    self.model = VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: self.cp, lambda: self.offroad,
                                 root / "bogpilot", root / LONG)
    preap_params.set_bool(RADAR, True)

  def test_keys_match_params_and_have_help(self):
    self.assertEqual((RADAR_FLIP, RADAR_OFFSET), (PreApParamKeys.RADAR_FLIP, PreApParamKeys.RADAR_OFFSET))
    self.assertIn(RADAR_FLIP, HELP)
    self.assertIn(RADAR_OFFSET, HELP)
    self.assertIn(RADAR_FLIP, TITLES)

  def test_defaults_off_and_zero(self):
    self.assertFalse(self.model.read(RADAR_FLIP))
    self.assertEqual(self.model.radar_offset(), 0.0)
    self.assertEqual(self.model.radar_offset_text(), "0.00 m")

  def test_flip_toggle_writes_param(self):
    self.assertTrue(self.model.write(RADAR_FLIP, True))
    self.assertTrue(self.model.read(RADAR_FLIP))
    self.assertEqual((self.pdir / RADAR_FLIP).read_text(), "1")

  def test_offset_steps_by_one_hundredth(self):
    self.assertEqual([self.model.step_radar_offset(1) for _ in range(3)], [0.01, 0.02, 0.03])
    self.assertEqual(self.model.step_radar_offset(-1), 0.02)
    self.assertEqual((self.pdir / RADAR_OFFSET).read_text(), "0.02")

  def test_offset_clamps_at_both_ends_without_wrapping(self):
    preap_params.set_float(PreApParamKeys.RADAR_OFFSET, 0.99)
    self.assertEqual([self.model.step_radar_offset(1) for _ in range(3)], [1.0, 1.0, 1.0])
    preap_params.set_float(PreApParamKeys.RADAR_OFFSET, -0.99)
    self.assertEqual([self.model.step_radar_offset(-1) for _ in range(3)], [-1.0, -1.0, -1.0])
    self.assertEqual(self.model.radar_offset_text(), "-1.00 m")

  def test_stored_out_of_range_or_off_grid_value_steps_on_the_hundredths_grid(self):
    preap_params.set_float(PreApParamKeys.RADAR_OFFSET, 5.0)       # read clamped to 1.00, plus can not leave the range
    self.assertEqual(self.model.step_radar_offset(1), 1.0)
    preap_params.set_float(PreApParamKeys.RADAR_OFFSET, 0.3749)
    self.assertEqual(self.model.step_radar_offset(1), 0.38)

  def test_float_rounding_stays_at_one_hundredth(self):
    for _ in range(100):
      self.model.step_radar_offset(1)
    self.assertEqual(self.model.radar_offset(), 1.0)
    for _ in range(137):
      self.model.step_radar_offset(-1)
    self.assertEqual((self.pdir / RADAR_OFFSET).read_text(), "-0.37")
    self.assertEqual(self.model.radar_offset(), -0.37)

  def test_text_has_two_decimals_unit_and_ascii_minus(self):
    self.assertEqual(self.model.radar_offset_text(), "0.00 m")
    preap_params.set_float(PreApParamKeys.RADAR_OFFSET, 0.1)
    self.assertEqual(self.model.radar_offset_text(), "0.10 m")
    preap_params.set_float(PreApParamKeys.RADAR_OFFSET, -0.05)
    text = self.model.radar_offset_text()
    self.assertEqual(text, "-0.05 m")
    self.assertTrue(text.isascii())                       # no U+2212: it can render as ? in the UI font
    self.assertEqual((RADAR_OFFSET_MINUS, RADAR_OFFSET_PLUS), ("-", "+"))
    from openpilot.selfdrive.ui.bogpilot.phase2_sounds import MINUS_GLYPH, PLUS_GLYPH
    self.assertEqual((RADAR_OFFSET_MINUS, RADAR_OFFSET_PLUS), (MINUS_GLYPH, PLUS_GLYPH))   # same glyphs as the Alert Volume rows

  def test_refused_onroad(self):
    self.offroad = False
    self.assertIsNone(self.model.step_radar_offset(1))
    self.assertIsNone(self.model.step_radar_offset(-1))
    self.assertFalse(self.model.write(RADAR_FLIP, True))
    self.assertFalse((self.pdir / RADAR_OFFSET).exists() or (self.pdir / RADAR_FLIP).exists())

  def test_shown_only_on_preap_with_radar_on(self):
    for key in (RADAR_FLIP, RADAR_OFFSET):
      self.assertTrue(self.model.visible(key))
    preap_params.set_bool(RADAR, False)
    for key in (RADAR_FLIP, RADAR_OFFSET):
      self.assertFalse(self.model.visible(key))
    preap_params.set_bool(RADAR, True)
    self.cp.carFingerprint = AP1
    for key in (RADAR_FLIP, RADAR_OFFSET):
      self.assertFalse(self.model.visible(key))


if __name__ == "__main__":
  unittest.main()
