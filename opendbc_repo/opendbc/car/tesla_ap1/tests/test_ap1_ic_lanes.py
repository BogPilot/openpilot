"""ICLanes (ic_lanes.py): unscaled lane-line 0x239 path for the AP1 cluster.

Pure-function tests plus the CarController wiring (stub-free: the harness uses
the real DBC packer). Display only: no steering or longitudinal frame changes.
"""
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1 import cluster as c
from opendbc.car.tesla_ap1 import ic_lanes as L
from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller
from opendbc.car.tesla_ap1.values import CAR

AP1 = CAR.TESLA_AP1_MODELS
NS = 1_000_000_000


@pytest.fixture
def toggle(tmp_path, monkeypatch):
  p = tmp_path / "ICLanes"
  monkeypatch.setattr(L, "_iclanes_path", p)
  return p


def _line(xs, f):
  return SimpleNamespace(x=list(xs), y=[f(x) for x in xs])


def model(center=lambda x: 0.0, probs=(0.9, 0.9, 0.9, 0.9), width=3.3, path=None, n=33):
  xs = np.linspace(0.0, 100.0, n)
  lines = [_line(xs, lambda x, k=k: center(x) + k * width) for k in (-1.5, -0.5, 0.5, 1.5)]
  p = path or center
  return SimpleNamespace(laneLines=lines, laneLineProbs=list(probs),
                         position=SimpleNamespace(x=list(xs[1:]), y=[p(x) for x in xs[1:]]))


def stock_lanes(width=3.25):
  vals = {"DAS_leftLaneExists": 0, "DAS_rightLaneExists": 0, "DAS_virtualLaneWidth": width,
          "DAS_virtualLaneViewRange": 60, "DAS_virtualLaneC0": 0.1, "DAS_virtualLaneC1": 0.0,
          "DAS_virtualLaneC2": 0.0, "DAS_virtualLaneC3": 0.0, "DAS_leftLineUsage": 2, "DAS_rightLineUsage": 2,
          "DAS_leftFork": 0, "DAS_rightFork": 0}
  word = c.pack(c.DAS_LANES, c.SIGNALS[c.DAS_LANES], vals)
  return c.unpack(c.DAS_LANES, word.to_bytes(8, "little"))


def hud(**kw):
  args = dict(enabled=True, fcw=False, steer_required=False, audible=False, human_steering=False,
              left_lane_depart=False, right_lane_depart=False, left_blinker=False, right_blinker=False,
              curvature=0.0, ic_integration=True, model_path=None, cruise_set_mph=None)
  args.update(kw)
  return c.HudInputs(**args)


def test_default_on_and_ap1_model_s_only(toggle):
  assert not toggle.exists()
  assert L.ic_lanes_mode(AP1) == L.MODE_LANES  # missing file = on (0.9.7 default)
  for word, mode in (("1", L.MODE_LANES), ("lanes\n", L.MODE_LANES), ("SNAP", L.MODE_LANES),
                     ("", L.MODE_LANES), ("junk", L.MODE_LANES),
                     ("0", L.MODE_OFF), ("false", L.MODE_OFF), ("OFF\n", L.MODE_OFF), (" 0 ", L.MODE_OFF)):
    toggle.write_text(word)
    assert L.ic_lanes_mode(AP1) == mode, word
  assert L.ic_lanes_mode(AP1, stored=b"off") == L.MODE_OFF
  toggle.write_text("1")
  assert L.ic_lanes_mode(CAR.TESLA_AP1_MODELX) == L.MODE_OFF
  assert L.ic_lanes_mode("TESLA_AP2_MODELS") == L.MODE_OFF
  assert L.ic_lanes_mode(None) == L.MODE_OFF


def test_poll_rereads_toggle_once_a_second(toggle):
  il = L.IcLanes(AP1)
  assert il.poll() == L.MODE_LANES and il.on
  toggle.write_text("0")
  for _ in range(L.TOGGLE_POLL_FRAMES - 1):
    assert il.poll() == L.MODE_LANES
  assert il.poll() == L.MODE_OFF and not il.on


def test_lane_fit_unscaled_keeps_offset_and_sign():
  # Lane center 0.3 m right of the car, curving right: y = 0.3 + 0.0005 x^2.
  m = model(center=lambda x: 0.3 + 0.0005 * x * x)
  p, src = L.corrected_lane_poly(m, 0.0)
  assert src == L.SRC_LANES
  assert p.c0 == pytest.approx(0.3, abs=1e-3)
  assert p.c1 == pytest.approx(0.0, abs=1e-4)
  assert p.c2 == pytest.approx(0.0005, abs=1e-6)  # NOT 4x (no 2^n scale)
  assert p.view_range_m == 100


def test_lane_fit_clipped_to_dbc():
  p, _ = L.corrected_lane_poly(model(center=lambda x: 9.0 + 0.01 * x * x), 0.0)
  assert p.c0 == c.C0_RANGE[1] and p.c2 == c.C2_RANGE[1]


def test_low_probs_still_use_lane_lines_by_default():
  p, src = L.corrected_lane_poly(model(center=lambda x: 0.5, probs=(0.1, 0.05, 0.05, 0.1)), 0.0)
  assert src == L.SRC_LANES and p.c0 == pytest.approx(0.5, abs=1e-3)


def test_missing_lines_fall_back_to_unscaled_path_then_curvature(monkeypatch):
  monkeypatch.setattr(L, "LANE_PROB_MIN", 0.5)  # optional gate
  m = model(center=lambda x: 2.0, probs=(0.9, 0.2, 0.9, 0.9), path=lambda x: 0.0002 * x * x)
  p, src = L.corrected_lane_poly(m, 0.0)
  assert src == L.SRC_PATH
  assert (p.c0, p.c1, p.c3) == (0.0, 0.0, 0.0)
  assert p.c2 == pytest.approx(0.0002, abs=1e-6)
  assert c.path_from_model_v2(m).c2 == pytest.approx(0.0008, abs=1e-6)  # shipped: 4x
  m.laneLines = []
  monkeypatch.setattr(L, "LANE_PROB_MIN", 0.0)
  assert L.corrected_lane_poly(m, 0.0)[1] == L.SRC_PATH
  p, src = L.corrected_lane_poly(None, 0.0004)
  assert src == L.SRC_CURV and p.c2 == pytest.approx(0.0002) and p.view_range_m == 50


def test_garbage_model_never_raises():
  assert L.lane_poly_from_model_v2(SimpleNamespace()) is None
  assert L.path_poly_unscaled(SimpleNamespace()) is None
  nan_lines = [_line(np.linspace(0, 60, 20), lambda x: float("nan")) for _ in range(4)]
  m = SimpleNamespace(laneLines=nan_lines, laneLineProbs=[1] * 4,
                      position=SimpleNamespace(x=[], y=[]))
  assert L.corrected_lane_poly(m, 0.0004)[1] == L.SRC_CURV


def test_lane_poly_sent_as_is_in_0x239_and_stock_fields_kept():
  lanes = stock_lanes()
  poly = c.ModelPath(c0=0.4, c1=-0.01, c2=0.0006, c3=1e-6, view_range_m=70)
  ctl = c.ClusterController()
  out = dict(ctl.update(hud(lane_poly=poly), {c.DAS_LANES: lanes}, NS))
  v = c.unpack(c.DAS_LANES, out[c.DAS_LANES])
  assert v["DAS_virtualLaneC0"] == pytest.approx(0.4, abs=0.035)
  assert v["DAS_virtualLaneC1"] == pytest.approx(-0.01, abs=0.0016)
  assert v["DAS_virtualLaneC2"] == pytest.approx(0.0006, abs=2e-5)
  assert v["DAS_virtualLaneC3"] == pytest.approx(1e-6, abs=2.4e-7)
  assert v["DAS_virtualLaneViewRange"] == 70
  for k in ("DAS_virtualLaneWidth", "DAS_leftLineUsage", "DAS_rightLineUsage", "DAS_leftLaneExists"):
    assert v[k] == pytest.approx(lanes[k], abs=0.32)
  # counter continues from the stock counter, as before
  assert v["DAS_lanesCounter"] == (int(lanes["DAS_lanesCounter"]) + 1) % 16


def test_shipped_mapping_unchanged_without_lane_poly():
  ctl = c.ClusterController()
  out = dict(ctl.update(hud(curvature=0.001), {c.DAS_LANES: stock_lanes()}, NS))
  v = c.unpack(c.DAS_LANES, out[c.DAS_LANES])
  assert v["DAS_virtualLaneC0"] == pytest.approx(0.0, abs=0.035)
  assert v["DAS_virtualLaneC2"] == pytest.approx(0.001 / 2 * 4, abs=2e-5)  # shipped 4x


def _cs(stock):
  return SimpleNamespace(
    out=SimpleNamespace(steeringAngleDeg=0.0, vEgo=20.0, gasPressed=False, standstill=False),
    steer_warning="EAC_ERROR_IDLE", hands_on_level=0, eac_fault=False, eac_status="EAC_ACTIVE",
    acc_state=4, das_control_counters=deque([1]), msg_stw_actn_req={}, stock_steer_counters=[3],
    stock_ap_active=False, cluster_stock=stock)


def _cc(enabled=True, curvature=0.001):
  CC = structs.CarControl()
  CC.enabled = enabled
  CC.latActive = enabled
  CC.longActive = enabled
  CC.actuators.curvature = curvature
  return CC


def _lanes_c2(ctl, enabled=True, now=NS):
  _, can = ctl.update(_cc(enabled), _cs({c.DAS_LANES: stock_lanes()}), now)
  lanes = [m for m in can if m[0] == c.DAS_LANES]
  return (c.unpack(c.DAS_LANES, bytes(lanes[0][1])), can) if lanes else (None, can)


def _ctl(model_v2=None):
  ctl = make_controller(long=True, raw=True)
  ctl.model_v2_provider = (lambda: model_v2) if model_v2 is not None else None
  return ctl


def test_controller_off_is_shipped_mapping(toggle):
  toggle.write_text("0")
  v, _ = _lanes_c2(_ctl())
  assert v["DAS_virtualLaneC2"] == pytest.approx(0.001 / 2 * 4, abs=2e-5)


def test_controller_default_on_curvature_fallback_is_unscaled(toggle):
  assert not toggle.exists()
  v, _ = _lanes_c2(_ctl())
  assert v["DAS_virtualLaneC2"] == pytest.approx(0.001 / 2, abs=2e-5)


def test_controller_uses_lane_lines_from_provider(toggle):
  m = model(center=lambda x: 0.25 + 0.0003 * x * x)
  v, _ = _lanes_c2(_ctl(m))
  assert v["DAS_virtualLaneC0"] == pytest.approx(0.25, abs=0.035)
  assert v["DAS_virtualLaneC2"] == pytest.approx(0.0003, abs=2e-5)


def test_controller_not_engaged_sends_no_lane_frame(toggle):
  v, can = _lanes_c2(_ctl(model(center=lambda x: 0.25)), enabled=False)
  assert v is None


def test_controller_ic_integration_off_sends_nothing(toggle, monkeypatch):
  from opendbc.car.tesla_ap1 import toggles
  monkeypatch.setattr(toggles, "_ic_integration_path", toggle.parent / "EnableICIntegration")
  (toggle.parent / "EnableICIntegration").write_text("0")
  v, _ = _lanes_c2(_ctl(model(center=lambda x: 0.25)))
  assert v is None


def test_controller_failure_disables_ic_lanes_only(toggle, monkeypatch):
  ctl = _ctl()
  monkeypatch.setattr(ctl.ic_lanes, "poly", lambda *a: 1 / 0)
  v, can = _lanes_c2(ctl)
  assert ctl.ic_lanes is None and ctl.cluster is not None
  assert v["DAS_virtualLaneC2"] == pytest.approx(0.001 / 2 * 4, abs=2e-5)  # shipped mapping again


def test_no_0x309_and_no_actuator_frame_changes(toggle):
  """ICLanes adds nothing but the 0x239 payload: same frame set and the same non-cluster bytes on or off."""
  def frames(mode):
    toggle.write_text(mode)
    ctl = _ctl(model(center=lambda x: 0.25 + 0.0003 * x * x))
    _, can = ctl.update(_cc(True), _cs({c.DAS_LANES: stock_lanes()}), NS)
    return {m[0]: bytes(m[1]) for m in can}
  on, off = frames("1"), frames("0")
  assert 0x309 not in on and set(on) == set(off)
  assert {a for a in on if on[a] != off[a]} == {c.DAS_LANES}
  assert all(a in (0x488, 0x2b9, 0x349, 0x399, 0x389, 0x239, 0x45) for a in on)


def test_model_x_has_no_ic_lanes(toggle):
  ctl = make_controller(long=False, fingerprint=CAR.TESLA_AP1_MODELX)
  assert ctl.ic_lanes is None and ctl.cluster is None
