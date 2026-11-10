"""System Settings > Utilities backend for BogPilot 0.11.2 (feae lane).

Working actions only:
  - Debug Mode preference (existing onroad consumers)
  - Reset BogPilot settings to current shipping defaults (durable backup first)
  - Clear allowlisted download/model/API caches
  - Save a local debug report (no network)

Never flashes firmware, never changes OS/boot slots, never force-drives onroad,
never uploads reports. All destructive work requires the caller's confirm dialog
to have already succeeded; this module re-checks offroad/capability guards.
"""
from __future__ import annotations

import errno
import json
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
MAX_ENTRIES = 100000
MAX_DEPTH = 24
MAX_REPORT_BYTES = 512 * 1024
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")

# Never delete these even if a caller tries to point a fixture root at them.
FORBIDDEN_CACHE_NAMES = frozenset({
  "params",  # /cache/params holds SecOCKey
  "bogpilot",  # /cache/bogpilot/settings-backups
  "on_backup",
})

# Soft API/nav caches stored as Params strings — not secrets.
API_CACHE_KEYS = ("ApiCache_DriveStats", "ApiCache_NavDestinations")

PENDING = {
  "Flash Panda": "Pending verified firmware/update lifecycle. No flash request is issued.",
  "Force Drive State": "Pending isolated simulation policy; real ignition and safety state stay untouched.",
}

# Phase3 adoption markers (file-store). Surviving after a defaults reset would make
# gas/brake/follow/speed consumers LIVE on rewritten shipping values — unlike a
# fresh install. Cleared on every BogPilot-defaults reset.
ADOPTION_MARKERS = (
  "Phase3LongAccelProfilesEnabled",
  "Phase3AdvancedLongEnabled",
  "Phase3CEMEnabled",
  "Phase3StoppedDistanceEnabled",
  "Phase3ForceStopsEnabled",
  "Phase3ManualWeatherEnabled",
  # gasFollowSpeed (lane t994)
  "Phase3SpeedLimitEnabled",
  "Phase3PersonalitiesEnabled",
  "Phase3HumanFollowingEnabled",
  "Phase3LeadDetectionEnabled",
  # laneChange (lane t994)
  "Phase3LaneChangeEnabled",
  "Phase3HumanLaneChangesEnabled",
  "Phase3TurnDesiresEnabled",
  # gasAccelStop stop rows (t1003u)
  "Phase3StopAccelEnabled",
  "Phase3StoppingRateEnabled",
)

# t999 Driving Model selection + fallback state (file store): reset returns to Default (stock).
DRIVING_MODEL_KEYS = ("BogPilotDrivingModel", "BogPilotDrivingModelState")


def shipping_defaults():
  """BogPilot fresh-install / shipping defaults (NOT stock-off values).

  Uses the real registry default column BOGPILOT_PARAMS[k][2] plus locked
  shipping overlays. Distinct from toggle_reset.reset_defaults(), which is the
  stock-openpilot column and turns GreenLightAlert/LeadDepartingAlert/
  AdjacentLeadsUI/ScreenRecorder/BlindSpotPath OFF.
  """
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  from openpilot.common.bogpilot_shipping_defaults import PARAM_OVERRIDES
  from openpilot.common.bogpilot_toggles import FILE_TOGGLES
  from openpilot.system.bogpilot.toggle_reset import RESET_KEYS, FILE_RESET_KEYS

  values = {}
  for key in sorted(RESET_KEYS):
    default = BOGPILOT_PARAMS[key][2]
    if default is None:
      continue
    values[key] = default if default != "" else None
  for key, (value, _level) in PARAM_OVERRIDES.items():
    if key in values:
      values[key] = value
  from openpilot.system.bogpilot.toggle_reset import DEVICE_STOCK_FRESH
  values.update({key: v for key, v in DEVICE_STOCK_FRESH.items() if key in values})
  values.update({key: "1" if FILE_TOGGLES[key][0] else "0" for key in sorted(FILE_RESET_KEYS)})
  values["OffroadScreensaver"] = "0"
  values["AlertVolumeControl"] = "0"
  for key in list(values):
    if key.endswith("Volume"):
      values[key] = "101"
  # Fresh install: TuningLevel unset + all Phase3 adoption markers absent.
  for key in ("TuningLevel", "TuningLevelConfirmed", *ADOPTION_MARKERS, *DRIVING_MODEL_KEYS):
    values[key] = None
  return values



def _valid_report_name(value: str) -> str:
  if not isinstance(value, str) or not NAME_RE.fullmatch(value) or value in {".", ".."}:
    raise ValueError("Invalid report name")
  return value


@contextmanager
def open_directory(path):
  """Reject symlinks in every ancestor."""
  p = Path(path)
  if not p.is_absolute() or ".." in p.parts:
    raise ValueError("Absolute bounded root required")
  fd = os.open("/", DIR_FLAGS)
  try:
    for part in p.parts[1:]:
      new = os.open(part, DIR_FLAGS, dir_fd=fd)
      os.close(fd)
      fd = new
    yield fd
  finally:
    os.close(fd)


def _scan(fd, dev, depth=0, count=None):
  count = [0] if count is None else count
  if depth > MAX_DEPTH:
    raise ValueError("Directory nesting exceeds safety limit")
  result = []
  for name in sorted(os.listdir(fd)):
    count[0] += 1
    if count[0] > MAX_ENTRIES:
      raise ValueError("Directory entry limit exceeded")
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if st.st_dev != dev or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
      raise ValueError("Symlink, mount or special file refused")
    children = None
    if stat.S_ISDIR(st.st_mode):
      child = os.open(name, DIR_FLAGS, dir_fd=fd)
      try:
        opened = os.fstat(child)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
          raise ValueError("Directory changed during inspection")
        children = _scan(child, dev, depth + 1, count)
      finally:
        os.close(child)
    result.append((name, st.st_ino, children))
  return result


def _remove(fd, entries, dev, guard):
  removed = 0
  for name, inode, children in entries:
    guard()
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if st.st_dev != dev or st.st_ino != inode or stat.S_ISLNK(st.st_mode):
      raise ValueError("Contents changed; operation stopped")
    if children is None:
      if not stat.S_ISREG(st.st_mode):
        raise ValueError("File type changed")
      os.unlink(name, dir_fd=fd)
      removed += 1
    else:
      child = os.open(name, DIR_FLAGS, dir_fd=fd)
      try:
        if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (dev, inode):
          raise ValueError("Directory changed")
        removed += _remove(child, children, dev, guard)
      finally:
        os.close(child)
      os.rmdir(name, dir_fd=fd)
      removed += 1
  return removed


class UtilitiesActions:
  """Injectable offroad/capability guards; production roots never come from UI text."""

  def __init__(self, offroad, capable, *, params=None, store=None, file_root=None,
               backup_root=None, cache_roots=None, report_root=None, now=None):
    self.offroad = offroad
    self.capable = capable
    self.params = params
    self.store = store
    self.file_root = Path(file_root or os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))
    self.backup_root = Path(backup_root or os.getenv("BOGPILOT_BACKUP_DIR", "/cache/bogpilot/settings-backups"))
    self.report_root = Path(report_root or "/data/bogpilot_debug_reports")
    self.cache_roots = tuple(cache_roots) if cache_roots is not None else self._default_cache_roots()
    self.now = now or time.time

  @staticmethod
  def _default_cache_roots():
    roots = []
    try:
      from openpilot.common.hardware.hw import Paths
      roots.append(Paths.download_cache_root().rstrip("/") or "/tmp/comma_download_cache")
    except Exception:
      roots.append("/tmp/comma_download_cache")
    roots.append("/data/comma_download_cache")
    roots.append("/data/model_replay_cache")
    return tuple(roots)

  def guard(self):
    if not self.offroad() or not self.capable():
      raise PermissionError("Offroad supported device required")

  # --- Debug Mode -----------------------------------------------------------

  def get_debug_mode(self) -> bool:
    if self.store is not None:
      return bool(self.store.get_bool("DebugMode", False))
    if self.params is None:
      return False
    return bool(self.params.get_bool("DebugMode"))

  def set_debug_mode(self, enabled: bool) -> str:
    self.guard()
    if type(enabled) is not bool:
      raise ValueError("Boolean required")
    if self.store is not None:
      self.store.put_bool("DebugMode", enabled)
      if self.store.get_bool("DebugMode", not enabled) != enabled:
        raise OSError("DebugMode write verification failed")
    elif self.params is not None:
      self.params.put_bool("DebugMode", enabled, block=True)
      if bool(self.params.get_bool("DebugMode")) != enabled:
        raise OSError("DebugMode write verification failed")
    else:
      raise RuntimeError("No preference store available")
    return "Debug Mode " + ("enabled" if enabled else "disabled") + "; active for the next drive (clears on the following offroad transition)."


  @staticmethod
  def _atomic_file(path: Path, content: bytes | None) -> None:
    if content is None:
      path.unlink(missing_ok=True)
      return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
      with os.fdopen(fd, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
      os.replace(name, path)
    finally:
      Path(name).unlink(missing_ok=True)

  # --- Reset BogPilot settings to defaults ---------------------------------

  def reset_bogpilot_defaults(self) -> str:
    """Apply audited BogPilot shipping defaults after a durable backup.

    Uses shipping_defaults() (registry default column + shipping overlays), NOT
    toggle_reset.reset_defaults() (stock-off column). Clears AP1 one-shot marker
    and all Phase3* adoption markers so the device matches a fresh install.
    Does not reboot. Never touches identity, VIN, dongle, calibration or secrets.
    """
    self.guard()
    from openpilot.system.bogpilot.toggle_reset import FILE_ONLY_UI_KEYS
    from openpilot.common.bogpilot_ap1_profile import clear_ap1_defaults_marker

    if self.params is None:
      raise RuntimeError("Params required for defaults reset")

    values = shipping_defaults()
    # Durable backup is mandatory before any mutation.
    receipt = self._backup("before-bogpilot-defaults-reset")
    if not receipt:
      raise OSError("Durable settings backup failed; reset refused")

    known = {k.decode() if isinstance(k, bytes) else k for k in self.params.all_keys()}
    typed = (set(values) & known) - FILE_ONLY_UI_KEYS
    original_params = {k: self.params.get(k) for k in typed}
    original_files = {}
    directory = self.file_root
    for k in values.keys() - typed:
      path = directory / k
      if path.is_symlink():
        raise ValueError("symlink target refused")
      original_files[k] = path.read_bytes() if path.exists() else None

    try:
      self.guard()
      for k, text in values.items():
        self.guard()
        if k in typed:
          value = None if text in (None, "") else self.params.cpp2python(k, text.encode())
          if value is None:
            self.params.remove(k)
          else:
            self.params.put(k, value, block=True)
        else:
          self._atomic_file(directory / k, None if text is None else text.encode())
      clear_ap1_defaults_marker(directory)
    except Exception:
      # Best-effort rollback; caller sees failure rather than a half-applied state.
      for k, value in original_params.items():
        try:
          if value is None:
            self.params.remove(k)
          else:
            self.params.put(k, value, block=True)
        except Exception:
          pass
      for k, content in original_files.items():
        try:
          self._atomic_file(directory / k, content)
        except Exception:
          pass
      raise

    return ("BogPilot settings reset to shipping defaults (fresh-install table). "
            "AP1 + Phase3 adoption markers cleared. No reboot performed.")

  def queue_stock_reset(self) -> str:
    """Queue DoToggleResetStock for the next manager restart (existing lifecycle)."""
    self.guard()
    if self.params is None:
      raise RuntimeError("Params required")
    known = {k.decode() if isinstance(k, bytes) else k for k in self.params.all_keys()}
    if "DoToggleResetStock" not in known:
      raise RuntimeError("DoToggleResetStock not in compiled Params")
    self.params.put_bool("DoToggleResetStock", True, block=True)
    if not self.params.get_bool("DoToggleResetStock"):
      raise OSError("Stock reset request write verification failed")
    return "Stock reset queued for next manager restart; no reset performed now."

  def _backup(self, reason: str):
    from openpilot.system.bogpilot.settings_backup import backup_settings
    outcome = backup_settings(
      self.params,
      file_root=self.file_root,
      backup_root=self.backup_root,
      reason=reason,
    )
    return outcome if getattr(outcome, "success", False) is True else None

  # --- Clear caches ---------------------------------------------------------

  def clear_caches(self) -> str:
    """Delete allowlisted download/model cache contents and soft API cache params.

    Never touches /cache/params, settings-backups, persist, boot slots or OS.
    """
    self.guard()
    removed = 0
    cleared_roots = []
    for root in self.cache_roots:
      path = Path(root)
      if not path.is_absolute() or ".." in path.parts:
        continue
      # Refuse forbidden leaf names and anything under /cache/params or backups.
      if path.name in FORBIDDEN_CACHE_NAMES:
        continue
      parts = set(path.parts)
      if "params" in parts and "cache" in parts:
        continue
      if "settings-backups" in parts or (path.parts[-2:] == ("bogpilot", "settings-backups")):
        continue
      if not path.exists():
        continue
      if path.is_symlink() or not path.is_dir():
        continue
      with open_directory(path) as fd:
        st = os.fstat(fd)
        entries = _scan(fd, st.st_dev)
        removed += _remove(fd, entries, st.st_dev, self.guard)
        os.fsync(fd)
      cleared_roots.append(str(path))

    api_cleared = 0
    if self.params is not None:
      known = {k.decode() if isinstance(k, bytes) else k for k in self.params.all_keys()}
      for key in API_CACHE_KEYS:
        if key in known:
          self.guard()
          self.params.remove(key)
          api_cleared += 1

    if not cleared_roots and api_cleared == 0:
      return "No allowlisted caches present; nothing deleted."
    return (f"Cleared {removed} cache entries under {len(cleared_roots)} root(s); "
            f"removed {api_cleared} API cache param(s). Settings backups kept.")

  # --- Local debug report ---------------------------------------------------

  def save_debug_report(self, *, extra=None) -> str:
    """Write a local JSON diagnostics report. No network upload."""
    self.guard()
    payload = self._build_report(extra=extra)
    raw = json.dumps(payload, sort_keys=True, indent=2).encode()
    if len(raw) > MAX_REPORT_BYTES:
      raise ValueError("Debug report exceeds size limit")

    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now()))
    name = _valid_report_name(f"bogpilot-debug-{stamp}.json")
    root = self.report_root
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
      raise ValueError("Report root must not be a symlink")

    fd, temporary = tempfile.mkstemp(prefix=".debug-report-", dir=root)
    try:
      with os.fdopen(fd, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
      dest = root / name
      os.replace(temporary, dest)
      parent_fd = os.open(root, DIR_FLAGS)
      try:
        os.fsync(parent_fd)
      finally:
        os.close(parent_fd)
    finally:
      Path(temporary).unlink(missing_ok=True)

    return f"Debug report saved locally as {name} (not uploaded)."

  def _build_report(self, *, extra=None) -> dict:
    report = {
      "format": "bogpilot-local-debug-report",
      "version": 1,
      "created_unix": int(self.now()),
      "debug_mode": self.get_debug_mode(),
      "notes": "Local only. No network upload. Secrets/VIN/dongle omitted.",
    }
    # Version / commit — best effort, never required.
    try:
      commit = Path("/data/openpilot/git_src_commit")
      if not commit.is_file():
        # Worktree / repo checkout
        here = Path(__file__).resolve()
        for parent in here.parents:
          candidate = parent / "git_src_commit"
          if candidate.is_file():
            commit = candidate
            break
      if commit.is_file() and not commit.is_symlink():
        report["git_src_commit"] = commit.read_text().strip()[:64]
    except Exception:
      report["git_src_commit"] = None

    try:
      from openpilot.common.hardware import HARDWARE
      report["device_type"] = HARDWARE.get_device_type()
    except Exception:
      report["device_type"] = "unknown"

    # Non-secret preference snapshot for triage.
    safe_keys = (
      "CarModel", "DebugMode", "IsMetric", "Version", "GitCommit",
      "GreenLightAlert", "LeadDepartingAlert", "AdjacentLeadsUI",
      "HasCompletedSetup", "DongleId",  # DongleId listed then redacted below
    )
    prefs = {}
    src = self.store if self.store is not None else self.params
    if src is not None:
      for key in safe_keys:
        try:
          if hasattr(src, "raw"):
            value = src.raw(key)
          elif hasattr(src, "get"):
            value = src.get(key)
          else:
            continue
        except Exception:
          continue
        if key in {"DongleId", "CarVin", "SecOCKey", "GithubSshKeys"}:
          prefs[key] = "<redacted>" if value not in (None, "", b"") else None
        else:
          if isinstance(value, bytes):
            try:
              value = value.decode("utf-8", "replace")
            except Exception:
              value = "<bytes>"
          prefs[key] = value if (value is None or len(str(value)) < 200) else str(value)[:200]
    report["prefs"] = prefs

    # Error log filenames only (not contents).
    error_names = []
    for errors_root in ("/data/error_logs",):
      path = Path(errors_root)
      if path.is_dir() and not path.is_symlink():
        try:
          with open_directory(path) as fd:
            for name in sorted(os.listdir(fd))[:50]:
              st = os.stat(name, dir_fd=fd, follow_symlinks=False)
              if stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode):
                error_names.append(name)
        except Exception:
          pass
    report["error_log_names"] = error_names

    if extra:
      if not isinstance(extra, dict):
        raise ValueError("extra must be a dict")
      # Shallow merge, never overwrite protected keys with caller secrets.
      for key, value in extra.items():
        if key in {"format", "version"}:
          continue
        report[key] = value
    return report
