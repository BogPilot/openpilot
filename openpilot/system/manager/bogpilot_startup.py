"""Optional BogPilot settings lifecycle. Never launch processes or reset on our own.

The manager owns ordering; backup/reset own transactions and policy. Missing optional
modules are reported, not fatal. Storage failures must never turn into manager loops.
"""
from __future__ import annotations

import importlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class StartupResult:
  events: list[str] = field(default_factory=list)
  errors: list[str] = field(default_factory=list)
  profile_suppressed: bool = False


def _optional(name: str, result: StartupResult):
  try:
    return importlib.import_module(name)
  except Exception as exc:
    result.errors.append(f"{name}: {type(exc).__name__}")
    return None


def before_defaults(params, *, file_root: Path | None = None,
                    backup: Callable | None = None, reset: Callable | None = None,
                    cache_root: Path | None = None) -> StartupResult:
  """After manager transient clears, before defaults. No reset implementation here.

  reset_requested MUST inspect its own explicit request and require a durable backup
  receipt before mutation. Never substitute a truthy sentinel for a missing backup.
  Called again on manager restart; transaction idempotency belongs to the modules.
  """
  result = StartupResult()
  directory = Path(file_root or os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))
  try:
    known = {k.decode() if isinstance(k, bytes) else k for k in params.all_keys()}
    result.profile_suppressed = "DoToggleResetStock" in known and params.get_bool("DoToggleResetStock")
  except Exception:
    # Unknown native key: no speculative reset/profile state changes.
    pass

  # Optional adapter contract for w5. No restore-from-cache path is authorized:
  # current persistent settings are authoritative on every ordinary manager boot.
  backup_module = None
  if backup is None:
    module = _optional("openpilot.system.bogpilot.settings_backup", result)
    backup_module = module
    snapshot = getattr(module, "backup_settings", None)
    if snapshot is not None:
      destination = Path(cache_root or os.getenv("BOGPILOT_BACKUP_DIR", "/cache/bogpilot/settings-backups"))
      def snapshot_receipt(reason):
        outcome = snapshot(params, file_root=directory, backup_root=destination, reason=reason)
        # w5 BackupResult.success is true only after durable snapshot publication.
        # Do not accept a truthy failed-result wrapper.
        return outcome if getattr(outcome, "success", False) is True else None
      try:
        result.events.append("backup:boot" if snapshot_receipt("startup") else "backup:failed")
      except Exception as exc:
        result.errors.append(f"backup: {type(exc).__name__}")
      backup = lambda: snapshot_receipt("before-reset")

  def guarded_backup():
    receipt = backup()
    if not receipt:
      return None
    # Persist stock-selection intent AFTER durable originals, BEFORE reset can
    # clear its request. Survives power loss / manager restart at that boundary.
    # A marker IO failure raises before reset mutates any setting.
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".stock-reset-", dir=directory)
    try:
      with os.fdopen(fd, "w") as f:
        f.write("1\n")
        f.flush()
        os.fsync(f.fileno())
      os.replace(temporary, directory / "AP1StockReset1")
      parent_fd = os.open(directory, os.O_RDONLY)
      try:
        os.fsync(parent_fd)
      finally:
        os.close(parent_fd)
    finally:
      Path(temporary).unlink(missing_ok=True)
    return receipt

  if reset is None:
    module = _optional("openpilot.system.bogpilot.toggle_reset", result)
    reset = getattr(module, "reset_requested", None)
    if reset is not None and backup_module is not None and result.profile_suppressed:
      try:
        # Backup excludes private/freeform/runtime settings. Fail closed on scope
        # drift rather than allowing reset to erase keys absent from the archive.
        from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
        covered = set(backup_module.FILE_KEYS) | {
          k for k in backup_module.SETTING_KEYS
          if k in BOGPILOT_PARAMS and BOGPILOT_PARAMS[k][0] == "PERSISTENT"
        }
        if set(module.reset_defaults()) - covered:
          raise ValueError("reset scope exceeds backup")
      except Exception:
        result.errors.append("reset: backup scope mismatch")
        result.profile_suppressed = True
        reset = None
  try:
    if reset is not None:
      outcome = reset(params, directory, backup=guarded_backup if backup is not None else None)
      result.events.append(f"reset:{outcome.status}")
      if outcome.status == "failed":
        result.errors.append(f"reset: {outcome.error}")
      result.profile_suppressed |= outcome.status in ("completed", "failed")
  except Exception as exc:
    # Keep the request and original settings under the reset module's transaction.
    result.errors.append(f"reset: {type(exc).__name__}")
  return result


DEVICE_STOCK_MARKER = "DeviceStockDefaults1"
# key -> (compiled 0.9.7 default, STOCK value). Compiled defaults live in the precompiled libparams (not changed
# in this build), so fresh installs are moved to stock once; any value the user already changed is left alone.
DEVICE_STOCK_DEFAULTS = {"DeviceShutdown": ("9", "33"), "ScreenTimeoutOnroad": ("30", "10")}


def _device_stock_defaults(params, directory: Path) -> list[str]:
  marker = directory / DEVICE_STOCK_MARKER
  if marker.exists():
    return []
  changed = []
  for key, (compiled, stock) in DEVICE_STOCK_DEFAULTS.items():
    raw = params.get(key)
    if isinstance(raw, bytes):
      raw = raw.decode(errors="ignore")
    raw = None if raw is None else str(raw).strip()
    if raw in (None, "", compiled):
      params.put(key, stock)
      changed.append(key)
  directory.mkdir(parents=True, exist_ok=True)
  marker.write_text("1\n")
  return changed


def after_defaults(params, *, file_root: Path | None = None, startup: StartupResult | None = None) -> StartupResult:
  """After native registered defaults, before metadata/registration/process startup.

  Shared ParamStore handles typed keys vs file-only keys. The AP1 migration has
  its existing persistent markers, so stop/restart is not an implicit toggle reset.
  """
  result = StartupResult()
  directory = Path(file_root or os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))
  try:
    from openpilot.common import bogpilot_toggles
    migrate = getattr(bogpilot_toggles, "migrate_screensaver_default_off", None)
    if migrate is not None:
      migrate(directory=directory)
      result.events.append("screensaver:migrated")
    else:
      result.events.append("screensaver:dependency-missing")
  except Exception as exc:
    result.errors.append(f"screensaver: {type(exc).__name__}")
  try:
    from openpilot.system.bogpilot.drive_tracking import ensure_stats_stores
    status = ensure_stats_stores(params, history_path=directory / "DriveHistory")
    result.events.append(
      f"drive-stats:{status['stats']}/{status['history']}")
  except Exception as exc:
    result.errors.append(f"drive-stats: {type(exc).__name__}")
  try:
    changed = _device_stock_defaults(params, directory)
    result.events.append(f"device-stock:{len(changed)}")
  except Exception as exc:
    result.errors.append(f"device-stock: {type(exc).__name__}")
  if (startup is not None and startup.profile_suppressed) or (directory / "AP1StockReset1").exists():
    result.events.append("ap1:suppressed-stock-reset")
    return result
  try:
    from openpilot.common.bogpilot_ap1_profile import apply_ap1_defaults_once
    changed = apply_ap1_defaults_once(params, bogpilot_dir=directory)
    result.events.append(f"ap1:{len(changed)}")
  except Exception as exc:
    result.errors.append(f"ap1: {type(exc).__name__}")
  return result
