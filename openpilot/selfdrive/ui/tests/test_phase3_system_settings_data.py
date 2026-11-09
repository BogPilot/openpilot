"""Fixture-only tests for System Settings > Data. Never deletes real device data."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]  # openpilot/
BOGPILOT = ROOT / "selfdrive/ui/bogpilot"


def load(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module
  spec.loader.exec_module(module)
  return module


b = load("openpilot.selfdrive.ui.bogpilot.phase3_system_settings_backend",
         BOGPILOT / "phase3_system_settings_backend.py")


class Store:
  def __init__(self, values=None):
    self.values = dict(values or {})
    self.writes = []

  def raw(self, key):
    return self.values.get(key)

  def get(self, key, default=""):
    return self.values.get(key, default)

  def get_bool(self, key, default=False):
    return self.values.get(key, "1" if default else "0") == "1"

  def put(self, key, value):
    self.values[key] = str(value)
    self.writes.append((key, str(value)))

  def put_bool(self, key, value):
    self.put(key, "1" if value else "0")

  def remove(self, key):
    self.values.pop(key, None)


class TestLocalData(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name).resolve()
    self.allowed = True
    self.recording = False
    self.roots = {}
    for category in ("driving", "errors", "recordings"):
      directory = self.root / category
      directory.mkdir()
      self.roots[category] = (str(directory),)
    self.data = b.LocalData(lambda: self.allowed, lambda: True, roots=self.roots, recording=lambda: self.recording)

  def file(self, category, name, data=b"fixture"):
    p = Path(self.roots[category][0]) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p

  def test_delete_recordings_is_scoped(self):
    self.file("recordings", "clip.mp4")
    keep = self.file("recordings", "readme.txt")
    self.assertEqual(self.data.delete("recordings"), 1)
    self.assertTrue(keep.exists())

  def test_driving_keeps_root_files_and_preserved_route(self):
    keep = self.file("driving", "bootlog")
    preserve = self.file("driving", "route-kept/rlog")
    self.file("driving", "route-delete/rlog")
    preserved_inode = preserve.parent.stat().st_ino

    def fixture_xattr(fd, key):
      if os.fstat(fd).st_ino == preserved_inode:
        return b"1"
      raise OSError(b.errno.ENODATA, "fixture without preserve flag")

    with patch.object(b.os, "getxattr", fixture_xattr, create=True):
      self.assertEqual(self.data.delete("driving"), 1)
    self.assertTrue(keep.exists())
    self.assertTrue(preserve.exists())

  def test_delete_errors_preserves_other_roots(self):
    self.file("errors", "crash/a.txt")
    other = self.file("recordings", "clip.mp4")
    self.data.delete("errors")
    self.assertTrue(other.exists())
    self.assertTrue(Path(self.roots["errors"][0]).is_dir())

  def test_symlink_entry_refuses_without_touching_target(self):
    target = self.file("errors", "outside")
    (Path(self.roots["recordings"][0]) / "link.mp4").symlink_to(target)
    with self.assertRaises(ValueError):
      self.data.delete("recordings")
    self.assertTrue(target.exists())

  def test_offroad_guard(self):
    self.file("errors", "error.txt")
    self.allowed = False
    with self.assertRaises(PermissionError):
      self.data.delete("errors")
    self.assertTrue((self.root / "errors/error.txt").exists())

  def test_active_recording_and_lock_block(self):
    self.file("recordings", "clip.mp4")
    self.recording = True
    with self.assertRaises(PermissionError):
      self.data.delete("recordings")
    self.recording = False
    self.file("recordings", "clip.mp4.lock")
    with self.assertRaises(PermissionError):
      self.data.delete("recordings")

  def test_path_traversal_rejected(self):
    for value in ("../clip.mp4", "/root.mp4", "a/b.mp4", ".", "a\x00.mp4"):
      with self.assertRaises(ValueError):
        self.data.delete("recordings", value)

  def test_rename_no_overwrite_and_extension(self):
    old = self.file("recordings", "old.mp4", b"old")
    existing = self.file("recordings", "existing.mp4", b"keep")
    with self.assertRaises(FileExistsError):
      self.data.rename_recording("old.mp4", "existing")
    self.assertEqual(existing.read_bytes(), b"keep")
    self.assertTrue(old.exists())
    self.assertEqual(self.data.rename_recording("old.mp4", "new name"), "new_name.mp4")
    self.assertFalse(old.exists())

  def test_storage_use_read_only(self):
    self.file("driving", "route/rlog", b"12345")
    self.file("errors", "e.txt", b"xyz")
    self.file("recordings", "clip.mp4", b"abcdefghij")
    before = {c: sorted(Path(self.roots[c][0]).rglob("*")) for c in self.roots}
    report = self.data.storage_use()
    self.assertEqual(report["recordings"]["bytes"], 10)
    self.assertGreaterEqual(report["driving"]["bytes"], 5)
    self.assertEqual(report["errors"]["bytes"], 3)
    after = {c: sorted(Path(self.roots[c][0]).rglob("*")) for c in self.roots}
    self.assertEqual(before, after)

  def test_storage_use_offroad_guard(self):
    self.allowed = False
    with self.assertRaises(PermissionError):
      self.data.storage_use()


class TestStatsAndExport(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.export = Path(self.tmp.name).resolve() / "exports"
    self.export.mkdir()
    self.store = Store({"FrogPilotStats": '{"distance":5,"weeks":{}}'})
    self.allowed = True
    self.backups = Path(self.tmp.name).resolve() / "stats_backups"
    self.p = b.SystemPreferences(self.store, lambda: self.allowed, lambda: True, stats_backup_dir=str(self.backups))

  def test_stats_display_and_reset_only_explicit(self):
    self.assertEqual(self.p.stats(), {"distance": 5, "weeks": {}})
    self.assertEqual(self.store.writes, [])
    self.p.reset_stats()
    self.assertEqual(self.p.stats(), {})

  def test_reset_writes_durable_backup_first(self):
    self.p.reset_stats()
    saved = list(self.backups.glob("FrogPilotStats.*.json"))
    self.assertEqual(len(saved), 1)
    self.assertEqual(saved[0].read_text(), '{"distance":5,"weeks":{}}')

  def test_reset_refused_without_backup_dir_and_stats_kept(self):
    p = b.SystemPreferences(self.store, lambda: True, lambda: True)
    with self.assertRaises(PermissionError):
      p.reset_stats()
    self.assertEqual(self.store.writes, [])
    self.assertEqual(p.stats(), {"distance": 5, "weeks": {}})

  def test_bad_stats_preserved(self):
    self.store.values["FrogPilotStats"] = "broken"
    with self.assertRaises(ValueError):
      self.p.stats()
    self.assertEqual(self.store.writes, [])

  def test_export_stats_local_only_no_overwrite(self):
    path = Path(self.p.export_stats(str(self.export)))
    self.assertTrue(path.is_file())
    self.assertEqual(json.loads(path.read_text()), {"distance": 5, "weeks": {}})
    with self.assertRaises(FileExistsError):
      self.p.export_stats(str(self.export))
    self.allowed = False
    with self.assertRaises(PermissionError):
      # would fail even with different name; guard first
      self.p.reset_stats()


class TestPreferenceArchive(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name).resolve()
    self.store = Store({"ScreenTimeout": "30", "ScreenManagement": "0", "SshEnabled": "1", "CarParams": "secret-fixture"})
    self.p = b.SystemPreferences(self.store, lambda: True, lambda: True)
    self.a = b.PreferenceArchive(self.p, self.root / "toggle_backups")

  def test_scoped_roundtrip_durable_before_restore(self):
    name = self.a.backup()
    content = (self.a.root / name).read_text()
    self.assertNotIn("SshEnabled", content)
    self.assertNotIn("CarParams", content)
    self.p.set("ScreenTimeout", 60)
    receipt = self.a.restore(name)
    self.assertTrue((self.a.root / receipt).exists())
    self.assertEqual(self.store.values["ScreenTimeout"], "30")
    self.assertEqual(self.store.values["CarParams"], "secret-fixture")

  def test_tampered_snapshot_refused(self):
    name = self.a.backup()
    p = self.a.root / name
    doc = json.loads(p.read_text())
    doc["values"]["SshEnabled"] = "0"
    p.write_text(json.dumps(doc))
    with self.assertRaises(ValueError):
      self.a.restore(name)

  def test_delete_all_keeps_unrelated_legacy_backups(self):
    self.a.backup()
    legacy = self.a.root / "legacy-backup.tar.zst"
    legacy.write_bytes(b"fixture")
    self.assertEqual(self.a.delete(), 1)
    self.assertTrue(legacy.exists())


class TestDataUIContract(unittest.TestCase):
  """Smoke: Data page titles exist; destructive paths go through confirm helper."""

  def test_module_exports_builder(self):
    path = ROOT / "selfdrive/ui/layouts/settings/phase3_system_settings_data_ui.py"
    src = path.read_text()
    self.assertIn("def build_data_layout", src)
    self.assertIn("ConfirmDialog", src)
    self.assertIn("Delete Driving Data", src)
    self.assertIn("Storage Use", src)
    self.assertIn("Toggle Backups", src)
    self.assertIn("BogPilot Stats", src)
    # cloud exclusions
    for banned in ("Share Driving Data", "Use Konik Server", "Disable Uploads", "Firehose", "Remote Screen Viewer"):
      self.assertNotIn(banned, src)
    # sister lanes not owned here
    self.assertNotIn("Flash Panda", src)
    self.assertNotIn("Force Drive State", src)
    self.assertNotIn("Device Shutdown Timer", src)


if __name__ == "__main__":
  unittest.main()
