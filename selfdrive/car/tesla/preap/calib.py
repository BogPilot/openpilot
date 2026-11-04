"""Comma Pedal calibration math and gating — from NotAutopilot nap_conf.

Credit: NotAutopilot. User-facing product name: BogPilot.
"""
from __future__ import annotations

from openpilot.selfdrive.car.tesla.preap.params import (
  DEFAULTS,
  PreApParamKeys,
  get_bool,
  get_float,
  get_int,
  set_bool,
  set_float,
)

# DI units (NotAutopilot)
PEDAL_DI_ZERO = 0.0
PEDAL_DI_PRESSED = 2.0

STATUS_NOT_DETECTED = "not_detected"
STATUS_NEEDS_CALIBRATION = "needs_calibration"
STATUS_READY = "ready"


def transform_di_to_pedal(val: float, pedal_zero: float, pedal_factor: float) -> float:
  """DI units -> pedal command voltage/percent."""
  if pedal_factor == 0:
    pedal_factor = 1.0
  return pedal_zero + (val - PEDAL_DI_ZERO) / pedal_factor


def transform_pedal_to_di(val: float, pedal_zero: float, pedal_factor: float) -> float:
  """Pedal voltage/percent -> DI units."""
  return PEDAL_DI_ZERO + (val - pedal_zero) * pedal_factor


def coast_pedal_zero(calib_zero: float, pedal_factor: float) -> float:
  """Coast position: calib_zero - 1/factor (NotAutopilot pedal_zero property)."""
  if pedal_factor == 0:
    pedal_factor = 1.0
  return calib_zero - 1.0 / pedal_factor


def compute_calibration(coast_raw: float, pressed_raw: float) -> dict[str, float]:
  """Compute calib fields from foot-off and full-press samples.

  factor = 100 / (pressed - coast) when span is usable; otherwise leave safe
  incomplete values (caller must not mark done).
  """
  span = float(pressed_raw) - float(coast_raw)
  if abs(span) < 1e-3:
    return {
      "pedal_calib_zero": float(coast_raw),
      "pedal_calib_factor": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_FACTOR]),
      "pedal_calib_min": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_MIN]),
      "pedal_calib_max": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_MAX]),
      "ok": 0.0,
    }
  factor = 100.0 / span
  return {
    "pedal_calib_zero": float(coast_raw),
    "pedal_calib_factor": float(factor),
    "pedal_calib_min": float(min(coast_raw, pressed_raw)),
    "pedal_calib_max": float(max(coast_raw, pressed_raw)),
    "ok": 1.0,
  }


def is_pedal_calibrated(done: bool | None = None, zero: float | None = None,
                        factor: float | None = None) -> bool:
  """Defaults-sanity: done flag only counts if zero or factor left defaults."""
  if done is None:
    done = get_bool(PreApParamKeys.PEDAL_CALIB_DONE)
  if not done:
    return False
  if zero is None:
    zero = get_float(PreApParamKeys.PEDAL_CALIB_ZERO)
  if factor is None:
    factor = get_float(PreApParamKeys.PEDAL_CALIB_FACTOR)
  if zero == float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_ZERO]) and \
     factor == float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_FACTOR]):
    return False
  return True


def pedal_detected(stored: bool | None = None) -> bool:
  if stored is None:
    return get_bool(PreApParamKeys.PEDAL_DETECTED, False)
  return bool(stored)


def pedal_status(*, detected: bool | None = None, calibrated: bool | None = None) -> str:
  if detected is None:
    detected = pedal_detected()
  if not detected:
    return STATUS_NOT_DETECTED
  if calibrated is None:
    calibrated = is_pedal_calibrated()
  if not calibrated:
    return STATUS_NEEDS_CALIBRATION
  return STATUS_READY


def pedal_long_allowed(*, user_wants_long: bool, detected: bool | None = None,
                       calibrated: bool | None = None) -> bool:
  """Pedal long engages only when user wants it AND pedal detected AND calibrated."""
  if not user_wants_long:
    return False
  if detected is None:
    detected = pedal_detected()
  if calibrated is None:
    calibrated = is_pedal_calibrated()
  return bool(detected and calibrated)


def pedal_can_bus() -> int:
  bus = get_int(PreApParamKeys.PEDAL_CAN_BUS, 2)
  return 0 if bus == 0 else 2


def apply_calibration_result(result: dict[str, float]) -> bool:
  """Persist a successful compute_calibration result and mark done."""
  if not result.get("ok"):
    return False
  set_float(PreApParamKeys.PEDAL_CALIB_ZERO, result["pedal_calib_zero"])
  set_float(PreApParamKeys.PEDAL_CALIB_FACTOR, result["pedal_calib_factor"])
  set_float(PreApParamKeys.PEDAL_CALIB_MIN, result["pedal_calib_min"])
  set_float(PreApParamKeys.PEDAL_CALIB_MAX, result["pedal_calib_max"])
  set_bool(PreApParamKeys.PEDAL_CALIB_DONE, True)
  set_bool(PreApParamKeys.PEDAL_CALIB_ARMED, False)
  return True


def current_pedal_transform() -> tuple[float, float]:
  """Return (pedal_zero_coast, factor) for command mapping."""
  factor = get_float(PreApParamKeys.PEDAL_CALIB_FACTOR)
  zero = coast_pedal_zero(get_float(PreApParamKeys.PEDAL_CALIB_ZERO), factor)
  return zero, factor
