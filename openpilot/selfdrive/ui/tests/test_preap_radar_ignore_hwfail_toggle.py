"""Pre-AP Ignore radar HWFail Vehicle Settings toggle (TeslaRadarIgnoreHwFail).

Shown only on a detected Pre-AP Model S while Bosch Radar is on. Hidden on AP1 and while the car is unknown.
Default off. The param is already read live each radar cycle; this file covers the row, not the radar path.
"""
import inspect
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.params import DEFAULTS, PreApParamKeys
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import (
  AP1, IBOOSTER, LONG, PREAP, RADAR, RADAR_IGNORE_HW_FAIL, VehicleSettings, is_preap, supported)
from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP


def _cp(fingerprint, dashcam_only=False, long_control=True):
  return SimpleNamespace(carFingerprint=fingerprint, dashcamOnly=dashcam_only,
                         openpilotLongitudinalControl=long_control, alphaLongitudinalAvailable=False)


class TestPreApRadarIgnoreHwFailToggle(unittest.TestCase):
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
    self.cp = _cp(PREAP)
    self.offroad = True
    self.model = VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: self.cp, lambda: self.offroad,
                                 root / "bogpilot", root / LONG)
    preap_params.set_bool(RADAR, True)

  def stored(self):
    p = self.pdir / RADAR_IGNORE_HW_FAIL
    return p.read_text() if p.exists() else None

  def test_key_matches_params_and_help(self):
    self.assertEqual(RADAR_IGNORE_HW_FAIL, PreApParamKeys.RADAR_IGNORE_HW_FAIL)
    self.assertEqual(RADAR_IGNORE_HW_FAIL, "TeslaRadarIgnoreHwFail")
    self.assertIn(RADAR_IGNORE_HW_FAIL, HELP)
    self.assertEqual(self.model.title(RADAR_IGNORE_HW_FAIL), "Ignore Radar Hardware Fault (Pre-AP)")
    self.assertTrue(HELP[RADAR_IGNORE_HW_FAIL].default.startswith("Off"))

  def test_default_is_off_and_no_file_until_toggled(self):
    self.assertIs(DEFAULTS[PreApParamKeys.RADAR_IGNORE_HW_FAIL], False)
    self.assertFalse(self.model.read(RADAR_IGNORE_HW_FAIL))
    self.assertFalse(preap_params.get_bool(RADAR_IGNORE_HW_FAIL))
    self.assertIsNone(self.stored())

  def test_shown_on_preap_with_radar(self):
    self.assertTrue(is_preap(self.cp))
    self.assertTrue(self.model.visible(RADAR_IGNORE_HW_FAIL))
    self.assertTrue(self.model.enabled(RADAR_IGNORE_HW_FAIL))

  def test_hidden_on_preap_when_radar_is_off(self):
    preap_params.set_bool(RADAR, False)
    self.assertFalse(self.model.visible(RADAR_IGNORE_HW_FAIL))
    self.assertFalse(self.model.enabled(RADAR_IGNORE_HW_FAIL))
    self.assertFalse(self.model.write(RADAR_IGNORE_HW_FAIL, True))
    self.assertIsNone(self.stored())

  def test_hidden_on_ap1(self):
    self.cp = _cp(AP1)
    self.assertTrue(supported(self.cp))
    self.assertFalse(is_preap(self.cp))
    self.assertFalse(self.model.visible(RADAR_IGNORE_HW_FAIL))
    self.assertFalse(self.model.enabled(RADAR_IGNORE_HW_FAIL))
    self.assertFalse(self.model.write(RADAR_IGNORE_HW_FAIL, True))
    self.assertFalse(self.model.read(RADAR_IGNORE_HW_FAIL))
    self.assertIsNone(self.stored())

  def test_hidden_when_car_is_unknown(self):
    self.cp = None
    self.assertFalse(self.model.visible(RADAR_IGNORE_HW_FAIL))
    self.cp = _cp("MOCK")
    self.assertFalse(self.model.visible(RADAR_IGNORE_HW_FAIL))
    self.cp = _cp(PREAP, dashcam_only=True)
    self.assertFalse(self.model.visible(RADAR_IGNORE_HW_FAIL))

  def test_toggle_sets_the_param_offroad_and_is_refused_onroad(self):
    self.assertTrue(self.model.write(RADAR_IGNORE_HW_FAIL, True))
    self.assertTrue(self.model.read(RADAR_IGNORE_HW_FAIL))
    self.assertTrue(preap_params.get_bool(RADAR_IGNORE_HW_FAIL))
    self.assertEqual(self.stored().strip(), "1")
    self.assertTrue(self.model.write(RADAR_IGNORE_HW_FAIL, False))
    self.assertFalse(self.model.read(RADAR_IGNORE_HW_FAIL))
    self.assertEqual(self.stored().strip(), "0")
    preap_params.set_bool(RADAR_IGNORE_HW_FAIL, True)
    self.offroad = False
    self.assertTrue(self.model.visible(RADAR_IGNORE_HW_FAIL))
    self.assertFalse(self.model.enabled(RADAR_IGNORE_HW_FAIL))
    self.assertFalse(self.model.write(RADAR_IGNORE_HW_FAIL, False))
    self.assertTrue(preap_params.get_bool(RADAR_IGNORE_HW_FAIL))  # unchanged

  def test_ap1_ibooster_and_other_rows_unchanged(self):
    # The new row must not alter AP1 visibility of the existing AP1 / Pre-AP rows.
    self.cp = _cp(AP1)
    self.assertFalse(self.model.visible(RADAR))
    self.assertFalse(self.model.visible(IBOOSTER))
    self.assertTrue(self.model.visible(LONG))
    self.cp = None
    self.assertFalse(self.model.visible(LONG))
    self.assertFalse(self.model.visible(RADAR))

  def test_mutant_shown_on_ap1_or_dropped_preap_check_is_caught(self):
    """A version that shows the row on AP1, or that drops is_preap(cp), must fail this test."""
    self.cp = _cp(AP1)
    preap_params.set_bool(RADAR, True)
    self.assertFalse(self.model.visible(RADAR_IGNORE_HW_FAIL))
    self.cp = None
    self.assertFalse(self.model.visible(RADAR_IGNORE_HW_FAIL))

    src = textwrap.dedent(inspect.getsource(VehicleSettings.visible))
    start = src.find("if key == RADAR_IGNORE_HW_FAIL")
    self.assertNotEqual(start, -1, "visible() has no Ignore HWFail branch")
    chunk = src[start:start + 400]
    end = chunk.find("if key ==", 10)
    if end != -1:
      chunk = chunk[:end]
    self.assertIn("is_preap(cp)", chunk)
    self.assertNotIn("return True", chunk)
    self.assertNotIn("return supported(cp)", chunk)

    # The behavioural tests above fail if the guard is dropped: a mutant that returns
    # supported(cp) would show the row on AP1, and a mutant that returns True would show
    # it on an unknown car.
    self.cp = _cp(AP1)
    mutant_supported = supported(self.cp) and preap_params.get_bool(RADAR)
    mutant_always = True
    self.assertTrue(mutant_supported, "sanity: AP1 is a supported tesla_ap1 car")
    self.assertTrue(mutant_always)
    self.assertFalse(self.model.visible(RADAR_IGNORE_HW_FAIL))
    self.assertNotEqual(self.model.visible(RADAR_IGNORE_HW_FAIL), mutant_supported)
    self.assertNotEqual(self.model.visible(RADAR_IGNORE_HW_FAIL), mutant_always)


if __name__ == "__main__":
  unittest.main()
