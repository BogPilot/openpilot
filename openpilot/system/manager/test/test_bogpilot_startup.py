"""Synthetic lifecycle/manager smoke. Hardware, registration, IPC and Params are mocks.

Real manager.py, process.py, process_config.py, policy and lifecycle modules are imported.
No Process.start, daemon launcher, network registration or hardware daemon may run.
"""
import importlib
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import pytest

from openpilot.system.manager import bogpilot_startup as lifecycle


class MemoryParams:
  """Strict file-only exclusion with in-memory persistence across manager restarts."""
  def __init__(self):
    self.values = {}
    self.history = []

  def all_keys(self):
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    return list(set(BOGPILOT_PARAMS) | {"CarModel", "IsMetric", "CarParamsPersistent", "RecordFrontLock", "DoToggleResetStock"})

  def get(self, key, *args, **kwargs):
    from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
    assert key not in FILE_ONLY_UI_KEYS, key
    self.history.append(("get", key))
    return self.values.get(key)

  def get_bool(self, key):
    return self.get(key) in (True, "1", b"1")

  def put(self, key, value, **kwargs):
    from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
    assert key not in FILE_ONLY_UI_KEYS, key
    self.history.append(("put", key))
    self.values[key] = value

  def put_bool(self, key, value, **kwargs):
    self.put(key, value, **kwargs)

  def clear_all(self, flag):
    self.history.append(("clear", flag))

  def get_default_value(self, key):
    return None


def test_missing_optional_module_is_nonfatal(monkeypatch, tmp_path):
  monkeypatch.setattr(lifecycle.importlib, "import_module", MagicMock(side_effect=ModuleNotFoundError))
  p = MemoryParams()
  result = lifecycle.before_defaults(p, file_root=tmp_path)
  assert result.errors and not p.values and not list(tmp_path.iterdir())


def test_no_request_path_does_not_call_backup(tmp_path):
  backup = MagicMock(side_effect=AssertionError("no speculative backup/reset"))
  def reset(params, directory, *, backup):
    assert not params.get_bool("DoToggleResetStock")
    return NS(status="not_requested")
  result = lifecycle.before_defaults(MemoryParams(), file_root=tmp_path, backup=backup, reset=reset)
  assert result.events == ["reset:not_requested"]
  backup.assert_not_called()


def test_reset_backup_order_contract(tmp_path):
  # Injected transaction fixture, NOT validation of absent peer backup/reset code.
  events = []
  p = MemoryParams()
  p.values["DoToggleResetStock"] = True
  p.values["OwnerChoice"] = "original"
  def backup():
    events.append("durable-backup")
    return NS(path=tmp_path / "receipt")
  def reset(params, directory, *, backup):
    if params.get_bool("DoToggleResetStock"):
      assert backup()
      events.append("reset")
      params.put("OwnerChoice", "default")
      params.put_bool("DoToggleResetStock", False)
    return NS(status="done")
  result = lifecycle.before_defaults(p, file_root=tmp_path, backup=backup, reset=reset)
  assert not result.errors and events == ["durable-backup", "reset"]
  lifecycle.before_defaults(p, file_root=tmp_path, backup=backup, reset=reset)
  assert events == ["durable-backup", "reset"]  # manager restart is not a reset request


def test_partial_failure_keeps_originals_and_request(tmp_path):
  p = MemoryParams()
  p.values.update(DoToggleResetStock=True, OwnerChoice="original")
  original = dict(p.values)
  def backup():
    raise OSError("optional storage unavailable")
  def reset(params, directory, *, backup):
    backup()
    raise AssertionError("must not reach destructive operation")
  result = lifecycle.before_defaults(p, file_root=tmp_path, backup=backup, reset=reset)
  assert result.errors == ["reset: OSError"]
  assert p.values == original


def test_profile_real_repeated_boot_preserves_choices(monkeypatch, tmp_path):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  p = MemoryParams()
  p.values.update(CarModel="TESLA_AP1_MODELS", AlwaysOnLateral=False,
                  NudgelessLaneChange=False, EngageVolume=53)
  first = lifecycle.after_defaults(p, file_root=tmp_path)
  assert not first.errors
  assert (tmp_path / "AP1DefaultsApplied").exists()
  assert p.values["EngageVolume"] == 53
  original = dict(p.values)
  assert lifecycle.after_defaults(p, file_root=tmp_path).events[-1:] == ["ap1:0"]
  assert p.values == original
  assert p.values["AlwaysOnLateral"] in (False, "0")
  assert "TuningLevel" not in p.values and "TuningLevelConfirmed" not in p.values


def test_profile_non_ap1_no_writes(tmp_path):
  p = MemoryParams()
  assert lifecycle.after_defaults(p, file_root=tmp_path).events[-1:] == ["ap1:0"]
  assert not p.values and not list(tmp_path.iterdir())


def test_profile_optional_storage_unavailable(tmp_path):
  p = MemoryParams()
  p.values["CarModel"] = "TESLA_AP1_MODELS"
  unavailable = tmp_path / "regular-file"
  unavailable.write_text("not a directory")
  # Profile's established never-raise API absorbs optional store errors.
  lifecycle.after_defaults(p, file_root=unavailable)
  assert unavailable.read_text() == "not a directory"


def test_policy_and_sounds():
  from openpilot.common.bogpilot_shipping_defaults import PARAM_OVERRIDES, AP1_PARAM_REMOVE
  from openpilot.common.bogpilot_alert_volumes import FROGPILOT_VOLUME_DEFAULTS, resolve_alert_gain
  from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
  assert PARAM_OVERRIDES["AlwaysOnLateral"][0] == "0"
  assert PARAM_OVERRIDES["NudgelessLaneChange"][0] == "0"
  assert {"TuningLevel", "TuningLevelConfirmed"} <= AP1_PARAM_REMOVE
  assert {"RedesignUI", "BSMFlameTracks", "SwapSpeedGraph", "DeveloperHUD", "HideAccelGraph"} <= FILE_ONLY_UI_KEYS
  assert FROGPILOT_VOLUME_DEFAULTS["AlertVolumeControl"] == "0"
  for key, value in FROGPILOT_VOLUME_DEFAULTS.items():
    if key != "AlertVolumeControl":
      assert value == "101"
      assert resolve_alert_gain(alert_volume_control=True, percent=101, ambient=0.7, key=key) == 0.7


@contextmanager
def imported_manager(tmp_path, params):
  """Import real manager/process configuration with explicit platform boundary mocks."""
  def module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    return m
  flags = NS(CLEAR_ON_MANAGER_START=4, CLEAR_ON_ONROAD_TRANSITION=8,
             CLEAR_ON_OFFROAD_TRANSITION=16, CLEAR_ON_IGNITION_ON=128, DEVELOPMENT_ONLY=64)
  fake_log = MagicMock()
  hw = MagicMock()
  metadata = NS(release_channel=False, tested_channel=False, channel="sandbox",
                openpilot=NS(version="smoke", git_commit="sandbox", git_commit_date="sandbox",
                             git_origin="sandbox", git_normalized_origin="sandbox", is_dirty=True))
  boundaries = {
    "openpilot.cereal": module("openpilot.cereal", log=fake_log),
    "openpilot.cereal.messaging": module("openpilot.cereal.messaging"),
    "opendbc": module("opendbc"), "opendbc.car": module("opendbc.car"),
    "opendbc.car.structs": module("opendbc.car.structs", car=NS(CarParams=object)),
    "setproctitle": module("setproctitle", setproctitle=MagicMock()),
    "openpilot.common.params": module("openpilot.common.params", Params=lambda: params, ParamKeyFlag=flags),
    "openpilot.common.hardware": module("openpilot.common.hardware", HARDWARE=hw, PC=True, COMMA_HARDWARE=False),
    "openpilot.common.hardware.hw": module("openpilot.common.hardware.hw", Paths=NS(shm_path=lambda: str(tmp_path / "shm"))),
    "openpilot.common.swaglog": module("openpilot.common.swaglog", cloudlog=MagicMock(), add_file_handler=MagicMock()),
    "openpilot.common.text_window": module("openpilot.common.text_window", TextWindow=MagicMock()),
    "openpilot.common.version": module("openpilot.common.version", get_build_metadata=lambda: metadata),
    "openpilot.common.utils": module("openpilot.common.utils", atomic_write=MagicMock()),
    "openpilot.system.manager.helpers": module("openpilot.system.manager.helpers", unblock_stdout=MagicMock(), save_bootlog=MagicMock()),
    "openpilot.system.athena.registration": module("openpilot.system.athena.registration", register=MagicMock(return_value="sandbox"), UNREGISTERED_DONGLE_ID="sandbox-unregistered"),
  }
  actual = ["openpilot.system.manager.manager", "openpilot.system.manager.process", "openpilot.system.manager.process_config"]
  saved = {k: sys.modules.pop(k) for k in actual if k in sys.modules}
  try:
    with patch.dict(sys.modules, boundaries), patch.dict(os.environ, {"BOGPILOT_PARAMS_DIR": str(tmp_path / "params_bogpilot")}):
      manager = importlib.import_module(actual[0])
      process = importlib.import_module(actual[1])
      # Any accidental real daemon launch is a hard error, not a fake success.
      with patch.object(process.Process, "start", side_effect=AssertionError("hardware launch forbidden")), \
           patch.object(process.subprocess, "Popen", side_effect=AssertionError("daemon launch forbidden")):
        yield manager, process
  finally:
    for k in actual:
      sys.modules.pop(k, None)
    sys.modules.update(saved)


def test_actual_manager_init_order_and_restart(tmp_path):
  p = MemoryParams()
  p.get_default_value = lambda key: False if key == "IsMetric" else None
  with imported_manager(tmp_path, p) as (manager, process):
    def before(params):
      assert len([h for h in params.history if h[0] == "clear"]) == 4
      params.history.append(("before", None))
      return lifecycle.StartupResult()
    def after(params, **kwargs):
      assert ("before", None) in params.history
      params.history.append(("after", None))
      return lifecycle.StartupResult()
    with patch.object(manager, "before_defaults", before), patch.object(manager, "after_defaults", after):
      manager.manager_init()
    assert p.history.index(("before", None)) < p.history.index(("put", "IsMetric")) < p.history.index(("after", None)) < p.history.index(("put", "Version"))
    assert all(proc.proc is None for proc in manager.managed_processes.values())
    # stop then re-init: cleanup is real, no process has ever been started.
    manager.manager_cleanup()
    p.history.clear()
    with patch.object(manager, "before_defaults", before), patch.object(manager, "after_defaults", after):
      manager.manager_init()
    assert p.values["Version"] == "smoke"


def test_actual_process_config_and_manager_real_hooks(tmp_path):
  p = MemoryParams()
  p.values["CarModel"] = "TESLA_AP1_MODELS"
  with imported_manager(tmp_path, p) as (manager, process):
    manager.manager_init()
    assert "plannerd" in manager.managed_processes and "soundd" in manager.managed_processes
    assert manager.managed_processes["plannerd"].module == "openpilot.selfdrive.controls.plannerd"
    cp = NS(notCar=False)
    config = importlib.import_module("openpilot.system.manager.process_config")
    assert config.only_offroad(False, p, cp) and not config.only_offroad(True, p, cp)
    assert config.only_onroad(True, p, cp) and not config.only_onroad(False, p, cp)
    # Evaluate actual scheduling predicates; do not call ensure_running or start.
    for proc in manager.managed_processes.values():
      if proc.enabled:
        assert isinstance(proc.should_run(False, p, cp), bool)
        assert isinstance(proc.should_run(True, p, cp), bool)
    manager.manager_cleanup()
  assert (tmp_path / "params_bogpilot" / "AP1DefaultsApplied").exists()


def test_peer_reset_runtime_when_present(tmp_path):
  try:
    reset = importlib.import_module("openpilot.system.bogpilot.toggle_reset")
  except ModuleNotFoundError:
    pytest.skip("w6 reset module not assembled: injected contract tests are not peer runtime validation")
  p = MemoryParams()
  assert not lifecycle.before_defaults(p, file_root=tmp_path, reset=reset.reset_requested).errors


def test_stock_reset_suppresses_profile_across_restarts(tmp_path):
  p = MemoryParams()
  p.values.update(CarModel="TESLA_AP1_MODELS", DoToggleResetStock=True)
  def reset(params, directory, *, backup):
    assert backup()
    assert (directory / "AP1StockReset1").exists()  # intent durable before mutation
    params.values.pop("DoToggleResetStock")
    return NS(status="completed")
  result = lifecycle.before_defaults(p, file_root=tmp_path, backup=lambda: object(), reset=reset)
  assert result.profile_suppressed
  assert lifecycle.after_defaults(p, file_root=tmp_path, startup=result).events[-1] == "ap1:suppressed-stock-reset"
  assert lifecycle.after_defaults(p, file_root=tmp_path).events[-1] == "ap1:suppressed-stock-reset"
  assert not (tmp_path / "AP1DefaultsApplied").exists()


def test_failed_backup_has_no_intent_marker_or_profile_replay(tmp_path):
  p = MemoryParams()
  p.values.update(CarModel="TESLA_AP1_MODELS", DoToggleResetStock=True)
  def reset(params, directory, *, backup):
    assert not backup()
    return NS(status="failed", error="backup failed")
  result = lifecycle.before_defaults(p, file_root=tmp_path, backup=lambda: None, reset=reset)
  assert result.errors and result.profile_suppressed
  lifecycle.after_defaults(p, file_root=tmp_path, startup=result)
  assert not (tmp_path / "AP1StockReset1").exists()
  assert not (tmp_path / "AP1DefaultsApplied").exists()
  assert p.values == {"CarModel": "TESLA_AP1_MODELS", "DoToggleResetStock": True}


def test_backup_adapter_rejects_truthy_failure(monkeypatch, tmp_path):
  snapshots = []
  def snapshot(params, directory, destination, *, reason):
    snapshots.append(reason)
    return NS(success=False)  # object is truthy, but must not authorize reset
  def reset(params, directory, *, backup):
    assert not backup()
    return NS(status="failed", error="backup failed")
  module = NS(backup_settings=snapshot)
  monkeypatch.setattr(lifecycle.importlib, "import_module", lambda name: module)
  result = lifecycle.before_defaults(MemoryParams(), file_root=tmp_path, cache_root=tmp_path / "cache", reset=reset)
  assert snapshots == ["boot", "pre-reset"]
  assert not (tmp_path / "AP1StockReset1").exists()
  assert result.errors == ["reset: backup failed"]


def test_screensaver_peer_migration_when_present(monkeypatch, tmp_path):
  from openpilot.common import bogpilot_toggles
  if not hasattr(bogpilot_toggles, "migrate_screensaver_default_off"):
    pytest.skip("w8 migration/default OFF not assembled")
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  (tmp_path / "OffroadScreensaver").write_text("1")
  lifecycle.after_defaults(MemoryParams(), file_root=tmp_path)
  assert (tmp_path / "OffroadScreensaver").read_text().strip() == "0"
  (tmp_path / "OffroadScreensaver").write_text("1")
  lifecycle.after_defaults(MemoryParams(), file_root=tmp_path)
  assert (tmp_path / "OffroadScreensaver").read_text().strip() == "1"
  assert bogpilot_toggles.FILE_TOGGLES["OffroadScreensaver"][0] is False
