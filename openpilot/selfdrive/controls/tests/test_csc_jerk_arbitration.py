"""AP1 comfort arbitration (ap1_curve_arbitration.py) and the elapsed-time CSC target slew."""
import numpy as np
import pytest

import openpilot.selfdrive.controls.lib.ap1_curve_arbitration as arb_mod
from openpilot.selfdrive.controls.lib.ap1_curve_arbitration import (BYPASS_ACCEL, COMFORT_JERK_DOWN, COMFORT_JERK_UP, CurveArbiter, ModelClock)
from openpilot.selfdrive.controls.lib.bogpilot_csc import CurveSpeedController, TARGET_RELEASE_RATE
from openpilot.selfdrive.controls.tests.csc_replay_helpers import DT_MDL, SM, Store

DT = 0.05


def arbiter(initial=0.7):
  a = CurveArbiter(DT)
  a.arbitrate([("cruise", initial), ("mpc", 2.0)], DT, True)
  return a


def test_no_switch_no_change_min_semantics():
  a = arbiter()
  out, winner, _ = a.arbitrate([("mpc", 2.0), ("cruise", 0.7)], DT, False)
  assert out == pytest.approx(0.7) and winner == "cruise"


def test_winner_switch_step_is_slewed_at_the_comfort_jerk():
  a = arbiter(0.7)
  out, winner, _ = a.arbitrate([("mpc", 2.0), ("cruise", 0.7), ("curve", -0.075)], DT, False)
  assert out == pytest.approx(0.7 - COMFORT_JERK_DOWN * DT)
  assert winner == "curve"  # the curve brake is the active comfort candidate even while the slew is catching up
  outs = [out]
  for _ in range(10):
    outs.append(a.arbitrate([("mpc", 2.0), ("cruise", 0.7), ("curve", -0.075)], DT, False)[0])
  assert np.all(np.diff(outs) >= -COMFORT_JERK_DOWN * DT - 1e-12)
  assert outs[-1] == pytest.approx(-0.075)  # reaches the request, never below it


def test_ramps_at_native_jerk_pass_through_unchanged():
  a = arbiter(0.0)
  raw = 0.0
  for _ in range(15):
    raw -= 1.5 * DT   # the curve brake onset jerk
    out, _, _ = a.arbitrate([("mpc", 2.0), ("cruise", 0.5), ("curve", raw)], DT, False)
    assert out == pytest.approx(min(raw, 0.5)) if raw > BYPASS_ACCEL else out == pytest.approx(raw)


def test_release_is_slewed_at_the_release_jerk():
  a = arbiter(-0.5)
  a.arbitrate([("cruise", 0.7), ("curve", -0.5)], DT, False)
  out, _, _ = a.arbitrate([("cruise", 0.7)], DT, False)
  assert out == pytest.approx(-0.5 + COMFORT_JERK_UP * DT)


@pytest.mark.parametrize("name", ["mpc", "e2e"])
def test_lead_and_e2e_candidates_are_never_slewed(name):
  a = arbiter(0.7)
  out, winner, info = a.arbitrate([(name, -3.0), ("cruise", 0.7)], DT, False)
  assert out == -3.0 and winner == name and not info["bypass"]
  # and back up: the other candidate is not slewed either, the comfort one keeps its own state
  out, winner, _ = a.arbitrate([(name, 1.0), ("cruise", 0.7)], DT, False)
  assert out == pytest.approx(0.7)


def test_output_never_above_a_non_comfort_candidate_with_random_inputs():
  rng = np.random.default_rng(3)
  a = arbiter(0.2)
  for _ in range(2000):
    c = [("mpc", float(rng.uniform(-3.5, 2.0))), ("cruise", float(rng.uniform(-1.2, 1.5)))]
    if rng.random() < 0.5:
      c.append(("curve", float(rng.uniform(-1.2, 0.0))))
    out, _, _ = a.arbitrate(c, float(rng.uniform(0.01, 0.1)), False)
    assert out <= c[0][1] + 1e-12


def test_strong_request_bypasses_the_comfort_limit_and_is_logged(monkeypatch):
  events = []
  monkeypatch.setattr(arb_mod.cloudlog, "event", lambda name, **kw: events.append((name, kw)))
  a = arbiter(0.7)
  out, _, info = a.arbitrate([("cruise", 0.7), ("curve", BYPASS_ACCEL - 0.1)], DT, False)
  assert out == pytest.approx(BYPASS_ACCEL - 0.1) and info["bypass"]
  a.arbitrate([("cruise", 0.7), ("curve", BYPASS_ACCEL - 0.2)], DT, False)
  assert [e[0] for e in events] == ["ap1_comfort_bypass"]  # one log line per episode


def test_reset_reseeds_the_comfort_state():
  a = arbiter(0.7)
  out, _, _ = a.arbitrate([("cruise", -0.4)], DT, True)
  assert out == pytest.approx(-0.4)


def test_elapsed_time_scales_the_slew():
  a1, a2 = arbiter(0.7), arbiter(0.7)
  o1 = a1.arbitrate([("cruise", 0.7), ("curve", -0.5)], 0.05, False)[0]
  o2 = a2.arbitrate([("cruise", 0.7), ("curve", -0.5)], 0.10, False)[0]
  assert (0.7 - o2) == pytest.approx(2 * (0.7 - o1))


def test_record_has_winner_candidates_and_dt():
  a = arbiter(0.7)
  a.arbitrate([("mpc", 2.0), ("cruise", 0.7), ("curve", -0.075)], DT, False, ages={"curve": 0.05})
  assert set(a.last) >= {"winner", "out", "candidates", "comfort_raw", "comfort", "bypass", "dt", "ages"}
  assert a.last["candidates"]["curve"] == -0.075 and a.last["ages"] == {"curve": 0.05}


def test_model_clock_is_monotonic_bounded_with_fallback():
  c = ModelClock(0.05)
  assert c.step(SM({}, mono_ns=1_000_000_000)) == 0.05            # first sample: fallback
  assert c.step(SM({}, mono_ns=1_050_000_000)) == pytest.approx(0.05)
  assert c.step(SM({}, mono_ns=1_150_000_000)) == pytest.approx(0.10)
  assert c.step(SM({}, mono_ns=9_150_000_000)) == pytest.approx(0.2)  # gap bounded
  assert c.step(SM({}, mono_ns=9_150_000_000)) == 0.05            # not advancing: fallback, never 0 or negative
  assert c.step({}) == 0.05                                        # no time source


def store_csc():
  return CurveSpeedController(Store(), 2.0)


def test_csc_target_fall_uses_elapsed_time():
  a, b = store_csc(), store_csc()
  k = 2.0 / 15.0 ** 2
  for c in (a, b):
    c.update_target(30.0, k, 4.0)
  a.update_target(30.0, k, 4.0, None, 0.05)
  b.update_target(30.0, k, 4.0, None, 0.10)
  assert (30.0 - b.target) == pytest.approx(2 * (30.0 - a.target))


def test_csc_target_rises_at_the_release_rate_not_instantly():
  c = store_csc()
  c.update_target(20.0, 2.0 / 15.0 ** 2, 2.0)      # active, tight curve: seeded at v_ego
  for _ in range(40):
    c.update_target(20.0, 2.0 / 15.0 ** 2, 2.0)
  low = c.target
  assert low < 20.0
  c.update_target(20.0, 2.0 / 40.0 ** 2, 2.0)       # curve opens up: loose curve speed 40 m/s
  assert c.target == pytest.approx(min(low + TARGET_RELEASE_RATE * DT_MDL, 40.0))
  c.update_target(20.0, 2.0 / 40.0 ** 2, 2.0)
  assert c.target <= 20.0 + 1e-9                    # still never above max(v_ego, curve speed)
