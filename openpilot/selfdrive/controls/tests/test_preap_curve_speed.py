"""Pre-AP pedal CSC on the real Ap1CurveSpeed with synthetic modelV2 / carState messages (not a log replay, not a drive).

CSC controls (curve braking; the displayed set speed follows the curve speed) only while the Pre-AP pull FSM is in FULL
with a live pedal; steering only never brakes. The cruise speed handed back to the planner is never lowered. Needs the
native messaging / MPC libraries: skipped where they are not built."""
from types import SimpleNamespace

import numpy as np
import pytest

try:
  import openpilot.cereal.messaging as messaging
  from openpilot.common.realtime import DT_MDL
  from openpilot.selfdrive.controls.lib.curve_speed_planner import A_MIN
  from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed
  from openpilot.selfdrive.modeld.constants import ModelConstants
except (ImportError, OSError) as e:   # msgq / params / acados natives not built on this host
  pytest.skip(f"native libraries unavailable: {e}", allow_module_level=True)

T = np.array(ModelConstants.T_IDXS)
K, START = 0.02, 300.0                # 50 m radius: curve speed sqrt(2.0 / 0.02) = 10 m/s
FULL, LAT_ONLY, LAT_PENDING, OFF = 4, 3, 2, 0


class ToggleStore:
  def toggle_bool(self, key):
    assert key == "CurveSpeedController"
    return True

  def get(self, key, default=None):
    return default

  def put(self, key, value):
    pass


class SM(dict):
  def __init__(self, msgs, valid=None):
    super().__init__(msgs)
    self.valid = dict.fromkeys(msgs, True)
    self.alive = dict.fromkeys(msgs, True)
    self.valid.update(valid or {})


def preap_cp():
  return SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True, pcmCruise=False)


def road(start=START, k=K, length=150.0):
  return lambda s: k if start <= s < start + length else 0.0


def msgs(v_ego, s, road_k, mode=FULL, pedal=True, n=None, long_active=None):
  n = len(T) if n is None else n
  v_model = np.full(len(T), v_ego, dtype=float)
  x = np.cumsum(np.concatenate([[0.0], np.diff(T) * (v_model[:-1] + v_model[1:]) / 2]))
  yaw = np.array([road_k(s + xi) * vi for xi, vi in zip(x, v_model, strict=True)])
  model = messaging.new_message('modelV2').modelV2
  model.position.x = [float(v) for v in x[:n]]
  model.velocity.x = [float(v) for v in v_model[:n]]
  model.orientationRate.z = [float(v) for v in yaw[:n]]
  model.orientationRate.t = [float(v) for v in T[:n]]
  cs = messaging.new_message('carState').carState
  cs.vEgo = float(v_ego)
  cs.bogpilot.preapFsmMode = mode
  cs.bogpilot.preapPedalDetected = pedal
  cs.bogpilot.preapPedalCalibrated = pedal
  ctrl = messaging.new_message('controlsState').controlsState
  ctrl.curvature = float(road_k(s))
  ss = messaging.new_message('selfdriveState').selfdriveState
  ss.enabled = True                    # cruiseState.enabled is true in LAT_PENDING / LAT_ONLY / FULL
  cc = messaging.new_message('carControl').carControl
  cc.longActive = (mode == FULL) if long_active is None else long_active
  radar = messaging.new_message('radarState').radarState
  return {'modelV2': model, 'carState': cs, 'controlsState': ctrl, 'selfdriveState': ss, 'carControl': cc, 'radarState': radar}


def run(v_cruise, mode=FULL, pedal=True, seconds=6.0, s0=200.0, v=20.0, road_k=None, valid=None, n=None):
  c = Ap1CurveSpeed(preap_cp(), DT_MDL, ToggleStore(), pedal_ok=True)
  road_k = road() if road_k is None else road_k
  outs = []
  for i in range(int(seconds / DT_MDL)):
    s = s0 + v * i * DT_MDL
    out = c.update(SM(msgs(v, s, road_k, mode=mode, pedal=pedal, n=n), valid=valid), v, v_cruise, False)
    assert out == v_cruise
    outs.append((c.v_cruise_out, c.a_curve, c.controlling))
  return c, outs


def test_available_preap_pedal_op_long():
  c = Ap1CurveSpeed(preap_cp(), DT_MDL, ToggleStore(), pedal_ok=True)
  assert c.available and c.preap and c.planner is not None


def test_unavailable_preap_no_pedal():
  c = Ap1CurveSpeed(preap_cp(), DT_MDL, ToggleStore(), pedal_ok=False)
  assert not c.available and c.planner is None and c.csc is None


def test_controls_only_in_full_mode():
  c, outs = run(30.0, mode=FULL)
  assert any(ctl for _, _, ctl in outs)
  assert min(o for o, _, _ in outs) < 30.0 - 1.0
  assert all(o <= 30.0 + 1e-9 for o, _, _ in outs)              # never raises the set
  assert any(a < 0.0 for _, a, _ in outs) and all(a >= A_MIN - 1e-9 for _, a, _ in outs)
  assert c.valid


@pytest.mark.parametrize("mode", [OFF, LAT_PENDING, LAT_ONLY])
def test_lat_only_does_not_cap(mode):
  c, outs = run(30.0, mode=mode)
  assert all(o == pytest.approx(30.0) and a == 0.0 and not ctl for o, a, ctl in outs)
  assert c.valid                                                # active (learning allowed), just never controlling


def test_missing_mode_fails_closed():
  c, outs = run(30.0, mode=FULL, pedal=False)                   # pedal flags false (or missing): inactive
  assert all(o == pytest.approx(30.0) and a == 0.0 and not ctl for o, a, ctl in outs)
  assert not c.valid


@pytest.mark.parametrize("valid,n", [({'modelV2': False}, None), ({'carState': False}, None), (None, 32)])
def test_missing_model_fails_closed_on_preap(valid, n):
  c, outs = run(30.0, mode=FULL, valid=valid, n=n)
  assert all(o == pytest.approx(30.0) and a == 0.0 and not ctl for o, a, ctl in outs)
  assert not c.valid


def test_setspeedlimit_then_csc_min():
  engage_set = (45 + 5) * 0.44704                                # 45 mph limit + 5 mph offset, as SetSpeedLimit sets it
  _, curve = run(engage_set, mode=FULL)
  assert min(o for o, _, _ in curve) < engage_set - 1.0 and all(o <= engage_set + 1e-9 for o, _, _ in curve)
  _, straight = run(engage_set, mode=FULL, road_k=lambda s: 0.0)
  assert all(o == pytest.approx(engage_set) for o, _, _ in straight)


def test_training_policy_in_lat_only():
  # Default: learning is allowed in steering only (0.9.7 trained while longActive was False).
  steady = road(0.0, 0.004, 1e9)                                # 1.6 m/s^2 at 20 m/s: a curve the driver is taking
  c, _ = run(30.0, mode=LAT_ONLY, seconds=12.0, road_k=steady)
  assert c.training and not c.controlling
  c, _ = run(30.0, mode=FULL, seconds=12.0, road_k=steady)
  assert c.controlling and not c.training                       # CSC controlling in FULL: no learning from its own speed
