"""AP1 Model X dash cluster frames (0x399 AutopilotStatus, 0x389 DAS_status2, 0x239 DAS_lanes).

The fixtures are three stock bus 2 frames from an AP1 Model X drive (payload bytes only): autopilot available,
fused speed limit 45, stock IC set 50 mph, both lane lines fused. The Model X sends the same layout, counter and
checksum as the Model S, so the Model S substitution path is used unchanged. With stock TACC (openpilot longitudinal
off) the X keeps the stock IC set digit; with openpilot longitudinal on it shows openpilot's set, as on the Model S.
"""
from collections import deque
from types import SimpleNamespace

import pytest

from opendbc.car import Bus, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1 import cluster as c
from opendbc.car.tesla_ap1 import ic_lanes, toggles
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller
from opendbc.car.tesla_ap1.values import CAR, TeslaAp1SafetyFlags

X = CAR.TESLA_AP1_MODELX
S = CAR.TESLA_AP1_MODELS
X_LONG_PARAM = int(TeslaAp1SafetyFlags.AP1 | TeslaAp1SafetyFlags.LONG_CONTROL)
NS = 1_000_000_000

X_STOCK = {
  c.AUTOPILOT_STATUS: bytes.fromhex("020909000000a050"),
  c.DAS_STATUS2: bytes.fromhex("7d004400308000fd"),
  c.DAS_LANES: bytes.fromhex("4157657b7c7e0a30"),
}
OP_SET_MS = 65 * CV.MPH_TO_MS


@pytest.fixture(autouse=True)
def _files(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ic_integration_path", tmp_path / "EnableICIntegration")
  monkeypatch.setattr(ic_lanes, "_iclanes_path", tmp_path / "ICLanes")
  return tmp_path


def _stock():
  return {addr: c.unpack(addr, dat) for addr, dat in X_STOCK.items()}


def _cs(stock):
  return SimpleNamespace(
    out=SimpleNamespace(steeringAngleDeg=0.0, vEgo=25.0, gasPressed=False, standstill=False),
    steer_warning="EAC_ERROR_IDLE", hands_on_level=0, eac_fault=False, eac_status="EAC_ACTIVE",
    acc_state=4, das_control_counters=deque([1]), msg_stw_actn_req={}, stock_steer_counters=[3],
    stock_ap_active=False, cluster_stock=stock)


def _cc(enabled=True, set_ms=OP_SET_MS):
  CC = structs.CarControl()
  CC.enabled = enabled
  CC.latActive = enabled
  CC.longActive = enabled
  CC.actuators.curvature = 0.0005
  CC.hudControl.setSpeed = set_ms
  return CC


def _x(long):
  return make_controller(long=long, fingerprint=X, safety_param=X_LONG_PARAM if long else int(TeslaAp1SafetyFlags.AP1))


def _cluster(can):
  return {addr: bytes(dat) for addr, dat, bus in can if addr in c.CLUSTER_ADDRS and bus == c.CLUSTER_BUS}


def test_fixtures_are_valid_stock_frames():
  for addr in (c.AUTOPILOT_STATUS, c.DAS_STATUS2):
    dat = X_STOCK[addr]
    assert c.tesla_checksum(addr, dat) == dat[7]
  s = _stock()
  assert s[c.AUTOPILOT_STATUS]["autopilotStatus"] == c.AP_STATE_AVAILABLE
  assert s[c.AUTOPILOT_STATUS]["DAS_fusedSpeedLimit"] == 45
  assert s[c.DAS_STATUS2]["DAS_accSpeedLimit"] == pytest.approx(50, abs=0.4)
  assert s[c.DAS_LANES]["DAS_leftLineUsage"] == 2 and s[c.DAS_LANES]["DAS_rightLineUsage"] == 2


def test_carstate_reads_x_cluster_frames_from_bus_2():
  cp = SimpleNamespace(carFingerprint=X)
  state = CarState(cp)
  parsers = CarState.get_can_parsers(cp)
  cam = parsers[Bus.cam]
  cam.update([(0, [(addr, dat, cam.bus) for addr, dat in X_STOCK.items()])])
  got = state.new_cluster_frames(cam)
  assert set(got) == set(c.CLUSTER_ADDRS)
  assert got[c.AUTOPILOT_STATUS]["DAS_fusedSpeedLimit"] == 45
  assert got[c.DAS_STATUS2]["DAS_accSpeedLimit"] == pytest.approx(50, abs=0.4)


def test_carstate_x_subscribes_cluster_frames_and_none_received_is_empty():
  cp = SimpleNamespace(carFingerprint=X)
  parsers = CarState.get_can_parsers(cp)
  cam = parsers[Bus.cam]
  assert {"AutopilotStatus", "DAS_status2", "DAS_lanes"} <= set(cam.vl)
  cam.update([(0, [])])
  assert CarState(cp).new_cluster_frames(cam) == {}


@pytest.mark.parametrize("long", [False, True])
def test_x_engaged_substitutes_all_three_frames_on_bus_0(long):
  ctl = _x(long)
  _, can = ctl.update(_cc(), _cs(_stock()), NS)
  out = _cluster(can)
  assert set(out) == set(c.CLUSTER_ADDRS)
  for addr, dat in out.items():
    v = c.unpack(addr, dat)
    stock_ctr = c.unpack(addr, X_STOCK[addr])[c.COUNTER_SIGNALS[addr]]
    assert v[c.COUNTER_SIGNALS[addr]] == (stock_ctr + 1) % 16
    if addr in c.CHECKSUM_SIGNALS:
      assert c.tesla_checksum(addr, dat) == dat[7]
  status = c.unpack(c.AUTOPILOT_STATUS, out[c.AUTOPILOT_STATUS])
  assert status["autopilotStatus"] == c.AP_STATE_OPENPILOT
  assert status["DAS_fusedSpeedLimit"] == 45                       # stock speed-limit sign kept
  lanes = c.unpack(c.DAS_LANES, out[c.DAS_LANES])
  assert lanes["DAS_leftLineUsage"] == 2 and lanes["DAS_rightLineUsage"] == 2


def test_x_stock_tacc_keeps_stock_ic_set_digit():
  ctl = _x(long=False)
  _, can = ctl.update(_cc(set_ms=OP_SET_MS), _cs(_stock()), NS)
  s2 = c.unpack(c.DAS_STATUS2, _cluster(can)[c.DAS_STATUS2])
  assert s2["DAS_accSpeedLimit"] == pytest.approx(50, abs=0.4)


def test_x_op_long_shows_openpilot_set_on_ic_digit():
  ctl = _x(long=True)
  _, can = ctl.update(_cc(set_ms=OP_SET_MS), _cs(_stock()), NS)
  s2 = c.unpack(c.DAS_STATUS2, _cluster(can)[c.DAS_STATUS2])
  assert s2["DAS_accSpeedLimit"] == pytest.approx(65, abs=0.4)


@pytest.mark.parametrize("long", [False, True])
def test_model_s_ic_set_digit_unchanged(long):
  ctl = make_controller(long=long, fingerprint=S)
  assert ctl.cluster_set_overlay is True
  _, can = ctl.update(_cc(set_ms=OP_SET_MS), _cs(_stock()), NS)
  s2 = c.unpack(c.DAS_STATUS2, _cluster(can)[c.DAS_STATUS2])
  assert s2["DAS_accSpeedLimit"] == pytest.approx(65, abs=0.4)


def test_x_not_engaged_sends_no_cluster_frames():
  ctl = _x(long=True)
  _, can = ctl.update(_cc(enabled=False), _cs(_stock()), NS)
  assert _cluster(can) == {}


def test_x_toggle_off_sends_no_cluster_frames(_files):
  (_files / "EnableICIntegration").write_text("0")
  ctl = _x(long=True)
  _, can = ctl.update(_cc(), _cs(_stock()), NS)
  assert _cluster(can) == {}


def test_x_no_stock_frame_no_cluster_frame():
  ctl = _x(long=True)
  _, can = ctl.update(_cc(), _cs({}), NS)
  assert _cluster(can) == {}


def test_toggle_defaults():
  assert toggles.enable_ic_integration(X, stored="") is True
  assert toggles.enable_ic_integration(X, stored="0") is False
  assert toggles.enable_ic_integration(S, stored="") is True
  assert toggles.enable_ic_integration(CAR.TESLA_PREAP_MODELS, stored="1") is False
  assert ic_lanes.ic_lanes_mode(X, stored="") == ic_lanes.MODE_LANES
  assert ic_lanes.ic_lanes_mode(CAR.TESLA_PREAP_MODELS, stored="1") == ic_lanes.MODE_OFF
