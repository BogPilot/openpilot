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


def _rename_migration(params, directory: Path, result: StartupResult) -> None:
  """One-time carry-over of values saved under the pre-rename key names. Never raises, never blocks boot.

  Must run before registered defaults are applied (a default would make the new key look already set).
  Only key names and exception types are reported; values (one is an API token) are never logged.
  """
  migration = _optional("openpilot.system.bogpilot.legacy_migration", result)
  migrate = getattr(migration, "migrate_legacy_params", None)
  done = getattr(migration, "migration_done", None)
  if migrate is not None and done is not None:
    try:
      if not done(directory):
        moved = migrate(params, file_root=directory)
        if moved["migrated"]:
          result.events.append(f"rename-migration:{len(moved['migrated'])}")
        result.errors.extend(f"rename-migration: {e}" for e in moved["errors"])
    except Exception as exc:
      result.errors.append(f"rename-migration: {type(exc).__name__}")


def _tap_speed_migration(params, directory: Path, result: StartupResult) -> None:
  """One-time Standstill Tap Speed carry-over, whole mph (AP1TapFromZeroMph) -> m/s (AP1TapFromZeroMs).

  Same placement rule as the rename carry-over: before clear_all (the old key is no longer registered, so clear_all
  deletes its file) and before registered defaults (the new key's 6.7056 default would look already set).
  """
  migration = _optional("openpilot.system.bogpilot.legacy_migration", result)
  migrate = getattr(migration, "migrate_tap_from_zero_ms", None)
  done = getattr(migration, "tap_speed_migration_done", None)
  if migrate is not None and done is not None:
    try:
      if not done(directory):
        moved = migrate(params, file_root=directory)
        if moved["status"] == "migrated":
          result.events.append("tap-speed-migration:1")
        result.errors.extend(f"tap-speed-migration: {e}" for e in moved["errors"])
    except Exception as exc:
      result.errors.append(f"tap-speed-migration: {type(exc).__name__}")


def before_clear(params, *, file_root: Path | None = None) -> StartupResult:
  """Before manager_init's clear_all. Only the rename carry-over runs here.

  The pre-rename FrogPilot* names (BogPilot 0.9.7 / FrogPilot key names) are not registered keys any more, so
  clear_all unlinks their files under the params dir as unknown. Copy them to the BogPilot* names first. The
  old names are read as plain files by the migration and are never registered or written.
  """
  result = StartupResult()
  directory = Path(file_root or os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))
  _rename_migration(params, directory, result)
  _tap_speed_migration(params, directory, result)
  return result


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
  # Normally already done by before_clear; this pass still serves values kept only under the BogPilot file
  # store, and retries if the pre-clear pass reported an error.
  _rename_migration(params, directory, result)
  _tap_speed_migration(params, directory, result)
  try:
    known = {k.decode() if isinstance(k, bytes) else k for k in params.all_keys()}
    result.profile_suppressed = "DoToggleResetStock" in known and params.get_bool("DoToggleResetStock")
  except Exception:
    # Unknown native key: no speculative reset/profile state changes.
    pass

  # Optional adapter contract for the settings backup. No restore-from-cache path is authorized:
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
        # BackupResult.success is true only after durable snapshot publication.
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
  # First-install Experimental Mode defaults (starts in Chill; confirmed while FRESH_INSTALL_CONFIRM_EXPERIMENTAL).
  # Must run before manager_init writes the registered defaults: the fresh-install check reads HasAcceptedTerms
  # unset, and that loop is what sets it. Upgrades and explicit values are never changed. No event is recorded.
  # A pending, failed or partial toggle reset is never a fresh install: its originals must stay untouched.
  if result.profile_suppressed or any(e.startswith("reset") for e in result.errors):
    return result
  fresh = _optional("openpilot.common.bogpilot_fresh_defaults", result)
  apply_fresh = getattr(fresh, "apply_fresh_install_defaults", None)
  if apply_fresh is not None:
    try:
      apply_fresh(params)
    except Exception as exc:
      result.errors.append(f"fresh-defaults: {type(exc).__name__}")
  return result



def after_defaults(params, *, file_root: Path | None = None, startup: StartupResult | None = None) -> StartupResult:
  """After native registered defaults, before metadata/registration/process startup.

  Shared ParamStore handles typed keys vs file-only keys. The AP1 migration has
  its existing persistent markers, so stop/restart is not an implicit toggle reset.
  """
  result = StartupResult()
  directory = Path(file_root or os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))
  try:
    from openpilot.system.bogpilot.boot_logo import install_boot_logo, install_boot_bg_png
    result.events.append(f"boot-logo:{install_boot_logo()}")
    result.events.append(f"boot-bg-png:{install_boot_bg_png()}")
  except Exception as exc:
    result.errors.append(f"boot-logo: {type(exc).__name__}")
  try:
    from openpilot.common import bogpilot_toggles
    migrate = getattr(bogpilot_toggles, "migrate_screensaver_default_off", None)
    if migrate is not None:
      migrate(directory=directory)
      result.events.append("screensaver:migrated")
    else:
      result.events.append("screensaver:dependency-missing")
    layout = getattr(bogpilot_toggles, "migrate_ui_layout_defaults", None)
    if layout is not None:
      layout(directory=directory)
      result.events.append("ui-layout:migrated")
    else:
      result.events.append("ui-layout:dependency-missing")
  except Exception as exc:
    result.errors.append(f"screensaver: {type(exc).__name__}")
  try:
    from openpilot.system.bogpilot.drive_tracking import ensure_stats_stores
    status = ensure_stats_stores(params, history_path=directory / "DriveHistory")
    result.events.append(
      f"drive-stats:{status['stats']}/{status['history']}")
  except Exception as exc:
    result.errors.append(f"drive-stats: {type(exc).__name__}")
  if (startup is not None and startup.profile_suppressed) or (directory / "AP1StockReset1").exists():
    result.events.append("ap1:suppressed-stock-reset")
    return result
  try:
    from openpilot.common.bogpilot_ap1_profile import apply_ap1_defaults_once
    changed = apply_ap1_defaults_once(params, bogpilot_dir=directory)
    result.events.append(f"ap1:{len(changed)}")
  except Exception as exc:
    result.errors.append(f"ap1: {type(exc).__name__}")
  try:
    from openpilot.common.bogpilot_ap1_profile import apply_legacy_slc_defaults_once
    changed = apply_legacy_slc_defaults_once(params, bogpilot_dir=directory)
    result.events.append(f"legacy-slc:{len(changed)}")
  except Exception as exc:
    result.errors.append(f"legacy-slc: {type(exc).__name__}")
  try:
    from openpilot.common.bogpilot_ap1_profile import apply_legacy_tesla_long_defaults_once
    changed = apply_legacy_tesla_long_defaults_once(params, bogpilot_dir=directory)
    result.events.append(f"legacy-tesla-long:{len(changed)}")
  except Exception as exc:
    result.errors.append(f"legacy-tesla-long: {type(exc).__name__}")
  try:
    from openpilot.common.bogpilot_ap1_profile import apply_legacy_tesla_ce_off_once
    changed = apply_legacy_tesla_ce_off_once(params, bogpilot_dir=directory)
    result.events.append(f"legacy-tesla-ce-off:{len(changed)}")
  except Exception as exc:
    result.errors.append(f"legacy-tesla-ce-off: {type(exc).__name__}")
  return result
