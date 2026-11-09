#!/usr/bin/env python3
"""BogPilot drive stats producer: DriveHistory ledger + FrogPilotStats counters.

Port of frogpilot_tracking @ 367e1fe / bogpilot_trackd from the AGNOS 19.9 drive-stats
lane, adapted for feae (stock-default, no AOL runtime, no model switcher).

Fresh install:
  - FrogPilotStats gets valid zero counters so the home card shows 0, not unavailable/'?'.
  - DriveHistory is created as {}.
Existing valid history/counters are never overwritten with zeros.
Corrupt stores are copied to a timestamped .corrupt backup before recovery.

Drive credit (same contract as 367e1fe): after >= 60 s tracked, at standstill, if
openpilot engaged at least once; ledger write only when the wall clock is valid.
"""
from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from openpilot.common import bogpilot_toggles as _bt

DT_MDL = 0.05
DRIVE_HISTORY_DAYS = 14
DRIVE_CREDIT_S = 60
TIMEZONE_NAME_PATH = Path("/data/etc/timezone")
V_CRUISE_MAX = 145  # kph
KPH_TO_MS = 1 / 3.6
MODEL_NAME = "openpilot 0.11.2"

DISABLED, OVERRIDING = "disabled", "overriding"
ACTIVE_STATES = ("enabled", "softDisabling", "overriding")

ZERO_COUNTERS = {
  "FrogPilotDrives": 0,
  "FrogPilotMeters": 0.0,
  "FrogPilotSeconds": 0.0,
}


def drive_history_path() -> Path:
  return _bt.BOGPILOT_DIR / "DriveHistory"


def bogpilot_timezone(params_get=None):
  names = []
  try:
    if params_get is not None:
      v = params_get("Timezone")
      names.append(v.decode() if isinstance(v, bytes) else v)
  except Exception:
    pass
  try:
    names.append(TIMEZONE_NAME_PATH.read_text())
  except Exception:
    pass
  for name in names:
    name = (name or "").strip()
    if name:
      try:
        return ZoneInfo(name)
      except Exception:
        pass
  return datetime.datetime.now().astimezone().tzinfo or datetime.UTC


def local_day(now_utc, tz):
  if now_utc.tzinfo is None:
    now_utc = now_utc.replace(tzinfo=datetime.UTC)
  return now_utc.astimezone(tz).date()


def _atomic_write_text(path: Path, text: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{time.time_ns()}")
  try:
    with open(tmp, "w", encoding="utf-8") as f:
      f.write(text)
      f.flush()
      os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
      dir_fd = os.open(str(path.parent), os.O_RDONLY)
      try:
        os.fsync(dir_fd)
      finally:
        os.close(dir_fd)
    except OSError:
      pass
  finally:
    try:
      tmp.unlink(missing_ok=True)
    except TypeError:
      if tmp.exists():
        tmp.unlink()


def _backup_corrupt(path: Path, reason: str) -> Path | None:
  """Keep a durable backup of a bad store. Never delete the original until replace succeeds."""
  if not path.exists():
    return None
  stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
  backup = path.with_name(f"{path.name}.corrupt.{stamp}")
  try:
    data = path.read_bytes()
    with open(backup, "wb") as f:
      f.write(data)
      f.flush()
      os.fsync(f.fileno())
    # sidecar reason for integrators / forensics
    _atomic_write_text(backup.with_suffix(backup.suffix + ".reason"), reason + "\n")
    return backup
  except OSError as e:
    print(f"Drive stats corrupt backup failed: {e}")
    return None


def _read_history_object(path: Path) -> tuple[dict, bool]:
  """Return (object, recovered). recovered=True means a backup was taken and caller may rewrite."""
  if not path.exists():
    return {}, False
  try:
    if path.stat().st_size > 2 * 1024 * 1024:
      raise ValueError("oversized")
    raw = path.read_text(encoding="utf-8")
    if raw.strip() == "":
      # empty file: treat as missing initializer case, no backup needed
      return {}, False
    obj = json.loads(raw)
    if not isinstance(obj, dict):
      raise ValueError("not an object")
    # schema soft-check: reject only if every entry is unusable AND file nonempty
    return obj, False
  except (OSError, ValueError, TypeError, UnicodeError) as e:
    _backup_corrupt(path, f"DriveHistory read: {type(e).__name__}: {e}")
    return {}, True


def add_drive_history(day, routes=0, meters=0.0, seconds=0.0, path: Path | None = None):
  path = path or drive_history_path()
  history, _recovered = _read_history_object(path)
  try:
    oldest = day - datetime.timedelta(days=DRIVE_HISTORY_DAYS)
    kept = {}
    for key, value in history.items():
      try:
        if datetime.date.fromisoformat(key) >= oldest and isinstance(value, dict):
          kept[key] = {
            "routes": int(value.get("routes", 0) or 0),
            "meters": float(value.get("meters", 0) or 0),
            "seconds": float(value.get("seconds", 0) or 0),
          }
      except (TypeError, ValueError):
        pass
    key = day.isoformat()
    bucket = kept.get(key, {"routes": 0, "meters": 0.0, "seconds": 0.0})
    bucket["routes"] = int(bucket.get("routes", 0)) + int(routes)
    bucket["meters"] = float(bucket.get("meters", 0)) + float(meters)
    bucket["seconds"] = float(bucket.get("seconds", 0)) + float(seconds)
    kept[key] = bucket
    _atomic_write_text(path, json.dumps(kept, sort_keys=True))
  except Exception as e:
    print(f"DriveHistory write failed: {e}")


def ensure_drive_history(path: Path | None = None) -> str:
  """Create empty ledger on fresh install. Never zero-clobber a valid nonempty ledger."""
  path = path or drive_history_path()
  if not path.exists():
    _atomic_write_text(path, "{}")
    return "created"
  obj, recovered = _read_history_object(path)
  if recovered:
    # backup already kept; write empty so weekly card can show genuine 0 going forward
    _atomic_write_text(path, "{}")
    return "recovered"
  if obj == {} and path.stat().st_size == 0:
    _atomic_write_text(path, "{}")
    return "normalized"
  # valid (including valid empty {}): leave untouched
  return "preserved"


def load_stats(raw) -> dict:
  corrupt = False
  try:
    if raw is None or raw == "" or raw == b"":
      stats = {}
    else:
      if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
      if len(raw) > 2 * 1024 * 1024:
        raise ValueError("oversized")
      stats = json.loads(raw)
  except (TypeError, ValueError, UnicodeError):
    stats = {}
    corrupt = True
  if not isinstance(stats, dict):
    stats = {}
    corrupt = True

  stats.setdefault("AOLTime", stats.get("TotalAOLTime", 0))
  stats.setdefault("LateralTime", stats.get("TotalLateralTime", 0))
  stats.setdefault("LongitudinalTime", stats.get("TotalLongitudinalTime", 0))
  stats.setdefault("TrackedTime", stats.get("TotalTrackedTime", 0))
  stats = {
    key: ({k: v for k, v in value.items() if k.lower() != "unknown"} if isinstance(value, dict) else value)
    for key, value in stats.items()
    if key.lower() != "unknown"  # INT t994: never drop saved keys (review MAJOR 3a)
  }
  # INT t994 (review MAJOR 3b): missing counters become zero; existing counters are never overwritten.
  for _k in ("Disengages", "Engages", "FrogChirps", "FrogSqueaks", "Overrides"):
    stats.setdefault(_k, 0)
  stats.setdefault("ResetStats", True)
  stats.pop("CurrentMonthsKilometers", None)

  # Card-required counters: missing -> genuine zero. Never wipe existing nonzero.
  for key, zero in ZERO_COUNTERS.items():
    if key not in stats:
      stats[key] = zero
    else:
      # coerce valid numbers; leave bad values for the next save after setdefault-like repair
      try:
        if key == "FrogPilotDrives":
          stats[key] = int(stats[key])
          if stats[key] < 0:
            stats[key] = 0
        else:
          stats[key] = float(stats[key])
          if stats[key] < 0 or stats[key] != stats[key]:  # NaN
            stats[key] = 0.0
      except (TypeError, ValueError):
        stats[key] = zero

  stats["_corrupt_source"] = corrupt  # internal; stripped on save
  return stats


def _add(d: dict, key, amount):
  d[key] = d.get(key, 0) + amount


def ensure_stats_stores(params, *, history_path: Path | None = None) -> dict:
  """Idempotent fresh-install initializer. Preserves valid history and counters."""
  history_status = ensure_drive_history(history_path)

  raw = None
  try:
    raw = params.get("FrogPilotStats")
  except Exception:
    raw = None

  # Backup corrupt Params blob if we can locate the file
  stats = load_stats(raw)
  corrupt = bool(stats.pop("_corrupt_source", False))
  if corrupt and raw not in (None, "", b""):
    try:
      # Params file path when available
      get_path = getattr(params, "get_param_path", None)
      if callable(get_path):
        p = Path(get_path("FrogPilotStats"))
        if p.exists():
          _backup_corrupt(p, "FrogPilotStats JSON corrupt on ensure")
    except Exception:
      pass

  # Detect whether required counters were already present as valid zeros/nonzero
  # Always persist after ensure so a fresh missing key becomes valid zero JSON.
  raw_out = {k: v for k, v in stats.items() if not k.startswith("_")}
  text = json.dumps(raw_out)
  # INT t994 (review MAJOR 3c): rewrite only when the store is missing/corrupt/lacks a required key.
  unchanged = False
  if not corrupt and raw not in (None, "", b""):
    try:
      existing = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
      unchanged = existing == raw_out
    except (TypeError, ValueError, UnicodeError):
      unchanged = False
  if not unchanged:
    try:
      params.put("FrogPilotStats", text, block=True)
    except TypeError:
      params.put("FrogPilotStats", text)

  return {"history": history_status, "stats": "recovered" if corrupt else ("created" if raw in (None, "", b"") else "preserved")}


class DriveTracker:
  def __init__(self, params, *, history_path: Path | None = None, initialize_stores: bool = True):
    self.params = params
    self.history_path = history_path
    if initialize_stores:
      ensure_stats_stores(params, history_path=history_path)

    self.stats = load_stats(params.get("FrogPilotStats"))
    self.stats.pop("_corrupt_source", None)
    self._save(block=True)

    self.drive_added = False
    self.previously_enabled = False
    self.distance_since_override = 0.0
    self.history_meters = 0.0
    self.history_routes = 0
    self.history_seconds = 0.0
    self.tracked_time = 0.0
    self.previous_alert = None
    self.previous_state = DISABLED
    # engaged time = seconds with selfdrive enabled (or lat/long active)
    self.engaged_time = 0.0

  def _save(self, block=False):
    payload = {k: v for k, v in self.stats.items() if not k.startswith("_")}
    # Always include card counters
    for key, zero in ZERO_COUNTERS.items():
      payload.setdefault(key, zero)
    raw = json.dumps(payload)
    try:
      self.params.put("FrogPilotStats", raw, block=block)
    except TypeError:
      self.params.put("FrogPilotStats", raw)

  def update(self, now, time_validated, car_state, selfdrive_state, car_control, aol_enabled=False):
    # aol_enabled accepted for API compat but AOL core is out of runtime; ignore unless caller passes True.
    s = self.stats
    state = str(selfdrive_state.state)
    v_cruise = min(car_state.vCruiseCluster, V_CRUISE_MAX) * KPH_TO_MS
    distance = max(car_state.vEgo, 0) * DT_MDL
    self.previously_enabled |= bool(selfdrive_state.enabled or aol_enabled)
    self.tracked_time += DT_MDL
    if selfdrive_state.enabled or aol_enabled:
      self.engaged_time += DT_MDL

    alert = selfdrive_state.alertType
    if alert not in (self.previous_alert, ""):
      events = s.setdefault("TotalEvents", {})
      _add(events, alert.split("/")[0], 1)
    self.previous_alert = alert

    if selfdrive_state.enabled:
      _add(s.setdefault("CruiseSpeedTimes", {}), str(round(v_cruise, 2)), DT_MDL)

    _add(s, "CurrentMonthsMeters", distance)

    if state != self.previous_state:
      if state in ACTIVE_STATES and self.previous_state not in ACTIVE_STATES:
        _add(s, "Engages", 1)
      elif state == DISABLED and self.previous_state in ACTIVE_STATES:
        _add(s, "Disengages", 1)
      if state == OVERRIDING and self.previous_state != OVERRIDING:
        _add(s, "Overrides", 1)
      self.previous_state = state

    if selfdrive_state.experimentalMode:
      _add(s, "ExperimentalModeTime", DT_MDL)

    _add(s, "FrogPilotMeters", distance)
    self.history_meters += distance

    if car_control.latActive:
      _add(s, "LateralTime", DT_MDL)
    if car_control.longActive:
      _add(s, "LongitudinalTime", DT_MDL)
      _add(s.setdefault("PersonalityTimes", {}), str(selfdrive_state.personality).capitalize(), DT_MDL)
    elif aol_enabled:
      _add(s, "AOLTime", DT_MDL)

    if state in (DISABLED, OVERRIDING):
      self.distance_since_override = 0.0
      _add(s, "OverrideTime", DT_MDL)
    else:
      self.distance_since_override += distance
      s["LongestDistanceWithoutOverride"] = max(self.distance_since_override, s.get("LongestDistanceWithoutOverride", 0))

    if car_state.standstill:
      _add(s, "StandstillTime", DT_MDL)

    if self.tracked_time >= DRIVE_CREDIT_S and car_state.standstill and self.previously_enabled:
      self.flush(now, time_validated)

  def flush(self, now, time_validated):
    s = self.stats
    if time_validated and now.month != s.get("Month"):
      s.update({"CurrentMonthsMeters": 0, "Month": now.month})
    _add(s, "FrogPilotSeconds", self.tracked_time)
    _add(s, "EngagedSeconds", self.engaged_time)
    _add(s.setdefault("ModelTimes", {}), MODEL_NAME, self.tracked_time)
    _add(s, "TrackedTime", self.tracked_time)

    new_drive = not self.drive_added
    self.history_routes += int(new_drive)
    self.history_seconds += self.tracked_time
    if time_validated:
      day = local_day(now, bogpilot_timezone(self.params.get))
      add_drive_history(
        day,
        routes=self.history_routes,
        meters=self.history_meters,
        seconds=self.history_seconds,
        path=self.history_path,
      )
      self.history_meters, self.history_routes, self.history_seconds = 0.0, 0, 0.0
    self.tracked_time = 0.0
    self.engaged_time = 0.0

    if new_drive:
      _add(s, "FrogPilotDrives", 1)
      self.drive_added = True
    self._save()


def main():
  """Never exits on error: selfdrived treats any should-run-but-stopped process as processNotRunning."""
  import time

  from openpilot.common.swaglog import cloudlog

  try:
    import openpilot.cereal.messaging as messaging
    from openpilot.common.params import Params
    from openpilot.common.time_helpers import system_time_valid

    params = Params()
    tracker = DriveTracker(params)
    # AOL / frogpilotCarState intentionally omitted (AOL blocked on stock-default build).
    services = ["modelV2", "carState", "selfdriveState", "carControl"]
    sm = messaging.SubMaster(services, poll="modelV2")
  except Exception:
    cloudlog.exception("bogpilot_trackd setup failed; idling")
    while True:
      time.sleep(10)

  while True:
    try:
      sm.update()
      if not sm.updated["modelV2"]:
        continue
      tracker.update(
        datetime.datetime.now(datetime.UTC),
        system_time_valid(),
        sm["carState"],
        sm["selfdriveState"],
        sm["carControl"],
        aol_enabled=False,
      )
    except Exception:
      cloudlog.exception("bogpilot_trackd update failed")
      time.sleep(1)


if __name__ == "__main__":
  main()
