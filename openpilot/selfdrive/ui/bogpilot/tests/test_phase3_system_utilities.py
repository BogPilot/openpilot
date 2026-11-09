"""Fixture-only tests for System Settings > Utilities. No hardware, flash, or live Params."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load_backend():
  """Load the lane module even when not installed on PYTHONPATH."""
  path = HERE / "phase3_system_utilities.py"
  if not path.is_file():
    # Installed tree path during worktree runs.
    path = HERE.parent / "phase3_system_utilities.py"
  name = "openpilot.selfdrive.ui.bogpilot.phase3_system_utilities"
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module
  spec.loader.exec_module(module)
  return module


b = load_backend()


class FakeParams:
  def __init__(self, values=None, known=None):
    self.values = dict(values or {})
    self.known = set(known or self.values) | {
      "DebugMode", "DoToggleResetStock", "ApiCache_DriveStats", "ApiCache_NavDestinations",
      "CarModel", "IsMetric", "GreenLightAlert",
    }
    self.writes = []

  def all_keys(self):
    return list(self.known)

  def get(self, key, *args, **kwargs):
    return self.values.get(key)

  def get_bool(self, key, default=False):
    value = self.values.get(key)
    if value is None:
      return default
    if isinstance(value, bool):
      return value
    return value in (True, "1", 1, b"1")

  def put(self, key, value, block=False):
    self.values[key] = value
    self.writes.append(("put", key, value))

  def put_bool(self, key, value, block=False):
    self.values[key] = bool(value)
    self.writes.append(("put_bool", key, bool(value)))

  def remove(self, key):
    self.values.pop(key, None)
    self.writes.append(("remove", key))

  def cpp2python(self, key, raw: bytes):
    text = raw.decode()
    if text in {"0", "1"}:
      return text == "1"
    try:
      if "." in text:
        return float(text)
      return int(text)
    except ValueError:
      return text


class FakeStore:
  def __init__(self, values=None):
    self.values = {k: ("1" if v else "0") if isinstance(v, bool) else v for k, v in (values or {}).items()}

  def raw(self, key):
    return self.values.get(key)

  def get(self, key, default=""):
    return self.values.get(key, default)

  def get_bool(self, key, default=False):
    value = self.values.get(key)
    if value is None:
      return default
    return value == "1"

  def put(self, key, value):
    self.values[key] = str(value)

  def put_bool(self, key, value):
    self.values[key] = "1" if value else "0"


class BackupReceipt:
  success = True


class UtilitiesTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name).resolve()
    self.file_root = self.root / "params_bogpilot"
    self.file_root.mkdir()
    self.backup_root = self.root / "settings-backups"
    self.backup_root.mkdir()
    self.report_root = self.root / "reports"
    self.cache_a = self.root / "comma_download_cache"
    self.cache_b = self.root / "model_replay_cache"
    self.cache_a.mkdir()
    self.cache_b.mkdir()
    self.allowed = True
    self.params = FakeParams({"DebugMode": False, "GreenLightAlert": True})
    self.store = FakeStore({"DebugMode": "0"})

  def actions(self, **overrides):
    kw = dict(
      offroad=lambda: self.allowed,
      capable=lambda: True,
      params=self.params,
      store=self.store,
      file_root=self.file_root,
      backup_root=self.backup_root,
      cache_roots=(str(self.cache_a), str(self.cache_b)),
      report_root=self.report_root,
      now=lambda: 1_700_000_000.0,
    )
    kw.update(overrides)
    return b.UtilitiesActions(**kw)

  def test_debug_mode_roundtrip(self):
    act = self.actions()
    self.assertFalse(act.get_debug_mode())
    self.assertIn("enabled", act.set_debug_mode(True))
    self.assertTrue(act.get_debug_mode())
    self.assertEqual(self.store.values["DebugMode"], "1")

  def test_debug_mode_requires_offroad(self):
    self.allowed = False
    with self.assertRaises(PermissionError):
      self.actions().set_debug_mode(True)
    self.assertEqual(self.store.values.get("DebugMode"), "0")

  def test_clear_caches_removes_files_only_in_allowlist(self):
    (self.cache_a / "blob").write_bytes(b"x")
    nested = self.cache_b / "sub"
    nested.mkdir()
    (nested / "frame.bin").write_bytes(b"y")
    outside = self.root / "keep_me"
    outside.write_bytes(b"z")
    self.params.values["ApiCache_DriveStats"] = "{}"
    self.params.values["ApiCache_NavDestinations"] = "[]"
    msg = self.actions().clear_caches()
    self.assertIn("Cleared", msg)
    self.assertFalse((self.cache_a / "blob").exists())
    self.assertFalse(nested.exists())
    self.assertTrue(outside.exists())
    self.assertNotIn("ApiCache_DriveStats", self.params.values)
    self.assertNotIn("ApiCache_NavDestinations", self.params.values)

  def test_clear_caches_refuses_when_onroad(self):
    (self.cache_a / "blob").write_bytes(b"x")
    self.allowed = False
    with self.assertRaises(PermissionError):
      self.actions().clear_caches()
    self.assertTrue((self.cache_a / "blob").exists())

  def test_clear_caches_skips_forbidden_params_name(self):
    forbidden = self.root / "params"
    forbidden.mkdir()
    secret = forbidden / "SecOCKey"
    secret.write_bytes(b"secret")
    act = self.actions(cache_roots=(str(forbidden), str(self.cache_a)))
    (self.cache_a / "ok").write_bytes(b"1")
    act.clear_caches()
    self.assertTrue(secret.exists())
    self.assertFalse((self.cache_a / "ok").exists())

  def test_clear_caches_refuses_symlink_entries(self):
    target = self.root / "outside_target"
    target.write_bytes(b"keep")
    (self.cache_a / "link").symlink_to(target)
    with self.assertRaises(ValueError):
      self.actions().clear_caches()
    self.assertTrue(target.exists())

  def test_save_debug_report_local_only(self):
    act = self.actions()
    msg = act.save_debug_report()
    self.assertIn("not uploaded", msg.lower())
    reports = list(self.report_root.glob("bogpilot-debug-*.json"))
    self.assertEqual(len(reports), 1)
    doc = json.loads(reports[0].read_text())
    self.assertEqual(doc["format"], "bogpilot-local-debug-report")
    self.assertEqual(doc["version"], 1)
    self.assertIn("prefs", doc)
    self.assertNotIn("SecOCKey", doc.get("prefs", {}))

  def test_save_debug_report_requires_confirm_guard(self):
    self.allowed = False
    with self.assertRaises(PermissionError):
      self.actions().save_debug_report()
    self.assertFalse(self.report_root.exists() and any(self.report_root.iterdir()))

  def test_queue_stock_reset_writes_request_only(self):
    msg = self.actions().queue_stock_reset()
    self.assertIn("queued", msg.lower())
    self.assertTrue(self.params.get_bool("DoToggleResetStock"))
    # No reboot / manager side effects in this module.

  def test_shipping_defaults_real_table_keeps_shipped_on_features(self):
    """BLOCKER fix: assert against REAL registry/overlays — never a mocked map."""
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    from openpilot.system.bogpilot.toggle_reset import reset_defaults

    shipped = b.shipping_defaults()
    for key in ("GreenLightAlert", "LeadDepartingAlert", "AdjacentLeadsUI",
                "ScreenRecorder", "BlindSpotPath"):
      self.assertEqual(shipped[key], "1", key)
      self.assertEqual(shipped[key], BOGPILOT_PARAMS[key][2], key)
    # Stock column (used by "Reset to Stock") still turns them OFF — prove divergence.
    stock = reset_defaults()
    for key in ("GreenLightAlert", "LeadDepartingAlert", "AdjacentLeadsUI"):
      self.assertEqual(stock[key], "0", key)
      self.assertNotEqual(shipped[key], stock[key], key)
    self.assertEqual(shipped["AlertVolumeControl"], "0")
    self.assertIsNone(shipped["TuningLevel"])
    self.assertIsNone(shipped["TuningLevelConfirmed"])
    for key in b.ADOPTION_MARKERS:
      self.assertIn(key, shipped)
      self.assertIsNone(shipped[key], key)
    for key in ("DongleId", "CarVin", "SecOCKey", "CalibrationParams", "CarModel"):
      self.assertNotIn(key, shipped)

  def test_reset_bogpilot_defaults_applies_real_shipping_and_clears_markers(self):
    act = self.actions()

    def fake_backup(params, *, file_root, backup_root, reason):
      self.assertEqual(reason, "before-bogpilot-defaults-reset")
      (Path(backup_root) / "receipt.json").write_text("{}")
      return BackupReceipt()

    cleared = {}

    def fake_clear(directory=None):
      cleared["dir"] = str(directory)

    # Seed STOCK-OFF / adopted state that a buggy stock-reset would leave alone.
    for key in ("GreenLightAlert", "LeadDepartingAlert", "AdjacentLeadsUI",
                "ScreenRecorder", "BlindSpotPath"):
      self.params.values[key] = False
      self.params.known.add(key)
    self.params.values["TuningLevel"] = 2
    self.params.known.add("TuningLevel")
    for marker in b.ADOPTION_MARKERS:
      (self.file_root / marker).write_text("1")

    import openpilot.system.bogpilot.settings_backup as sb
    import openpilot.common.bogpilot_ap1_profile as ap1
    with patch.object(sb, "backup_settings", fake_backup), \
         patch.object(ap1, "clear_ap1_defaults_marker", fake_clear):
      msg = act.reset_bogpilot_defaults()

    self.assertIn("fresh-install", msg.lower())
    for key in ("GreenLightAlert", "LeadDepartingAlert", "AdjacentLeadsUI",
                "ScreenRecorder", "BlindSpotPath"):
      self.assertTrue(self.params.get_bool(key), key)
    self.assertNotIn("TuningLevel", self.params.values)
    for marker in b.ADOPTION_MARKERS:
      self.assertFalse((self.file_root / marker).exists(), marker)
    self.assertIn("dir", cleared)
    self.assertTrue((self.backup_root / "receipt.json").exists())

  def test_reset_bogpilot_defaults_refuses_without_backup(self):
    act = self.actions()
    self.params.values["GreenLightAlert"] = False  # would become ON on a successful shipping reset
    marker = self.file_root / b.ADOPTION_MARKERS[0]
    marker.write_text("1")

    def fake_backup(*args, **kwargs):
      return None

    import openpilot.system.bogpilot.settings_backup as sb
    with patch.object(sb, "backup_settings", fake_backup):
      with self.assertRaises(OSError):
        act.reset_bogpilot_defaults()
    self.assertFalse(self.params.get_bool("GreenLightAlert"))
    self.assertTrue(marker.exists())

  def test_pending_explanations_cover_forbidden_rows(self):
    self.assertIn("flash", b.PENDING["Flash Panda"].lower())
    self.assertIn("ignition", b.PENDING["Force Drive State"].lower())


if __name__ == "__main__":
  unittest.main()
