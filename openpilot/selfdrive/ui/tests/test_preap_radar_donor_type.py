"""Pre-AP Radar Donor Type row (TeslaRadarDonorType): NAP NAPRadarPosition, 0 / 1 / 2, default 0, offroad only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import (LONG, PREAP, RADAR, RADAR_DONOR_TYPE, RADAR_DONOR_TYPE_NAMES,
                                                            RADAR_NOSECONE, VehicleSettings)
from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP


class TestPreApRadarDonorType(unittest.TestCase):
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
    self.cp = SimpleNamespace(carFingerprint=PREAP, dashcamOnly=False, openpilotLongitudinalControl=True,
                              alphaLongitudinalAvailable=False)
    self.offroad = True
    self.model = VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: self.cp, lambda: self.offroad,
                                 root / "bogpilot", root / LONG)
    preap_params.set_bool(RADAR, True)

  def stored(self):
    p = self.pdir / PreApParamKeys.RADAR_DONOR_TYPE
    return p.read_text() if p.exists() else None

  def test_key_matches_params(self):
    self.assertEqual(RADAR_DONOR_TYPE, PreApParamKeys.RADAR_DONOR_TYPE)
    self.assertIn(RADAR_DONOR_TYPE, HELP)

  def test_default_is_pre_facelift_model_s(self):
    self.assertEqual(self.model.donor_type(), 0)
    self.assertEqual(self.model.donor_type_text(), RADAR_DONOR_TYPE_NAMES[0])
    self.assertIsNone(self.stored())

  def test_press_cycles_0_1_2_0(self):
    self.assertEqual([self.model.next_donor_type() for _ in range(4)], [1, 2, 0, 1])
    self.assertEqual(self.stored(), "1")
    self.assertEqual(self.model.donor_type_text(), "Model S facelift")

  def test_bad_file_reads_as_0_and_press_goes_to_1(self):
    (self.pdir / PreApParamKeys.RADAR_DONOR_TYPE).write_text("9")
    self.assertEqual(self.model.donor_type(), 0)
    self.assertEqual(self.model.next_donor_type(), 1)

  def test_refused_onroad(self):
    self.offroad = False
    self.assertIsNone(self.model.next_donor_type())
    self.assertIsNone(self.stored())

  def test_shown_only_on_preap_with_radar_and_independent_of_nosecone(self):
    self.assertTrue(self.model.visible(RADAR_DONOR_TYPE))
    preap_params.set_bool(RADAR_NOSECONE, True)
    self.assertEqual(self.model.donor_type(), 0)
    self.assertEqual(self.model.next_donor_type(), 1)
    preap_params.set_bool(RADAR_NOSECONE, False)
    self.assertEqual(self.model.donor_type(), 1)
    preap_params.set_bool(RADAR, False)
    self.assertFalse(self.model.visible(RADAR_DONOR_TYPE))
    self.assertIsNone(self.model.next_donor_type())
    self.cp = SimpleNamespace(carFingerprint="TESLA_AP1_MODELS", dashcamOnly=False, openpilotLongitudinalControl=True,
                              alphaLongitudinalAvailable=False)
    preap_params.set_bool(RADAR, True)
    self.assertFalse(self.model.visible(RADAR_DONOR_TYPE))


if __name__ == "__main__":
  unittest.main()
