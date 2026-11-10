"""t999/t1019: BogPilotDrivingModel is in the reset scope (back to Default) and in the settings backup."""
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import selection
from openpilot.system.bogpilot import settings_backup, toggle_reset
from openpilot.system.bogpilot.tests.test_settings_backup import SandboxParams
from openpilot.system.bogpilot.tests.test_toggle_reset import TypedParams

SEL = '{"id": "x", "pin_manifest": "b", "pin_model": "a", "v": 1}'


class FileStore:
  def __init__(self, root):
    self.root = Path(root)

  def raw(self, key):
    p = self.root / key
    return p.read_text() if p.exists() else None

  def put(self, key, text):
    self.root.mkdir(parents=True, exist_ok=True)
    (self.root / key).write_text(text)

  def remove(self, key):
    (self.root / key).unlink(missing_ok=True)


class TestDrivingModelResetBackup(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.files = Path(self.tmp.name) / "params_bogpilot"
    self.store = FileStore(self.files)

  def test_keys_match_selector(self):
    self.assertEqual(toggle_reset.DRIVING_MODEL_KEYS, (selection.KEY_SELECTION, selection.KEY_STATE))
    from openpilot.selfdrive.ui.bogpilot import phase3_system_utilities as u
    self.assertEqual(u.DRIVING_MODEL_KEYS, toggle_reset.DRIVING_MODEL_KEYS)

  def test_every_reset_table_unsets_the_selection(self):
    from openpilot.selfdrive.ui.bogpilot import phase3_system_utilities as u
    for table in (toggle_reset.reset_defaults(), toggle_reset.shipping_defaults(), u.shipping_defaults()):
      for key in toggle_reset.DRIVING_MODEL_KEYS:
        self.assertIn(key, table)
        self.assertIsNone(table[key])

  def test_reset_returns_to_default(self):
    self.store.put(selection.KEY_SELECTION, SEL)
    self.store.put(selection.KEY_STATE, '{"fallback": {"requested_id": "x"}}')
    params = TypedParams({toggle_reset.REQUEST_KEY: True})
    res = toggle_reset.reset_requested(params, self.files, backup=lambda: "receipt")
    self.assertEqual(res.status, "completed", res)
    self.assertIsNone(selection.read_selection(self.store)[0])
    self.assertFalse(selection.read_selection(self.store)[1])
    self.assertEqual(selection.read_state(self.store), {})
    from openpilot.common.bogpilot_models import alert
    self.assertIsNone(alert.current_alert(self.store))

  def test_selection_is_in_the_backup_but_runtime_state_is_not(self):
    self.assertIn(selection.KEY_SELECTION, settings_backup.FILE_KEYS)
    self.assertNotIn(selection.KEY_STATE, settings_backup.FILE_KEYS | settings_backup.SETTING_KEYS)
    self.assertNotIn(selection.KEY_SELECTION, settings_backup.SETTING_KEYS)
    self.store.put(selection.KEY_SELECTION, SEL)
    self.store.put(selection.KEY_STATE, "{}")
    native = Path(self.tmp.name) / "native"
    native.mkdir()
    out = Path(self.tmp.name) / "backups"
    r = settings_backup.backup_settings(SandboxParams(native), file_root=self.files, backup_root=out)
    self.assertTrue(r, r.error)
    doc = settings_backup.read_snapshot(r.path)
    self.assertEqual(doc["entries"][selection.KEY_SELECTION]["store"], "file")
    self.assertNotIn(selection.KEY_STATE, doc["entries"])
    import base64
    self.assertEqual(base64.b64decode(doc["entries"][selection.KEY_SELECTION]["value"]).decode(), SEL)

  def test_reset_runs_backup_first_and_the_backup_holds_the_selection(self):
    self.store.put(selection.KEY_SELECTION, SEL)
    native = Path(self.tmp.name) / "native"
    native.mkdir()
    out = Path(self.tmp.name) / "backups"
    params = TypedParams({toggle_reset.REQUEST_KEY: True})
    res = toggle_reset.reset_requested(
      params, self.files, backup=lambda: settings_backup.backup_settings(SandboxParams(native), file_root=self.files, backup_root=out))
    self.assertEqual(res.status, "completed", res)
    self.assertIsNone(selection.read_selection(self.store)[0])
    doc = settings_backup.read_snapshot(out / "latest.json")
    self.assertIn(selection.KEY_SELECTION, doc["entries"])


if __name__ == "__main__":
  unittest.main()
