"""Pre-AP Radar EPAS Type row (TeslaRadarEpasType): NAP nap-dev NAPRadarEpasType, 0..4, default 0, edit gate (reboot-prompt class)."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys
from openpilot.selfdrive.ui.bogpilot import phase2_vehicle
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import (AP1, LONG, PREAP, RADAR, RADAR_EPAS_TYPE, RADAR_EPAS_TYPE_NAMES,
                                                            RADAR_EPAS_TYPE_TITLE, VehicleSettings)
from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP


class TestPreApRadarEpasType(unittest.TestCase):
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
    self.changed = []
    self.model = VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: self.cp, lambda: self.offroad,
                                 root / "bogpilot", root / LONG, on_change=self.changed.append)
    preap_params.set_bool(RADAR, True)

  def stored(self):
    p = self.pdir / PreApParamKeys.RADAR_EPAS_TYPE
    return p.read_text() if p.exists() else None

  def test_key_matches_params_and_has_help(self):
    self.assertEqual(RADAR_EPAS_TYPE, PreApParamKeys.RADAR_EPAS_TYPE)
    self.assertIn(RADAR_EPAS_TYPE, HELP)
    text = HELP[RADAR_EPAS_TYPE].what
    self.assertIn("5 seconds", text)
    for name in RADAR_EPAS_TYPE_NAMES:
      self.assertIn(name, text.replace("Bosch L538 (the default)", "Bosch L538"))

  def test_labels_are_naps_in_naps_order(self):
    self.assertEqual(RADAR_EPAS_TYPE_NAMES, ("Bosch L538", "Bosch L405", "Mando FGR64", "Mando VGR66", "Mando VGR66 Gen3"))
    self.assertEqual(RADAR_EPAS_TYPE_TITLE, "Pre-AP: Radar EPAS Type")
    self.assertIn("5 seconds", phase2_vehicle.RADAR_EPAS_TYPE_DESCRIPTION)

  def test_default_is_bosch_l538_and_nothing_stored(self):
    self.assertEqual(self.model.epas_type(), 0)
    self.assertEqual(self.model.epas_type_text(), "Bosch L538")
    self.assertIsNone(self.stored())

  def test_steps_up_and_down_and_stops_at_both_ends(self):
    self.assertIsNone(self.stored())
    self.assertEqual(self.model.step_epas_type(-1), 0)                      # no wrap below Bosch L538
    self.assertEqual([self.model.step_epas_type(1) for _ in range(6)], [1, 2, 3, 4, 4, 4])
    self.assertEqual(self.model.epas_type_text(), "Mando VGR66 Gen3")
    self.assertEqual(self.stored(), "4")
    self.assertEqual([self.model.step_epas_type(-1) for _ in range(5)], [3, 2, 1, 0, 0])
    self.assertEqual(self.model.epas_type_text(), "Bosch L538")
    self.assertTrue(all(key == RADAR_EPAS_TYPE for key in self.changed) and len(self.changed) == 12)

  def test_bad_file_reads_as_0_or_clamps(self):
    for text, want in (("9", 4), ("-3", 0), ("x", 0), ("1.5", 0), ("", 0)):
      (self.pdir / PreApParamKeys.RADAR_EPAS_TYPE).write_text(text)
      self.assertEqual(self.model.epas_type(), want, text)
      self.assertIn(self.model.epas_type_text(), RADAR_EPAS_TYPE_NAMES)

  def test_refused_while_the_edit_gate_is_closed(self):
    self.offroad = False
    self.assertTrue(self.model.visible(RADAR_EPAS_TYPE))
    self.assertFalse(self.model.enabled(RADAR_EPAS_TYPE))
    self.assertIsNone(self.model.step_epas_type(1))
    self.assertIsNone(self.stored())
    self.assertEqual(self.changed, [])

  def test_same_visibility_rule_as_the_other_donor_rows(self):
    group = (phase2_vehicle.RADAR_READ_VIN, phase2_vehicle.RADAR_DONOR_TYPE, RADAR_EPAS_TYPE, phase2_vehicle.RADAR_DONOR_VIN,
             phase2_vehicle.RADAR_FLIP, phase2_vehicle.RADAR_OFFSET)
    for radar in (True, False):
      preap_params.set_bool(RADAR, radar)
      for key in group:
        self.assertEqual(self.model.visible(key), radar, key)
    preap_params.set_bool(RADAR, True)
    self.cp.carFingerprint = AP1
    for key in group:
      self.assertFalse(self.model.visible(key), key)
    self.assertIsNone(self.model.step_epas_type(1))
    self.cp = None
    self.assertFalse(self.model.visible(RADAR_EPAS_TYPE))

  def test_row_registered_right_under_donor_type(self):
    src = Path(phase2_vehicle.__file__).read_text()
    a = src.index("self.rows[RADAR_DONOR_TYPE] = ")
    b = src.index("self.rows[RADAR_EPAS_TYPE] = ")
    c = src.index("self.rows[RADAR_DONOR_VIN] = ")
    self.assertTrue(a < b < c)
    self.assertIn("gated_value_step_item(lambda: tr(RADAR_EPAS_TYPE_TITLE)", src)   # the Alert Volume row layout


if __name__ == "__main__":
  unittest.main()
