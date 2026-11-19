"""Pre-AP Flip Radar toggle and Radar Offset row (TeslaRadarUpsideDown / TeslaRadarOffset), offroad only, next to Radar Donor Type."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import (AP1, LONG, PREAP, RADAR, RADAR_FLIP, RADAR_OFFSET, TITLES, VehicleSettings)
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
    self.assertEqual(self.model.radar_offset_text(), "0.00 M")

  def test_flip_toggle_writes_param(self):
    self.assertTrue(self.model.write(RADAR_FLIP, True))
    self.assertTrue(self.model.read(RADAR_FLIP))
    self.assertEqual((self.pdir / RADAR_FLIP).read_text(), "1")

  def test_offset_press_steps_up_by_0_05_and_wraps(self):
    self.assertEqual([self.model.next_radar_offset() for _ in range(3)], [0.05, 0.1, 0.15])
    self.assertEqual(self.model.radar_offset_text(), "+0.15 M")
    preap_params.set_float(PreApParamKeys.RADAR_OFFSET, 1.0)
    self.assertEqual(self.model.next_radar_offset(), -1.0)
    self.assertEqual(self.model.radar_offset_text(), "-1.00 M")
    preap_params.set_float(PreApParamKeys.RADAR_OFFSET, -0.05)
    self.assertEqual(self.model.next_radar_offset(), 0.0)

  def test_refused_onroad(self):
    self.offroad = False
    self.assertIsNone(self.model.next_radar_offset())
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
