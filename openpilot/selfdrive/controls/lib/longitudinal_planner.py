#!/usr/bin/env python3
import math
import numpy as np

import openpilot.cereal.messaging as messaging
from opendbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from opendbc.car.tesla_ap1.throttle_gate import ap1_throttle_gate_for, apply_cut
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalMpc, LongitudinalPlanSource
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import T_IDXS as T_IDXS_MPC
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan, should_stop
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX, V_CRUISE_UNSET
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib.ap1_planning import (
  Ap1Planning, AP1_CRUISE_GAIN, AP1_CRUISE_J_SCALE,
)
from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed
from openpilot.selfdrive.controls.lib.comfort_regen import ComfortRegen
from openpilot.selfdrive.controls.lib.ap1_curve_arbitration import CurveArbiter, ModelClock
try:  # optional Gas/Brake consumers: import/init failure falls back to the stock planner
  from openpilot.selfdrive.controls.lib.phase3_long_accel import LongAccelPort
  from openpilot.selfdrive.controls.lib.phase3_long_stopping import LongStoppingRuntime
except Exception:
  LongAccelPort = LongStoppingRuntime = None
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import get_T_FOLLOW
from openpilot.selfdrive.controls.lib.phase3_following import FollowingPlanner
from openpilot.selfdrive.controls.lib.phase3_speed_control import Ap1SpeedControl

A_CRUISE_MAX_VALS = [1.6, 1.2, 0.8, 0.6]
A_CRUISE_MAX_BP = [0., 10.0, 25., 40.]
J_CRUISE_VALS = [1.6, 1.2, 0.8, 0.6]
A_CRUISE_MIN = -1.2
CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
ALLOW_THROTTLE_THRESHOLD = 0.4
MIN_ALLOW_THROTTLE_SPEED = 2.5

# Lookup table for turns
_A_TOTAL_MAX_V = [1.7, 3.2]
_A_TOTAL_MAX_BP = [20., 40.]

def get_max_accel(v_ego):
  return np.interp(v_ego, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)

def get_coast_accel(pitch):
  return np.sin(pitch) * -5.65 - 0.3  # fitted from data using xx/projects/allow_throttle/compute_coast_accel.py

def get_cruise_accel(e2e, v_cruise, v_ego, a_cruise_prev, angle_steers, CP, dt, accel_coast, allow_throttle, profile_limits=None,
                     throttle_cut=None, ap1_shape=False):
  max_accel = ACCEL_MAX if e2e else get_max_accel(v_ego)

  if profile_limits is not None and not e2e:
    max_accel = profile_limits[1]

  if not e2e:
    a_total_max = np.interp(v_ego, _A_TOTAL_MAX_BP, _A_TOTAL_MAX_V)
    a_y = v_ego ** 2 * angle_steers * CV.DEG_TO_RAD / (CP.steerRatio * CP.wheelbase)
    a_x_allowed = math.sqrt(max(a_total_max ** 2 - a_y ** 2, 0.))
    max_accel = min(max_accel, a_x_allowed)
    # throttle_cut: AP1 0..1 fraction (tesla_ap1/throttle_gate.py); None keeps the stock 0/1 allow_throttle cut.
    if throttle_cut is None:
      throttle_cut = 0.0 if allow_throttle else 1.0
    if throttle_cut > 0.0:
      clipped_accel_coast = max(accel_coast, ACCEL_MIN)
      coast_limit = np.interp(v_ego, [MIN_ALLOW_THROTTLE_SPEED, MIN_ALLOW_THROTTLE_SPEED*2], [max_accel, clipped_accel_coast])
      max_accel = apply_cut(max_accel, coast_limit, throttle_cut)

  min_accel = profile_limits[0] if profile_limits is not None and not e2e else A_CRUISE_MIN
  speed_error, j_scale = v_cruise - v_ego, 1.0
  if ap1_shape and not e2e:
    # AP1 only: softer set-speed reaction (gain and slower jerk). The floor is the profile's (Eco+ -0.875 by default) or the
    # stock one; there is no extra floor here, so it can never be applied twice. Lead braking is untouched.
    speed_error, j_scale = AP1_CRUISE_GAIN * speed_error, AP1_CRUISE_J_SCALE
  target_accel = np.clip(speed_error, min_accel, max_accel)
  j_cruise = np.interp(v_ego, A_CRUISE_MAX_BP, J_CRUISE_VALS) * j_scale
  target_accel = float(np.clip(target_accel, a_cruise_prev - j_cruise * dt, a_cruise_prev + j_cruise * dt))

  return target_accel


class LongitudinalPlanner:
  def __init__(self, CP, init_v=0.0, init_a=0.0, dt=DT_MDL):
    self.CP = CP
    self.mpc = LongitudinalMpc(dt=dt)
    self.fcw = False
    self.dt = dt
    self.ap1_plan = Ap1Planning(CP, dt)
    self.curve_speed = Ap1CurveSpeed(CP, dt)
    self.arbiter = CurveArbiter(dt) if self.curve_speed.available else None  # CSC cars (AP1, Pre-AP pedal): comfort arbitration
    self.arbiter_clock = ModelClock(dt)
    try:
      self.long_accel = LongAccelPort(CP, dt)
      self.long_stopping = LongStoppingRuntime(self.long_accel.store, CP, dt)
    except Exception:
      cloudlog.exception("BogPilot Gas/Brake runtime unavailable at init; stock planner behaviour")
      self.long_accel = None
      self.long_stopping = None
    self.force_stop_result = None
    self.following = FollowingPlanner(CP, dt=dt)
    self.effective_t_follow = get_T_FOLLOW()
    self.speed_control = Ap1SpeedControl(CP)
    # Comfort regen v2 (RegenComfortBrake, AP1/Pre-AP): add-only layer after the stock plan; read once per planner start.
    try:
      self.comfort_regen = ComfortRegen(CP, dt)
    except Exception:
      cloudlog.exception("BogPilot comfort regen unavailable at init; stock planner behaviour")
      self.comfort_regen = ComfortRegen(None, dt, enabled=False)
    self.experimental = False
    self.allow_throttle = True
    # AP1-only allowThrottle smoothing (tesla_ap1/throttle_gate.py); None on every other car.
    self.throttle_cut = 0.0
    self.ap1_throttle_gate = ap1_throttle_gate_for(CP.carFingerprint)

    self.v_desired_filter = FirstOrderFilter(init_v, 2.0, self.dt)
    self.a_cruise = init_a
    self.output_a_target = init_a
    self.output_should_stop = False

    self.v_desired_trajectory = np.zeros(CONTROL_N)
    self.a_desired_trajectory = np.zeros(CONTROL_N)
    self.j_desired_trajectory = np.zeros(CONTROL_N)

  def update(self, sm):
    if len(sm['carControl'].orientationNED) == 3:
      accel_coast = get_coast_accel(sm['carControl'].orientationNED[1])
    else:
      accel_coast = ACCEL_MAX

    v_ego = sm['carState'].vEgo
    v_cruise_kph = min(sm['carState'].vCruise, V_CRUISE_MAX)
    v_cruise = v_cruise_kph * CV.KPH_TO_MS
    if sm['controlsState'].forceDecel:
      v_cruise = 0.0

    long_control_off = sm['controlsState'].longControlState == LongCtrlState.off

    # Reset current state when not engaged, or user is controlling the speed
    reset_state = long_control_off if self.CP.openpilotLongitudinalControl else not sm['selfdriveState'].enabled
    # PCM cruise speed may be updated a few cycles later, check if initialized
    v_cruise_initialized = sm['carState'].vCruise != V_CRUISE_UNSET
    reset_state = reset_state or not v_cruise_initialized

    # AP1 Speed Limit Controller + software stalk set (phase3_speed_control; bit-exact passthrough unless SLC is active).
    try:
      v_cruise = self.speed_control.update(sm, v_cruise, v_ego, self.dt)
    except Exception:
      cloudlog.exception("BogPilot Speed Limit Controller unavailable; stock cruise target retained")

    # BogPilot phase3 following: ONE effective T-follow (custom profile / AP1 stalk / weather / human following),
    # also handed to the Gas/Brake consumers (context["t_follow"]). follow None -> exact stock path.
    personality = sm['selfdriveState'].personality
    stalk_t_follow = self.ap1_plan.t_follow(sm["carState"], not reset_state)
    try:
      model_x = sm['modelV2'].position.x
      follow = self.following.update(enabled=not reset_state, v_ego=v_ego, a_ego=sm['carState'].aEgo, personality=personality,
                                     lead=sm['radarState'].leadOne, model_length=float(model_x[-1]) if len(model_x) else 0.0,
                                     standstill=sm['carState'].standstill,
                                     traffic_mode=bool(sm['carState'].bogpilot.trafficModeEnabled),
                                     stalk_t_follow=stalk_t_follow)
    except Exception:
      cloudlog.exception("BogPilot following unavailable; stock following")
      follow = None
    t_follow_override = follow.t_follow if follow is not None else stalk_t_follow
    self.effective_t_follow = t_follow_override if t_follow_override is not None else get_T_FOLLOW(personality)
    t_follow = self.effective_t_follow
    # Any settings/Params failure falls back to the exact stock behaviour; it must never take the planner down.
    try:
      if self.long_accel is None:
        raise RuntimeError("Gas/Brake runtime not initialised")
      conditional = self.long_accel.update(sm, reset_state, context={"t_follow": t_follow})
      profile_limits = self.long_accel.limits(v_ego, v_cruise, ACCEL_MIN)
      action_delay = self.long_accel.delay()
    except Exception:
      if self.long_accel is not None:  # init failure was already logged once
        cloudlog.exception("BogPilot Gas/Brake settings unavailable; stock acceleration behaviour")
      conditional, profile_limits, action_delay = False, None, self.CP.longitudinalActuatorDelay
    # Fallback Speed = Experimental Mode: the SLC-derived flag REPLACES the manual flag (0.9.7 controlsd.py:811-812);
    # no override -> the manual flag unchanged (stock path). CEM (conditional) still ORs in as in 0.9.7.
    experimental = self.speed_control.resolve_experimental(sm['selfdriveState'].experimentalMode) or conditional
    self.experimental = bool(experimental)

    # Curve speed control (AP1, Pre-AP pedal in FULL): can only lower the cruise speed (never above the driver's set speed).
    v_cruise = self.curve_speed.update(sm, v_ego, v_cruise, reset_state)
    try:
      if self.long_stopping is None or self.long_accel is None:
        raise RuntimeError("stopping runtime not initialised")
      self.long_stopping.store = self.long_accel.store
      observation = self.long_stopping.observe_model_stop(sm, self.long_accel, active=not reset_state)
      self.force_stop_result = self.long_stopping.arbitrate_force_stop(
        v_cruise, model_stop=observation, longitudinal_active=not reset_state,
        gas_pressed=bool(sm['carState'].gasPressed), accel_pressed=bool(sm['carState'].bogpilot.accelPressed),
        standstill=bool(sm['carState'].standstill), v_ego=v_ego, dt=self.dt)
      v_cruise = self.force_stop_result.target
    except Exception:
      if self.long_stopping is not None and self.long_accel is not None:
        cloudlog.exception("BogPilot force-stop unavailable; stock cruise target retained")
      self.force_stop_result = None

    throttle_probs = sm['modelV2'].meta.disengagePredictions.gasPressProbs
    throttle_prob = throttle_probs[1] if len(throttle_probs) > 1 else 1.0
    raw_allow_throttle = throttle_prob > ALLOW_THROTTLE_THRESHOLD or v_ego <= MIN_ALLOW_THROTTLE_SPEED
    if self.ap1_throttle_gate is not None:
      # AP1: 0..1 cut fraction instead of a 0/1 step. Follows the raw flag at creep speed and while not engaged.
      self.throttle_cut = self.ap1_throttle_gate.update(raw_allow_throttle, low_speed=v_ego <= MIN_ALLOW_THROTTLE_SPEED,
                                                        reset=reset_state)
      self.allow_throttle = self.throttle_cut < 0.5
      throttle_cut = self.throttle_cut
    else:
      self.allow_throttle = raw_allow_throttle
      throttle_cut = None

    steer_angle_without_offset = sm['carState'].steeringAngleDeg - sm['vehicleParameters'].angleOffsetDeg

    if reset_state:
      self.v_desired_filter.x = v_ego
      self.output_a_target = np.clip(sm['carState'].aEgo, ACCEL_MIN, ACCEL_MAX)
      self.a_cruise = self.output_a_target

    # Prevent divergence, smooth in current v_ego
    self.v_desired_filter.x = max(0.0, self.v_desired_filter.update(v_ego))

    # No change cost when user is controlling the speed, or when standstill
    prev_accel_constraint = not (reset_state or sm['carState'].standstill)

    self.mpc.set_weights(prev_accel_constraint, personality=personality,
                         cost_override=follow.mpc_weights() if follow is not None else None)
    self.mpc.set_cur_state(self.v_desired_filter.x, self.output_a_target)
    self.mpc.update(sm['radarState'], personality=personality, comfort_brake=self.ap1_plan.comfort_brake,
                    t_follow_override=t_follow_override)

    self.v_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.v_solution)
    self.a_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.a_solution)
    self.j_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC[:-1], self.mpc.j_solution)

    # TODO counter is only needed because radar is glitchy, remove once radar is gone
    self.fcw = self.mpc.crash_cnt > 2 and not sm['carState'].standstill
    if self.fcw:
      cloudlog.info("FCW triggered")

    # Save starting point for next iteration
    a_prev = self.output_a_target

    action_t = action_delay + DT_MDL
    output_a_target_mpc = get_accel_from_plan(self.v_desired_trajectory, self.a_desired_trajectory, CONTROL_N_T_IDX,
                                              action_t=action_t)
    output_should_stop_mpc = should_stop(v_ego, output_a_target_mpc)
    output_a_target_e2e = sm['modelV2'].action.desiredAcceleration
    output_should_stop_e2e = sm['modelV2'].action.shouldStop

    self.a_cruise = get_cruise_accel(experimental, v_cruise, v_ego,
                                     self.a_cruise, steer_angle_without_offset, self.CP, self.dt,
                                     accel_coast, self.allow_throttle, profile_limits, throttle_cut,
                                     ap1_shape=self.ap1_plan.active)
    cruise_should_stop = should_stop(v_ego, self.a_cruise)

    candidates = [(output_a_target_mpc, self.mpc.source, output_should_stop_mpc),
                  (self.a_cruise, LongitudinalPlanSource.cruise, cruise_should_stop)]
    if experimental:
      candidates.append((output_a_target_e2e, LongitudinalPlanSource.e2e, output_should_stop_e2e))
    if self.curve_speed.a_brake < 0.0:
      # AP1 look-ahead curve brake: an extra min() candidate, so it can only add braking.
      candidates.append((self.curve_speed.a_brake, LongitudinalPlanSource.cruise, False))

    dt_model = self.arbiter_clock.step(sm)
    if self.arbiter is not None:
      # AP1: the one arbitration point. Same min(), comfort-class (cruise, curve brake) switches are slewed, lead/e2e are not.
      named = [("mpc", output_a_target_mpc), ("cruise", self.a_cruise)]
      if experimental:
        named.append(("e2e", output_a_target_e2e))
      if self.curve_speed.a_brake < 0.0:
        named.append(("curve", self.curve_speed.a_brake))
      output_a_target, winner, _ = self.arbiter.arbitrate(named, dt_model, reset_state)
      self.mpc.source = {"mpc": self.mpc.source, "e2e": LongitudinalPlanSource.e2e}.get(winner, LongitudinalPlanSource.cruise)
    else:
      output_a_target, self.mpc.source, _ = min(candidates, key=lambda c: c[0])
    self.output_should_stop = any(should_stop for _, _, should_stop in candidates)
    output_a_target = self._apply_lead_accel_cap(sm, output_a_target, v_ego, t_follow, profile_limits)
    output_a_target = self.ap1_plan.shape_stop(sm, output_a_target, not reset_state)
    output_a_target = self._apply_comfort_regen(sm, output_a_target, v_ego, t_follow, reset_state)
    self.output_a_target = np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)

    self.v_desired_filter.x = self.v_desired_filter.x + self.dt * (self.output_a_target + a_prev) / 2.0

  def _apply_comfort_regen(self, sm, a_target, v_ego, t_follow, reset_state):
    """Comfort regen v2: final = min(stock, comfort). Never raises a_target; any error returns a_target unchanged."""
    cr = self.comfort_regen
    if not cr.enabled:
      return a_target
    try:
      cs = sm['carState']
      out = cr.update(a_target, engaged=not reset_state, gas_pressed=bool(cs.gasPressed), standstill=bool(cs.standstill),
                      v_ego=v_ego, lead=sm['radarState'].leadOne, t_follow=t_follow)
    except Exception:
      cloudlog.exception("BogPilot comfort regen failed; stock plan unchanged")
      cr.reset()
      return a_target
    return min(a_target, out)

  def _apply_lead_accel_cap(self, sm, a_target, v_ego, t_follow, profile_limits=None):
    """AdaptiveAccelLead (legacy Teslas, default off): cap a positive request near a lead. Unchanged when off or on any error."""
    la = self.long_accel
    if la is None or a_target <= 0.0:
      return a_target
    try:
      ceiling = profile_limits[1] if profile_limits is not None else get_max_accel(v_ego)   # what the cruise path may ask for now
      cap = la.lead_accel_cap(v_ego, float(ceiling), sm['radarState'].leadOne, t_follow)
    except Exception:
      cloudlog.exception("BogPilot adaptive accel cap unavailable; plan unchanged")
      return a_target
    return a_target if cap is None else min(a_target, cap)

  def publish(self, sm, pm):
    plan_send = messaging.new_message('longitudinalPlan')

    plan_send.valid = sm.all_checks()

    longitudinalPlan = plan_send.longitudinalPlan
    longitudinalPlan.modelMonoTime = sm.logMonoTime['modelV2']
    longitudinalPlan.processingDelay = (plan_send.logMonoTime / 1e9) - sm.logMonoTime['modelV2']
    longitudinalPlan.solverExecutionTime = self.mpc.solve_time

    longitudinalPlan.speeds = self.v_desired_trajectory.tolist()
    longitudinalPlan.accels = self.a_desired_trajectory.tolist()
    longitudinalPlan.jerks = self.j_desired_trajectory.tolist()

    longitudinalPlan.hasLead = sm['radarState'].leadOne.present
    longitudinalPlan.longitudinalPlanSource = self.mpc.source
    longitudinalPlan.fcw = self.fcw

    longitudinalPlan.aTarget = float(self.output_a_target)
    longitudinalPlan.shouldStop = bool(self.output_should_stop)
    longitudinalPlan.allowBrake = True
    longitudinalPlan.allowThrottle = bool(self.allow_throttle)

    pm.send('longitudinalPlan', plan_send)

  def publish_bogpilot_plan(self, pm):
    try:
      if self.long_accel is not None:
        self.long_accel.publish_status()
    except Exception:
      cloudlog.exception("BogPilot CEM status unavailable")
    # CSC report for the cluster's CSC MAX slot; valid only while AP1 CSC is on with fresh inputs.
    msg = messaging.new_message('bogpilotPlan')
    la = self.long_accel
    msg.valid = bool(self.curve_speed.valid or self.speed_control.active or (la is not None and la.conditions is not None) or
                     (self.force_stop_result is not None and self.force_stop_result.forcing_stop))
    self.curve_speed.fill(msg.bogpilotPlan)
    self.speed_control.fill(msg.bogpilotPlan)
    if la is not None:
      msg.bogpilotPlan.experimentalMode = bool(self.experimental)
      msg.bogpilotPlan.redLight = bool(la.cem.red_light)
    if self.force_stop_result is not None:
      msg.bogpilotPlan.forcingStop = self.force_stop_result.forcing_stop
      msg.bogpilotPlan.forcingStopLength = self.force_stop_result.tracked_model_length
    pm.send('bogpilotPlan', msg)
