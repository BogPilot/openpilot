"""BogPilot Pre-AP param keys (file-backed under /data/params_bogpilot).

July prebuilt params_pyx.so cannot store new Params keys (UnknownKeyName at
boot if added to frogpilot_default_params). Same pattern as EnableICIntegration.

Credit: NotAutopilot nap_params / nap_conf (names without NAP prefix).
User-facing product name: BogPilot.
"""
from __future__ import annotations

from pathlib import Path

PARAMS_DIR = Path("/data/params_bogpilot")

# Registration SoT — key names used by UI, car code, and tests.
class PreApParamKeys:
  PEDAL_CALIB_DONE = "PedalCalibDone"
  PEDAL_CALIB_MIN = "PedalCalibMin"
  PEDAL_CALIB_MAX = "PedalCalibMax"
  PEDAL_CALIB_FACTOR = "PedalCalibFactor"
  PEDAL_CALIB_ZERO = "PedalCalibZero"
  PEDAL_CAN_BUS = "PedalCanBus"
  PEDAL_CALIB_ARMED = "PedalCalibArmed"  # runtime: UI arms, car completes
  PEDAL_DETECTED = "PedalDetected"      # runtime mirror for UI status line
  RADAR_ENABLED = "TeslaRadarEnabled"
  RADAR_BEHIND_NOSECONE = "TeslaRadarBehindNosecone"
  RADAR_OFFSET = "TeslaRadarOffset"  # meters internally
  # NAP NAPRadarIgnoreHwFail (default off). Hides RADC_HWFail; SGUFail already ignored on Pre-AP.
  RADAR_IGNORE_HW_FAIL = "TeslaRadarIgnoreHwFail"
  # Opt-in F190 donor VIN read (Phase A). Default off. Never log the stored VIN.
  RADAR_READ_VIN = "TeslaRadarReadVin"
  RADAR_DONOR_VIN = "TeslaRadarDonorVin"  # 17-char; file-backed; never log


# Safe defaults (match NotAutopilot DEFAULT_CONFIG; radar off).
DEFAULTS = {
  PreApParamKeys.PEDAL_CALIB_DONE: False,
  PreApParamKeys.PEDAL_CALIB_MIN: -3.0,
  PreApParamKeys.PEDAL_CALIB_MAX: 99.6,
  PreApParamKeys.PEDAL_CALIB_FACTOR: 1.0,
  PreApParamKeys.PEDAL_CALIB_ZERO: 0.0,
  PreApParamKeys.PEDAL_CAN_BUS: 2,
  PreApParamKeys.PEDAL_CALIB_ARMED: False,
  PreApParamKeys.PEDAL_DETECTED: False,
  PreApParamKeys.RADAR_ENABLED: False,
  PreApParamKeys.RADAR_BEHIND_NOSECONE: False,
  PreApParamKeys.RADAR_OFFSET: 0.0,
  PreApParamKeys.RADAR_IGNORE_HW_FAIL: False,
  PreApParamKeys.RADAR_READ_VIN: False,
  PreApParamKeys.RADAR_DONOR_VIN: "",
}

# Overridable in tests.
_params_dir = PARAMS_DIR


def _path(key: str) -> Path:
  return _params_dir / key


def _read_text(key: str) -> str:
  try:
    p = _path(key)
    if p.is_file():
      return p.read_text(encoding="utf-8", errors="replace").strip()
  except OSError:
    pass
  return ""


def _write_text(key: str, text: str) -> None:
  _params_dir.mkdir(parents=True, exist_ok=True)
  _path(key).write_text(text, encoding="utf-8")


def get_bool(key: str, default: bool | None = None) -> bool:
  if default is None:
    default = bool(DEFAULTS.get(key, False))
  text = _read_text(key)
  if text == "":
    return default
  if text in ("1", "true", "on"):
    return True
  if text in ("0", "false", "off"):
    return False
  return default


def set_bool(key: str, value: bool) -> None:
  # Avoid rewriting identical values every controlsd frame (PedalDetected mirror).
  want = "1" if value else "0"
  if _read_text(key) == want:
    return
  try:
    _write_text(key, want)
  except OSError:
    # Fresh device / read-only /data must not kill controlsd.
    pass


def get_float(key: str, default: float | None = None) -> float:
  if default is None:
    default = float(DEFAULTS.get(key, 0.0))
  text = _read_text(key)
  if text == "":
    return default
  try:
    return float(text)
  except ValueError:
    return default


def set_float(key: str, value: float) -> None:
  _write_text(key, repr(float(value)))


def get_int(key: str, default: int | None = None) -> int:
  if default is None:
    default = int(DEFAULTS.get(key, 0))
  text = _read_text(key)
  if text == "":
    return default
  try:
    return int(float(text))
  except ValueError:
    return default


def set_int(key: str, value: int) -> None:
  _write_text(key, str(int(value)))


def get_str(key: str, default: str | None = None) -> str:
  if default is None:
    default = str(DEFAULTS.get(key, ""))
  text = _read_text(key)
  return default if text == "" else text


def set_str(key: str, value: str) -> None:
  # Do not log value — may hold a donor VIN.
  try:
    _write_text(key, str(value))
  except OSError:
    pass
