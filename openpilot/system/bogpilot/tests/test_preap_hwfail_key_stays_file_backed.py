"""TeslaRadarIgnoreHwFail is file-backed and must never be passed to C++ Params.

The committed libparams_c.so does not register it. Startup defaults and settings
backup must not raise UnknownKeyName when the key exists as a params_bogpilot file.
"""
import base64
from pathlib import Path

import pytest

from openpilot.system.bogpilot import settings_backup as sb

KEY = "TeslaRadarIgnoreHwFail"
ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "openpilot/common/libparams_c.so"


def test_key_absent_from_committed_libparams_so():
  assert LIB.is_file()
  assert LIB.read_bytes().count(KEY.encode()) == 0
  # siblings that share the file-backed store are also unregistered
  data = LIB.read_bytes()
  assert data.count(b"TeslaRadarEnabled") == 0
  assert data.count(b"TeslaHasIBooster") == 0


def test_file_toggle_and_backup_scope_list_the_key():
  from openpilot.common.bogpilot_toggles import FILE_TOGGLES
  assert KEY in FILE_TOGGLES
  assert FILE_TOGGLES[KEY][0] is False
  assert KEY in sb.FILE_KEYS
  from openpilot.system.bogpilot.toggle_reset import FILE_RESET_KEYS
  assert KEY not in FILE_RESET_KEYS  # backed up, never reset


def test_startup_defaults_and_backup_do_not_raise_unknown_key(tmp_path):
  """VM check with real Params: defaults + backup/restore never call libparams for this key."""
  from openpilot.common.params import Params, UnknownKeyName
  from openpilot.common.prefix import OpenpilotPrefix

  files = tmp_path / "params_bogpilot"
  files.mkdir()
  (files / KEY).write_text("1\n", encoding="utf-8")
  backups = tmp_path / "backups"

  try:
    with OpenpilotPrefix():
      params = Params()
      known = {k.decode() if isinstance(k, bytes) else k for k in params.all_keys()}
      assert KEY not in known
      with pytest.raises(UnknownKeyName):
        params.get(KEY)
      with pytest.raises(UnknownKeyName):
        params.get_bool(KEY)

      from openpilot.system.manager.bogpilot_startup import after_defaults, before_defaults
      before_defaults(params, file_root=files)
      after_defaults(params, file_root=files)

      result = sb.backup_settings(params, file_root=files, backup_root=backups, reason="test")
      assert result, getattr(result, "error", result)
      doc = sb.read_snapshot(result.path)
      assert KEY in doc["entries"]
      assert doc["entries"][KEY]["store"] == "file"
      raw = base64.b64decode(doc["entries"][KEY]["value"])
      # Restore is a file write, never Params.put (this key is not in all_keys).
      (files / KEY).write_bytes(raw)
      assert (files / KEY).read_bytes() == raw
      with pytest.raises(UnknownKeyName):
        params.put(KEY, raw, block=True)
  except (OSError, ImportError) as exc:
    pytest.skip(f"real Params not usable on this host: {type(exc).__name__}")
