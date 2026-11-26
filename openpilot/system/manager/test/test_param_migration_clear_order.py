"""Pre-rename (FrogPilot-era) values must be carried over before manager_init's clear_all deletes them.

The old key names are no longer registered, so clear_all treats their files as unknown and unlinks them
(common/params.cc clearAll). The copy to the new BogPilot* names has to happen first.
"""
import json
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.system.bogpilot import legacy_migration as lm
from openpilot.system.manager import bogpilot_startup as lifecycle
from openpilot.system.manager.test.test_bogpilot_startup import imported_manager

# Param key names (not secrets), built from parts like the migration table does.
OLD_TOKEN = "Frog" + "PilotApi" + "Token"
NEW_TOKEN = "Bog" + "PilotApi" + "Token"

# ParamKeyFlag values (common/params.py) and the extra registered keys manager_init touches.
FLAG_BITS = {"PERSISTENT": 0x02, "CLEAR_ON_MANAGER_START": 0x04, "CLEAR_ON_ONROAD_TRANSITION": 0x08,
             "CLEAR_ON_OFFROAD_TRANSITION": 0x10, "DEVELOPMENT_ONLY": 0x40, "CLEAR_ON_IGNITION_ON": 0x80,
             "DONT_LOG": 0x0}
CORE_KEYS = ("Version", "GitCommit", "GitCommitDate", "GitBranch", "GitRemote", "IsTestedBranch",
             "IsReleaseBranch", "HardwareSerial", "RecordFrontLock", "RecordFront", "DoToggleResetStock")


def _flags(key: str) -> int:
  row = BOGPILOT_PARAMS.get(key)
  if row is None:
    return FLAG_BITS["PERSISTENT"]
  bits = 0
  for name in row[0].split("|"):
    bits |= FLAG_BITS[name.strip()]
  return bits


class ClearingDirParams:
  """Params-like object on a real directory with clearAll's rule: unlink unknown files and files with the flag."""
  def __init__(self, root: Path):
    self.root = root
    root.mkdir(parents=True, exist_ok=True)
    self.known = set(BOGPILOT_PARAMS) | set(CORE_KEYS)
    self.fail_put = set()

  def get_param_path(self, key=""):
    return str(self.root / key)

  def all_keys(self):
    return [k.encode() for k in sorted(self.known)]

  def _check(self, key):
    if key not in self.known:
      raise KeyError("unknown param")
    return key

  def get(self, key, *a, **k):
    self._check(key)
    p = self.root / key
    if not p.exists():
      return None
    data = p.read_bytes()
    row = BOGPILOT_PARAMS.get(key)
    return data if row is not None and row[1] == "BYTES" else data.decode()

  def get_bool(self, key, *a, **k):
    return self.get(key) in ("1", b"1")

  def put(self, key, value, block=False):
    self._check(key)
    if key in self.fail_put:
      raise OSError("disk")
    if isinstance(value, bool):
      value = "1" if value else "0"
    (self.root / key).write_bytes(value if isinstance(value, bytes) else str(value).encode())

  def put_bool(self, key, value, block=False):
    self.put(key, "1" if value else "0", block)

  def get_default_value(self, key):
    row = BOGPILOT_PARAMS.get(key)
    return row[2] if row is not None else None

  def clear_all(self, flag):
    for p in self.root.iterdir():
      if p.is_dir():
        continue
      if p.name not in self.known or (_flags(p.name) & int(flag)):
        p.unlink()


def _secret() -> str:
  return "test-" + uuid.uuid4().hex


def _boot(tmp_path, params):
  """Run the real manager_init with the real rename migration; backup/reset and post-default hooks stubbed."""
  def before(p):
    return lifecycle.before_defaults(p, backup=lambda reason: None, reset=lambda *a, **k: NS(status="none"))
  with imported_manager(tmp_path, params) as (manager, _process):
    with patch.object(manager, "before_defaults", before), \
         patch.object(manager, "after_defaults", lambda p, **k: lifecycle.StartupResult()):
      manager.manager_init()
      return manager


def test_old_key_only_in_params_d_is_migrated_before_clear(tmp_path):
  d = tmp_path / "d"
  params = ClearingDirParams(d)
  secret = _secret()
  (d / OLD_TOKEN).write_text(secret)
  (d / "FrogPilotDrives").write_text("42")
  (d / "FrogPilotKilometers").write_text("123.5")
  (d / "FrogPilotTelemetry").write_text("1")
  (d / "FrogPilotStats").write_text(json.dumps({"FrogPilotDrives": 7, "Engages": 3}))
  (d / "FrogPilotCarParamsPersistent").write_bytes(b"\x00\x01\xffcp")
  _boot(tmp_path, params)
  assert (d / NEW_TOKEN).read_text() == secret
  assert (d / "BogPilotDrives").read_text() == "42"
  assert float((d / "BogPilotKilometers").read_text()) == 123.5
  assert (d / "BogPilotTelemetry").read_text() == "1"  # migrated value, not the registered default "0"
  assert json.loads((d / "BogPilotStats").read_text()) == {"BogPilotDrives": 7, "Engages": 3}
  assert (d / "BogPilotCarParamsPersistent").read_bytes() == b"\x00\x01\xffcp"
  # the old names are still unregistered, so clear_all still removed them after the copy
  assert not any(p.name.startswith("FrogPilot") for p in d.iterdir())
  assert lm.migration_done(tmp_path / "params_bogpilot")


def test_existing_bogpilot_value_wins(tmp_path):
  d = tmp_path / "d"
  params = ClearingDirParams(d)
  old_secret, new_secret = _secret(), _secret()
  (d / OLD_TOKEN).write_text(old_secret)
  (d / NEW_TOKEN).write_text(new_secret)
  (d / "FrogPilotDrives").write_text("42")
  (d / "BogPilotDrives").write_text("7")
  _boot(tmp_path, params)
  assert (d / NEW_TOKEN).read_text() == new_secret
  assert (d / "BogPilotDrives").read_text() == "7"


def test_unknown_junk_and_clear_on_start_keys_are_still_cleared(tmp_path):
  d = tmp_path / "d"
  params = ClearingDirParams(d)
  (d / "SomeOtherForkLeftover").write_text("1")
  (d / "FrogPilotToggles").write_text("{}")  # was CLEAR_ON_MANAGER_START in 0.9.7: not carried over
  (d / "FrogPilotTuningLevels").write_text("{}")
  (d / "BogPilotToggles").write_text("{}")  # CLEAR_ON_MANAGER_START now too
  (d / "BogPilotDrives").write_text("3")  # PERSISTENT: kept
  _boot(tmp_path, params)
  names = {p.name for p in d.iterdir()}
  assert "SomeOtherForkLeftover" not in names
  assert "FrogPilotToggles" not in names and "FrogPilotTuningLevels" not in names
  assert "BogPilotToggles" not in names and "BogPilotTuningLevels" not in names
  assert (d / "BogPilotDrives").read_text() == "3"


def test_secret_never_reaches_logs_or_stdout(tmp_path, capfd, caplog):
  caplog.set_level(logging.DEBUG)
  d = tmp_path / "d"
  params = ClearingDirParams(d)
  params.fail_put = {NEW_TOKEN}  # force the error path, which is the one that logs
  secret = _secret()
  (d / OLD_TOKEN).write_text(secret)
  with imported_manager(tmp_path, params) as (manager, _process):
    with patch.object(manager, "before_defaults", lambda p: lifecycle.before_defaults(
                        p, backup=lambda reason: None, reset=lambda *a, **k: NS(status="none"))), \
         patch.object(manager, "after_defaults", lambda p, **k: lifecycle.StartupResult()):
      manager.manager_init()
    logged = str(manager.cloudlog.mock_calls)
  out, err = capfd.readouterr()
  for text in (logged, out, err, caplog.text):
    assert secret not in text
  # the failure was reported, by key name and exception type only
  assert f"{OLD_TOKEN}: OSError" in logged


def _real_params(root: Path):
  try:
    from openpilot.common.params import Params, ParamKeyFlag
    params = Params(str(root))
    params.get_param_path()
  except (ImportError, OSError, AttributeError) as exc:
    pytest.skip(f"native params library not loadable here: {type(exc).__name__}")
  return params, ParamKeyFlag


def test_real_params_clear_all_after_pre_clear_migration(tmp_path):
  params, flag = _real_params(tmp_path / "op")
  d = Path(params.get_param_path())
  fileroot = tmp_path / "params_bogpilot"
  secret = _secret()
  (d / OLD_TOKEN).write_text(secret)
  (d / "FrogPilotDrives").write_text("42")
  (d / "SomeOtherForkLeftover").write_text("1")
  res = lifecycle.before_clear(params, file_root=fileroot)
  assert not res.errors, res.errors
  params.clear_all(flag.CLEAR_ON_MANAGER_START)
  assert params.get(NEW_TOKEN) == secret
  assert params.get("BogPilotDrives") == 42
  assert not (d / OLD_TOKEN).exists() and not (d / "SomeOtherForkLeftover").exists()
  assert secret not in " ".join(res.events + res.errors)
