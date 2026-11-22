"""Probe for test_tesla_tuning_menu.py: run in a fresh interpreter (the consumers read Tesla Tuning once, at import).

  python tesla_tuning_probe.py values   -> JSON {row key: the value each consumer really uses}
  python tesla_tuning_probe.py replay   -> sha256 of a fixed 20,000-step replay through every consumer

`replay` does not import tesla_tuning, so the same file runs on a baseline tree that does not have the feature.
"""
import hashlib
import json
import struct
import sys
import types
from collections import deque


def _consumers():
  from opendbc.car.tesla_ap1 import actuator_plan, curve_speed, long_smooth, regen_aware
  from opendbc.car.tesla_ap1.preap import accel_limits, vdas_constants
  from openpilot.selfdrive.controls.lib import ap1_curve_brake, comfort_regen
  return actuator_plan, curve_speed, long_smooth, regen_aware, accel_limits, vdas_constants, ap1_curve_brake, comfort_regen


def _standby_command(actuator_plan):
  plan = actuator_plan.build_actuator_plan(
    frame=0, lat_active=False, hands_on_fault=False, openpilot_longitudinal_control=True, enabled=False, long_active=False,
    measured_angle_deg=0.0, requested_angle_deg=0.0, last_angle_deg=0.0, v_ego=0.0, accel=0.0, acc_state=0,
    das_counters=deque([1]), pcm_cancel=False, chassis_das_only=True, standby=True)
  return plan.longitudinal[0]


def values():
  ap, cs, ls, ra, al, vc, cb, cr = _consumers()
  out = {}
  # rise: a fresh smoother seeds last=0 (a_ego 0), the next step rises by rise_jerk * dt
  s = ls.Ap1AccelSmoother()
  first = s.update(2.0, True, 10.0, a_ego=0.0)
  out["AP1RiseJerk"] = round(first / ls.DT_CTRL, 6)
  out["AP1DriveReleaseJerk"] = s.fall_jerk
  out["AP1DriveReleaseBrakeJerk"] = s.brake_release_jerk
  out["AP1BrakeOnsetJerk"] = ls.ap1_brake_ramp_jerk(-0.5)
  out["AP1BrakeHardAccel"] = s.hard_brake
  out["AP1ComfortJerkLimit"] = ls.ap1_jerk_limit_target(0.0)
  out["AP1LaunchJerkMax"] = ls.Ap1JerkLimit().update(0.0, True, 0.0)[1]
  cmd = _standby_command(ap)
  out["AP1StandbyAccelMin"] = cmd.min_accel
  out["AP1StandbyJerkMin"] = cmd.jerk_min
  out["AP1StandbyJerkMax"] = cmd.jerk_max
  # comfort regen: engaged, closing on a radar lead, gentle request; the first output is the onset ramp
  lead = types.SimpleNamespace(present=True, radar=True, vLead=17.0, dRel=39.65, radarTrackId=1)
  c = cr.ComfortRegen(enabled=True)
  first = c.update(0.0, engaged=True, gas_pressed=False, standstill=False, v_ego=20.0, lead=lead, t_follow=1.45)
  out["ComfortRegenOnsetJerk"] = round(-first / c.dt, 6)
  out["ComfortRegenMaxDecel"] = cr.A_GENTLE_ON
  out["ComfortRegenReleaseJerk"] = cr.JERK_OFF
  sh = ra.RegenStopShaper(car=ra.MODEL_S)
  _, early = sh.update(15.0, 0.0, 20.0, 30.0, 0.05)
  out["StopShaperOnsetJerk"] = round(-early / 0.05, 6)
  out["StopShaperReleaseJerk"] = ra.RELEASE_JERK
  out["StopShaperOnsetFrac"] = ra.ONSET_FRAC
  out["StopShaperGentleFrac"] = ra.GENTLE_FRAC
  import inspect
  out["CurveMaxLatAccel"] = inspect.signature(cb.curve_target_speed).parameters["max_lat_accel"].default
  out["CurveMaxDecel"] = cb.A_MIN
  out["CurveOnsetJerk"] = cb.ONSET_JERK
  out["CurveReleaseJerk"] = cb.RELEASE_JERK
  out["PreApPedalAccelMax"] = vc.ACCEL_MAX
  out["PreApPedalRegenMax"] = al.get_preap_accel_limits(10.0)[0]
  # the second copy of the curve brake in opendbc follows the same rows
  out["_opendbc_curve"] = [cs.TESLA_CSC_MAX_LAT_ACCEL, cs.A_MIN, cs.ONSET_JERK, cs.RELEASE_JERK]
  from opendbc.car.tesla_ap1.preap import virtual_das, pedal_controller
  out["_preap_modules"] = [virtual_das.ACCEL_MAX, virtual_das.REGEN_MAX, pedal_controller.ACCEL_MAX, pedal_controller.REGEN_MAX]
  out["_standby_engage_hold"] = ls.AP1_STANDSTILL_ENGAGE_ACCEL
  return out


def replay():
  ap, cs, ls, ra, al, vc, cb, cr = _consumers()
  h = hashlib.sha256()

  def feed(*xs):
    for x in xs:
      h.update(struct.pack("<d", float(x)))

  state = 12345
  def rnd():
    nonlocal state
    state = (1103515245 * state + 12345) % (2 ** 31)
    return state / 2 ** 31

  smoother, jl = ls.Ap1AccelSmoother(), ls.Ap1JerkLimit()
  comfort = cr.ComfortRegen(enabled=True)
  shaper = ra.RegenStopShaper(car=ra.MODEL_S)
  shaper_x = ra.RegenStopShaper(car=ra.MODEL_X)
  target, v_ego, v_lead, d_rel = 0.0, 18.0, 15.0, 45.0
  for i in range(20000):
    target = max(-3.0, min(2.0, target + (rnd() - 0.5) * 0.4))
    v_ego = max(0.0, v_ego + target * 0.05 + (rnd() - 0.5) * 0.1)
    v_lead = max(0.0, v_lead + (rnd() - 0.5) * 0.3)
    d_rel = max(3.0, d_rel + (v_lead - v_ego) * 0.05)
    active = i % 997 > 40
    urgent = target < -2.4
    out = smoother.update(target, active, v_ego, urgent=urgent, a_ego=target * 0.8, gas_pressed=(i % 1500) < 20)
    jmin, jmax = jl.update(out, active, v_ego, gas_neutral=(i % 1500) < 20, urgent=urgent)
    lead = types.SimpleNamespace(present=True, radar=True, vLead=v_lead, dRel=d_rel, radarTrackId=1 + i // 3000)
    c = comfort.update(target, engaged=active, gas_pressed=False, standstill=v_ego < 0.1, v_ego=v_ego, lead=lead, t_follow=1.45)
    a1, e1 = shaper.update(v_ego, target, d_rel if v_lead < 2.0 else None, 30.0, 0.05)
    a2, e2 = shaper_x.update(v_ego, target, d_rel, 51.1, 0.05)
    feed(out, jmin, jmax, c, a1, e1, a2, e2)
  for v, lat in ((10.0, 0.5), (25.0, 2.5), (30.0, 1.0)):
    feed(ra.profile_distance(v, 30.0, car=ra.MODEL_S), cb.landing_decel(v * 0.3), cb.tesla_csc_lateral_accel(lat))
  for sp in (0.0, 5.0, 20.0, 35.0):
    for p in (0, 1, 2):
      feed(*al.get_preap_accel_limits(sp, p))
  feed(vc.ACCEL_MAX, vc.REGEN_MAX, cb.TESLA_CSC_MAX_LAT_ACCEL, cb.A_MIN, cb.ONSET_JERK, cb.RELEASE_JERK)
  return h.hexdigest()


if __name__ == "__main__":
  print(json.dumps(values() if sys.argv[1] == "values" else replay()))
