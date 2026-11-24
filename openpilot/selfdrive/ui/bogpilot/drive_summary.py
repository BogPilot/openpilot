"""Per-drive summary shown on the home screen after a drive (port of the 0.9.7 Drive Summary card).

Pure logic, no pyray. bogpilot_trackd keeps lifetime counters in BogPilotStats. The UI copies them
when the car goes onroad and, after the onroad-to-offroad transition, shows the difference for that
one drive. The tracker saves its counters at standstill (TrackedTime only moves on a save), so the
controller re-reads the param for a short window until TrackedTime moves, then gives up gracefully.

Engaged time is the time openpilot was steering (LateralTime, from carControl.latActive), measured
against TrackedTime. Both are written by the same save, so the percentage never mixes two saves.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

STATS_KEY = "BogPilotStats"

TRACKED_KEY = "TrackedTime"
ENGAGED_KEY = "LateralTime"
EXPERIMENTAL_KEY = "ExperimentalModeTime"
DISTANCE_KEY = "BogPilotMeters"

METER_TO_MILE = 1 / 1609.344
POLL_INTERVAL_S = 1.0
SAVE_TIMEOUT_S = 15.0
MAX_RAW_BYTES = 2 * 1024 * 1024


def parse_stats(raw: Any) -> dict | None:
  """Missing param is an empty store ({}); anything unreadable is None."""
  if isinstance(raw, dict):
    return raw
  if raw is None or raw == "" or raw == b"":
    return {}
  if isinstance(raw, bytes):
    try:
      raw = raw.decode("utf-8")
    except UnicodeError:
      return None
  if not isinstance(raw, str) or len(raw) > MAX_RAW_BYTES:
    return None
  try:
    value = json.loads(raw)
  except ValueError:
    return None
  return value if isinstance(value, dict) else None


def _number(stats: dict, key: str) -> float:
  value = stats.get(key, 0)
  if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
    return 0.0
  return float(value)


def percent(part: float, whole: float) -> int:
  """Whole percent, truncated like 0.9.7 (integer division), clamped to 0..100."""
  if whole <= 0:
    return 0
  return int(max(0.0, min(100.0, part * 100.0 / whole)))


@dataclass(frozen=True)
class DriveSummary:
  tracked_s: float = 0.0
  engaged_s: float = 0.0
  experimental_s: float = 0.0
  meters: float = 0.0

  @property
  def recorded(self) -> bool:
    return self.tracked_s > 0

  @property
  def engaged_pct(self) -> int:
    return percent(self.engaged_s, self.tracked_s)

  @property
  def experimental_pct(self) -> int:
    return percent(self.experimental_s, self.tracked_s)


def diff_summary(before: dict | None, after: dict | None) -> DriveSummary | None:
  """Counters gained during one drive. None when either copy is unreadable.

  If TrackedTime went backwards the stats were reset during the drive, so the new totals are the drive.
  """
  if before is None or after is None:
    return None
  if _number(after, TRACKED_KEY) < _number(before, TRACKED_KEY):
    before = {}

  def delta(key: str) -> float:
    return max(0.0, _number(after, key) - _number(before, key))

  return DriveSummary(delta(TRACKED_KEY), delta(ENGAGED_KEY), delta(EXPERIMENTAL_KEY), delta(DISTANCE_KEY))


def round_half_up(value: float) -> int:
  return int(math.floor(value + 0.5))


def distance_value(meters: float, metric: bool) -> int:
  return round_half_up(meters / 1000.0 if metric else meters * METER_TO_MILE)


def time_parts(seconds: float) -> tuple[int, int, int]:
  """(days, hours, minutes), minutes truncated like 0.9.7."""
  total = max(0, int(seconds))
  return total // 86400, (total % 86400) // 3600, (total % 3600) // 60


class Phase(IntEnum):
  HIDDEN = 0
  WAITING = 1   # just went offroad, waiting for the tracker's save
  READY = 2     # a drive was found; keeps re-reading until the window ends
  NO_DRIVE = 3  # window ended with no tracked time for this drive


class DriveSummaryController:
  def __init__(self, read_raw: Callable[[], Any], poll_interval: float = POLL_INTERVAL_S, timeout: float = SAVE_TIMEOUT_S):
    self._read_raw = read_raw
    self._poll_interval = poll_interval
    self._timeout = timeout
    self._before: dict | None = None
    self._was_onroad = False
    self._polling = False
    self._deadline = 0.0
    self._next_poll = 0.0
    self.phase = Phase.HIDDEN
    self.summary: DriveSummary | None = None

  @property
  def visible(self) -> bool:
    return self.phase != Phase.HIDDEN

  def _read(self) -> dict | None:
    try:
      return parse_stats(self._read_raw())
    except Exception:
      return None

  def on_transition(self, started: bool, now: float) -> None:
    if started:
      self._before = self._read()
      self._was_onroad = True
      self._polling = False
      self.phase = Phase.HIDDEN
      self.summary = None
      return
    if not self._was_onroad:
      return  # UI start while offroad, or a repeated offroad callback: no drive to summarise
    self._was_onroad = False
    self.summary = None
    self.phase = Phase.WAITING
    self._polling = True
    self._deadline = now + self._timeout
    self._next_poll = now
    self.poll(now)

  def poll(self, now: float) -> None:
    if not self._polling or self.phase == Phase.HIDDEN:
      return
    if now >= self._next_poll:
      self._next_poll = now + self._poll_interval
      summary = diff_summary(self._before, self._read())
      if summary is not None and summary.recorded:
        self.summary = summary
        self.phase = Phase.READY
    if now >= self._deadline:
      self._polling = False
      if self.phase == Phase.WAITING:
        self.phase = Phase.NO_DRIVE

  def dismiss(self) -> None:
    self._polling = False
    self.phase = Phase.HIDDEN
    self.summary = None
