"""Which cars may run curve speed control (CSC) and when a Pre-AP car may let it control speed.

BogPilot 0.9.7 / na-preap @568fea947 ran the vision-only CSC on any car with openpilot longitudinal and the
CurveSpeedController toggle (frogpilot_variables.py:851, frogpilot_vcruise.py:54-70), Pre-AP pedal cars
included; road curvature came from modelV2 only (frogpilot_utilities.py:104-115 calculate_road_curvature).
This tree keeps the AP1 gate and adds Pre-AP back, stricter than 0.9.7:

  * AP1 (TESLA_AP1_MODELS) with openpilot longitudinal: unchanged.
  * AP1 Model X (TESLA_AP1_MODELX) with openpilot longitudinal (the AP1XOpenpilotLong opt-in): the same as the AP1
    Model S (same Curve Speed Control, Smooth Curve Braking, Map Curve Speed, the same 2.0 m/s^2 cornering cap). With
    stock cruise the X never runs it. The cap is provisional on the X: no X drive with openpilot longitudinal and
    real cornering exists yet, so nothing in X data justifies a different value.
  * Pre-AP (TESLA_PREAP_MODELS) only with openpilot longitudinal (pcmCruise False) AND a stored, detected and
    calibrated Comma Pedal (preap/calib.py pedal_long_allowed). Never on a no-pedal Pre-AP car: stock cruise
    owns speed there.
  * On Pre-AP, CSC may lower the cruise speed or brake only while the pedal is live on its latched bus
    (carState.bogpilot preapPedalDetected / preapPedalCalibrated, not preapPedalUnavailable or
    preapPedalNotResponding) AND the pull FSM is in FULL (preapFsmMode 4, preap/engagement.py Mode.FULL).
    Never in steering only. Missing fields fail closed.

Userspace only: no panda, safety, DBC or CAN signal is added or changed.
"""
from __future__ import annotations

AP1 = "TESLA_AP1_MODELS"
AP1_X = "TESLA_AP1_MODELX"
PREAP = "TESLA_PREAP_MODELS"
PREAP_FSM_FULL = 4   # opendbc tesla_ap1/preap/engagement.py Mode.FULL, published as carState.bogpilot.preapFsmMode


def stored_pedal_ok() -> bool:
  """Stored pedal state: detected and calibrated (preap/calib.py pedal_long_allowed). Any failure reads as no pedal."""
  try:
    from opendbc.car.tesla_ap1.preap.calib import pedal_long_allowed
    return bool(pedal_long_allowed(user_wants_long=True))
  except Exception:
    return False


def csc_supported(CP, pedal_ok: bool | None = None) -> bool:
  """CSC is available on this car: AP1 Model S or Model X + openpilot long, or Pre-AP + openpilot long + a calibrated pedal."""
  if CP is None or not bool(getattr(CP, "openpilotLongitudinalControl", False)):
    return False
  fp = str(getattr(CP, "carFingerprint", "") or "")
  if fp in (AP1, AP1_X):
    return True
  if fp == PREAP:
    if bool(getattr(CP, "pcmCruise", True)):
      return False
    return stored_pedal_ok() if pedal_ok is None else bool(pedal_ok)
  return False


def is_preap(CP) -> bool:
  return str(getattr(CP, "carFingerprint", "") or "") == PREAP


def preap_pedal_live(CS) -> bool:
  """The pedal is heard on its latched bus, calibrated, acquired and responding. Missing fields fail closed."""
  try:
    bp = CS.bogpilot
    return (bool(bp.preapPedalDetected) and bool(bp.preapPedalCalibrated)
            and not bool(bp.preapPedalUnavailable) and not bool(bp.preapPedalNotResponding))
  except AttributeError:
    return False


def preap_full(CS) -> bool:
  """The Pre-AP pull FSM is in FULL (steering + speed control). Anything else, or a missing field, is False."""
  try:
    return int(CS.bogpilot.preapFsmMode) == PREAP_FSM_FULL
  except (AttributeError, TypeError, ValueError):
    return False


def csc_gate(preap: bool, CS) -> tuple[bool, bool]:
  """(active, may_control) for one planner step. AP1: (True, True). Pre-AP: inactive without a live pedal; active but
  never controlling outside FULL (steering only may still learn, 0.9.7 trained while longActive was False,
  curve_speed_controller.py:35-37); controlling only in FULL."""
  if not preap:
    return True, True
  if not preap_pedal_live(CS):
    return False, False
  return True, preap_full(CS)


def csc_row_visible(CP, pedal_ok: bool | None = None) -> bool:
  """Settings row for CurveSpeedController (and its children): AP1 Model S or X + openpilot long, or Pre-AP with a calibrated
  pedal (stored state, so it shows offroad once calibrated). Hidden on a no-pedal Pre-AP car and without CarParams."""
  return csc_supported(CP, pedal_ok)
