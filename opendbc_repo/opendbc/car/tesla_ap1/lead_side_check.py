"""AP1 lead side check (phantom brake Option C), default OFF.

radard matches the camera's lead to the most likely radar track. On AP1 Bosch radar that match sometimes lands on a car
in the next lane, and the planner then slows for a car that is not in front of us. With the side check on, a radar
track can only be the camera lead's match when its sideways position is within SIDE_CHECK_LIMIT_M (2.5 m, 8.2 ft) of
the camera lead, or within 2x the camera's sideways uncertainty when that is larger. If no track is close enough, the
planner uses the camera lead (it always keeps a lead; nothing is dropped). It is only active at SIDE_CHECK_MIN_SPEED_MS
(34 mph) and up: below that the match is stock, because at stop-and-go speeds the check lost or delayed real leads in
replay.

Scope: the AP1 Model S, and the AP1 Model X only while openpilot longitudinal is on (the same cars as the AP1 radar lead
glitch filter). Pre-AP and every other car never run it. The human lane change adjacent-lead preference is unchanged.

File-backed under /data/params_bogpilot/AP1LeadSideCheck (the prebuilt params table has no key for it). Missing, empty
or unknown => off. "1"/"true"/"on" => on. Read once when radard starts (the next car start).

  echo 1 > /data/params_bogpilot/AP1LeadSideCheck   # on
  echo 0 > /data/params_bogpilot/AP1LeadSideCheck   # off (default)
"""
from pathlib import Path

SIDE_CHECK_KEY = "AP1LeadSideCheck"
SIDE_CHECK_PATH = Path("/data/params_bogpilot") / SIDE_CHECK_KEY
# Tests may override the path via this module attribute.
_side_check_path = SIDE_CHECK_PATH

SIDE_CHECK_LIMIT_M = 2.5                 # 8.2 ft
SIDE_CHECK_YSTD_FACTOR = 2.0             # or 2x the camera lead's sideways std, whichever is larger
SIDE_CHECK_MIN_SPEED_MS = 34 * 0.44704   # 34 mph (15.2 m/s); off below


def _as_text(stored) -> str:
  if stored is None:
    return ""
  if isinstance(stored, bytes):
    stored = stored.decode(errors="replace")
  return str(stored).strip().lower()


def side_check_enabled(stored=None, path: Path | None = None) -> bool:
  """The user's setting. Default off. `stored` overrides the file (tests)."""
  if stored is None:
    target = path if path is not None else _side_check_path
    try:
      stored = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    except OSError:
      stored = ""
  return _as_text(stored) in ("1", "true", "on")


def set_side_check(enabled: bool, path: Path | None = None) -> None:
  target = path if path is not None else _side_check_path
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text("1" if enabled else "0")


def side_check_platform(car_fingerprint, op_long: bool = False) -> bool:
  """AP1 Model S, and the AP1 Model X with openpilot longitudinal. Never Pre-AP or any other car."""
  fp = str(car_fingerprint)
  return fp == "TESLA_AP1_MODELS" or (fp == "TESLA_AP1_MODELX" and bool(op_long))


def side_check_active(car_fingerprint, op_long: bool = False, stored=None, path: Path | None = None) -> bool:
  return side_check_platform(car_fingerprint, op_long) and side_check_enabled(stored=stored, path=path)


def side_check_limit(lead_y_std: float) -> float:
  return max(SIDE_CHECK_LIMIT_M, SIDE_CHECK_YSTD_FACTOR * float(lead_y_std))


def track_within_side_limit(track_y_rel: float, lead_y: float, lead_y_std: float) -> bool:
  """radar yRel is left-positive, model y is right-positive: the sideways gap is |yRel + y|."""
  return abs(float(track_y_rel) + float(lead_y)) <= side_check_limit(lead_y_std)
