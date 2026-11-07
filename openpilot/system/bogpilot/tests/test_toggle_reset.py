"""Sandbox-only reset tests; no Params construction, Mac/VM/product data IO."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS, EXCLUDED_KEYS
from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
from openpilot.system.bogpilot.toggle_reset import (
  REQUEST_KEY, RESET_KEYS, FILE_RESET_KEYS, UNSET_KEYS, reset_defaults, reset_requested,
)


class TypedParams:
  """Strict in-memory 0.11.2 typed Params boundary, never backed by /data."""
  def __init__(self, values=None, unknown=()):
    self.known = set(BOGPILOT_PARAMS) | {REQUEST_KEY, "DongleId", "CalibrationParams", "GithubSshKeys"}
    self.known -= set(unknown)
    self.values = dict(values or {})
    self.calls = []
    self.fail = None

  def all_keys(self):
    return [k.encode() for k in self.known]

  def _check(self, k):
    assert k in self.known, k
    assert k not in FILE_ONLY_UI_KEYS, "file-only key reached Params"

  def get_bool(self, k):
    self._check(k)
    return self.values.get(k) is True

  def get(self, k):
    self._check(k)
    return self.values.get(k)

  def cpp2python(self, k, raw):
    self._check(k)
    typ = BOGPILOT_PARAMS.get(k, (None, "BOOL"))[1]
    return {"BOOL": lambda: raw == b"1", "INT": lambda: int(raw),
            "FLOAT": lambda: float(raw), "STRING": lambda: raw.decode(),
            "BYTES": lambda: raw}[typ]()

  def put(self, k, value, block=False):
    self._check(k)
    assert block
    if self.fail == k:
      self.fail = None
      raise OSError("injected failure")
    typ = BOGPILOT_PARAMS.get(k, (None, "STRING"))[1]
    expected = {"BOOL": bool, "INT": int, "FLOAT": float, "STRING": str, "BYTES": bytes}[typ]
    assert type(value) is expected, (k, type(value), expected)
    self.calls.append(("put", k))
    self.values[k] = value

  def remove(self, k):
    self._check(k)
    self.calls.append(("remove", k))
    self.values.pop(k, None)


class TestReset(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory(prefix="bogpilot-reset-test-")
    self.addCleanup(self.tmp.cleanup)
    self.files = Path(self.tmp.name) / "params_bogpilot"
    self.params = TypedParams({REQUEST_KEY: True})

  def reset(self, backup=lambda: "durable-test-receipt"):
    return reset_requested(self.params, self.files, backup=backup)

  def test_fresh_install_is_noop(self):
    self.params.values.clear()
    self.assertEqual(self.reset(backup=lambda: self.fail("unexpected backup")).status, "not_requested")
    self.assertFalse(self.files.exists())
    self.assertEqual(self.params.calls, [])

  def test_approved_reset_defaults(self):
    result = self.reset()
    self.assertEqual(result.status, "completed", result)
    p = self.params.values
    self.assertFalse(p["AlwaysOnLateral"])
    self.assertFalse(p["NudgelessLaneChange"])
    self.assertFalse(p["AlertVolumeControl"])
    for k in reset_defaults():
      if k.endswith("Volume"):
        self.assertEqual(p[k], 101)
    for k in UNSET_KEYS:
      self.assertNotIn(k, p)
      self.assertFalse((self.files / k).exists())
    self.assertEqual((self.files / "OffroadScreensaver").read_text(), "0")
    self.assertEqual((self.files / "DeveloperHUD").read_text(), "0")
    self.assertEqual((self.files / "SwapSpeedGraph").read_text(), "1")
    self.assertTrue(p["BorderMetrics"])
    self.assertFalse(p["CurveSpeedController"])  # stock column, not daily default
    self.assertEqual(self.params.calls[-1], ("remove", REQUEST_KEY))

  def test_scope_preserves_identity_auth_calibration_and_unknown(self):
    saved = {"DongleId": "test-only", "CalibrationParams": b"test-only", "GithubSshKeys": "test-only",
             "CarMake": "test-only", "KonikDongleId": "test-only", "WeatherToken": "test-only",
             "CalibratedLateralAcceleration": 1.9, "CalibrationProgress": 37,
             "CurvatureData": "test-only", "CarParamsPersistent": "test-only"}
    self.params.values.update(saved)
    self.files.mkdir()
    for k in ("UnknownSetting", "ShowUploadRate", "EnableICIntegration", "AP1DefaultsApplied", "DriveHistory"):
      (self.files / k).write_bytes(b"original")
    self.assertEqual(self.reset().status, "completed")
    for k, v in saved.items():
      self.assertEqual(self.params.values[k], v)
    for k in ("UnknownSetting", "ShowUploadRate", "EnableICIntegration", "AP1DefaultsApplied", "DriveHistory"):
      self.assertEqual((self.files / k).read_bytes(), b"original")
    self.assertFalse(RESET_KEYS & EXCLUDED_KEYS)

  def test_uncompiled_key_fallback_and_file_only_ownership(self):
    self.params = TypedParams({REQUEST_KEY: True}, unknown={"AlwaysOnLateral"})
    self.assertEqual(self.reset().status, "completed")
    self.assertEqual((self.files / "AlwaysOnLateral").read_text(), "0")
    for k in FILE_ONLY_UI_KEYS:
      self.assertTrue((self.files / k).exists())
      self.assertNotIn(k, self.params.values)
    self.assertFalse(any(k in FILE_ONLY_UI_KEYS for _, k in self.params.calls))

  def test_backup_missing_false_exception_never_changes_originals(self):
    for backup in (None, lambda: False, lambda: (_ for _ in ()).throw(OSError())):
      with self.subTest(backup=backup):
        self.params = TypedParams({REQUEST_KEY: True, "AlwaysOnLateral": True})
        before = dict(self.params.values)
        self.assertEqual(self.reset(backup=backup).status, "failed")
        self.assertEqual(self.params.values, before)
        self.assertEqual(self.params.calls, [])
        self.assertFalse(self.files.exists())

  def test_backup_precedes_all_changes(self):
    self.params.values["AlwaysOnLateral"] = True
    def backup():
      self.assertTrue(self.params.values["AlwaysOnLateral"])
      self.assertTrue(self.params.values[REQUEST_KEY])
      self.assertFalse(self.params.calls)
      return "receipt"
    self.assertEqual(self.reset(backup=backup).status, "completed")

  def test_second_boot_is_noop(self):
    self.assertEqual(self.reset().status, "completed")
    calls = list(self.params.calls)
    self.assertEqual(self.reset(backup=lambda: self.fail("backup repeated")).status, "not_requested")
    self.assertEqual(self.params.calls, calls)

  def test_typed_failure_rolls_back_and_retains_request(self):
    self.params.values.update({"AlwaysOnLateral": True, "ScreenTimeout": 60})
    self.files.mkdir()
    (self.files / "DeveloperHUD").write_bytes(b"on")
    before = dict(self.params.values)
    self.params.fail = "ScreenTimeout"
    result = self.reset()
    self.assertEqual(result.status, "failed")
    self.assertIn("rolled back", result.error)
    self.assertEqual(self.params.values, before)
    self.assertEqual((self.files / "DeveloperHUD").read_bytes(), b"on")
    self.assertEqual(self.reset().status, "completed")

  def test_file_failure_retains_request_and_rollback(self):
    from openpilot.system.bogpilot import toggle_reset
    write = toggle_reset._atomic_file
    def fail_once(path, content):
      if path.name == "OffroadScreensaver" and content == b"0":
        raise OSError("injected")
      return write(path, content)
    before = dict(self.params.values)
    with patch.object(toggle_reset, "_atomic_file", side_effect=fail_once):
      self.assertEqual(self.reset().status, "failed")
    self.assertEqual(self.params.values, before)

  def test_flag_clear_failure_rolls_back(self):
    original = self.params.remove
    def remove(k):
      if k == REQUEST_KEY:
        raise OSError("injected clear failure")
      original(k)
    before = dict(self.params.values)
    self.params.remove = remove
    result = self.reset()
    self.assertEqual(result.status, "failed")
    self.assertIn("clear request", result.error)
    self.assertEqual(self.params.values, before)

  def test_rollback_failure_requires_durable_backup(self):
    original = self.params.put
    self.params.values["AlwaysOnLateral"] = True
    def put(k, value, block=False):
      if k == "AlwaysOnLateral":
        raise OSError("persistent storage failure")
      original(k, value, block=block)
    self.params.put = put
    result = self.reset()
    self.assertEqual(result.status, "failed")
    self.assertIn("restore backup", result.error)
    self.assertTrue(self.params.values[REQUEST_KEY])

  def test_symlink_refused_without_touching_target(self):
    self.files.mkdir()
    target = Path(self.tmp.name) / "original"
    target.write_bytes(b"original")
    (self.files / "DeveloperHUD").symlink_to(target)
    self.assertEqual(self.reset().status, "failed")
    self.assertEqual(target.read_bytes(), b"original")
    self.assertEqual(self.params.calls, [])

  def test_registry_unknown_keys_are_not_implicitly_owned(self):
    with patch.dict(BOGPILOT_PARAMS, {"FutureSetting": ("PERSISTENT", "BOOL", "1", 0, "0")}):
      self.assertNotIn("FutureSetting", reset_defaults())
    self.assertNotIn("ShowUploadRate", FILE_RESET_KEYS)


if __name__ == "__main__":
  unittest.main()
