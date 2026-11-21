"""Map Curve Speed (CSCMapCurvature, mapd v2 mapCurveSpeed) in Ap1CurveSpeed: off by default, only ever lowers the
cruise speed, only where CSC could cap, fails closed on stale data, follows mapd's value raw (no hold). Synthetic, no mapd."""
import pytest

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib import ap1_curve_speed as A
from openpilot.selfdrive.controls.lib.bogpilot_csc import CRUISING_SPEED
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, ap1_cp, msgs, planner, drive, road
from openpilot.system.bogpilot.osm.mapd_v2 import MapdV2Data, NO_V2, map_curve_cap


class Store:
  def __init__(self, csc=True, map_curve=True, engine=True):
    self.vals = {"CurveSpeedController": csc, "CSCMapCurvature": map_curve, "MapdV2": engine}
    self.reads = []

  def toggle_bool(self, key):
    self.reads.append(key)
    return self.vals[key]

  def get_bool(self, key, default=None):
    self.reads.append(key)
    return self.vals[key]

  def get(self, key, default=None):
    return default

  def put(self, key, value):
    pass


class Tick:
  def __init__(self, data=NO_V2):
    self.data = data
    self.calls = 0

  def get(self):
    self.calls += 1
    return self.data


def csc(store, tick=None):
  c = A.Ap1CurveSpeed(ap1_cp(), DT_MDL, store)
  c._map_tick = tick
  return c


def step(c, v_ego=25.0, v_cruise=30.0, **kw):
  return c.update(SM(msgs(v_ego, v_cruise, **kw)), v_ego, v_cruise, False)


def test_toggle_defaults_off():
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  assert BOGPILOT_PARAMS["CSCMapCurvature"][2] == "0" and BOGPILOT_PARAMS["MapdV2"][2] == "0"
  assert BOGPILOT_PARAMS["CSCMapCurvature"][4] in (None, "0")


def test_toggle_off_never_reads_mapd_and_output_is_unchanged():
  for vals in ({"map_curve": False}, {"engine": False}):
    tick = Tick(MapdV2Data(True, 25.0, 0, 0, 12.0))
    c, base = csc(Store(**vals), tick), csc(Store(map_curve=False, engine=False), Tick())
    for _ in range(50):
      assert step(c) == step(base)
    assert tick.calls == 0 and c.map_cap == 0.0


def test_map_cap_lowers_only_and_is_rescaled_never_up():
  c = csc(Store(), Tick(MapdV2Data(True, 25.0, 0, 0, 12.0)))
  out = step(c)
  lat = min(c.csc.effective_lateral_acceleration(), A.TESLA_CSC_MAX_LAT_ACCEL)
  assert out == pytest.approx(min(30.0, map_curve_cap(12.0, lat)))
  assert out <= 12.0 + 1e-9
  # set speed below the map cap: unchanged
  c2 = csc(Store(), Tick(MapdV2Data(True, 25.0, 0, 0, 12.0)))
  assert step(c2, v_ego=10.0, v_cruise=10.0) == pytest.approx(10.0)


def test_cap_rescale_math():
  assert map_curve_cap(20.0, 2.0) == pytest.approx(20.0)
  assert map_curve_cap(20.0, 3.0) == pytest.approx(20.0)                 # never above mapd's own speed
  assert map_curve_cap(20.0, 1.0) == pytest.approx(20.0 * 0.5 ** 0.5)
  for bad in (0.0, float("nan"), float("inf"), -5.0, 100.0):
    assert map_curve_cap(bad, 2.0) == 0.0
  assert map_curve_cap(20.0, float("nan")) == 0.0


def test_floor_at_cruising_speed():
  c = csc(Store(), Tick(MapdV2Data(True, 25.0, 0, 0, 4.5)))
  assert step(c) == pytest.approx(max(CRUISING_SPEED, map_curve_cap(4.5, 2.0)))
  assert step(c) >= CRUISING_SPEED


def test_stale_or_missing_map_data_is_no_cap():
  for d in (NO_V2, MapdV2Data(fresh=True), MapdV2Data(False, 25.0, 0, 0, 12.0)):
    c = csc(Store(), Tick(d))
    assert step(c) == pytest.approx(30.0) and c.map_cap == 0.0


class Boom:
  def get(self):
    raise RuntimeError("x")


def test_reader_failure_fails_closed():
  c = csc(Store(), Boom())
  assert step(c) == pytest.approx(30.0)


@pytest.mark.parametrize("kw", [{"enabled": False}, {"blinker": True}])
def test_not_where_csc_cannot_cap(kw):
  c = csc(Store(), Tick(MapdV2Data(True, 25.0, 0, 0, 12.0)))
  assert step(c, **kw) == pytest.approx(30.0) and c.map_cap == 0.0


def test_slow_speed_and_csc_off():
  c = csc(Store(), Tick(MapdV2Data(True, 25.0, 0, 0, 12.0)))
  assert step(c, v_ego=CRUISING_SPEED - 1, v_cruise=30.0) == pytest.approx(30.0)
  c = csc(Store(csc=False), Tick(MapdV2Data(True, 25.0, 0, 0, 12.0)))
  assert step(c) == pytest.approx(30.0)


def test_lower_raise_and_release_are_immediate():
  tick = Tick(MapdV2Data(True, 25.0, 0, 0, 15.0))
  c = csc(Store(), tick)
  a = step(c)
  tick.data = MapdV2Data(True, 25.0, 0, 0, 11.0)
  b = step(c)
  assert b < a                                               # lower at once
  tick.data = MapdV2Data(True, 25.0, 0, 0, 0.0)              # curve left mapd's report
  assert step(c) == pytest.approx(30.0) and c.map_cap == 0.0  # released on the very next tick


def test_immediate_rise_at_curve_exit():
  tick = Tick(MapdV2Data(True, 25.0, 0, 0, 10.0))
  c = csc(Store(), tick)
  low = step(c)
  assert low <= 10.0 + 1e-9
  tick.data = MapdV2Data(True, 25.0, 0, 0, 18.0)             # exit: mapd's next-curve speed rises
  up = step(c)
  assert up > low and up == pytest.approx(min(30.0, c.map_cap))
  assert up <= 18.0 + 1e-9 and up >= CRUISING_SPEED
  tick.data = MapdV2Data(True, 25.0, 0, 0, 25.0)
  assert step(c) > up                                        # follows mapd upward every tick, still never above mapd


def test_no_hold_constant_left():
  assert not hasattr(A, "MAP_HOLD_S")


def test_closed_loop_map_cap_reaches_map_speed_before_a_curve_vision_cannot_see_yet():
  # straight road for the model; mapd reports a 12 m/s curve ahead: the planner slows to it, never below CRUISING_SPEED
  store = Store()
  p = planner(store=store)
  p.curve_speed._map_tick = Tick(MapdV2Data(True, 25.0, 0, 0, 12.0))
  log = []
  out = drive(p, 25.0, 30.0, road(), 25.0, log=log)
  assert all(row[3] <= 30.0 + 1e-9 for row in log)
  assert out[-1][1] == pytest.approx(12.0, abs=0.6)
  assert min(v for _, v in out) >= CRUISING_SPEED
  base = drive(planner(store=Store(map_curve=False)), 25.0, 30.0, road(), 25.0)
  assert base[-1][1] > 24.0
