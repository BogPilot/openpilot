"""AP1-only planner bridge. No solver layout changes or weakened braking limits."""
import math
import numpy as np
from opendbc.car.tesla_ap1.regen_aware import (
  RegenPowerEstimator, RegenStopShaper, regen_aware_enabled, regen_car, lead_stop_distance, model_stop_distance,
)

AP1 = "TESLA_AP1_MODELS"
AP1_X = "TESLA_AP1_MODELX"
PREAP = "TESLA_PREAP_MODELS"

# AP1 cruise (set-speed) reaction shaping, used by longitudinal_planner.get_cruise_accel for AP1 only.
# Evidence: 0.9.7 drive logs. 0.9.7 planned ~0.24 m/s^2 per m/s of speed error (MPC cruise
# obstacle + Human/Eco+ limits); stock 0.11 cruise law is 1.0 m/s^2 per m/s with the -1.2 floor.
AP1_CRUISE_GAIN = 0.30       # (m/s^2) per (m/s) of v_cruise - v_ego; 1.0 is the stock 0.11.2 law
AP1_CRUISE_J_SCALE = 0.40    # scale on stock J_CRUISE_VALS (1.6/1.2/0.8/0.6 m/s^3 over 0/10/25/40 m/s)
# The temporary -0.875 cruise decel floor (an earlier stand-in for 0.9.7 Eco+) is gone. The decel floor is owned by the
# Gas/Brake profile (Eco+ = ACCEL_MIN / 4 = -0.875, adopted by default on the legacy Tesla platforms) or, with the tune
# off, by the stock A_CRUISE_MIN. Only the gain and the jerk scale stay: a replay of the 0.9.7 set-speed logs
# shows profiles alone leave the plan jerk at the stock 1.3 m/s^3 (0.9.7: 0.49).


def comfort_distance_delta(v, comfort_brake):
  if not math.isfinite(comfort_brake) or not 0 < comfort_brake < 2.5:
    return np.zeros_like(v, dtype=float)
  return 0.5 * (1.0 / comfort_brake - 1.0 / 2.5) * np.maximum(v, 0.0) ** 2


def lead_present(lead):
  # Schema name changed in 0.11; do not change either track's wire format.
  return bool(getattr(lead, "present", getattr(lead, "status", False)))


def _trim_profile(fingerprint):
  try:
    from opendbc.car.tesla_ap1.trims import profile_for
    return profile_for(fingerprint)
  except Exception:
    return None


def _finite(x):
  try:
    x = float(x)
  except (TypeError, ValueError):
    return None
  return x if math.isfinite(x) else None


def drive_inputs(bp):
  """(front torque Nm, front rpm, rear rpm per m/s, front rpm per m/s) from carState.bogpilot. The front values are None
  unless the car is a detected dual-motor car with a fresh 0x186 frame; the rpm per m/s are None when not positive."""
  dual = int(getattr(bp, "ap1DriveLayout", 0) or 0) == 2
  front_tq = _finite(getattr(bp, "ap1FrontMotorTorqueNm", None)) if dual else None
  front_rpm = _finite(getattr(bp, "ap1FrontMotorRpm", None)) if dual else None
  rear_k = _finite(getattr(bp, "ap1RearRpmPerMs", None))
  front_k = _finite(getattr(bp, "ap1FrontRpmPerMs", None)) if dual else None
  return (front_tq, front_rpm, rear_k if rear_k and rear_k > 0 else None, front_k if front_k and front_k > 0 else None)


class Ap1Planning:
  def __init__(self, CP, dt):
    self.active = CP.carFingerprint == AP1 and CP.openpilotLongitudinalControl
    # Pre-AP uses the same follow-distance seconds when an AP1 stalk is parsed; regen stop shaping stays AP1-only.
    self.stalk_follow_active = CP.carFingerprint in (AP1, PREAP) and CP.openpilotLongitudinalControl
    # Stock 2.5 m/s^2 always: the v1 regen gap widening is retired. RegenComfortBrake now drives the add-only comfort
    # layer (comfort_regen.py) after the stock plan, so the MPC lead gap stays exactly stock.
    self.comfort_brake = 2.5
    # Regen-aware stop shaping: AP1 Model S and AP1 Model X with openpilot longitudinal, each with its own car physics
    # (regen_aware.MODEL_S / MODEL_X). The set-speed reaction shaping above (self.active) stays Model S only.
    regen_platform = CP.carFingerprint in (AP1, AP1_X) and CP.openpilotLongitudinalControl
    self.regen_enabled = bool(regen_platform) and regen_aware_enabled(CP.carFingerprint)
    self.dt = dt
    # Trim profile (opendbc tesla_ap1/trims.py), read once here at planner start: the picked trim's mass (Auto keeps the
    # base mass), the rpm per m/s seeds and, on a dual-motor car, the front + rear regen. Never fails the planner.
    car = regen_car(CP.carFingerprint, _trim_profile(CP.carFingerprint) if regen_platform else None)
    self.power = RegenPowerEstimator(car=car)
    self.stop = RegenStopShaper(car=car)

  def t_follow(self, CS, enabled):
    if not self.stalk_follow_active or not enabled:
      return None
    seconds = float(CS.bogpilot.ap1StalkFollowS)
    if not math.isfinite(seconds) or not 1.0 <= seconds <= 1.75:
      return None
    # Detent 1 is the existing traffic profile (0.5 s stopped -> 1 s cruising).
    return float(np.interp(CS.vEgo, [0.0, 5.0], [0.5, 1.0])) if abs(seconds - 1.0) < 1e-3 else seconds

  def shape_stop(self, sm, a_plan, enabled):
    CS = sm['carState']
    if not self.regen_enabled or not enabled or CS.gasPressed or CS.brakePressed or not CS.canValid:
      self.stop.reset()
      return a_plan
    bp = CS.bogpilot
    front_tq, front_rpm, rear_k, front_k = drive_inputs(bp)
    p_kw = self.power.update(CS.vEgo, a_plan, bp.ap1MotorTorqueNm, bp.ap1MotorRpm, bp.ap1AmbientTempC, self.dt,
                             front_torque_nm=front_tq, front_rpm=front_rpm, rpm_per_ms=rear_k, front_rpm_per_ms=front_k)
    lead = sm['radarState'].leadOne
    distance = lead_stop_distance(lead_present(lead), lead.dRel, lead.vLead, 6.0)
    model = sm['modelV2']
    if sm['selfdriveState'].experimentalMode:
      model_distance = model_stop_distance(model.position.x, model.velocity.x)
      if model_distance is not None:
        distance = model_distance if distance is None else min(distance, model_distance)
    output, _ = self.stop.update(CS.vEgo, a_plan, distance, p_kw, self.dt)
    return min(a_plan, output)  # add-only; caller retains stock ACCEL_MIN/MAX
