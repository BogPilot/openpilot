"""BogPilot alert-volume policy for AGNOS 12.8 / 19.9 ports (stream 7).

FrogPilot table defaults (frogpilot_variables / frogpilot_defaults):
  AlertVolumeControl = 0 (off) — ambient volume for every alert, including engage/disengage
  EngageVolume / DisengageVolume / Prompt* / Refuse / Warning* = 101 (auto) when the controller is on

The old AP1 one-time profile muted engage/disengage (AlertVolumeControl=1, volumes 0)
because the car already chimes. Owner decision for the new bases: do **not** mute.
AP1_VOLUME_PROFILE below matches FrogPilot defaults so engage/disengage stay audible.
"""
from __future__ import annotations

# FrogPilot / BogPilot table defaults (percent; 101 = auto/ambient)
FROGPILOT_VOLUME_DEFAULTS: dict[str, str] = {
  "AlertVolumeControl": "0",
  "EngageVolume": "101",
  "DisengageVolume": "101",
  "PromptVolume": "101",
  "PromptDistractedVolume": "101",
  "RefuseVolume": "101",
  "WarningSoftVolume": "101",
  "WarningImmediateVolume": "101",
}

# One-time AP1 shipping profile for alert volumes ONLY.
# Intentionally identical to FrogPilot defaults — NOT the legacy mute.
AP1_VOLUME_PROFILE: dict[str, str] = dict(FROGPILOT_VOLUME_DEFAULTS)

AUTO_VOLUME_PERCENT = 101
WARNING_IMMEDIATE_MIN_PERCENT = 25
# Safety alert categories can never be muted below an audible floor (consumer-side, independent of the UI).
# promptRepeat shares PromptVolume. Engage / Disengage / Refuse are informational and stay mutable.
SAFETY_FLOOR_PERCENT = 25
SAFETY_FLOOR_KEYS: tuple[str, ...] = (
  "PromptVolume",
  "PromptDistractedVolume",
  "WarningSoftVolume",
  "WarningImmediateVolume",
)

VOLUME_PARAM_KEYS: tuple[str, ...] = (
  "EngageVolume",
  "DisengageVolume",
  "RefuseVolume",
  "PromptVolume",
  "PromptDistractedVolume",
  "WarningSoftVolume",
  "WarningImmediateVolume",
)


def values_equal(stored: str | None, expected) -> bool:
  """Match ap1_defaults.values_equal for volume strings like '0.000000' vs 0."""
  if stored is None:
    return False
  try:
    return float(stored) == float(expected)
  except (TypeError, ValueError):
    return str(stored).strip() == str(expected).strip()


def is_muted_engage_disengage(profile: dict[str, str]) -> bool:
  """True when a profile would silence engage and disengage chimes."""
  try:
    ctrl = str(profile.get("AlertVolumeControl", "0")).strip() in ("1", "true", "on")
    eng = float(profile.get("EngageVolume", "101"))
    dis = float(profile.get("DisengageVolume", "101"))
  except (TypeError, ValueError):
    return False
  return ctrl and eng == 0.0 and dis == 0.0


def volume_fraction(percent: int | float, *, key: str | None = None) -> float:
  """Convert a FrogPilot percent setting to a soundd gain. 101 -> sentinel 1.01 (auto)."""
  pct = int(percent)
  if key in SAFETY_FLOOR_KEYS:
    pct = max(pct, SAFETY_FLOOR_PERCENT)
  return pct / 100.0


def resolve_alert_gain(
  *,
  alert_volume_control: bool,
  percent: int,
  ambient: float,
  key: str | None = None,
) -> float:
  """Gain to apply for one alert. Controller off -> ambient. 101 -> ambient. Else percent/100."""
  if not alert_volume_control:
    return ambient
  frac = volume_fraction(percent, key=key)
  if abs(frac - 1.01) < 1e-9:
    return ambient
  return frac
