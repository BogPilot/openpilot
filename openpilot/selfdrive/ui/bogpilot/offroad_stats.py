"""Read-only local offroad stats, ported from 568fea drive_stats.cc.

No network/account calls, writes or drive-tracking service. The existing counters
and ledger are authoritative; absence/corruption is not fabricated as zero.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

METER_TO_MILE = 1 / 1609.344
HISTORY_PATH = Path("/data/params_bogpilot/DriveHistory")
TIMEZONE_PATH = Path("/data/etc/timezone")


@dataclass(frozen=True)
class StatsRow:
  drives: int | None = None
  distance: int | None = None
  hours: int | None = None
  available: bool = False
  status: str = "No local data"


def _object(raw: Any) -> dict | None:
  if raw is None or raw == "" or raw == b"":
    return None
  if not isinstance(raw, (str, bytes)) or len(raw) > 2 * 1024 * 1024:
    raise ValueError("invalid local stats")
  value = json.loads(raw)
  if not isinstance(value, dict):
    raise ValueError("invalid local stats")
  return value


def _number(value: Any, *, integer: bool = False) -> float:
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    raise ValueError("invalid local counter")
  number = float(value)
  if not math.isfinite(number) or number < 0 or (integer and not number.is_integer()):
    raise ValueError("invalid local counter")
  return number


def _row(drives: Any, meters: Any, seconds: Any, metric: bool) -> StatsRow:
  routes = _number(drives, integer=True)
  distance = _number(meters)
  duration = _number(seconds)
  return StatsRow(int(routes), int(distance * (0.001 if metric else METER_TO_MILE)), int(duration / 3600), True, "")


def cumulative_row(raw: Any, metric: bool) -> StatsRow:
  try:
    obj = _object(raw)
    if obj is None:
      return StatsRow()
    return _row(obj["FrogPilotDrives"], obj["FrogPilotMeters"], obj["FrogPilotSeconds"], metric)
  except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
    return StatsRow(status="Invalid local data")


def resolve_timezone(name: Any, timezone_path: Path = TIMEZONE_PATH) -> tzinfo:
  # Same priority as old Qt card/tracker: Param -> /data/etc/timezone -> system -> UTC.
  names = [name] if isinstance(name, str) else []
  try:
    names.append(timezone_path.read_text().strip())
  except (OSError, UnicodeError):
    pass
  try:
    names.append(str(Path("/etc/localtime").resolve()).split("/zoneinfo/", 1)[1])
  except (OSError, IndexError):
    pass
  for candidate in names:
    try:
      if candidate.strip():
        return ZoneInfo(candidate.strip())
    except (ZoneInfoNotFoundError, ValueError):
      continue
  return datetime.now().astimezone().tzinfo or UTC


def past_week_row(raw: Any, metric: bool, today: date) -> StatsRow:
  try:
    obj = _object(raw)
    if obj is None:
      return StatsRow()
    oldest = today - timedelta(days=6)
    routes = meters = seconds = 0.0
    valid_days = 0
    for key, values in obj.items():
      try:
        day = date.fromisoformat(key)
        if day.isoformat() != key:
          continue
      except (ValueError, TypeError):
        continue
      # Includes future-labelled local days, exactly as old card after timezone changes.
      if day < oldest:
        continue
      if not isinstance(values, dict):
        raise ValueError("invalid local day")
      routes += _number(values["routes"], integer=True)
      meters += _number(values["meters"])
      seconds += _number(values["seconds"])
      valid_days += 1
    if obj and not valid_days:
      # Valid old-only ledgers are known zero; malformed-only ledgers are unavailable.
      for key in obj:
        try:
          day = date.fromisoformat(key)
          if day.isoformat() == key:
            return _row(0, 0, 0, metric)
        except (ValueError, TypeError):
          pass
      return StatsRow(status="Invalid local data")
    return _row(routes, meters, seconds, metric)
  except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
    return StatsRow(status="Invalid local data")


def read_rows(params: Any, *, history_path: Path = HISTORY_PATH, timezone_path: Path = TIMEZONE_PATH,
              now: datetime | None = None) -> tuple[StatsRow, StatsRow, StatsRow]:
  metric = params.get_bool("IsMetric")
  try:
    raw = params.get("FrogPilotStats")
  except (KeyError, OSError, ValueError):
    raw = None
  total = cumulative_row(raw, metric)
  try:
    zone_name = params.get("Timezone")
  except (KeyError, OSError, ValueError):
    zone_name = None
  zone = resolve_timezone(zone_name, timezone_path)
  current = now or datetime.now(UTC)
  if current.tzinfo is None:
    raise ValueError("stats clock must be timezone-aware")
  try:
    if history_path.stat().st_size > 2 * 1024 * 1024:
      raise ValueError("oversized local ledger")
    weekly = past_week_row(history_path.read_bytes(), metric, current.astimezone(zone).date())
  except FileNotFoundError:
    weekly = StatsRow()
  except (OSError, ValueError):
    weekly = StatsRow(status="Invalid local data")
  # ALL TIME local fallback and BOGPILOT row share the original genuine counter source.
  return total, weekly, total
