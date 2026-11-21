"""Comfort regen v2 through the real LongitudinalPlanner (needs the native MPC, so it runs on AGNOS).

Each tick the final output is <= the stock plan the same planner computed on that tick; off, or with a camera-only lead, the
output is bit-identical to a planner without the layer."""
import numpy as np

import openpilot.selfdrive.controls.lib.longitudinal_planner as lp
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, ap1_cp, msgs

V = 20.0


def new_planner(on):
  p = LongitudinalPlanner(ap1_cp(), init_v=V)
  from openpilot.selfdrive.controls.lib.phase3_speed_control import Ap1SpeedControl
  p.speed_control = Ap1SpeedControl(p.CP, adopted=False)
  p.comfort_regen.enabled = on
  return p


def drive(p, lead_fn, radar=True, steps=120, record=None):
  out = []
  orig = p._apply_comfort_regen
  def spy(sm, a, *args):
    r = orig(sm, a, *args)
    if record is not None:
      record.append((float(a), float(r)))
    return r
  p._apply_comfort_regen = spy
  for i in range(steps):
    m = msgs(V, 30.0, lead=lead_fn(i), a_ego=0.0)
    if lead_fn(i) is not None:
      m['radarState'].leadOne.radar = radar
      m['radarState'].leadOne.radarTrackId = 3
    p.update(SM(m))
    out.append(float(p.output_a_target))
  return np.array(out)


def test_never_above_stock_on_any_tick_and_acts_on_far_slower_radar_lead():
  rec = []
  far_slower = lambda i: (95.0 - 3.0 * i * 0.05, V - 3.0)
  drive(new_planner(True), far_slower, record=rec)
  stock = np.array([a for a, _ in rec]); final = np.array([b for _, b in rec])
  assert np.all(final <= stock + 1e-12)
  assert np.any(final < stock - 0.05), "comfort layer never acted on a far, slower radar lead"
  assert final.min() >= min(stock.min(), -0.9) - 1e-9


def test_off_and_camera_only_are_bit_identical_to_stock():
  far_slower = lambda i: (95.0 - 3.0 * i * 0.05, V - 3.0)
  off = drive(new_planner(False), far_slower)
  cam = drive(new_planner(True), far_slower, radar=False)
  assert np.array_equal(off, cam)


def test_no_lead_identical():
  assert np.array_equal(drive(new_planner(False), lambda i: None), drive(new_planner(True), lambda i: None))


def test_setting_default_on_for_ap1_and_mpc_gap_is_stock(monkeypatch):
  import opendbc.car.tesla_ap1.regen_brake as rb
  monkeypatch.setattr(rb, "_read_regen_comfort_file", lambda: "")
  p = LongitudinalPlanner(ap1_cp(), init_v=V)
  assert p.comfort_regen.enabled and p.ap1_plan.comfort_brake == 2.5
