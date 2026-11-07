"""Phase 2 lane 2: Alert Volume Controller (BogPilot > Alerts and Sounds), active rows only.

Source: bogpilot-tesla 0.9.7 @ 04d560f3 frogpilot/ui/qt/offroad/sounds_settings.cc:44-80.
Base: c6582fc3. Every offered key is read by selfdrive/ui/soundd.py (Soundd.__init__) via
_bogpilot_read_param (file /data/params_bogpilot/<key> first, then Params) and applied per
AudibleAlert by alert_volumes.resolve_alert_gain in soundd_thread.
Not owned here: BogPilot Alerts rows (lane 1), test-play buttons (0.9.7 used ffplay; unverified),
any default/registry change. Writes happen only on an explicit user set; nothing is written at import.
Mandatory stock behaviour is untouched: soundd still ramps warningSoft/warningImmediate to MAX_VOLUME,
clamps WarningImmediateVolume >= 25, and alerts without a volume key (preAlert, CRITICAL_MAX) stay ambient.
"""
from __future__ import annotations

HISTORICAL_REVISION = "04d560f3ece97797b8f1ee2f714e682e6d0ef40e"
AUDITED_BASE = "c6582fc3efc1038b4e0e6bca8a6841b657e8ccf6"

PARENT_KEY = "AlertVolumeControl"
AUTO = 101
# (key, title, min, max) — ranges exactly as 0.9.7 (warnings 25..101, others 0..101)
VOLUME_ROWS: tuple[tuple[str, str, int, int], ...] = (
  ("DisengageVolume", "Disengage Volume", 0, AUTO),
  ("EngageVolume", "Engage Volume", 0, AUTO),
  ("PromptVolume", "Prompt Volume", 0, AUTO),
  ("PromptDistractedVolume", "Prompt Distracted Volume", 0, AUTO),
  ("RefuseVolume", "Refuse Volume", 0, AUTO),
  ("WarningSoftVolume", "Warning Soft Volume", 25, AUTO),
  ("WarningImmediateVolume", "Warning Immediate Volume", 25, AUTO),
)
VOLUME_KEYS = tuple(r[0] for r in VOLUME_ROWS)
OMITTED = (
  ("CustomAlerts/GreenLightAlert/LeadDepartingAlert/LoudBlindspotAlert/SpeedLimitChangedAlert", "Alerts lane 1"),
  ("GoatScream", "owner t968u: skip"),
  ("per-row test-play button", "0.9.7 ffplay path; no verified raylib/device audio path"),
)


def _sd():
  from openpilot.selfdrive.ui import soundd
  return soundd


def label(value: int) -> str:
  return "Muted" if value == 0 else "Auto" if value == AUTO else f"{value}%"


def read_controller() -> bool:
  sd = _sd()
  return sd._bogpilot_bool(sd._bogpilot_read_param(PARENT_KEY),
                           sd._bogpilot_bool(sd.FROGPILOT_VOLUME_DEFAULTS.get(PARENT_KEY), False))


def raw_volume(key: str) -> int:
  """Exactly the integer soundd loads at startup (stored, else default 101; non-numeric -> default)."""
  sd = _sd()
  return sd._bogpilot_int(sd._bogpilot_read_param(key), int(float(sd.FROGPILOT_VOLUME_DEFAULTS.get(key, "101"))))


def read_volume(key: str) -> int:
  """Value shown in the UI: soundd's value clamped to the 0.9.7 range. Out-of-range stored values are
  displayed clamped but NOT rewritten (saved prefs preserved); see raw_out_of_range()."""
  return clamp(key, raw_volume(key))


def raw_out_of_range(key: str) -> bool:
  return raw_volume(key) != read_volume(key)


def clamp(key: str, value: int) -> int:
  lo, hi = next((r[2], r[3]) for r in VOLUME_ROWS if r[0] == key)
  return max(lo, min(hi, int(value)))


def _write(key: str, text: str) -> None:
  from openpilot.common.bogpilot_store import write_text
  # soundd reads the file store first, so write there (volume keys are not compiled Params keys).
  if not write_text(key, text):
    raise OSError(f"could not write {key}")


def set_controller(on: bool) -> None:
  _write(PARENT_KEY, "1" if on else "0")


def set_volume(key: str, value: int) -> int:
  if key not in VOLUME_KEYS:
    raise KeyError(key)
  v = clamp(key, value)
  _write(key, str(v))
  return v


def rows() -> list[dict]:
  """Panel model: parent toggle, children visible only when it is on (0.9.7 FrogPilotManageControl)."""
  on = read_controller()
  out = [{"key": PARENT_KEY, "title": "Alert Volume Controller", "type": "toggle", "value": on, "visible": True}]
  for key, title, lo, hi in VOLUME_ROWS:
    v = read_volume(key)
    out.append({"key": key, "title": title, "type": "slider", "min": lo, "max": hi,
                "value": v, "label": label(v), "visible": on})
  return out


def effective_gain(key: str, ambient: float) -> float:
  """Gain current soundd applies at its next start for this row's alert using its own resolver (before the stock warning ramp)."""
  sd = _sd()
  return sd.resolve_alert_gain(alert_volume_control=read_controller(), percent=raw_volume(key),
                               ambient=ambient, key=key)
