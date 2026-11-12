"""AP1 allowThrottle smoothing is called from the real longitudinal planner (synthetic messages, real planner + capnp).

test_ap1_throttle_gate.py covers the filter module; these tests cover the call site: the planner owns an Ap1ThrottleCap
only on TESLA_AP1_MODELS, feeds it the model's allowThrottle flag every plan step, and hands the 0..1 cut fraction to
get_cruise_accel. Only the cruise max-accel limit can be lowered: ACCEL_MIN and the braking limits are untouched.
Synthetic checks, not a log replay and not a drive.
"""
import numpy as np
import pytest

import openpilot.selfdrive.controls.lib.longitudinal_planner as lp
from opendbc.car.honda.interface import CarInterface as HondaInterface
from opendbc.car.interfaces import ACCEL_MIN
from opendbc.car.tesla_ap1.throttle_gate import Ap1ThrottleCap, apply_cut
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.longitudinal_planner import (
  ALLOW_THROTTLE_THRESHOLD, MIN_ALLOW_THROTTLE_SPEED, LongitudinalPlanner, get_cruise_accel,
)
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, ap1_cp, msgs

V = 20.0       # well above 2 * MIN_ALLOW_THROTTLE_SPEED: the coast limit is fully applied
V_SET = 30.0   # far above V: the cruise limit is the max-accel cap


def new_planner(cp=None):
  p = LongitudinalPlanner(cp if cp is not None else ap1_cp(), init_v=V)
  from openpilot.selfdrive.controls.lib.phase3_speed_control import Ap1SpeedControl
  p.speed_control = Ap1SpeedControl(p.CP, adopted=False)   # keep the default-ON Speed Limit Controller out of these checks
  return p


def step(p, throttle_prob, v=V, enabled=True):
  m = msgs(v, V_SET, enabled=enabled)
  m['modelV2'].meta.disengagePredictions.gasPressProbs = [1.0, float(throttle_prob), 1.0, 1.0, 1.0, 1.0]
  p.update(SM(m))


@pytest.fixture
def cut_log(monkeypatch):
  """Records the throttle_cut argument the planner passes to get_cruise_accel."""
  calls = []
  real = lp.get_cruise_accel

  def spy(*args, **kwargs):
    calls.append(kwargs["throttle_cut"] if "throttle_cut" in kwargs else (args[10] if len(args) > 10 else None))
    return real(*args, **kwargs)
  monkeypatch.setattr(lp, "get_cruise_accel", spy)
  return calls


def test_only_ap1_planner_owns_a_gate():
  assert isinstance(new_planner().ap1_throttle_gate, Ap1ThrottleCap)
  for cp in (HondaInterface.get_non_essential_params("HONDA_CIVIC"),):
    other = LongitudinalPlanner(cp, init_v=V)
    assert other.ap1_throttle_gate is None


def test_planner_feeds_the_gate_and_passes_the_cut_to_the_cruise_limit(cut_log):
  p = new_planner()
  ref = Ap1ThrottleCap()
  probs = [0.9] * 5 + [0.0] + [0.9] * 10 + [0.1] * 10 + [0.9, 0.0] * 10     # single blip, sustained no-throttle, chatter
  for prob in probs:
    step(p, prob)
    expected = ref.update(prob > ALLOW_THROTTLE_THRESHOLD, low_speed=False, reset=False)
    assert p.throttle_cut == pytest.approx(expected)
    assert cut_log[-1] == pytest.approx(expected)          # the call site: get_cruise_accel receives the gate output
    assert p.allow_throttle == (expected < 0.5)            # published allowThrottle follows the filtered cut
  assert len(cut_log) == len(probs)
  assert max(cut_log) > 0.9 and 0.0 < cut_log[5] < 0.5     # a single 50 ms flip is only a partial cut


def test_single_frame_flip_is_not_a_full_step_in_the_published_flag(cut_log):
  p = new_planner()
  for _ in range(5):
    step(p, 0.9)
  step(p, 0.0)
  assert p.allow_throttle is True and 0.0 < p.throttle_cut < 0.5      # stock planner would publish allowThrottle False here
  stock = new_planner()
  stock.ap1_throttle_gate = None
  for _ in range(5):
    step(stock, 0.9)
  step(stock, 0.0)
  assert stock.allow_throttle is False and stock.throttle_cut == 0.0


def test_not_engaged_and_creep_speed_follow_the_raw_flag(cut_log):
  p = new_planner()
  step(p, 0.0, enabled=False)
  assert p.throttle_cut == 1.0                  # reset_state: raw flag at once
  step(p, 0.9, enabled=False)
  assert p.throttle_cut == 0.0
  step(p, 0.0, v=MIN_ALLOW_THROTTLE_SPEED - 0.5)
  assert p.throttle_cut == 0.0                  # creep: model flag ignored, raw_allow is True


def test_non_ap1_planner_keeps_the_stock_0_1_cut(cut_log):
  cp = HondaInterface.get_non_essential_params("HONDA_CIVIC")
  cp.openpilotLongitudinalControl = True
  p = LongitudinalPlanner(cp, init_v=V)
  for prob in (0.9, 0.0, 0.9):
    step(p, prob)
    assert p.allow_throttle == (prob > ALLOW_THROTTLE_THRESHOLD)
  assert cut_log == [None, None, None]


def cruise(allow, cut=None, v=V, e2e=False, accel_coast=-0.3):
  cp = ap1_cp()
  # dt is huge so the jerk slew on the cruise accel does not hide the max-accel limit
  return get_cruise_accel(e2e, V_SET, v, 0.0, 0.0, cp, 10, accel_coast, allow, None, throttle_cut=cut) if cut is not None \
    else get_cruise_accel(e2e, V_SET, v, 0.0, 0.0, cp, 10, accel_coast, allow, None)


def test_cut_0_and_1_are_exactly_the_stock_cruise_limit():
  assert cruise(True, 0.0) == cruise(True) and cruise(False, 1.0) == cruise(False)
  assert cruise(False) < cruise(True)
  assert cruise(False, 1.0) == pytest.approx(max(-0.3, ACCEL_MIN))


def test_partial_cut_lowers_the_limit_monotonically_and_never_raises_it():
  full = cruise(True)
  prev = full
  for c in np.linspace(0.0, 1.0, 11):
    lim = cruise(True, float(c))
    assert lim <= full + 1e-12 and lim <= prev + 1e-12
    prev = lim
  assert cruise(True, 0.25) == pytest.approx(apply_cut(full, max(-0.3, ACCEL_MIN), 0.25))
  assert cruise(False, 1.0) < cruise(True, 0.5) < full


def test_experimental_mode_is_unaffected_by_the_cut():
  assert cruise(True, 1.0, e2e=True) == cruise(True, e2e=True)


def test_chatter_keeps_most_of_the_cap_in_the_planner_output():
  gated, stock = new_planner(), new_planner()
  stock.ap1_throttle_gate = None
  g, s = [], []
  for i in range(200):
    prob = 0.9 if i % 2 == 0 else 0.0
    step(gated, prob)
    step(stock, prob)
    g.append(gated.a_cruise)
    s.append(stock.a_cruise)
  # 0.9.7 behaviour: the chatter acts as early caution (cap retained), the stock 0/1 flip averages out around the limit
  assert gated.throttle_cut > 0.6
  assert np.mean(g[100:]) < np.mean(s[100:]) - 0.05
  assert DT_MDL == 0.05
