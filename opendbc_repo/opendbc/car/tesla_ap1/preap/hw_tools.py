"""Pre-AP hardware-variant tools: Pedal Emergency Disable and Reset Hardware Settings.

Pure parameter logic, no UI and no CAN. The Vehicle Settings page (selfdrive/ui/bogpilot/phase2_vehicle.py) calls these; the
car process picks the new values up through its params snapshot (preap/params.py StepCache, refreshed every 0.1 s).

Credit: NotAutopilot (MIT, Copyright comma.ai) nap-dev selfdrive/ui/layouts/settings/nap.py `_on_emergency_disable` (drops the
pedal flag and clears PedalCalibDone) and `_on_reset_defaults` (writes the default of each NAP param). BogPilot's reset is
narrower than NAP's, as chosen: only the pedal calibration, the Bosch radar settings, the radar offset and the saved stalk-retrofit detection.

Pedal Emergency Disable
  Live part: PedalCalibDone goes False. preap/calib.pedal_long_allowed() needs a calibrated pedal, so pedal longitudinal stops
  asking for the pedal within one params refresh, while driving, and the pedal authority releases it the way it does for any
  calibration loss. The saved zero / factor / min / max are left as they are (NAP clears the done flag only); the next
  successful calibration overwrites them. An armed or half-finished calibration is cancelled.
  Restart part: the pedal flag (Disable Pedal Longitudinal, DisableOpenpilotLongitudinal) is written by the page through the
  same onroad staging as the existing row (it is applied when the car is off), because the planners read that flag live.

Reset Hardware Settings
  Writes the shipped default of each key in HW_RESET_KEYS and nothing else. It does not touch Disable Pedal Longitudinal, iBooster,
  Auto Speed, Double Pull, Override Sensitivity or any non-Pre-AP setting.
"""
from __future__ import annotations

from collections.abc import Callable

from opendbc.car.tesla_ap1.preap import calib
from opendbc.car.tesla_ap1.preap import params as P
from opendbc.car.tesla_ap1.preap.params import DEFAULTS, PreApParamKeys as K

# Pedal: the calibration the guided screen saves, and the pedal bus. (Runtime keys such as PedalDetected / PedalSeenTs are not settings.)
PEDAL_RESET_KEYS = (K.PEDAL_CALIB_DONE, K.PEDAL_CALIB_MIN, K.PEDAL_CALIB_MAX, K.PEDAL_CALIB_FACTOR, K.PEDAL_CALIB_ZERO, K.PEDAL_CAN_BUS)
# Radar: every Bosch radar setting row, including the donor VIN (default empty = this car) and the lateral offset.
RADAR_RESET_KEYS = (K.RADAR_ENABLED, K.RADAR_BEHIND_NOSECONE, K.RADAR_DONOR_VIN, K.RADAR_DONOR_TYPE, K.RADAR_EPAS_TYPE,
                    K.RADAR_IGNORE_HW_FAIL, K.RADAR_FLIP, K.RADAR_OFFSET)
# Stalk: forget a saved AP1 follow-distance stalk detection (preap/stalk_retrofit.py); the next start detects again.
STALK_RESET_KEYS = (K.STALK_RETROFIT_DETECTED,)
HW_RESET_KEYS = PEDAL_RESET_KEYS + RADAR_RESET_KEYS + STALK_RESET_KEYS


def clear_calibration_runtime() -> None:
  """Cancel an armed or half-finished calibration (the runtime keys only; no saved value is touched)."""
  P.set_bool(K.PEDAL_CALIB_ARMED, False)
  P.set_str(K.PEDAL_CALIB_MESSAGE, "")
  calib.set_stage(calib.STAGE_IDLE)


def clear_pedal_calibration() -> None:
  """NAP Emergency Disable's calibration half: the pedal counts as uncalibrated from now on, a running calibration is cancelled."""
  P.set_bool(K.PEDAL_CALIB_DONE, False)        # first: this is the live stop
  clear_calibration_runtime()


def hw_reset_defaults() -> dict:
  """{key: shipped default} for Reset Hardware Settings, in write order (calibration flag first, then the other pedal values, then radar)."""
  return {key: DEFAULTS[key] for key in HW_RESET_KEYS}


def write_default(key: str, value) -> None:
  """Write one reset default through the typed setters. Refuses a key outside the reset table (a typo can never reset another setting)."""
  if key not in HW_RESET_KEYS:
    raise KeyError(key)
  if isinstance(value, bool):
    P.set_bool(key, value)
  elif isinstance(value, int):
    P.set_int(key, value)
  elif isinstance(value, float):
    P.set_float(key, value)
  else:
    P.set_str(key, str(value))


def reset_hw_settings(write: Callable[[str, object], object] = write_default) -> list[str]:
  """Reset every key in HW_RESET_KEYS to its default and drop any running calibration. Returns the keys written, in order."""
  written = []
  for key, value in hw_reset_defaults().items():
    write(key, value)
    written.append(key)
  clear_calibration_runtime()
  return written
