"""Missing active-to-cancel gate cases; synthetic capnp, real CSC adapter.

Uses existing planner fixtures instead of duplicating simulations. Native suite.
"""
import pytest

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.ap1_curve_brake import RELEASE_JERK
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, msgs, planner, road, K


def primed():
  p = planner()
  for i in range(60):
    p.update(SM(msgs(20.0, 30.0, 240.0 + 20.0 * i * DT_MDL, road(300.0, K, 150.0))))
  assert p.curve_speed.controlling and p.curve_speed.a_brake < -0.3
  return p


@pytest.mark.parametrize("cause", ["right_blinker", "left_blinker", "toggle_off", "dead_car_state", "invalid_car_state"])
def test_active_curve_cancellation_only_releases(cause):
  p = primed()
  prev = p.curve_speed.a_brake
  for _ in range(40):
    sm = SM(msgs(20.0, 30.0, 300.0, road(300.0, K, 150.0)))
    if cause.endswith("blinker"):
      setattr(sm["carState"], "rightBlinker" if cause == "right_blinker" else "leftBlinker", True)
    elif cause == "toggle_off":
      p.curve_speed.store.on = False
    elif cause == "dead_car_state":
      sm.alive["carState"] = False
    else:
      sm.valid["carState"] = False
    p.update(sm)
    cs = p.curve_speed
    assert not cs.controlling and not cs.csc.target_set
    assert cs.v_cruise_out == pytest.approx(30.0)
    assert prev - 1e-9 <= cs.a_brake <= prev + RELEASE_JERK * DT_MDL + 1e-9
    if "blinker" not in cause:
      assert not cs.valid
    prev = cs.a_brake
  assert prev == 0.0


@pytest.mark.parametrize("state", ["preLaneChange", "laneChangeStarting", "laneChangeFinishing"])
def test_lane_change_continuation_without_blinker_cancels_curve(state):
  # Cancellation must not depend solely on a driver leaving the stalk signal on.
  # This is a hard acceptance assertion, NOT xfail/skip or a production quick fix.
  p = primed()
  previous = p.curve_speed.a_brake
  for _ in range(40):
    sm = SM(msgs(20.0, 30.0, 300.0, road(300.0, K, 150.0)))
    sm["modelV2"].meta.laneChangeState = state
    assert not sm["carState"].leftBlinker and not sm["carState"].rightBlinker
    p.update(sm)
    cs = p.curve_speed
    assert not cs.controlling, "CSC remains active during model lane-change continuation"
    assert not cs.csc.target_set and not cs.training
    assert cs.v_cruise_out == pytest.approx(30.0)
    assert previous - 1e-9 <= cs.a_brake <= previous + RELEASE_JERK * DT_MDL + 1e-9
    previous = cs.a_brake
  assert previous == 0.0
  # Ordinary curve control is available again once the actual model reports off.
  p.update(SM(msgs(20.0, 30.0, 300.0, road(300.0, K, 150.0))))
  assert p.curve_speed.controlling
