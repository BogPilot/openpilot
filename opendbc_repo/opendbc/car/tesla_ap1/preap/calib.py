"""Comma Pedal calibration math and gating — from BogPilot 0.9.7 na-preap calib.py.

Driver-press capture only (no commanded gas; never unlock panda for calib).
Credit: NotAutopilot (NAP) nap_conf @ e99f4dc75 (opendbc cc39c7fa), via BogPilot 0.9.7 na-preap 568fea947 calib.py. User-facing product name: BogPilot.
The saved zero follows Tinkla calibratePedal.py (BogGyver/openpilot tesla_unity_dev @ 501c7de): PedalCalibZero is the pedal reading where the car
first reports throttle, PedalCalibMin is the resting mean (see the step 2 notes below).
"""
from __future__ import annotations

import math
import statistics
import time

from opendbc.car.tesla_ap1.preap.pedal_can import PEDAL_ENABLED_COMMAND_LIMIT, accel_command_to_raw
from opendbc.car.tesla_ap1.preap.vdas_constants import PEDAL_MAX_VALUES
from opendbc.car.tesla_ap1.preap.params import (
  DEFAULTS,
  PreApParamKeys,
  get_bool,
  get_float,
  get_int,
  get_str,
  set_bool,
  set_float,
  set_str,
)

# Capture progress the car publishes for the guided UI screen (read-only for the UI).
STAGE_IDLE = ""
STAGE_COAST = "coast"          # armed, waiting for a quiet interceptor with no car gas
STAGE_COAST_OK = "coast_ok"    # coast captured, waiting for the driver press
STAGE_SAVED = "saved"
STAGE_FAILED = "failed"
# The failure reason is shown on the guided screen. na-preap (BogPilot 0.9.7 Pre-AP) stored only the first 120 characters, which cut the reason
# (and its "try again" advice) off mid-word; UI text only, no calibration value or threshold changed.
MESSAGE_MAX = 300
PEDAL_LIVE_S = 3.0             # PedalSeenTs older than this = the pedal is not being heard now

# DI units (NAP nap_conf / na-preap calib.py)
PEDAL_DI_ZERO = 0.0
PEDAL_DI_PRESSED = 2.0

STATUS_NOT_DETECTED = "not_detected"
STATUS_NEEDS_CALIBRATION = "needs_calibration"
STATUS_READY = "ready"
STATUS_CALIBRATING = "calibrating"
STATUS_FAILED = "failed"

# Reject the known-bad Ready (raw 0.762→6.451, span 5.69, factor ≈17.577).
# A real full press measured ~0.94 factor (span ≈106). MIN_SPAN of 10 alone
# would have rejected that capture; factor bounds reject other noise saves.
MIN_SPAN = 10.0
FACTOR_MAX = 3.0

# Pedal scale (the "factor" in the code) = 100 / span of a full driver press. The pedal command for a planner pedal position `di`
# is calib_zero - 1/scale + di/scale, and the planner never goes above PEDAL_DI_MAX. The panda drops any enabled command above
# PEDAL_ENABLED_RAW_LIMIT (pedal_can.py), so the encoder clamps every command to PEDAL_ENABLED_COMMAND_LIMIT (the one shared limit).
# A low scale therefore cannot overrun the panda cap; it only loses some top-end acceleration: planner positions above
#   max_reachable_di = 1 + scale * (PEDAL_ENABLED_COMMAND_LIMIT - calib_zero)
# all send the same (clamped) command. Fixed window, fixed: 0.82 to 3.0. The bounds will be revisited after the
# tester's 0.11.2 calibration and first-drive rlogs.
PEDAL_DI_MAX = max(PEDAL_MAX_VALUES)
FACTOR_MIN = 0.82


def max_reachable_di(calib_zero: float, factor: float) -> float:
  """Highest planner pedal position (DI %, 0 to PEDAL_DI_MAX) whose command is not clamped by the shared limit."""
  return max(0.0, min(PEDAL_DI_MAX, 1.0 + float(factor) * (PEDAL_ENABLED_COMMAND_LIMIT - float(calib_zero))))


def worst_case_raw_gas_cmd(calib_zero: float, factor: float) -> int:
  """The raw 0x551 command field the highest normal pedal command (planner at PEDAL_DI_MAX) asks for, BEFORE the encoder clamp."""
  zero = calib_zero - 1.0 / factor
  return accel_command_to_raw(zero + PEDAL_DI_MAX / factor)


def calibration_in_window(calib_zero: float, factor: float) -> bool:
  """True when the pedal scale is inside the accepted window and the idle reading leaves room under the shared command limit."""
  if not (math.isfinite(calib_zero) and math.isfinite(factor)):
    return False
  if PEDAL_ENABLED_COMMAND_LIMIT - max(0.0, float(calib_zero)) <= 0.0:
    return False
  return FACTOR_MIN <= factor <= FACTOR_MAX

# ---- Step 1, feet off: the rest window ----
# Taken only while the car reads DI_pedalPos = 0 (Tinkla calibratePedal.py:318-323 stops while di_gas > 0). The window is long and is judged by
# its medians, not by max-min: a Comma Pedal sensor can be noisy at rest (a tester's pedal read 0x552 raw 433 to 485 with the foot off, 2.64
# DBC units peak to peak), which the old "max-min <= 1.0 over 20 frames" test only let through by luck.
COAST_FRAMES = 200             # ~2 s at the 100 Hz controller (Tinkla averages 100 pedal frames, ~2 s at 50 Hz: :210, :340-347)
COAST_DRIFT_MAX = 1.0          # |median of the first half - median of the second half|: the reading is not drifting (DBC units)
COAST_P2P_MAX = 10.0           # peak-to-peak sanity cap (about 10 % of a full press): above it the pedal is moving, not resting
# Noise floor for the saved zero: the 99th percentile of the rest window plus a small margin. One 0x552 count is 0.0508 DBC units.
NOISE_FLOOR_PCT = 99.0
NOISE_FLOOR_MARGIN = 0.25      # ~5 raw counts

# ---- Step 2, driver press ----
# Zero = the pedal reading at the first frame the car reports throttle: DI_pedalPos >= 0.4 % (its first step, scale 0.4). Tinkla saves the pedal
# value where DI first goes above 0 (calibratePedal.py:362-364), fine-tuned to DI 0.4 % (:396-399), as TeslaPedalCalibZero (:444); the rest
# mean is only TeslaPedalCalibMin (:340-347, :436). NAP nap_conf.py:282-302 has the same meaning. Tinkla sweeps a commanded value; here the
# driver presses (the panda is never unlocked for calibration), so the sensor reading at those frames is used instead (documented divergence).
# Max = the pedal reading at the first frame with DI_pedalPos >= 99.6 % (Tinkla :354, fine-tuned :390, TeslaPedalCalibMax :440).
# Factor = 100 / (max - zero) (Tinkla :401; NAP nap_conf.py:302).
PRESS_DI_ONSET = 0.004 - 1e-6  # di_gas is DI_pedalPos / 100; the small tolerance only absorbs float rounding of the 0.4 % step
PRESS_DI_FULL = 0.996 - 1e-6
PRESS_DI_MIN = 0.05            # a press that went back to DI 0 without passing this was a twitch: ignored, the next press is measured
PRESS_RELEASE_FRAMES = 10      # consecutive DI 0 frames = the driver let go (~0.1 s at the 100 Hz controller)
PRESS_WINDOW_FRAMES = 500      # from the onset the car must read full throttle within this (~5 s), or the press fails

PRESS_NOT_FULL = ("The accelerator was not pressed all the way down. Press it slowly to the floor, then let go and try again.")
ONSET_BELOW_REST = ("The car saw the accelerator before the Comma Pedal reading moved. Check the Comma Pedal wiring and try again.")


def percentile(samples, pct: float) -> float:
  """Nearest-rank percentile (no interpolation): the smallest sample with at least pct % of the samples at or below it."""
  vals = sorted(float(v) for v in samples)
  k = max(1, math.ceil(pct / 100.0 * len(vals)))
  return vals[k - 1]


def rest_stats(samples) -> dict[str, float]:
  """Mean, median, p99 and peak-to-peak of a rest window."""
  vals = [float(v) for v in samples]
  return {
    "mean": float(statistics.fmean(vals)),
    "median": float(statistics.median(vals)),
    "p99": float(percentile(vals, NOISE_FLOOR_PCT)),
    "p2p": float(max(vals) - min(vals)),
    "n": float(len(vals)),
  }


def coast_steady(samples) -> bool:
  """A full rest window whose two half medians agree within COAST_DRIFT_MAX and whose peak-to-peak is under COAST_P2P_MAX."""
  vals = [float(v) for v in samples]
  if len(vals) < COAST_FRAMES:
    return False
  half = len(vals) // 2
  drift = abs(statistics.median(vals[:half]) - statistics.median(vals[half:]))
  return drift <= COAST_DRIFT_MAX and (max(vals) - min(vals)) <= COAST_P2P_MAX


def noise_floor(rest: dict[str, float]) -> float:
  return float(rest["p99"]) + NOISE_FLOOR_MARGIN


def zero_from_onset(rest: dict[str, float], onset_raw: float) -> tuple[float | None, bool, str]:
  """(zero, clamped, reason). The DI-onset reading is the zero, but never below the rest noise floor:
  - onset >= floor: zero = onset (Tinkla parity)
  - rest mean <= onset < floor: zero = floor (clamped), so the gasPressed cut (zero + 1/factor) stays above the resting noise
  - onset < rest mean: the car saw throttle while the pedal read below its own resting level; fail (wiring / sensor problem)
  """
  onset = float(onset_raw)
  floor = noise_floor(rest)
  if not math.isfinite(onset):
    return None, False, ONSET_BELOW_REST
  if onset >= floor:
    return onset, False, "ok"
  if onset >= float(rest["mean"]):
    return floor, True, "ok"
  return None, False, ONSET_BELOW_REST


def transform_di_to_pedal(val: float, pedal_zero: float, pedal_factor: float) -> float:
  """DI units -> pedal command voltage/percent."""
  if pedal_factor == 0:
    pedal_factor = 1.0
  return pedal_zero + (val - PEDAL_DI_ZERO) / pedal_factor


def transform_pedal_to_di(val: float, pedal_zero: float, pedal_factor: float) -> float:
  """Pedal voltage/percent -> DI units."""
  return PEDAL_DI_ZERO + (val - pedal_zero) * pedal_factor


def coast_pedal_zero(calib_zero: float, pedal_factor: float) -> float:
  """Coast position: calib_zero - 1/factor (NAP nap_conf pedal_zero property)."""
  if pedal_factor == 0:
    pedal_factor = 1.0
  return calib_zero - 1.0 / pedal_factor


def validate_calibration(coast_raw: float, pressed_raw: float) -> tuple[dict[str, float] | None, str]:
  """Return (result, "ok") or (None, reason) for a driver-press capture."""
  span = float(pressed_raw) - float(coast_raw)
  if span < MIN_SPAN:
    return None, "The accelerator pedal barely moved. Press it fully, check the Comma Pedal wiring and try again."
  factor = 100.0 / span
  if PEDAL_ENABLED_COMMAND_LIMIT - max(0.0, float(coast_raw)) <= 0.0:
    return None, "The pedal idle reading is too high. Check the Comma Pedal wiring and try again."
  if not calibration_in_window(float(coast_raw), factor):
    return None, f"Pedal scale {factor:.3f} is out of range ({FACTOR_MIN:.2f} to {FACTOR_MAX:.2f}). Check the Comma Pedal wiring and try again."
  return {
    "pedal_calib_zero": float(coast_raw),
    "pedal_calib_factor": float(factor),
    "pedal_calib_min": float(min(coast_raw, pressed_raw)),
    "pedal_calib_max": float(max(coast_raw, pressed_raw)),
    "ok": 1.0,
  }, "ok"


def compute_calibration(coast_raw: float, pressed_raw: float) -> dict[str, float]:
  """Compute calib fields from foot-off and full-press samples.

  Returns ok=0 and leaves safe incomplete values when validation fails
  (caller must not mark done / must not write Ready).
  """
  result, reason = validate_calibration(coast_raw, pressed_raw)
  if result is None:
    return {
      "pedal_calib_zero": float(coast_raw),
      "pedal_calib_factor": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_FACTOR]),
      "pedal_calib_min": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_MIN]),
      "pedal_calib_max": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_MAX]),
      "ok": 0.0,
      "reason": reason,
    }
  result["reason"] = "ok"
  return result


def compute_calibration_onset(rest: dict[str, float], onset_raw: float, full_raw: float) -> dict[str, float]:
  """A driver-press capture: zero from the DI-onset reading (zero_from_onset), factor = 100 / (full - zero).

  PedalCalibMin is the rest mean and PedalCalibMax the full-throttle reading (Tinkla TeslaPedalCalibMin / Max); both are informational, only
  PedalCalibZero and PedalCalibFactor drive gasPressed and the pedal command. ok=0 with a reason when anything fails; nothing is saved then.
  """
  zero, clamped, reason = zero_from_onset(rest, onset_raw)
  extra = {"rest_mean": float(rest["mean"]), "rest_p99": float(rest["p99"]), "rest_p2p": float(rest["p2p"]),
           "noise_floor": noise_floor(rest), "onset_raw": float(onset_raw), "full_raw": float(full_raw), "zero_clamped": float(clamped)}
  if zero is None:
    return {
      "pedal_calib_zero": float(rest["mean"]),
      "pedal_calib_factor": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_FACTOR]),
      "pedal_calib_min": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_MIN]),
      "pedal_calib_max": float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_MAX]),
      "ok": 0.0,
      "reason": reason,
    } | extra
  result = compute_calibration(zero, full_raw)
  if result.get("ok"):
    result["pedal_calib_min"] = float(rest["mean"])
    result["pedal_calib_max"] = float(full_raw)
  return result | extra


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
  if zero == float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_ZERO]) and      factor == float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_FACTOR]):
    return False
  # A saved scale outside the window is reported as "needs calibration" (see saved_calibration_out_of_range); the saved values themselves are never changed.
  return calibration_in_window(float(zero), float(factor))


def saved_calibration_out_of_range() -> bool:
  """A calibration is saved (done, not the defaults) but its pedal scale is outside the window: recalibrate. Values untouched."""
  if not get_bool(PreApParamKeys.PEDAL_CALIB_DONE):
    return False
  zero = get_float(PreApParamKeys.PEDAL_CALIB_ZERO)
  factor = get_float(PreApParamKeys.PEDAL_CALIB_FACTOR)
  if zero == float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_ZERO]) and factor == float(DEFAULTS[PreApParamKeys.PEDAL_CALIB_FACTOR]):
    return False
  return not calibration_in_window(float(zero), float(factor))


def pedal_detected(stored: bool | None = None) -> bool:
  if stored is None:
    return get_bool(PreApParamKeys.PEDAL_DETECTED, False)
  return bool(stored)


def pedal_status(*, detected: bool | None = None, calibrated: bool | None = None,
                  armed: bool | None = None, message: str | None = None) -> str:
  if armed is None:
    armed = get_bool(PreApParamKeys.PEDAL_CALIB_ARMED, False)
  if message is None:
    message = get_str(PreApParamKeys.PEDAL_CALIB_MESSAGE, "")
  if armed:
    return STATUS_CALIBRATING
  if message:
    return STATUS_FAILED
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
  set_str(PreApParamKeys.PEDAL_CALIB_MESSAGE, "")
  set_stage(STAGE_SAVED)
  return True


def fail_calibration(reason: str) -> None:
  """Clear the armed latch without writing Ready; surface the reason to the UI."""
  set_bool(PreApParamKeys.PEDAL_CALIB_ARMED, False)
  set_str(PreApParamKeys.PEDAL_CALIB_MESSAGE, str(reason)[:MESSAGE_MAX])
  set_stage(STAGE_FAILED)


def arm_calibration() -> None:
  """Start a fresh driver-press capture (UI Calibrate / Start)."""
  set_str(PreApParamKeys.PEDAL_CALIB_MESSAGE, "")
  set_str(PreApParamKeys.PEDAL_CALIB_STAGE, STAGE_IDLE)
  set_bool(PreApParamKeys.PEDAL_CALIB_ARMED, True)


def cancel_calibration() -> None:
  """Disarm without touching any stored calibration value (UI Cancel, timeout, leaving the screen)."""
  set_bool(PreApParamKeys.PEDAL_CALIB_ARMED, False)
  if get_str(PreApParamKeys.PEDAL_CALIB_STAGE) in (STAGE_COAST, STAGE_COAST_OK):
    set_str(PreApParamKeys.PEDAL_CALIB_STAGE, STAGE_IDLE)


def set_stage(stage: str) -> None:
  if get_str(PreApParamKeys.PEDAL_CALIB_STAGE) != stage:
    set_str(PreApParamKeys.PEDAL_CALIB_STAGE, stage)


def pedal_live(now: float | None = None, mono_now: float | None = None) -> bool:
  """True when the car process has heard the pedal in the last PEDAL_LIVE_S seconds (the PedalDetected file alone goes stale offroad).

  Either heartbeat counts: the wall-clock PedalSeenTs, or PedalSeenMono on time.monotonic() (one clock for every process
  since boot), so a wall-clock jump between the write and the read does not hide a live pedal."""
  if not pedal_detected():
    return False
  seen = get_float(PreApParamKeys.PEDAL_SEEN_TS)
  now = time.time() if now is None else now
  if seen > 0.0 and 0.0 <= (now - seen) <= PEDAL_LIVE_S:
    return True
  seen_mono = get_float(PreApParamKeys.PEDAL_SEEN_MONO)
  mono_now = time.monotonic() if mono_now is None else mono_now
  return bool(seen_mono > 0.0 and 0.0 <= (mono_now - seen_mono) <= PEDAL_LIVE_S)


def current_pedal_transform() -> tuple[float, float]:
  """Return (pedal_zero_coast, factor) for command mapping."""
  factor = get_float(PreApParamKeys.PEDAL_CALIB_FACTOR)
  zero = coast_pedal_zero(get_float(PreApParamKeys.PEDAL_CALIB_ZERO), factor)
  return zero, factor
