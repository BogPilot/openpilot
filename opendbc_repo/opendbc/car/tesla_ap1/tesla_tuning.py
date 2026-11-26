"""Tesla Tuning: user-adjustable AP1 / Pre-AP comfort tuning values (Settings > Vehicle Settings > Tesla Tuning).

One table (ROWS) holds every adjustable number: its shipped value, the bounds it is clamped to, its step and the cars it
applies to. The shipped value of each row is the constant the car code uses, so a row can never drift from the car:
the consumer modules call `get(key, shipped)` where they define the constant, and `get` returns `shipped` unchanged unless
the user saved a value.

Storage: one file per row, /data/params_bogpilot/TeslaTuning<Key> (the same file store as the other Tesla rows; honours
$BOGPILOT_PARAMS_DIR for tests). No file, an unreadable file, a non-number or a non-finite number all mean "shipped
value". A number outside the bounds is clamped to them. No bound can push a request past the panda limits (accel
-3.52 .. 2.0 m/s^2, standby window -3.52 .. 0.0), braking is never held back (hard braking still passes through, deep braking
still gets the full 8 m/s^3 jerk field, and the add-only layers can only add braking), and nothing here touches steering,
mass, wheelbase, steer limit timers or the safety flags.

Applied once, when the process that uses the value starts (card, plannerd, controlsd import the consumer modules at start),
so a change takes effect the next time the car starts. Tuning Level: the saved values are used only while the Tuning Level is
Advanced or Developer; below that every row reads as its shipped value (the files are kept).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

S, X, P = "TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"
ALL = (S, X, P)
AP1 = (S, X)

FILE_PREFIX = "TeslaTuning"
MIN_LEVEL = 2   # Advanced (tuning_level.ADVANCED)

GROUP_ACCEL = "accel_braking"
GROUP_STOP = "stop_start"
GROUP_CURVE = "curves_preap"


@dataclass(frozen=True)
class Row:
  key: str
  group: str
  title: str
  shipped: float
  lo: float
  hi: float
  step: float
  decimals: int
  unit: str
  cars: tuple
  what: str

  def clamp(self, value: float) -> float:
    return max(self.lo, min(self.hi, float(value)))


def _row(*args):
  return Row(*args)


# shipped values are the constants in the consumer modules; tests assert each one equals the live constant.
ROWS: tuple[Row, ...] = (
  # ---- 1. Acceleration and braking
  _row("AP1RiseJerk", GROUP_ACCEL, "Accel Ramp-Up", 2.5, 0.5, 5.0, 0.1, 1, "m/s^3", AP1,
       "How fast the accel request may rise (more throttle, or letting go of braking)."),
  _row("AP1DriveReleaseJerk", GROUP_ACCEL, "Throttle Release", 2.0, 0.5, 5.0, 0.1, 1, "m/s^3", AP1,
       "How fast drive torque is let off when the plan asks for less accel."),
  _row("AP1DriveReleaseBrakeJerk", GROUP_ACCEL, "Throttle Release Into Braking", 5.0, 1.0, 8.0, 0.5, 1, "m/s^3", AP1,
       "How fast drive torque is let off when the plan asks for braking at the same time."),
  _row("AP1BrakeOnsetJerk", GROUP_ACCEL, "Braking Onset", 2.0, 1.0, 8.0, 0.5, 1, "m/s^3", AP1,
       "How fast regen braking ramps in for a gentle braking request. Deeper requests ramp faster, up to 8.0."),
  _row("AP1BrakeHardAccel", GROUP_ACCEL, "Hard Braking Passthrough", -2.0, -2.0, -1.5, 0.1, 1, "m/s^2", AP1,
       "A braking request at or below this passes through with no ramp."),
  _row("AP1ComfortJerkLimit", GROUP_ACCEL, "Comfort Jerk Limit", 1.5, 0.5, 4.0, 0.1, 1, "m/s^3", AP1,
       "The jerk limit sent to the car while driving gently. It widens to 8.0 for real braking."),
  _row("AP1StandbyAccelMin", GROUP_ACCEL, "Standby Brake Limit", -1.4, -2.5, -0.5, 0.1, 1, "m/s^2", (S,),
       "The lowest accel the standstill-engage standby request allows. The top of the window stays 0.0."),
  _row("AP1StandbyJerkMin", GROUP_ACCEL, "Standby Jerk Down", -0.46, -1.0, -0.1, 0.02, 2, "m/s^3", (S,),
       "The jerk limit for falling accel in the standby request."),
  _row("AP1StandbyJerkMax", GROUP_ACCEL, "Standby Jerk Up", 0.476, 0.1, 1.0, 0.02, 2, "m/s^3", (S,),
       "The jerk limit for rising accel in the standby request."),
  _row("ComfortRegenMaxDecel", GROUP_ACCEL, "Comfort Regen Limit", 0.9, 0.3, 1.5, 0.05, 2, "m/s^2", ALL,
       "The strongest gentle braking Comfort Regen asks for; a bigger need hands over to the normal plan."),
  _row("ComfortRegenOnsetJerk", GROUP_ACCEL, "Comfort Regen Onset", 0.75, 0.3, 1.5, 0.05, 2, "m/s^3", ALL,
       "How fast Comfort Regen braking ramps in."),
  _row("ComfortRegenReleaseJerk", GROUP_ACCEL, "Comfort Regen Release", 1.0, 0.3, 2.0, 0.1, 1, "m/s^3", ALL,
       "How fast Comfort Regen braking ramps out."),
  # ---- 2. Stopping and starting
  _row("StopShaperOnsetJerk", GROUP_STOP, "Stop Shaper Onset", 0.6, 0.2, 2.0, 0.1, 1, "m/s^3", AP1,
       "How fast the added stop braking ramps in."),
  _row("StopShaperReleaseJerk", GROUP_STOP, "Stop Shaper Release", 1.5, 0.5, 3.0, 0.1, 1, "m/s^3", AP1,
       "How fast the added stop braking ramps out."),
  _row("StopShaperOnsetFrac", GROUP_STOP, "Stop Shaper Start Point", 0.85, 0.5, 1.0, 0.05, 2, "", AP1,
       "How early the shaper starts braking for a stop. Lower starts earlier."),
  _row("StopShaperGentleFrac", GROUP_STOP, "Stop Shaper Regen Share", 0.9, 0.5, 1.0, 0.05, 2, "", AP1,
       "How much of the estimated regen capacity a stop may use."),
  _row("AP1LaunchJerkMax", GROUP_STOP, "Launch Jerk", 1.5, 0.5, 4.0, 0.1, 1, "m/s^3", AP1,
       "The rising jerk limit sent at low speed while pulling away."),
  # ---- 3. Curves and Pre-AP
  _row("CurveMaxLatAccel", GROUP_CURVE, "Curve Speed Lateral Cap", 2.0, 1.0, 2.0, 0.1, 1, "m/s^2", ALL,
       "The most cornering accel the curve slowdown plans for. Lower slows more for curves."),
  _row("CurveMaxDecel", GROUP_CURVE, "Curve Braking Limit", -1.2, -1.2, -0.8, 0.1, 1, "m/s^2", ALL,
       "The hardest braking the curve slowdown may ask for."),
  _row("CurveOnsetJerk", GROUP_CURVE, "Curve Braking Onset", 1.5, 0.5, 2.0, 0.1, 1, "m/s^3", ALL,
       "How fast curve braking ramps in."),
  _row("CurveReleaseJerk", GROUP_CURVE, "Curve Braking Release", 1.2, 0.5, 2.0, 0.1, 1, "m/s^3", ALL,
       "How fast curve braking ramps out."),
  _row("PreApPedalAccelMax", GROUP_CURVE, "Pedal Accel Limit", 2.5, 1.1, 2.5, 0.1, 1, "m/s^2", (P,),
       "The most accel the Comfort Pedal path will ask for. The Pre-AP accel profiles ask for up to 1.1."),
  _row("PreApPedalRegenMax", GROUP_CURVE, "Pedal Regen Limit", -1.5, -1.5, -1.0, 0.1, 1, "m/s^2", (P,),
       "The strongest regen braking the Comfort Pedal path will ask for."),
)
BY_KEY = {r.key: r for r in ROWS}
KEYS = tuple(r.key for r in ROWS)


def rows_for(car) -> tuple[Row, ...]:
  return tuple(r for r in ROWS if str(car) in r.cars)


def file_key(key: str) -> str:
  return FILE_PREFIX + key


def _dir() -> Path:
  return Path(os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))


def _params_root() -> Path:
  return Path(os.getenv("PARAMS_ROOT", "/data/params")) / "d"


def _read(path: Path):
  try:
    return path.read_text(encoding="utf-8", errors="replace").strip()
  except OSError:
    return None


def level_allows() -> bool:
  """Saved values apply at Advanced and above. Never confirmed or unreadable reads as Developer, as tuning_level does."""
  root = _params_root()
  if _read(root / "TuningLevelConfirmed") not in ("1", "true", "True"):
    return True
  try:
    return int(float(_read(root / "TuningLevel") or "3")) >= MIN_LEVEL
  except (TypeError, ValueError):
    return True


def parse(row: Row, text) -> float | None:
  """The clamped number in `text`, or None when it is not a finite number."""
  try:
    value = float(str(text).strip())
  except (TypeError, ValueError):
    return None
  return row.clamp(value) if math.isfinite(value) else None


def stored(key: str) -> float | None:
  """The clamped saved value of a row, or None when nothing usable is saved. Reads the file; for the UI."""
  row = BY_KEY[key]
  text = _read(_dir() / file_key(key))
  return None if text is None else parse(row, text)


_cache: dict | None = None


def reload() -> dict:
  """Re-read every row's file (tests and processes that start later). Returns the overrides in force."""
  global _cache
  out: dict[str, float] = {}
  try:
    if _dir().is_dir() and level_allows():
      for row in ROWS:
        value = stored(row.key)
        if value is not None:
          out[row.key] = value
  except Exception:
    out = {}
  _cache = out
  return out


def get(key: str, shipped: float) -> float:
  """The value the consumer should use: the saved (clamped) value, else `shipped` exactly (same object, bit-identical)."""
  global _cache
  if _cache is None:
    reload()
  return _cache.get(key, shipped)
