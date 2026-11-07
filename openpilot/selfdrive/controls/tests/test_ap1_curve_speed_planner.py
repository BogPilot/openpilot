"""C3X planner integration for AP1 curve speed control (synthetic messages, real LongitudinalPlanner + capnp).

These are synthetic closed/open-loop checks, not a log replay and not a drive.
"""
import math

import numpy as np
import pytest

import openpilot.cereal.messaging as messaging
from opendbc.car.honda.interface import CarInterface as HondaInterface
from opendbc.car.honda.values import CAR as HONDA
from opendbc.car.tesla_ap1.interface import CarInterface as Ap1Interface
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.ap1_curve_brake import A_MIN, RELEASE_JERK
from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed
from openpilot.selfdrive.controls.lib.bogpilot_csc import CRUISING_SPEED
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner, LongitudinalPlanSource
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.ui.onroad.bogpilot import cluster_layout as L

T = np.array(ModelConstants.T_IDXS)
CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
LAT = 2.0  # TESLA_CSC_MAX_LAT_ACCEL with no learning data


class ToggleStore:
  def __init__(self, on=True):
    self.on = on
    self.puts = []

  def toggle_bool(self, key):
    assert key == "CurveSpeedController"
    return self.on

  def get(self, key, default=None):
    return default

  def put(self, key, value):
    self.puts.append((key, value))


class SM(dict):
  def __init__(self, msgs, valid=None, alive=None):
    super().__init__(msgs)
    self.valid = dict.fromkeys(msgs, True)
    self.alive = dict.fromkeys(msgs, True)
    self.valid.update(valid or {})
    self.alive.update(alive or {})


def ap1_cp(long=True):
  cp = Ap1Interface.get_non_essential_params("TESLA_AP1_MODELS")
  cp.openpilotLongitudinalControl = long
  return cp


def planner(cp=None, toggle=True, store=None):
  cp = cp if cp is not None else ap1_cp()
  p = LongitudinalPlanner(cp, init_v=0.0)
  if p.curve_speed.available:
    p.curve_speed = Ap1CurveSpeed(cp, DT_MDL, store if store is not None else ToggleStore(toggle))
  return p


def road(start=1e9, k=0.0, length=1e9):
  return lambda s: k if start <= s < start + length else 0.0


def msgs(v_ego, v_cruise, s=0.0, road_k=None, steer_ratio=15.0, wheelbase=2.959, experimental=False, e2e_accel=0.0,
         enabled=True, blinker=False, lead=None, model_v=None, n=None, yaw_override=None, a_ego=0.0):
  road_k = road() if road_k is None else road_k
  n = len(T) if n is None else n
  v_model = np.full(len(T), v_ego if model_v is None else model_v, dtype=float)
  x = np.cumsum(np.concatenate([[0.0], np.diff(T) * (v_model[:-1] + v_model[1:]) / 2]))
  yaw = np.array([road_k(s + xi) * vi for xi, vi in zip(x, v_model, strict=True)]) if yaw_override is None else np.asarray(yaw_override)
  model = messaging.new_message('modelV2')
  m = model.modelV2
  m.position.x = [float(v) for v in x[:n]]
  m.position.t = [float(v) for v in T[:n]]
  m.velocity.x = [float(v) for v in v_model[:n]]
  m.acceleration.x = [0.0] * n
  m.orientationRate.z = [float(v) for v in yaw[:n]]
  m.orientationRate.t = [float(v) for v in T[:n]]
  m.action.desiredAcceleration = float(e2e_accel)
  m.meta.disengagePredictions.gasPressProbs = [1.0] * 6

  cs = messaging.new_message('carState').carState
  cs.vEgo = float(v_ego)
  cs.aEgo = float(a_ego)
  cs.vCruise = float(v_cruise * 3.6)
  cs.standstill = v_ego < 0.01
  cs.leftBlinker = blinker
  cs.canValid = True
  k_now = road_k(s)
  cs.steeringAngleDeg = float(-math.degrees(k_now * steer_ratio * wheelbase))   # angle: left positive; curvature: right positive

  ctrl = messaging.new_message('controlsState').controlsState
  ctrl.longControlState = LongCtrlState.pid if enabled else LongCtrlState.off
  ctrl.curvature = float(k_now)
  ss = messaging.new_message('selfdriveState').selfdriveState
  ss.enabled = enabled
  ss.experimentalMode = experimental
  cc = messaging.new_message('carControl').carControl
  cc.longActive = enabled
  cc.orientationNED = [0.0, 0.0, 0.0]
  radar = messaging.new_message('radarState').radarState
  if lead is not None:
    d_rel, v_lead = lead
    radar.leadOne.present = True
    radar.leadOne.dRel = float(d_rel)
    radar.leadOne.vLead = float(v_lead)
    radar.leadOne.vLeadK = float(v_lead)
    radar.leadOne.vRel = float(v_lead - v_ego)
    radar.leadOne.aLeadTau = 1.5
    radar.leadOne.modelProb = 1.0
    radar.leadOne.radar = True
  vp = messaging.new_message('vehicleParameters').vehicleParameters
  return {'modelV2': m, 'carState': cs, 'controlsState': ctrl, 'selfdriveState': ss, 'carControl': cc,
          'radarState': radar, 'vehicleParameters': vp}


def drive(p, v0, v_cruise, road_k, seconds, lead_fn=None, experimental=False, e2e_accel=0.0, log=None):
  """Closed loop point mass on the planner output. Returns (s, v) samples."""
  v, s, a = v0, 0.0, 0.0
  out = []
  for i in range(int(seconds / DT_MDL)):
    lead = lead_fn(s, i) if lead_fn else None
    sm = SM(msgs(v, v_cruise, s, road_k, experimental=experimental, e2e_accel=e2e_accel, lead=lead, a_ego=a))
    p.update(sm)
    if log is not None:
      log.append((s, v, p.output_a_target, p.curve_speed.v_cruise_out, p.curve_speed.a_brake, p.curve_speed.controlling,
                  p.mpc.source, mpc_candidate(p)))
    a = float(p.output_a_target)
    v = max(0.0, v + a * DT_MDL)
    s += v * DT_MDL
    out.append((s, v))
  return out


def mpc_candidate(p):
  return float(get_accel_from_plan(p.v_desired_trajectory, p.a_desired_trajectory, CONTROL_N_T_IDX,
                                   action_t=p.CP.longitudinalActuatorDelay + DT_MDL))


def speed_at(samples, s_target):
  return next(v for s, v in samples if s >= s_target)


# --- regular mode: curve-only slowdown ---

K, START = 0.02, 300.0                       # 50 m radius: curve speed sqrt(2 / 0.02) = 10 m/s
V_CURVE = (LAT / K) ** 0.5


def test_regular_mode_slows_for_curve_ahead():
  log = []
  csc = drive(planner(), 25.0, 30.0, road(START, K, 150.0), 40.0, log=log)
  base = drive(planner(toggle=False), 25.0, 30.0, road(START, K, 150.0), 40.0)
  v_entry, v_entry_base = speed_at(csc, START), speed_at(base, START)
  v_in_curve = [v for s, v in csc if START <= s < START + 150.0]
  print("entry", v_entry, "base", v_entry_base, "min in curve", min(v_in_curve), "max in curve", max(v_in_curve))
  assert v_entry_base > 24.0                 # stock regular mode does not slow for the curve
  assert v_entry <= V_CURVE + 0.5            # reaches the curve speed by the curve
  assert max(v_in_curve) <= V_CURVE + 0.5 and max(v_in_curve) ** 2 * K <= LAT + 0.25
  assert min(v_in_curve) >= CRUISING_SPEED   # never stops for a curve
  assert any(row[5] for row in log)          # CSC controlled speed
  assert all(row[4] >= A_MIN - 1e-9 for row in log)
  assert any(row[4] < 0.0 for row in log)    # the look-ahead brake was used


def test_never_raises_the_driver_cruise_speed():
  log = []
  drive(planner(), 25.0, 30.0, road(START, K, 150.0), 40.0, log=log)
  assert all(row[3] <= 30.0 + 1e-9 for row in log)
  assert all(row[4] <= 0.0 for row in log)


def test_set_speed_below_curve_speed_unchanged():
  # Cruising at 8 m/s with a 10 m/s curve: CSC detects the curve but the result equals stock.
  a, b = [], []
  drive(planner(), 8.0, 8.0, road(60.0, K, 100.0), 25.0, log=a)
  drive(planner(toggle=False), 8.0, 8.0, road(60.0, K, 100.0), 25.0, log=b)
  assert any(row[5] for row in a)
  assert [row[2] for row in a] == pytest.approx([row[2] for row in b], abs=1e-9)


def test_straight_road_identical_to_toggle_off_regular_and_experimental():
  for exp in (False, True):
    a, b = [], []
    drive(planner(), 20.0, 30.0, road(), 20.0, experimental=exp, e2e_accel=0.3, log=a)
    drive(planner(toggle=False), 20.0, 30.0, road(), 20.0, experimental=exp, e2e_accel=0.3, log=b)
    assert [row[2] for row in a] == [row[2] for row in b]
    assert [row[6] for row in a] == [row[6] for row in b]


def test_lead_following_not_weakened():
  # Slower lead inside the curve: every output stays at or below the lead MPC candidate.
  def lead_fn(s, i):   # lead starts 50 m ahead at 8 m/s
    return (max(1.0, 50.0 + 8.0 * i * DT_MDL - s), 8.0)
  log = []
  drive(planner(), 20.0, 30.0, road(80.0, K, 200.0), 15.0, lead_fn=lead_fn, log=log)
  assert all(row[2] <= row[7] + 1e-6 for row in log)
  # Straight road with the same lead: identical to toggle off.
  a, b = [], []
  drive(planner(), 20.0, 30.0, road(), 15.0, lead_fn=lead_fn, log=a)
  drive(planner(toggle=False), 20.0, 30.0, road(), 15.0, lead_fn=lead_fn, log=b)
  assert [row[2] for row in a] == [row[2] for row in b]


def test_experimental_e2e_candidate_preserved():
  # Experimental mode still offers the model's accel; when it is the strongest it wins, CSC on or off.
  p = planner()
  for i in range(60):
    p.update(SM(msgs(20.0, 30.0, 220.0 + 20.0 * i * DT_MDL, road(300.0, K, 150.0), experimental=True, e2e_accel=-2.0)))
  assert p.curve_speed.controlling
  assert p.mpc.source == LongitudinalPlanSource.e2e and p.output_a_target == pytest.approx(-2.0, abs=0.05)
  # Regular mode never uses the model's accel even when it is lower.
  p = planner()
  for _ in range(20):
    p.update(SM(msgs(20.0, 30.0, 0.0, road(), experimental=False, e2e_accel=-2.0)))
  assert p.mpc.source != LongitudinalPlanSource.e2e and p.output_a_target > -1.0


# --- gating and fail-closed ---

def test_curvature_sign_convention_and_glyph():
  # openpilot frames: modelV2 is device frame (y right, z down), so positive orientationRate.z / road curvature is a
  # RIGHT curve, and controlsState.curvature = -VM.calc_curvature(steeringAngleDeg) is also right-positive. Public
  # 0.11.2 log replay agreed (road curvature vs steering angle opposite on every strong-signal frame). The daily rule
  # left = roadCurvature < 0 therefore draws a left glyph for left curves.
  for k, want_left in ((K, False), (-K, True)):
    p = planner()
    for i in range(80):
      p.update(SM(msgs(20.0, 30.0, 220.0 + 20.0 * i * DT_MDL, road(300.0, k, 150.0))))
    cs = p.curve_speed
    assert cs.controlling and math.copysign(1.0, cs.road_curvature) == math.copysign(1.0, k)
    msg = messaging.new_message('frogpilotPlan')
    cs.fill(msg.frogpilotPlan)
    slot = L.csc_slot(L.csc_status_from_plan(msg.frogpilotPlan),
                      L.CscContext(cruise_set=True, set_speed_display=67.0, display_conv=2.23694))
    assert slot.active and slot.left == want_left


def run_inactive(p, sm_kwargs=None, **kw):
  for i in range(80):
    p.update(SM(msgs(20.0, 30.0, 200.0 + 20.0 * i * DT_MDL, road(250.0, K, 150.0), **kw), **(sm_kwargs or {})))
  return p


@pytest.mark.parametrize("make", [
  lambda: planner(ap1_cp(long=False)),                                   # AP1 stock ACC
  lambda: planner(toggle=False),                                         # CurveSpeedController off
  lambda: LongitudinalPlanner(HondaInterface.get_non_essential_params(HONDA.HONDA_CIVIC)),   # not AP1
])
def test_inactive_paths(make):
  p = run_inactive(make())
  cs = p.curve_speed
  assert not cs.valid and not cs.controlling and cs.a_brake == 0.0 and cs.v_cruise_out == pytest.approx(30.0)


@pytest.mark.parametrize("sm_kwargs,kw", [
  ({"valid": {'modelV2': False}}, {}),
  ({"alive": {'modelV2': False}}, {}),
  ({"valid": {'carState': False}}, {}),
  ({}, {"n": 32}),                                                       # short arrays
  ({}, {"yaw_override": [float('nan')] * 33}),                           # non-finite
])
def test_stale_or_bad_model_fails_closed(sm_kwargs, kw):
  p = run_inactive(planner(), sm_kwargs, **kw)
  assert not p.curve_speed.valid and not p.curve_speed.controlling and p.curve_speed.a_brake == 0.0


def test_plain_dict_sm_fails_closed():
  p = planner()
  for i in range(40):
    p.update(msgs(20.0, 30.0, 220.0 + i, road(250.0, K, 150.0)))
  assert not p.curve_speed.valid and p.curve_speed.a_brake == 0.0


def test_model_goes_stale_mid_brake_only_releases():
  p = planner()
  for i in range(60):
    p.update(SM(msgs(20.0, 30.0, 240.0 + 20.0 * i * DT_MDL, road(300.0, K, 150.0))))
  assert p.curve_speed.a_brake < -0.3
  prev = p.curve_speed.a_brake
  for _ in range(40):
    p.update(SM(msgs(20.0, 30.0, 300.0, road(300.0, K, 150.0)), valid={'modelV2': False}))
    a = p.curve_speed.a_brake
    assert prev <= a <= prev + RELEASE_JERK * DT_MDL + 1e-9
    assert p.curve_speed.v_cruise_out == pytest.approx(30.0) and not p.curve_speed.valid
    prev = a
  assert prev == 0.0


def test_disengage_resets_and_reengage_restarts_target():
  p = planner()
  for i in range(60):
    p.update(SM(msgs(20.0, 30.0, 240.0 + 20.0 * i * DT_MDL, road(300.0, K, 150.0))))
  assert p.curve_speed.controlling and p.curve_speed.a_brake < 0.0
  p.update(SM(msgs(18.0, 30.0, 290.0, road(300.0, K, 150.0), enabled=False)))
  assert not p.curve_speed.controlling and p.curve_speed.a_brake == 0.0 and not p.curve_speed.csc.target_set
  assert p.curve_speed.brake.a_request == 0.0
  p.update(SM(msgs(18.0, 30.0, 291.0, road(300.0, K, 150.0))))
  assert p.curve_speed.controlling and p.curve_speed.target == pytest.approx(18.0)


def test_blinker_suspends_csc():
  p = planner()
  for i in range(40):
    p.update(SM(msgs(20.0, 30.0, 240.0 + 20.0 * i * DT_MDL, road(300.0, K, 150.0), blinker=True)))
  assert p.curve_speed.valid and not p.curve_speed.controlling


def test_non_finite_speed_fails_closed():
  cs = Ap1CurveSpeed(ap1_cp(), DT_MDL, ToggleStore())
  sm = SM(msgs(20.0, 30.0, 280.0, road(300.0, K, 150.0)))
  assert cs.update(sm, float('nan'), 30.0, False) == 30.0 and not cs.valid
  assert math.isnan(cs.update(sm, 20.0, float('nan'), False)) and not cs.valid


def test_learning_disabled_while_toggle_off():
  store = ToggleStore(False)
  p = planner(store=store)
  for _ in range(400):
    p.update(SM(msgs(15.0, 30.0, 0.0, road(0.0, 0.01, 1e9), enabled=False)))
  assert store.puts == [] and not p.curve_speed.training


# --- frogpilotPlan report: units, validity, UI slot ---

def test_frogpilot_plan_units_and_ui_slot():
  p = planner()
  for i in range(80):
    p.update(SM(msgs(20.0, 30.0, 220.0 + 20.0 * i * DT_MDL, road(300.0, K, 150.0))))
  cs = p.curve_speed
  assert cs.valid and cs.controlling
  msg = messaging.new_message('frogpilotPlan')
  msg.valid = cs.valid
  cs.fill(msg.frogpilotPlan)
  plan = msg.frogpilotPlan
  assert plan.roadCurvature == pytest.approx(K, rel=1e-5)                 # 1/m; positive = RIGHT curve (model frame)
  assert V_CURVE - 0.01 <= plan.cscSpeed <= 20.0 + 1e-6                   # m/s, ramping from v_ego to the curve speed
  assert plan.vCruise == pytest.approx(min(plan.cscSpeed, 30.0), rel=1e-6)
  status = L.csc_status_from_plan(plan)
  assert status.valid and status.controlling
  slot = L.csc_slot(status, L.CscContext(cruise_set=True, set_speed_display=30.0 * 2.23694, display_conv=2.23694))
  assert slot.active and not slot.left and slot.speed == str(round(plan.cscSpeed * 2.23694)) and slot.from_speed == round(30.0 * 2.23694)
  hidden = L.csc_slot(status, L.CscContext(cruise_set=True, show_status=False, set_speed_display=67.0, display_conv=2.23694))
  assert hidden == L.CscSlot()


class FakePM:
  def __init__(self):
    self.sent = []

  def send(self, name, msg):
    self.sent.append((name, msg))


@pytest.mark.parametrize("toggle", [True, False])
def test_publish_frogpilot_plan_valid_flag(toggle):
  p = planner(toggle=toggle)
  p.update(SM(msgs(20.0, 30.0, 280.0, road(300.0, K, 150.0))))
  pm = FakePM()
  p.publish_frogpilot_plan(pm)
  name, msg = pm.sent[0]
  assert name == 'frogpilotPlan' and msg.valid == toggle
