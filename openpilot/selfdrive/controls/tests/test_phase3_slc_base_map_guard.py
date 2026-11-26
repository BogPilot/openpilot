"""Planner side of the dashboard limit base-map guard: the real AP1 CarState (CAN frames -> dashboardSpeedLimit) feeds
the real Ap1SpeedControl. Fused and GTW map limits rise 25 -> 55 while the car's base map reads 0 and the camera-only
limit stays 25; the SLC target must stay at 25 + offset (30 mph). Without the guard the same frames give 55 + 7."""
import os
import tempfile

import pytest

from opendbc.car.tesla_ap1.tests.test_ap1_speed_limit_base_map_guard import UI_25, UI_55, Car
from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import CP_AP1, FakeStore, Sm, run
from openpilot.common.bogpilot_onroad_toggles import onroad_toggles

MPH = sc.MPH_TO_MS
SAVED = dict(SpeedLimitController="1", SLCPriority1="Dashboard", SLCFallback="2", SLCOverride="2", SLCConfirmation="0",
             SLCConfirmationHigher="0", Offset1="4", Offset2="5", Offset3="5", Offset4="5", Offset5="7", Offset6="8",
             Offset7="10", PreviousSpeedLimit=str(25 * MPH))
STEPS_PER_PLAN = 5   # CarState runs at 100 Hz, the planner at 20 Hz


def _fake_store():
  return FakeStore(**SAVED)


def _real_store(tmp):
  try:
    from openpilot.common.params import Params
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.selfdrive.controls.tests.test_phase3_speed_control_wiring import BlockingParams
  except Exception as exc:   # msgq / native params not built here
    pytest.skip(f"real Params unavailable here: {type(exc).__name__}")
  os.environ["BOGPILOT_PARAMS_DIR"] = os.path.join(tmp, "bp")
  p = BlockingParams(Params())
  for k in (*sc.SLC_KEYS, "PreviousSpeedLimit", "TuningLevel", "TuningLevelConfirmed", "IsMetric"):
    try:
      p.remove(k)
    except Exception:
      pass
  s = ParamStore(p)
  for k, v in SAVED.items():
    s.put(k, v)
  return s


def _drive(store, guard=True):
  """Returns the planner set (mph) on every planner tick after the pull engage at 25 mph."""
  t = onroad_toggles(store, CP_AP1)
  ctl = sc.Ap1SpeedControl(CP_AP1, store=store, toggles_fn=lambda: t, clock=lambda: 0.0, adopted=True)
  sm, car = Sm(), Car()
  if not guard:   # the same frames through the old four-argument call (no base-map guard)
    car.state.base_map_guard_args = lambda cp, cp_cam: {}
  v_ego, v_set = 25 * MPH, 30 * MPH

  def limit(**frames):
    out = 0.0
    for _ in range(STEPS_PER_PLAN):
      out = car.step(**frames) * MPH
    return out

  zone25 = dict(fused=25, vision=25, ui_map=UI_25, mpp=25, base_mph=24.6)
  for _ in range(40):   # 2 s in the 25 zone, cruise off
    run(ctl, sm, 0.0, v_ego, limit=limit(**zone25), cruise=False)
  run(ctl, sm, 0.0, v_ego, limit=limit(**zone25), cruise=False, rwd=True)   # pull
  run(ctl, sm, 0.0, v_ego, limit=limit(**zone25), cruise=False)
  out = [run(ctl, sm, v_set, v_ego, limit=limit(**zone25), cruise=True) for _ in range(20)]
  for _ in range(40):   # base map 0 and the GTW map / mpp 55; fused still 25
    out.append(run(ctl, sm, v_set, v_ego, limit=limit(fused=25, vision=25, ui_map=UI_55, mpp=55, base_mph=0.0), cruise=True))
  for _ in range(80):   # fused 55, camera still 25
    out.append(run(ctl, sm, v_set, v_ego, limit=limit(fused=55, vision=25, ui_map=UI_55, mpp=55, base_mph=0.0), cruise=True))
  return [x / MPH for x in out]


def test_planner_target_stays_at_or_below_30_mph():
  out = _drive(_fake_store())
  assert out[0] == pytest.approx(30.0, abs=0.05)
  assert max(out) <= 30.0 + 1e-3, max(out)


def test_planner_without_the_guard_targets_62():
  """Control: the same frames without the guard reproduce the reported 55 + 7."""
  out = _drive(_fake_store(), guard=False)
  assert max(out) == pytest.approx(62.0, abs=0.05)


def test_planner_target_with_real_params():
  with tempfile.TemporaryDirectory() as d:
    old = os.environ.get("BOGPILOT_PARAMS_DIR")
    try:
      out = _drive(_real_store(d))
    finally:
      if old is None:
        os.environ.pop("BOGPILOT_PARAMS_DIR", None)
      else:
        os.environ["BOGPILOT_PARAMS_DIR"] = old
  assert max(out) <= 30.0 + 1e-3, max(out)
