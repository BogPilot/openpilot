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
  if backup is None:
    module = _optional("openpilot.system.bogpilot.settings_backup", result)
    snapshot = getattr(module, "backup_settings", None)
    if snapshot is not None:
      destination = Path(cache_root or os.getenv("BOGPILOT_BACKUP_DIR", "/cache/bogpilot/settings"))
      def snapshot_receipt(reason):
        outcome = snapshot(params, directory, destination, reason=reason)
        # Do not accept a truthy failed-result wrapper. This adapter is pending
        # w5 contract confirmation; only explicit success authorizes reset.
        return outcome if getattr(outcome, "success", False) is True else None
      try:
        result.events.append("backup:boot" if snapshot_receipt("boot") else "backup:failed")
      except Exception as exc:
        result.errors.append(f"backup: {type(exc).__name__}")
      backup = lambda: snapshot_receipt("pre-reset")

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
