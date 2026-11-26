"""Merged Pre-AP radar rows in Vehicle Settings: visible() gating for the shared key tuple, and the row order under Radar Donor Type."""
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from opendbc.car.tesla_ap1.preap import params as preap_params
from openpilot.selfdrive.ui.bogpilot import phase2_vehicle
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import (AP1, LONG, PREAP, RADAR, RADAR_DONOR_TYPE, RADAR_DONOR_VIN, RADAR_EPAS_TYPE,
                                                            RADAR_FLIP, RADAR_OFFSET, RADAR_READ_VIN, VehicleSettings)

GROUP = (RADAR_READ_VIN, RADAR_DONOR_TYPE, RADAR_EPAS_TYPE, RADAR_DONOR_VIN, RADAR_FLIP, RADAR_OFFSET)


class TestRadarRowsMerged(unittest.TestCase):
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

  def test_all_six_follow_one_gate_pre_ap_with_radar(self):
    preap_params.set_bool(RADAR, True)
    for key in GROUP:
      self.assertTrue(self.model.visible(key), key)
      self.assertTrue(self.model.enabled(key), key)

  def test_hidden_without_radar_and_on_ap1(self):
    for key in GROUP:
      self.assertFalse(self.model.visible(key), key)
    preap_params.set_bool(RADAR, True)
    self.cp.carFingerprint = AP1
    for key in GROUP:
      self.assertFalse(self.model.visible(key), key)

  def test_editable_rows_locked_while_onroad(self):
    preap_params.set_bool(RADAR, True)
    self.offroad = False
    for key in (RADAR_DONOR_TYPE, RADAR_EPAS_TYPE, RADAR_DONOR_VIN, RADAR_FLIP, RADAR_OFFSET):
      self.assertTrue(self.model.visible(key), key)
      self.assertFalse(self.model.enabled(key), key)

  def test_row_order_under_donor_type(self):
    # The row widgets need the device UI toolkit, so read the registration order from the source.
    src = Path(phase2_vehicle.__file__).read_text()
    pos = {}
    for key in ("RADAR_DONOR_TYPE", "RADAR_EPAS_TYPE", "RADAR_DONOR_VIN", "RADAR_FLIP", "RADAR_OFFSET"):
      m = re.search(r"self\.rows\[%s\] = " % key, src)
      self.assertIsNotNone(m, key)
      pos[key] = m.start()
    self.assertLess(pos["RADAR_DONOR_TYPE"], pos["RADAR_EPAS_TYPE"])
    self.assertLess(pos["RADAR_EPAS_TYPE"], pos["RADAR_DONOR_VIN"])
    self.assertLess(pos["RADAR_DONOR_VIN"], pos["RADAR_FLIP"])
    self.assertLess(pos["RADAR_FLIP"], pos["RADAR_OFFSET"])
    self.assertEqual(len(re.findall(r"self\.rows\[RADAR_FLIP\] = self\.rows\.pop\(RADAR_FLIP\)", src)), 1)


if __name__ == "__main__":
  unittest.main()
