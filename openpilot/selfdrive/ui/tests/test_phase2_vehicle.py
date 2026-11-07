"""Native focused tests: all persistence is temporary; no bench params."""
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import VehicleSettings, AP1, LONG, CLUSTER, REGEN, DESCRIPTIONS


class TestPhase2Vehicle(unittest.TestCase):
  def setUp(self):
    self.temp = TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.files = self.root / 'bogpilot'
    self.files.mkdir()
    self.store = self.root / LONG
    self.cp = SimpleNamespace(carFingerprint=AP1, dashcamOnly=False, openpilotLongitudinalControl=True,
                              alphaLongitudinalAvailable=False)
    self.offroad = True
    self.writes = []

    def put_bool(key, value, block=False):
      self.writes.append((key, value, block))
      self.store.write_text('1' if value else '0')
    self.model = VehicleSettings(SimpleNamespace(put_bool=put_bool), lambda: self.cp, lambda: self.offroad,
                                 self.files, self.store)

  def test_missing_defaults(self):
    self.assertFalse(self.model.read(LONG))
    self.assertTrue(self.model.read(CLUSTER))
    self.assertTrue(self.model.read(REGEN))

  def test_override_priority(self):
    self.store.write_text('0')
    (self.files / LONG).write_text('true')
    self.assertTrue(self.model.read(LONG))
    self.assertTrue(self.model.write(LONG, False))
    self.assertFalse(self.model.read(LONG))
    self.assertEqual((self.files / LONG).read_text(), '0')
    self.assertEqual(self.writes, [(LONG, False, True)])

  def test_no_new_override(self):
    self.assertTrue(self.model.write(LONG, True))
    self.assertTrue(self.model.read(LONG))
    self.assertFalse((self.files / LONG).exists())

  def test_empty_override_is_not_params_fallback(self):
    self.store.write_text('1')
    (self.files / LONG).write_text('')
    self.assertFalse(self.model.read(LONG))

  def test_ap1_file_writers(self):
    for key in (CLUSTER, REGEN):
      self.assertTrue(self.model.write(key, False))
      self.assertEqual((self.files / key).read_text(), '0')
      self.assertFalse(self.model.read(key))
      self.assertTrue(self.model.write(key, True))
      self.assertTrue(self.model.read(key))
    self.assertEqual(self.writes, [])

  def test_consumer_parsing(self):
    for key in (CLUSTER, REGEN):
      for text, expected in [('off', False), ('false', False), ('', True), ('garbage', True), ('on', True)]:
        (self.files / key).write_text(text)
        self.assertEqual(self.model.read(key), expected)

  def test_onroad_write_guard_all_rows(self):
    self.offroad = False
    for key in (LONG, CLUSTER, REGEN):
      self.assertTrue(self.model.visible(key))
      self.assertFalse(self.model.enabled(key))
      self.assertFalse(self.model.write(key, False))
    self.assertEqual(list(self.files.iterdir()), [])
    self.assertEqual(self.writes, [])

  def test_unsupported_and_unknown_car(self):
    for cp in (None, SimpleNamespace(carFingerprint='OTHER', dashcamOnly=False),
               SimpleNamespace(carFingerprint=AP1, dashcamOnly=True)):
      self.cp = cp
      for key in (LONG, CLUSTER, REGEN):
        self.assertFalse(self.model.visible(key))
        self.assertFalse(self.model.write(key, True))
    self.assertEqual(self.writes, [])

  def test_capability_not_global_disable_file(self):
    (self.files / LONG).write_text('1')
    self.cp.carFingerprint = 'OTHER'
    self.assertFalse(self.model.visible(LONG))

  def test_reenable_available_when_long_disabled(self):
    self.cp.openpilotLongitudinalControl = False
    self.assertTrue(self.model.visible(LONG))
    self.assertTrue(self.model.visible(CLUSTER))
    self.assertFalse(self.model.visible(REGEN))
    self.assertFalse(self.model.write(REGEN, True))
    self.assertTrue(self.model.write(LONG, False))

  def test_alpha_long_hidden(self):
    self.cp.alphaLongitudinalAvailable = True
    self.assertFalse(self.model.visible(LONG))
    self.assertFalse(self.model.write(LONG, True))

  def test_unknown_key_is_not_writable(self):
    self.assertFalse(self.model.write('ForceFingerprint', True))

  def test_timing_labels(self):
    self.assertIn('immediately', DESCRIPTIONS[CLUSTER])
    self.assertIn('next time the planner starts', DESCRIPTIONS[REGEN])
    self.assertIn('next time the car starts', DESCRIPTIONS[LONG])

  def test_planner_samples_regen_at_construction(self):
    from openpilot.selfdrive.controls.lib.ap1_planning import Ap1Planning
    from unittest.mock import patch
    with patch('openpilot.selfdrive.controls.lib.ap1_planning.ap1_comfort_brake', return_value=1.0) as read:
      planner = Ap1Planning(self.cp, 0.05)
      self.assertEqual(planner.comfort_brake, 1.0)
      read.assert_called_once_with(AP1)
      read.return_value = 2.5
      self.assertEqual(planner.comfort_brake, 1.0)
      self.assertEqual(Ap1Planning(self.cp, 0.05).comfort_brake, 2.5)


if __name__ == '__main__':
  unittest.main()
