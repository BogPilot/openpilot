"""BogPilot: 367e1fe FrogPilot toggle semantics for the system daemons (no UI, no car code).

Every getter follows frogpilot_variables.py @ 367e1fe: a param is honoured only when the user's
tuning level reaches the param's level (bogpilot_params.BOGPILOT_PARAMS column 4); otherwise the
367e1fe default applies. Unconfirmed tuning level counts as 3 (all params honoured).
"""
from __future__ import annotations

from pathlib import Path

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.params import Params
from openpilot.common.version import BOGPILOT_BRANCHES

VBATT_PAUSE_CHARGING = 11.8  # system/hardware/power_monitoring.py
LOW_VOLTAGE_MAX = 12.5
BACKUP_PATH = Path("/cache/on_backup")
# frogpilot_variables.py: release_branch / vetting_branch (AutomaticUpdates is only user-settable there)
RELEASE_CHANNELS = frozenset({"FrogPilot", *BOGPILOT_BRANCHES})
VETTING_CHANNELS = frozenset({"FrogPilot-Vetting"})


def _level(key: str) -> int:
  return BOGPILOT_PARAMS[key][3]


def _default(key: str) -> str:
  return BOGPILOT_PARAMS[key][2] or ""


def tuning_level(params: Params) -> int:
  return params.get_int("TuningLevel") if params.get_bool("TuningLevelConfirmed") else 3


def _honoured(params: Params, key: str) -> bool:
  return tuning_level(params) >= _level(key)


def _bool(params: Params, key: str) -> bool:
  """Unset (never written) reads as the 367e1fe default, not False."""
  return params.get_bool(key) if params.get(key) is not None else _default(key) == "1"


def get_bool(params: Params, key: str) -> bool:
  if _honoured(params, key):
    return _bool(params, key)
  return _default(key) == "1"


def get_int(params: Params, key: str) -> int:
  if _honoured(params, key):
    return params.get_int(key, default=int(float(_default(key) or 0)))
  return int(float(_default(key) or 0))


def get_float(params: Params, key: str) -> float:
  if _honoured(params, key):
    return params.get_float(key, default=float(_default(key) or 0))
  return float(_default(key) or 0)


def lead_detection_probability(params: Params, openpilot_longitudinal: bool = True) -> float:
  """radard lead prob gate. frogpilot_variables.py: LeadDetectionThreshold / 100 clipped to
  [0.25, 0.50] when LongitudinalTune is on (openpilot long only) and the level is honoured,
  otherwise the 367e1fe default (35 -> 0.35)."""
  key = "LeadDetectionThreshold"
  if openpilot_longitudinal and get_bool(params, "LongitudinalTune") and _honoured(params, key):
    return min(max(params.get_int(key, default=int(_default(key))) / 100, 0.25), 0.50)
  return int(_default(key)) / 100


def device_management(params: Params) -> bool:
  return get_bool(params, "DeviceManagement")


def device_shutdown_time(params: Params) -> float:
  """Seconds offroad before shutdown. Setting 0..3 = 15 min steps (0 -> 5 min), >= 4 = (n-3) hours.
  367e1fe default 9 -> 6 h (stock openpilot 30 h)."""
  if device_management(params) and _honoured(params, "DeviceShutdown"):
    s = params.get_int("DeviceShutdown", default=int(_default("DeviceShutdown")))
  else:
    s = int(_default("DeviceShutdown"))
  return (s - 3) * 3600 if s >= 4 else (s * (60 * 15) or 300)


def low_voltage_shutdown(params: Params) -> float:
  """Volts (LPF car battery) below which the device shuts down offroad. Clipped to [11.8, 12.5]."""
  if device_management(params) and _honoured(params, "LowVoltageShutdown"):
    v = params.get_float("LowVoltageShutdown", default=float(_default("LowVoltageShutdown")))
    return min(max(v, VBATT_PAUSE_CHARGING), LOW_VOLTAGE_MAX)
  return float(_default("LowVoltageShutdown"))


def automatic_updates(params: Params, channel: str | None = None) -> bool:
  if channel is None:
    try:
      from openpilot.common.version import get_build_metadata
      channel = get_build_metadata().channel
    except Exception:
      channel = ""
  if _honoured(params, "AutomaticUpdates") and (channel in RELEASE_CHANNELS or channel in VETTING_CHANNELS):
    on = _bool(params, "AutomaticUpdates")
  else:
    on = _default("AutomaticUpdates") == "1"
  return on and not BACKUP_PATH.is_file()
