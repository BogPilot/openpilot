"""Pre-AP engage limit (SetSpeedLimit input): fresh UI frames only, units frame required, else 0."""
from types import SimpleNamespace

from opendbc.car import Bus
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1.speed_limit import LIMIT_MAX_AGE_S, frame_fresh, mpp_speed_limit_ms, ui_map_speed_limit_ms
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import Rig, _params_dir  # noqa: F401

MAP_CODE = 10   # any coded limit; the value comes from the shared table, not this test


def _ui(rig, mpp=None, units=0, map_code=None):
  if rig.nanos == 0:
    rig.frame()       # a real parser timestamp is never 0
  if mpp is not None:
    rig.send("UI_gpsVehicleSpeed", UI_mppSpeedLimit=mpp, UI_mapSpeedLimitUnits=units)
  if map_code is not None:
    rig.send("UI_driverAssistMapData", UI_mapSpeedLimit=map_code)


def _age(rig, s):
  """Advance the parser clock by s seconds of frames carrying only the base messages."""
  for _ in range(int(s * 100)):
    rig.frame()


def test_no_limit_frames_is_zero():
  rig = Rig()
  rig.frame()
  assert rig.cs.engage_limit_ms == 0.0


def test_fresh_mpp_mph_and_kph():
  rig = Rig()
  _ui(rig, mpp=45, units=0)
  rig.frame()
  assert abs(rig.cs.engage_limit_ms - 45 * CV.MPH_TO_MS) < 1e-3
  rig = Rig()
  _ui(rig, mpp=80, units=1)
  rig.frame()
  assert abs(rig.cs.engage_limit_ms - 80 * CV.KPH_TO_MS) < 1e-3


def test_stale_units_frame_never_latches():
  rig = Rig()
  _ui(rig, mpp=45, units=0, map_code=MAP_CODE)
  rig.frame()
  assert rig.cs.engage_limit_ms > 0.0
  _age(rig, LIMIT_MAX_AGE_S + 0.1)
  _ui(rig, map_code=MAP_CODE)          # map still arriving, but the units frame is stale -> unknown units
  rig.frame()
  assert rig.cs.engage_limit_ms == 0.0
  # dashboardSpeedLimit (display) is unchanged by the gate
  assert rig.frame().bogpilot.dashboardSpeedLimit > 0.0


def test_stale_map_frame_falls_back_to_fresh_mpp_only():
  rig = Rig()
  _ui(rig, mpp=0, units=0, map_code=MAP_CODE)
  rig.frame()
  assert abs(rig.cs.engage_limit_ms - ui_map_speed_limit_ms(MAP_CODE, False)) < 1e-3
  for _ in range(int((LIMIT_MAX_AGE_S + 0.1) * 100)):
    _ui(rig, mpp=0, units=0)
    rig.frame()
  assert rig.cs.engage_limit_ms == 0.0


def test_fresh_within_age_still_latches():
  rig = Rig()
  _ui(rig, mpp=45, units=0)
  rig.frame()
  _age(rig, LIMIT_MAX_AGE_S - 0.2)
  assert rig.cs.engage_limit_ms > 0.0


def test_frame_fresh_semantics():
  p = SimpleNamespace(ts_nanos={"M": {"a": 1_000}}, last_nonempty_nanos=1_000 + int(3.0e9))
  assert frame_fresh(p, "M")
  p.last_nonempty_nanos += 1
  assert not frame_fresh(p, "M")
  assert not frame_fresh(SimpleNamespace(ts_nanos={"M": {"a": 0}}, last_nonempty_nanos=5), "M")
  assert not frame_fresh(SimpleNamespace(), "M")
  # a silent bus (empty updates) ages the frame even though last_nonempty_nanos does not move
  p = SimpleNamespace(ts_nanos={"M": {"a": 1_000}}, last_nonempty_nanos=1_000, _last_update_nanos=1_000 + int(3.1e9))
  assert not frame_fresh(p, "M")


def test_silent_bus_ages_the_engage_limit():
  rig = Rig()
  _ui(rig, mpp=45, units=0)
  rig.frame()
  assert rig.cs.engage_limit_ms > 0.0
  pn = rig.parsers[Bus.chassis]
  for _ in range(int((LIMIT_MAX_AGE_S + 0.1) * 100)):
    rig.nanos += 10_000_000
    pn.update([(rig.nanos, [])])
  rig.frame()
  assert rig.cs.engage_limit_ms == 0.0


def test_mpp_physical_155_is_no_limit():
  # raw 31 * DBC factor 5. Neither the DBC VAL_ (none on this signal) nor Tinkla 501c7de rejects it.
  assert mpp_speed_limit_ms(155, False) == 0.0
  assert mpp_speed_limit_ms(155, True) == 0.0
  assert mpp_speed_limit_ms(150, False) > 0.0
  assert mpp_speed_limit_ms(45, False) > 0.0


def test_mpp_nonfinite_is_no_limit():
  for v in (float("nan"), float("inf"), float("-inf")):
    assert mpp_speed_limit_ms(v, False) == 0.0, v
    assert mpp_speed_limit_ms(v, True) == 0.0, v
  rig = Rig()
  _ui(rig, mpp=155, units=0)
  rig.frame()
  assert rig.cs.engage_limit_ms == 0.0
  assert rig.frame().bogpilot.dashboardSpeedLimit == 0.0
  # a valid map enum still wins when mpp is 155
  rig = Rig()
  _ui(rig, mpp=155, units=0, map_code=MAP_CODE)
  rig.frame()
  assert abs(rig.cs.engage_limit_ms - ui_map_speed_limit_ms(MAP_CODE, False)) < 1e-3


def test_map_units_follow_0x2f8_not_0x3c8():
  # 0x3C8 has UI_mapSpeedUnits (tesla_ap1_can.dbc BO_ 968) but the path uses 0x2F8's units bit.
  rig = Rig()
  _ui(rig, mpp=0, units=0, map_code=MAP_CODE)
  rig.send("UI_driverAssistMapData", UI_mapSpeedLimit=MAP_CODE, UI_mapSpeedUnits=1)
  rig.frame()
  expected = ui_map_speed_limit_ms(MAP_CODE, False)  # 0x2F8 MPH
  other = ui_map_speed_limit_ms(MAP_CODE, True)
  assert abs(rig.cs.engage_limit_ms - expected) < 1e-3
  assert abs(expected - other) > 1.0
