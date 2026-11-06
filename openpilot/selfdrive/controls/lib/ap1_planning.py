"""AP1-only planner bridge. No solver layout changes or weakened braking limits."""
import math
import numpy as np
from opendbc.car.tesla_ap1.regen_brake import ap1_comfort_brake
from opendbc.car.tesla_ap1.regen_aware import (
  RegenPowerEstimator, RegenStopShaper, regen_aware_enabled, lead_stop_distance, model_stop_distance,
)

AP1 = "TESLA_AP1_MODELS"


def comfort_distance_delta(v, comfort_brake):
  if not math.isfinite(comfort_brake) or not 0 < comfort_brake < 2.5:
    return np.zeros_like(v, dtype=float)
  return 0.5 * (1.0 / comfort_brake - 1.0 / 2.5) * np.maximum(v, 0.0) ** 2


def lead_present(lead):
  # Schema name changed in 0.11; do not change either track's wire format.
  return bool(getattr(lead, "present", getattr(lead, "status", False)))


class Ap1Planning:
  def __init__(self, CP, dt):
    self.active = CP.carFingerprint == AP1 and CP.openpilotLongitudinalControl
    self.comfort_brake = ap1_comfort_brake(CP.carFingerprint) if self.active else 2.5
    self.regen_enabled = self.active and regen_aware_enabled(CP.carFingerprint)
    self.dt = dt
    self.power = RegenPowerEstimator()
    self.stop = RegenStopShaper()

  def t_follow(self, CS, enabled):
    if not self.active or not enabled:
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
    p_kw = self.power.update(CS.vEgo, a_plan, bp.ap1MotorTorqueNm, bp.ap1MotorRpm, bp.ap1AmbientTempC, self.dt)
    lead = sm['radarState'].leadOne
    distance = lead_stop_distance(lead_present(lead), lead.dRel, lead.vLead, 6.0)
    model = sm['modelV2']
    if sm['selfdriveState'].experimentalMode:
      model_distance = model_stop_distance(model.position.x, model.velocity.x)
      if model_distance is not None:
        distance = model_distance if distance is None else min(distance, model_distance)
    output, _ = self.stop.update(CS.vEgo, a_plan, distance, p_kw, self.dt)
    return min(a_plan, output)  # add-only; caller retains stock ACCEL_MIN/MAX
