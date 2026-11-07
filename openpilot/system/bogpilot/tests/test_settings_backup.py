"""Pure Python sandbox tests: no native library, device, or host settings paths."""
import base64
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpilot.system.bogpilot import settings_backup as b


class SandboxParams:
  def __init__(self, root):
    self.root = root
    self.calls = []

  def all_keys(self):
    # Include file-only keys deliberately: these must never reach typed Params.
    return [b"AccelerationProfile", b"AlertVolumeControl", b"RedesignUI", b"DeveloperHUD", b"CarVin", b"DongleId"]

  def check_key(self, key):
    self.calls.append(key)
    if key in ("RedesignUI", "DeveloperHUD"):
      raise AssertionError("file-only typed access")

  def get_param_path(self, key):
    return str(self.root / key)

  def put(self, *args):
    raise AssertionError("backup must not write Params")


class TestSettingsBackup(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.native = self.root / "params"
    self.files = self.root / "files"
    self.backups = self.root / "backups"
    self.native.mkdir()
    self.files.mkdir()
    self.params = SandboxParams(self.native)

  def save(self, **kwargs):
    return b.backup_settings(self.params, file_root=self.files, backup_root=self.backups, **kwargs)

  def doc(self, result):
    self.assertTrue(result, result.error)
    return b.read_snapshot(result.path)

  def test_empty_missing_never_synthesizes_defaults(self):
    self.assertEqual(self.doc(self.save())["entries"], {})
    self.assertFalse((self.native / "TuningLevel").exists())

  def test_typed_and_non_utf8_exact(self):
    (self.native / "AccelerationProfile").write_bytes(b"2")
    (self.native / "AlertVolumeControl").write_bytes(b"0")
    (self.files / "Model").write_bytes(b"\xff\x00raw")
    entries = self.doc(self.save())["entries"]
    for key, raw in (("AccelerationProfile", b"2"), ("AlertVolumeControl", b"0"), ("Model", b"\xff\x00raw")):
      self.assertEqual(base64.b64decode(entries[key]["value"]), raw)
    self.assertEqual(entries["AccelerationProfile"]["store"], "params")
    self.assertEqual(entries["Model"]["store"], "file")

  def test_file_only_no_typed_params(self):
    for key in b.FILE_ONLY_UI_KEYS:
      (self.files / key).write_bytes(b"1")
    entries = self.doc(self.save())["entries"]
    self.assertTrue(all(entries[k]["store"] == "file" for k in b.FILE_ONLY_UI_KEYS))
    self.assertFalse(set(self.params.calls) & b.FILE_ONLY_UI_KEYS)

  def test_private_ephemeral_unknown_and_upload_excluded(self):
    excluded = ("DongleId", "CarVin", "KonikDongleId", "DiscordUsername", "AMapKey1", "DriveHistory", "LastKnownTime", "AP1DefaultsApplied", "ShowUploadRate", "FutureSecretKey", "DoToggleResetStock", "ApiCache_NavDestinations")
    for key in excluded:
      (self.files / key).write_bytes(b"synthetic-only")
      (self.native / key).write_bytes(b"synthetic-only")
    self.assertEqual(self.doc(self.save())["entries"], {})

  def test_future_registry_addition_not_included(self):
    (self.files / "FutureSetting").write_bytes(b"1")
    with patch.dict(b.BOGPILOT_PARAMS, {"FutureSetting": ("PERSISTENT", "BOOL", "0", 1, "0")}):
      self.assertEqual(self.doc(self.save())["entries"], {})

  def test_flag_changed_to_transient_excluded(self):
    (self.native / "AccelerationProfile").write_bytes(b"2")
    with patch.dict(b.BOGPILOT_PARAMS, {"AccelerationProfile": ("CLEAR_ON_MANAGER_START", "INT", "2", 1, "2")}):
      self.assertEqual(self.doc(self.save())["entries"], {})

  def test_snapshot_versions_and_corruption(self):
    with self.assertRaises(FileNotFoundError):
      b.read_snapshot(self.root / "missing")
    path = self.root / "bad.json"
    for raw in (b"{", b'{"version": 2, "entries": {}}', b'{"version": 1, "entries": {}, "digest": "bad"}'):
      path.write_bytes(raw)
      with self.assertRaises((ValueError, KeyError, TypeError)):
        b.read_snapshot(path)

  def test_base64_and_scope_validation(self):
    path = self.root / "bad.json"
    for key, value in (("AccelerationProfile", "!bad"), ("Unknown", "MQ==")):
      doc = {"version": 1, "entries": {key: {"store": "file", "value": value}}}
      doc["digest"] = b._digest(doc["entries"])
      path.write_text(json.dumps(doc))
      with self.assertRaises(ValueError):
        b.read_snapshot(path)

  def test_dedup_and_original_survives_explicit_reset(self):
    (self.native / "AccelerationProfile").write_bytes(b"2")
    receipt = self.save(reason="before-reset")
    self.assertTrue(receipt)
    # Reset contract: only mutate AFTER truthy receipt; backup itself makes no mutation.
    self.assertEqual((self.native / "AccelerationProfile").read_bytes(), b"2")
    original = receipt.path.read_bytes()
    (self.native / "AccelerationProfile").write_bytes(b"0")
    after = self.save()
    self.assertTrue(after)
    self.assertNotEqual(receipt.path, after.path)
    self.assertEqual(receipt.path.read_bytes(), original)
    self.assertEqual(self.save().path, after.path)

  def test_failed_backup_blocks_reset_closure(self):
    with patch.object(b, "_atomic_write", side_effect=PermissionError):
      receipt = self.save(reason="before-reset")
    self.assertFalse(receipt)
    self.assertEqual(receipt.error, "PermissionError")
    self.assertIsNone(receipt.path)

  def test_partial_write_crash_keeps_latest_and_original(self):
    first = self.save()
    original = (self.backups / "latest.json").read_bytes()
    (self.native / "AccelerationProfile").write_bytes(b"2")
    real_replace = os.replace
    def fail_latest(src, dst):
      if Path(dst).name == "latest.json":
        raise OSError("synthetic interruption")
      real_replace(src, dst)
    with patch.object(b.os, "replace", side_effect=fail_latest):
      self.assertFalse(self.save())
    self.assertEqual((self.backups / "latest.json").read_bytes(), original)
    self.assertEqual(first.path.read_bytes(), original)
    self.assertEqual(list(self.backups.glob(".snapshot-*")), [])
    self.assertTrue(self.save())

  def test_permission_failure_no_fallback(self):
    with patch.object(b.os, "chmod", side_effect=PermissionError("sensitive fake value")):
      result = self.save()
    self.assertFalse(result)
    self.assertEqual(result.error, "PermissionError")
    self.assertEqual(list(self.backups.glob("*.json")), [])

  def test_snapshot_rename_failure_preserves_previous(self):
    first = self.save()
    original = first.path.read_bytes()
    (self.native / "AccelerationProfile").write_bytes(b"2")
    with patch.object(b.os, "replace", side_effect=OSError):
      self.assertFalse(self.save())
    self.assertEqual(first.path.read_bytes(), original)
    self.assertEqual((self.backups / "latest.json").read_bytes(), original)
    self.assertEqual(list(self.backups.glob(".snapshot-*")), [])

  def test_fsync_failure_is_not_success(self):
    with patch.object(b.os, "fsync", side_effect=OSError):
      self.assertFalse(self.save())
    self.assertFalse((self.backups / "latest.json").exists())

  def test_empty_bytes_are_preserved(self):
    (self.files / "Model").write_bytes(b"")
    entry = self.doc(self.save())["entries"]["Model"]
    self.assertEqual(base64.b64decode(entry["value"]), b"")

  def test_permissions(self):
    result = self.save()
    self.assertEqual(self.backups.stat().st_mode & 0o777, 0o700)
    self.assertEqual(result.path.stat().st_mode & 0o777, 0o600)
    self.assertEqual((self.backups / "latest.json").stat().st_mode & 0o777, 0o600)

  def test_corrupt_existing_snapshot_not_overwritten(self):
    first = self.save()
    first.path.write_bytes(b"corrupt")
    self.assertFalse(self.save())
    self.assertEqual(first.path.read_bytes(), b"corrupt")

  def test_lock_busy_nonfatal(self):
    self.backups.mkdir()
    with (self.backups / ".lock").open("wb") as lock:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
      self.assertFalse(self.save())
    self.assertTrue(self.save())

  def test_symlink_refused(self):
    (self.files / "RedesignUI").symlink_to(self.native / "missing")
    self.assertFalse(self.save())

  def test_oversize_refused(self):
    (self.files / "RedesignUI").write_bytes(b"1" * (b.MAX_VALUE_BYTES + 1))
    self.assertFalse(self.save())


if __name__ == "__main__":
  unittest.main()
