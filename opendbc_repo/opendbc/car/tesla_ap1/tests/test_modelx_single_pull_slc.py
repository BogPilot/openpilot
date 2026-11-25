"""AP1 Model X with openpilot longitudinal: single-pull Speed Limit Control works as on the Model S. One pull toward the driver
engages at the posted limit plus offset (moving or from a stop), a tap latches the current speed, and the pull level reaches
the planner. The Model X with openpilot long off keeps the stock DI_cruiseSet."""
import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1.speed_limit import ui_map_speed_limit_ms
from opendbc.car.tesla_ap1.tests.test_ap1_op_long_set_speed import (ENABLED, MAP_65, RWD, STANDBY, STANDSTILL, UP, Car)
from opendbc.car.tesla_ap1.values import CAR

X = CAR.TESLA_AP1_MODELX
S = CAR.TESLA_AP1_MODELS
OFFSET = 5 * CV.MPH_TO_MS


def _pull_engage(fp, v_kph, engaged_state, lever=RWD):
  car = Car(fingerprint=fp, offset_ms=OFFSET)
  car.step(STANDBY, 0, v_kph, map_limit=MAP_65)
  pull = car.step(STANDBY, 0, v_kph, map_limit=MAP_65, lever=lever)
  rets = [car.step(engaged_state, 0, v_kph, map_limit=MAP_65) for _ in range(3)]
  return pull, rets


@pytest.mark.parametrize("fp", [X, S])
def test_moving_single_pull_engages_at_limit_plus_offset(fp):
  limit = ui_map_speed_limit_ms(MAP_65, False)
  pull, rets = _pull_engage(fp, 40.0, ENABLED)
  assert pull.bogpilot.resumePressed                              # the pull level reaches the planner (SLC confirm input)
  assert all(r.cruiseState.speed == pytest.approx(limit + OFFSET, abs=1e-3) for r in rets)


@pytest.mark.parametrize("fp", [X, S])
def test_standstill_single_pull_engages_at_limit_plus_offset(fp):
  limit = ui_map_speed_limit_ms(MAP_65, False)
  _pull, rets = _pull_engage(fp, 0.0, STANDSTILL)
  assert all(r.cruiseState.speed == pytest.approx(limit + OFFSET, abs=1e-3) for r in rets)
  assert not rets[-1].bogpilot.ap1SpeedLimitUnknown


def test_x_matches_s_frame_for_frame():
  for v_kph, state, lever in ((40.0, ENABLED, RWD), (0.0, STANDSTILL, RWD), (40.0, ENABLED, UP)):
    _px, rx = _pull_engage(X, v_kph, state, lever)
    _ps, rs = _pull_engage(S, v_kph, state, lever)
    assert [r.cruiseState.speed for r in rx] == pytest.approx([r.cruiseState.speed for r in rs], abs=1e-6), (v_kph, lever)


def test_x_rolling_tap_latches_speed_not_limit():
  limit = ui_map_speed_limit_ms(MAP_65, False)
  _pull, rets = _pull_engage(X, 40.0, ENABLED, lever=UP)
  assert all(abs(r.cruiseState.speed - (limit + OFFSET)) > 1.0 for r in rets)


def test_x_op_long_off_has_no_openpilot_set():
  car = Car(fingerprint=X, op_long=False)
  assert car.state.op_long_set is None
