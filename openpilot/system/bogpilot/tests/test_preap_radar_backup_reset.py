"""Pre-AP Bosch radar toggles: in the durable backup, never touched by Reset to Stock (sandbox only)."""
import json
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_toggles import FILE_TOGGLES
from openpilot.system.bogpilot import settings_backup as sb
from openpilot.system.bogpilot import toggle_reset as tr
from openpilot.system.bogpilot.tests.test_settings_backup import SandboxParams
from openpilot.system.bogpilot.tests.test_toggle_reset import TypedParams

RADAR_KEYS = ("TeslaRadarEnabled", "TeslaRadarBehindNosecone", "TeslaRadarIgnoreHwFail")


class TestPreApRadarBackupReset(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)
    self.files = self.root / "params_bogpilot"
    self.files.mkdir()
    (self.root / "params").mkdir()

  def test_keys_match_the_car_code_and_default_off(self):
    from opendbc.car.tesla_ap1.preap.params import DEFAULTS, PreApParamKeys as K
    self.assertEqual((K.RADAR_ENABLED, K.RADAR_BEHIND_NOSECONE, K.RADAR_IGNORE_HW_FAIL), RADAR_KEYS)
    for k in RADAR_KEYS:
      self.assertIs(DEFAULTS[k], False)
      self.assertIs(FILE_TOGGLES[k][0], False)

  def test_in_durable_backup_scope_and_fixture(self):
    scope = json.loads((Path(__file__).parent / "fixtures/reset_backup_scope.json").read_text())
    for k in RADAR_KEYS:
      self.assertIn(k, sb.FILE_KEYS)
      self.assertIn(k, scope["file_keys"])

  def test_backup_captures_exact_file_bytes(self):
    (self.files / "TeslaRadarEnabled").write_bytes(b"1")
    (self.files / "TeslaRadarBehindNosecone").write_bytes(b"0")
    result = sb.backup_settings(SandboxParams(self.root / "params"), file_root=self.files, backup_root=self.root / "backups")
    self.assertTrue(result, result.error)
    entries = sb.read_snapshot(result.path)["entries"]
    self.assertEqual(entries["TeslaRadarEnabled"], {"store": "file", "value": "MQ=="})
    self.assertEqual(entries["TeslaRadarBehindNosecone"], {"store": "file", "value": "MA=="})

  def test_missing_files_are_not_synthesized(self):
    result = sb.backup_settings(SandboxParams(self.root / "params"), file_root=self.files, backup_root=self.root / "backups")
    entries = sb.read_snapshot(result.path)["entries"]
    for k in RADAR_KEYS:
      self.assertNotIn(k, entries)

  def test_not_in_any_reset_scope(self):
    for k in RADAR_KEYS:
      self.assertNotIn(k, tr.RESET_KEYS)
      self.assertNotIn(k, tr.FILE_RESET_KEYS)
      self.assertNotIn(k, tr.FILE_CHOICE_RESET_KEYS)
      self.assertNotIn(k, tr.UNSET_ALL)
      self.assertNotIn(k, tr.reset_defaults())
      self.assertNotIn(k, tr.shipping_defaults())

  def test_reset_to_stock_leaves_stored_values(self):
    for on in (b"1", b"0"):
      with self.subTest(stored=on):
        for k in RADAR_KEYS:
          (self.files / k).write_bytes(on)
        params = TypedParams({tr.REQUEST_KEY: True})
        result = tr.reset_requested(params, self.files, backup=lambda: "durable-test-receipt")
        self.assertEqual(result.status, "completed", result)
        for k in RADAR_KEYS:
          self.assertEqual((self.files / k).read_bytes(), on)
          self.assertNotIn(k, params.values)


if __name__ == "__main__":
  unittest.main()
