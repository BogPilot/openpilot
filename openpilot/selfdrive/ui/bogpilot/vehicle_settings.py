"""Vehicle settings model: restored from BogPilot 568fea frogpilot/ui/qt/offroad/vehicle_settings.cc.

Only rows with an active consumer in this tree are offered (t964u):
  DisableOpenpilotLongitudinal      -> tesla_ap1 interface disable_openpilot_long() (car init) and onroad toggles
  EnableICIntegration (AP1)         -> tesla_ap1.toggles.enable_ic_integration (cluster TX, live)
  RegenComfortBrake (AP1)           -> tesla_ap1.regen_brake.regen_comfort_brake_enabled (lead MPC, live)
  Vehicle Info (read-only)          -> CarParams of the detected car
Not offered (no active consumer): Car Make/Model + ForceFingerprint (get_car only honours env FINGERPRINT),
Pre-AP pedal/radar rows (na-preap only), GM/HKG/Honda/Subaru/Toyota rows, Wheel Controls, TeslaEarly.
"""
from __future__ import annotations

from pathlib import Path

DISABLE_LONG_KEY = "DisableOpenpilotLongitudinal"
AP1_FINGERPRINT = "TESLA_AP1_MODELS"


def _text(v) -> str:
  if v is None:
    return ""
  if isinstance(v, (bytes, bytearray)):
    v = v.decode(errors="replace")
  return str(v).strip()


# ---- DisableOpenpilotLongitudinal: Params plus the file the car interface reads first ----
def disable_long_effective(file_dir: Path | None = None, params_file: Path | None = None) -> bool:
  """Exactly what the tesla_ap1 interface will read at car start (file dir first, then the Params file)."""
  from opendbc.car.tesla_ap1 import toggles
  if file_dir is None and params_file is None:
    return toggles.disable_openpilot_long()
  paths = (Path(file_dir or toggles.IC_INTEGRATION_DIR) / DISABLE_LONG_KEY,
           Path(params_file) if params_file else toggles.DISABLE_OP_LONG_PATHS[1])
  return toggles.disable_openpilot_long(paths=paths)


def set_disable_long(params, state: bool, file_dir: Path | None = None) -> None:
  params.put_bool(DISABLE_LONG_KEY, bool(state), block=True)
  from opendbc.car.tesla_ap1 import toggles
  f = (Path(file_dir) if file_dir else toggles.IC_INTEGRATION_DIR) / DISABLE_LONG_KEY
  if f.is_file():  # interface reads this before Params; keep it from overriding the user's choice
    f.write_text("1" if state else "0")


def disable_long_visible(CP) -> bool:
  """Old rule: shown when the car supports openpilot long or it is currently disabled; not for alpha long."""
  if CP is None:
    return False
  if getattr(CP, "alphaLongitudinalAvailable", False):
    return False
  return bool(getattr(CP, "openpilotLongitudinalControl", False)) or disable_long_effective()


# ---- AP1 file-backed rows via their consumers' own readers/writers ----
def ap1_rows():
  from opendbc.car.tesla_ap1 import regen_brake, toggles
  return {
    "EnableICIntegration": (toggles.enable_ic_integration, toggles.set_enable_ic_integration),
    "RegenComfortBrake": (regen_brake.regen_comfort_brake_enabled, regen_brake.set_regen_comfort_brake),
  }


def vehicle_info(CP) -> dict[str, str]:
  if CP is None or not _text(CP.carFingerprint):
    return {"Detected": "No connected vehicle"}
  def yes(value):
    return "Yes" if value else "No"
  return {"Detected": _text(CP.carFingerprint),
          "openpilot Longitudinal Support": yes(CP.openpilotLongitudinalControl),
          "Radar Support": yes(not CP.radarUnavailable),
          "Stop-and-Go Support": yes(CP.autoResumeSng)}
