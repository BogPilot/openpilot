"""AdaptiveAccelLead through the real LongitudinalPlanner (synthetic messages; needs the native msgq/MPC, so it runs on AGNOS).

Off (the default) the planner output is bit-identical to the same planner with the cap code removed from the path; on, only a
positive request near a lead on a legacy Tesla is lowered. Braking, far leads, no lead, other cars: unchanged."""
import numpy as np
import pytest

import openpilot.selfdrive.controls.lib.longitudinal_planner as lp
from opendbc.car.honda.interface import CarInterface as HondaInterface
from openpilot.selfdrive.controls.lib.lead_accel_cap import lead_accel_cap
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, ap1_cp, msgs

V = 20.0


class Toggle:
  """Delegates to the planner's real store; answers AdaptiveAccelLead (the prebuilt params library may predate the key)."""
  def __init__(self, inner, on):
    self.inner, self.on = inner, on

  def toggle_bool(self, key, level=None):
    return self.on if key == "AdaptiveAccelLead" else self.inner.toggle_bool(key, level)

  def __getattr__(self, name):
    return getattr(self.inner, name)


def new_planner(on, cp=None):
  p = LongitudinalPlanner(cp if cp is not None else ap1_cp(), init_v=V)
  from openpilot.selfdrive.controls.lib.phase3_speed_control import Ap1SpeedControl
  p.speed_control = Ap1SpeedControl(p.CP, adopted=False)
  if p.long_accel is not None:
    p.long_accel.store = Toggle(p.long_accel.store, on)
  return p


def run(p, lead_fn, v=V, v_cruise=30.0, steps=80):
  out = []
  for i in range(steps):
    p.update(SM(msgs(v, v_cruise, lead=lead_fn(i), a_ego=0.0)))
    out.append(float(p.output_a_target))
  return np.array(out)


def test_no_lead_is_identical_on_and_off():
  assert np.array_equal(run(new_planner(False), lambda i: None), run(new_planner(True), lambda i: None))


def test_far_lead_is_identical_on_and_off():
  far = lambda i: (150.0, V)
  assert np.array_equal(run(new_planner(False), far), run(new_planner(True), far))


def test_close_slow_lead_never_accelerates_harder_with_the_cap_and_cap_is_respected():
  close = lambda i: (V * 1.45 + 8.0, 0.0)          # very close and stopped: positive requests, if any, get capped
  off, on = run(new_planner(False), close), run(new_planner(True), close)
  assert np.all(on <= off + 1e-9)                   # the cap only ever lowers
  neg = off <= 0
  assert np.array_equal(on[neg], off[neg])          # braking is untouched


def test_cap_bites_on_a_positive_request_near_a_lead():
  p = new_planner(True)
  # A slower lead with the gap near the safe following distance: the cap must hold whatever the plan asks for.
  v_lead = V - 5.0
  gap = 1.1 * (V * V / 5 + 1.35 * V + 6.0) - v_lead ** 2 / 5     # obstacle-equivalent ratio ~1.1: fully inside the cap
  lead = lambda i: (gap, v_lead)
  seen = []
  for i in range(60):
    sm = SM(msgs(V, 30.0, lead=lead(i), a_ego=0.0))
    p.update(sm)
    cap = p.long_accel.lead_accel_cap(V, 1.6, sm["radarState"].leadOne, p.effective_t_follow)
    if cap is not None:
      assert p.output_a_target <= cap + 1e-9
      seen.append(cap)
  assert seen, "the cap never became active in the blend zone"


def test_other_cars_and_the_switch_off_state_never_cap():
  hp = LongitudinalPlanner(HondaInterface.get_non_essential_params("HONDA_CIVIC"), init_v=V)
  if hp.long_accel is not None:
    hp.long_accel.store = Toggle(hp.long_accel.store, True)
  close = (V * 1.45 + 8.0, 0.0)
  a = SM(msgs(V, 30.0, lead=close))
  hp.update(a)
  assert hp.long_accel is None or hp.long_accel.lead_accel_cap(V, 1.6, a["radarState"].leadOne, 1.45) is None


def test_module_is_not_called_when_the_toggle_is_off(monkeypatch):
  import openpilot.selfdrive.controls.lib.lead_accel_cap as mod
  called = []
  monkeypatch.setattr(mod, "lead_accel_cap", lambda *a, **k: called.append(1))
  run(new_planner(False), lambda i: (V * 1.45 + 8.0, 0.0), steps=20)
  assert not called
