"""AP1 comfort-band accel slew (long_smooth.py) and its CarController wiring."""
import math
import random

import pytest

from openpilot.selfdrive.car.tesla.long_smooth import (
  AP1_BRAKE_BYPASS_ACCEL, AP1_BRAKE_HARD_ACCEL, AP1_BRAKE_ONSET_JERK, AP1_BRAKE_URGENT_ACCEL, AP1_COMFORT_JERK_LIMIT,
  AP1_FALL_JERK, AP1_FULL_JERK_LIMIT, AP1_JERK_BLEND_START, AP1_JERK_LIMIT_NARROW_RATE, AP1_RISE_JERK, AP1_SLEW_MIN_SPEED,
  Ap1AccelSmoother, Ap1JerkLimit, ap1_brake_ramp_jerk, ap1_brake_urgent, ap1_jerk_limit_target,
)
from openpilot.selfdrive.car.tesla.values import CarControllerParams

UP = AP1_RISE_JERK * 0.01
DN = AP1_FALL_JERK * 0.01
ON = AP1_BRAKE_ONSET_JERK * 0.01
V = 10.0


def _run(seq, v=V, active=True):
  s = Ap1AccelSmoother()
  return [s.update(a, active, v) for a in seq]


def test_steady_and_normal_ramps_pass_unchanged():
  up = [0.01 * i for i in range(100)]  # 1 m/s^3
  assert _run(up) == pytest.approx(up)
  down = [-0.02 * i for i in range(100)]  # 2 m/s^3 into braking
  assert _run(down) == pytest.approx(down)
  assert _run([0.3] * 50) == pytest.approx([0.3] * 50)


def test_step_up_is_slewed():
  out = _run([0.0] + [0.5] * 30)
  assert out[1] == pytest.approx(UP)
  assert out[10] == pytest.approx(10 * UP)
  assert out[-1] == pytest.approx(0.5)


def test_brake_blip_reversal_is_smoothed():
  # 02a 158.2: +0.48 -> -0.44 (one plan step) -> -0.16
  seq = [0.48] * 5 + [-0.44] * 5 + [-0.16] * 20
  out = _run(seq)
  assert out[5] == pytest.approx(0.48 - DN)
  assert min(out) >= -0.16 - 1e-9  # the -0.44 blip is not passed on
  assert out[-1] == pytest.approx(-0.16)


@pytest.mark.parametrize("target", [AP1_BRAKE_HARD_ACCEL, -2.5, -3.5])
def test_hard_braking_is_never_delayed(target):
  assert _run([0.4, target])[1] == target
  assert _run([-0.2, target])[1] == target
  assert _run([1.5, target])[1] == target


@pytest.mark.parametrize("target", [-0.5, -0.9, -1.5, -1.95])
def test_moderate_braking_ramps_in(target):
  out = _run([0.0] + [target] * 100)
  assert out[1] == pytest.approx(-ap1_brake_ramp_jerk(target) * 0.01)
  assert out[1] > target
  assert out[-1] == pytest.approx(target)


def test_comfort_band_braking_ramps_at_onset_jerk():
  out = _run([0.0] + [-0.45] * 30)
  assert out[1] == pytest.approx(-ON)
  assert out[10] == pytest.approx(-10 * ON)
  n = math.ceil(0.45 / ON - 1e-9)
  assert out[n - 1] > -0.45
  assert out[n] == pytest.approx(-0.45)


def test_lead_pickup_step_e1_drive_release_then_regen_ramp():
  # 0000002e 16:09:22.12 ET: aTarget +1.37 -> -0.88 in one plan step (86 m lead).
  out = _run([1.37] * 5 + [-0.88] * 100)
  assert out[5] == pytest.approx(1.37 - DN)  # drive released at the comfort fall rate
  k0 = next(i for i, o in enumerate(out) if o <= 0.0)
  assert 0.25 <= (k0 - 4) * 0.01 <= 0.3
  for a, b in zip(out[k0 + 1:], out[k0 + 2:]):
    assert b >= a - ON - 1e-12  # regen ramps in no faster than the onset jerk
  k1 = next(i for i, o in enumerate(out) if o <= -0.88 + 1e-9)
  assert (k1 - 4) * 0.01 <= 0.72


@pytest.mark.parametrize("start,target,limit_s", [
  (0.0, -0.9, 0.46), (0.0, -1.0, 0.51), (0.0, -1.5, 0.31), (0.0, -1.95, 0.27),
  (1.5, -1.0, 0.81), (1.5, -1.5, 0.61), (2.0, -1.0, 0.91),
])
def test_time_to_reach_braking_is_bounded(start, target, limit_s):
  s = Ap1AccelSmoother()
  s.update(start, True, V)
  for i in range(1, 200):
    if s.update(target, True, V) <= target + 1e-9:
      break
  assert i * 0.01 <= limit_s


def test_ramp_jerk_blend():
  assert ap1_brake_ramp_jerk(0.0) == AP1_BRAKE_ONSET_JERK
  assert ap1_brake_ramp_jerk(AP1_BRAKE_URGENT_ACCEL) == AP1_BRAKE_ONSET_JERK
  assert ap1_brake_ramp_jerk(AP1_BRAKE_HARD_ACCEL) == AP1_FULL_JERK_LIMIT
  xs = [0.2 - 0.001 * i for i in range(2600)]
  ys = [ap1_brake_ramp_jerk(x) for x in xs]
  for y0, y1 in zip(ys, ys[1:]):
    assert y0 - 1e-12 <= y1 <= y0 + 0.01  # monotonic, no step


def test_urgent_passes_falling_through_but_not_rising():
  s = Ap1AccelSmoother()
  s.update(0.5, True, V)
  assert s.update(-0.9, True, V, urgent=True) == -0.9
  assert s.update(0.5, True, V, urgent=True) == pytest.approx(-0.9 + UP)


def test_release_from_braking_is_slewed():
  out = _run([-2.0, -0.2, -0.2])
  assert out[1] == pytest.approx(-2.0 + UP)


def test_property_bounded_and_hard_band_never_less_braking():
  rnd = random.Random(7)
  s = Ap1AccelSmoother()
  a = 0.0
  for _ in range(20000):
    a = rnd.uniform(-3.5, 2.0) if rnd.random() < 0.1 else max(-3.5, min(2.0, a + rnd.uniform(-0.3, 0.3)))
    prev = s.last
    out = s.update(a, True, V)
    if prev is not None:
      assert min(prev, a) - 1e-12 <= out <= max(prev, a) + 1e-12
      assert out <= prev + UP + 1e-12
      if a <= AP1_BRAKE_HARD_ACCEL:
        assert out <= a + 1e-12
      elif a < prev:
        jerk = max(AP1_FALL_JERK, ap1_brake_ramp_jerk(a)) if prev > 0 else ap1_brake_ramp_jerk(a)
        assert out == pytest.approx(max(a, prev - jerk * 0.01))


def test_inactive_resets_and_passes_through():
  s = Ap1AccelSmoother()
  s.update(0.0, True, V)
  assert s.update(1.0, False, V) == 1.0
  assert s.last is None
  assert s.update(0.8, True, V) == 0.8  # first active frame seeds


def test_gas_neutral_outputs_zero_and_release_ramps_from_zero():
  s = Ap1AccelSmoother()
  s.update(0.6, True, V)
  assert s.update(0.6, True, V, gas_neutral=True) == 0.0
  assert s.update(0.6, True, V) == pytest.approx(UP)


def test_low_speed_passes_through():
  s = Ap1AccelSmoother()
  s.update(-2.0, True, 0.0)
  assert s.update(0.3, True, AP1_SLEW_MIN_SPEED - 0.01) == 0.3
  assert s.update(0.8, True, AP1_SLEW_MIN_SPEED + 0.5) == pytest.approx(0.3 + UP)


# --- Jerk fields -------------------------------------------------------------

def test_full_jerk_matches_existing_constant():
  assert AP1_FULL_JERK_LIMIT == CarControllerParams.JERK_LIMIT_MAX == -CarControllerParams.JERK_LIMIT_MIN


@pytest.mark.parametrize("a", [AP1_BRAKE_BYPASS_ACCEL, -0.8, -2.0, -3.5])
def test_jerk_full_at_or_below_bypass(a):
  assert ap1_jerk_limit_target(a) == AP1_FULL_JERK_LIMIT


@pytest.mark.parametrize("a", [AP1_JERK_BLEND_START, -0.1, 0.0, 0.5, 2.0])
def test_jerk_comfort_in_band(a):
  assert ap1_jerk_limit_target(a) == AP1_COMFORT_JERK_LIMIT


def test_jerk_blend_is_continuous_and_monotonic():
  xs = [AP1_BRAKE_BYPASS_ACCEL - 0.1 + 0.001 * i for i in range(400)]
  ys = [ap1_jerk_limit_target(x) for x in xs]
  for y0, y1 in zip(ys, ys[1:]):
    assert y1 <= y0 + 1e-12
    assert abs(y1 - y0) < 0.05  # no step in the limit itself


def test_jerk_widens_immediately_and_narrows_at_rate():
  j = Ap1JerkLimit()
  assert j.update(0.2, True, V) == (-(AP1_FULL_JERK_LIMIT - AP1_JERK_LIMIT_NARROW_RATE * 0.01),
                                    AP1_FULL_JERK_LIMIT - AP1_JERK_LIMIT_NARROW_RATE * 0.01)
  for _ in range(100):
    lo, hi = j.update(0.2, True, V)
  assert (lo, hi) == (-AP1_COMFORT_JERK_LIMIT, AP1_COMFORT_JERK_LIMIT)
  assert j.update(-0.6, True, V) == (-AP1_FULL_JERK_LIMIT, AP1_FULL_JERK_LIMIT)  # same step


def test_jerk_full_immediately_when_urgent():
  j = Ap1JerkLimit()
  for _ in range(200):
    j.update(0.1, True, V)
  assert j.update(0.1, True, V, urgent=True) == (-AP1_FULL_JERK_LIMIT, AP1_FULL_JERK_LIMIT)


def test_brake_urgent_from_carcontrol():
  from cereal import car
  CC = car.CarControl.new_message()
  assert not ap1_brake_urgent(CC.as_reader())
  CC.hudControl.visualAlert = car.CarControl.HUDControl.VisualAlert.fcw
  assert ap1_brake_urgent(CC.as_reader())
  CC = car.CarControl.new_message()
  CC.actuators.longControlState = car.CarControl.Actuators.LongControlState.stopping
  assert ap1_brake_urgent(CC.as_reader())
  CC.actuators.longControlState = car.CarControl.Actuators.LongControlState.pid
  CC.hudControl.visualAlert = car.CarControl.HUDControl.VisualAlert.steerRequired
  assert not ap1_brake_urgent(CC.as_reader())


def test_jerk_full_when_low_speed_inactive_or_gas_neutral():
  for kw in ({"active": True, "v_ego": 0.5}, {"active": False, "v_ego": V}):
    j = Ap1JerkLimit()
    for _ in range(200):
      out = j.update(0.1, kw["active"], kw["v_ego"])
    assert out == (-AP1_FULL_JERK_LIMIT, AP1_FULL_JERK_LIMIT)
  j = Ap1JerkLimit()
  for _ in range(200):
    j.update(0.1, True, V)
  assert j.update(0.1, True, V, gas_neutral=True) == (-AP1_FULL_JERK_LIMIT, AP1_FULL_JERK_LIMIT)


def test_jerk_fields_pack_inside_dbc_range():
  # DAS_jerkMin 9 bit (0.03, -15.232), DAS_jerkMax 8 bit (0.059, 0)
  for v in (-AP1_COMFORT_JERK_LIMIT, -AP1_FULL_JERK_LIMIT):
    assert 0 <= round((v + 15.232) / 0.03) < 512
  for v in (AP1_COMFORT_JERK_LIMIT, AP1_FULL_JERK_LIMIT):
    assert 0 <= round(v / 0.059) < 256


# --- CarController wiring (stub packer, same pattern as test_ap1_resume_hold) ---

from openpilot.selfdrive.car.tesla.tests.test_ap1_resume_hold import cc_mod  # noqa: E402,F401


def _das(cc_mod, accels, v=V, gas=False, fcw_from=None):
  import ast
  from collections import deque
  from types import SimpleNamespace
  from cereal import car
  from openpilot.selfdrive.car.tesla.values import CAR
  ctl = cc_mod.CarController("tesla_can", SimpleNamespace(
    carFingerprint=CAR.TESLA_AP1_MODELS, openpilotLongitudinalControl=True), None)
  ctl.cluster = None
  sent = []
  for i, a in enumerate(accels):
    CC = car.CarControl.new_message()
    CC.enabled = True
    CC.latActive = True
    CC.longActive = True
    CC.actuators.accel = a
    if fcw_from is not None and i >= fcw_from:
      CC.hudControl.visualAlert = car.CarControl.HUDControl.VisualAlert.fcw
    CS = SimpleNamespace(
      out=SimpleNamespace(steeringAngleDeg=0.0, vEgo=v, gasPressed=gas),
      steer_warning="EAC_ERROR_IDLE", hands_on_level=0, eac_fault=False, eac_status="EAC_ACTIVE",
      acc_state=4, das_control_counters=deque([i % 8]), msg_stw_actn_req={}, cluster_stock={},
    )
    out, can = ctl.update(CC.as_reader(), CS, i * 10_000_000, None)
    das = [dict(ast.literal_eval(m[2].decode())) for m in can if m[0] == "DAS_control"]
    sent.append((out.accel, das[0]["DAS_accelMin"], das[0]["DAS_accelMax"], das[0]["DAS_jerkMin"], das[0]["DAS_jerkMax"]))
  return sent


def test_controller_slews_gas_step_into_das_control(cc_mod):  # noqa: F811
  sent = _das(cc_mod, [0.0, 0.5, 0.5])
  assert sent[1][2] == pytest.approx(UP)
  assert sent[1][0] == pytest.approx(UP)


def test_controller_hard_brake_reaches_das_control_same_step(cc_mod):  # noqa: F811
  sent = _das(cc_mod, [0.2, -2.0])
  assert sent[1][1] == pytest.approx(-2.0, abs=0.04)
  assert sent[1][2] == 0
  assert sent[1][3:] == (-AP1_FULL_JERK_LIMIT, AP1_FULL_JERK_LIMIT)


def test_controller_moderate_brake_ramps_in(cc_mod):  # noqa: F811
  sent = _das(cc_mod, [0.0] + [-0.9] * 50)
  assert sent[1][0] == pytest.approx(-ON)
  assert sent[1][1] == pytest.approx(-ON, abs=0.04)
  assert sent[-1][0] == pytest.approx(-0.9)


def test_controller_fcw_brake_reaches_das_control_same_step(cc_mod):  # noqa: F811
  sent = _das(cc_mod, [0.3, -1.2], fcw_from=1)
  assert sent[1][0] == pytest.approx(-1.2)
  assert sent[1][1] == pytest.approx(-1.2, abs=0.04)
  assert sent[1][3:] == (-AP1_FULL_JERK_LIMIT, AP1_FULL_JERK_LIMIT)


def test_controller_gas_neutral_frame_unchanged(cc_mod):  # noqa: F811
  sent = _das(cc_mod, [0.7, 0.7], gas=True)
  assert all(s[1] == 0 and s[2] == 0 for s in sent)


def test_controller_sends_comfort_jerk_then_full_for_braking(cc_mod):  # noqa: F811
  sent = _das(cc_mod, [0.1] * 100 + [-1.0] * 60)
  assert sent[0][3:] == (-(AP1_FULL_JERK_LIMIT - AP1_JERK_LIMIT_NARROW_RATE * 0.01), AP1_FULL_JERK_LIMIT - AP1_JERK_LIMIT_NARROW_RATE * 0.01)
  assert sent[99][3:] == (-AP1_COMFORT_JERK_LIMIT, AP1_COMFORT_JERK_LIMIT)
  # The field follows the ramped request: comfort while it is above the blend
  # start, full once it is at or below -0.5, and never narrower than before.
  for prev, cur in zip(sent[100:], sent[101:]):
    assert cur[4] >= prev[4] - 1e-9
    if cur[0] >= AP1_JERK_BLEND_START:
      assert cur[3:] == (-AP1_COMFORT_JERK_LIMIT, AP1_COMFORT_JERK_LIMIT)
    if cur[0] <= AP1_BRAKE_BYPASS_ACCEL:
      assert cur[3:] == pytest.approx((-AP1_FULL_JERK_LIMIT, AP1_FULL_JERK_LIMIT))
  assert sent[-1][0] == pytest.approx(-1.0)


def test_controller_low_speed_keeps_full_jerk(cc_mod):  # noqa: F811
  sent = _das(cc_mod, [0.3] * 50, v=0.5)
  assert all(s[3:] == (CarControllerParams.JERK_LIMIT_MIN, CarControllerParams.JERK_LIMIT_MAX) for s in sent)


def test_teslacan_default_jerk_unchanged_for_other_callers():
  import inspect
  from openpilot.selfdrive.car.tesla.teslacan import TeslaCAN
  sig = inspect.signature(TeslaCAN.create_longitudinal_commands)
  assert sig.parameters["jerk_min"].default == CarControllerParams.JERK_LIMIT_MIN
  assert sig.parameters["jerk_max"].default == CarControllerParams.JERK_LIMIT_MAX
