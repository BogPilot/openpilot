"""Engaged 0x239 lane reach (cluster.lane_view_range): the lane sent while engaged never ends short of the stock camera's
range, the floor, or openpilot's lead + margin. The failure it fixes: stopped close behind a truck, the planned path (the
old view range) ended a stop gap short of the lead and the cluster stopped drawing the stock camera's lead vehicle.
Display only."""
from types import SimpleNamespace

import numpy as np
import pytest

from opendbc.car.tesla_ap1 import cluster as c
from opendbc.car.tesla_ap1.tests.test_ap1_ic_lanes import _cc, _cs, _ctl, hud, stock_lanes, toggle  # noqa: F401

NS = 1_000_000_000
M = c.LEAD_REACH_MARGIN_M


def stock_with_range(view):
  s = dict(stock_lanes())
  s["DAS_virtualLaneViewRange"] = view
  return c.unpack(c.DAS_LANES, c.pack(c.DAS_LANES, c.SIGNALS[c.DAS_LANES], s).to_bytes(8, "little"))


def model(path_len=6.0, lead=None, prob=0.95, n=33):
  """Lane lines out to 100 m; planned path only out to path_len (a stop short of the lead); leadsV3[0] at lead m."""
  xs = np.linspace(0.0, 100.0, n)
  lines = [SimpleNamespace(x=list(xs), y=[k * 3.3 for _ in xs]) for k in (-1.5, -0.5, 0.5, 1.5)]
  px = list(np.linspace(0.6, path_len, 17))
  leads = [SimpleNamespace(prob=prob, x=[lead if lead is not None else 0.0] * 6)]
  return SimpleNamespace(laneLines=lines, laneLineProbs=[0.9] * 4, position=SimpleNamespace(x=px, y=[0.0] * len(px)),
                         leadsV3=leads if lead is not None else [SimpleNamespace(prob=0.0, x=[0.0] * 6)])


def sent_range(h, stock_view=20):
  out = dict(c.ClusterController().update(h, {c.DAS_LANES: stock_with_range(stock_view)}, NS))
  return c.unpack(c.DAS_LANES, out[c.DAS_LANES])


# ---- the rule ----

@pytest.mark.parametrize("lead", [6.0, 8.0, 15.0, 45.0, 70.0, 120.0])
def test_stopped_lead_short_path_reaches_past_the_lead(lead):
  path = c.ModelPath(0.0, 0.0, 0.0, 0.0, 6.0)        # plan ends a stop gap short of the stopped lead
  v = sent_range(hud(lane_poly=path, lead_dist_m=lead), stock_view=12)
  assert v["DAS_virtualLaneViewRange"] >= min(lead + M, c.VIEW_RANGE_MAX_M)
  assert v["DAS_virtualLaneViewRange"] >= c.VIEW_RANGE_FLOOR_M


def test_rule_table():
  f = c.lane_view_range
  assert f(6, 12, 8.0) == 50                 # stopped close: floor covers lead + margin (18 m)
  assert f(6, 12, 45.0) == 55                # stopped far: lead + margin
  assert f(100, 60, 40.0) == 100             # moving, plan longer than the lead: unchanged
  assert f(80, 60, 120.0) == 130             # moving, lead beyond the plan
  assert f(90, 140, None) == 140             # stock camera reaches further: keep its reach
  assert f(6, 0, None) == 50                 # no lead, short plan, stock 0: floor
  assert f(90, None, None) == 90             # no stock value: plan
  assert f(6, 12, 200.0) == c.VIEW_RANGE_MAX_M   # clamp to the DBC range
  assert f(500, 500, 500) == c.VIEW_RANGE_MAX_M
  for junk in (None, float("nan"), float("inf"), "x", -5, 0):
    assert f(junk, junk, junk) == c.VIEW_RANGE_FLOOR_M


def test_moving_long_plan_unchanged_and_geometry_untouched():
  poly = c.ModelPath(c0=0.4, c1=-0.01, c2=0.0006, c3=1e-6, view_range_m=110)
  a = sent_range(hud(lane_poly=poly, lead_dist_m=40.0), stock_view=60)
  b = sent_range(hud(lane_poly=poly, lead_dist_m=None), stock_view=60)
  assert a["DAS_virtualLaneViewRange"] == b["DAS_virtualLaneViewRange"] == 110
  for k in ("DAS_virtualLaneC0", "DAS_virtualLaneC1", "DAS_virtualLaneC2", "DAS_virtualLaneC3"):
    assert a[k] == b[k]                       # the lead only lengthens the lane, never bends it


def test_shipped_mapping_and_curvature_paths_also_reach():
  # ICLanes off (model_path) and the curvature fallback get the same reach rule
  mp = c.ModelPath(0.0, 0.0, 0.0001, 0.0, 7.0)
  assert sent_range(hud(model_path=mp, lead_dist_m=60.0))["DAS_virtualLaneViewRange"] == 70
  assert sent_range(hud(curvature=0.001, lead_dist_m=None))["DAS_virtualLaneViewRange"] == 50


def test_lead_distance_from_model():
  assert c.lead_distance_from_model_v2(model(lead=12.0)) == pytest.approx(12.0)
  assert c.lead_distance_from_model_v2(model(lead=12.0, prob=0.3)) is None
  assert c.lead_distance_from_model_v2(model(lead=None)) is None
  for bad in (None, SimpleNamespace(), SimpleNamespace(leadsV3=[]), model(lead=float("nan"))):
    assert c.lead_distance_from_model_v2(bad) is None


# ---- CarController end to end ----

def _lanes(ctl, enabled=True, stock_view=12, now=NS):
  _, can = ctl.update(_cc(enabled), _cs({c.DAS_LANES: stock_with_range(stock_view)}), now)
  lanes = [m for m in can if m[0] == c.DAS_LANES]
  return (c.unpack(c.DAS_LANES, bytes(lanes[0][1])) if lanes else None), can


def test_controller_stopped_close_truck(toggle):
  v, _ = _lanes(_ctl(model(path_len=6.0, lead=9.0)))
  assert v["DAS_virtualLaneViewRange"] >= 9.0 + M


def test_controller_far_stopped_lead_uses_the_lead(toggle):
  v, _ = _lanes(_ctl(model(path_len=30.0, lead=75.0)))
  assert v["DAS_virtualLaneViewRange"] == 85


def test_controller_lead_failure_keeps_cluster(toggle):
  class Boom:
    laneLines = model().laneLines
    laneLineProbs = [0.9] * 4
    position = model(path_len=6.0).position

    @property
    def leadsV3(self):
      raise RuntimeError("bad lead")
  ctl = _ctl(Boom())
  v, _ = _lanes(ctl)
  assert ctl.cluster is not None and ctl.ic_lanes is not None
  assert v["DAS_virtualLaneViewRange"] == c.VIEW_RANGE_FLOOR_M


def test_disengage_restores_stock_frames(toggle):
  ctl = _ctl(model(path_len=6.0, lead=9.0))
  v, _ = _lanes(ctl, enabled=True, now=NS)
  assert v is not None
  # disengaged: no 0x239 at all (the panda forwards the stock frame again), during and after the post window
  v, can = _lanes(ctl, enabled=False, now=2 * NS)
  assert v is None
  v, can = _lanes(ctl, enabled=False, now=2 * NS + c.POST_DISENGAGE_NS + 1)
  assert v is None and not [m for m in can if m[0] in c.CLUSTER_ADDRS]
