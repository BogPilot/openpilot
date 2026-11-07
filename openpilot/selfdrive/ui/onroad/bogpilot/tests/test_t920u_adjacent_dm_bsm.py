"""t920u / t921u: adjacent radar lead boxes, distance colour boundaries, stock 0.11.2 DM, BSM UI wiring.

Current-schema synthetic message stand-ins only (labelled); no device, no recorded data. Native renders and the real
replay are separate VM evidence."""
import hashlib
import math
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import ROOT, adapter_namespace, load

UI = ROOT.parents[1]                       # openpilot/selfdrive/ui
REPO = ROOT.parents[4]                     # tree root (openpilot/ package parent)

# pristine stock 0.11.2 (commaai/openpilot f7db927c728bab57bb1263e05465766a8f28fc9d), fetched read-only for the audit
STOCK_SHA256 = {
  "onroad/driver_state.py": "571da708ad25502806747ff86575b1239bcc43ffdd46677878769f432fa10adc",
  "mici/onroad/driver_state.py": "de98a84ec73f109a656e1e4acae9431e73127c186730a883c819d71b876e5089",
}
STOCK_FACE_PNG = "63a9d5027779d9f1e82da718628933eb31e5072097337c42b09bf368b642ecb7"


class R:
  """Style stub recording paints. Boxes: lead_lock_box(cx, cy, d, ...) -> 40x40 at the contact point."""
  ADJ_SPEED_MIN = 5

  def __init__(self):
    self.locks, self.speeds = [], []

  def rect(self, x, y, w, h):
    return SimpleNamespace(x=x, y=y, width=w, height=h)

  def lead_lock_box(self, cx, cy, d, max_x, max_y, min_x=0.0):
    self.last_size_d = d
    return self.rect(cx - 20, cy - 40, 40, 40)

  def lead_distance_color(self, d, adjacent, v):
    return ("adj" if adjacent else "main", d, v)

  def paint_lead_lock(self, box, dist, color, view):
    self.locks.append((round(box.x), color))

  def paint_adjacent_speed(self, box, speed, color, keepout, rhd, view):
    self.speeds.append((speed, rhd, len(keepout)))


class FakeRenderer:
  """Pinhole-like stand-in for the stock calibrated projection: x = 1000 + 20*y_car, y = 900 - 4*d."""
  def __init__(self):
    self._rect = SimpleNamespace(x=0.0, y=0.0, width=2160.0, height=1080.0)
    xs = np.arange(0.0, 150.0, 5.0)
    self._path = SimpleNamespace(raw_points=np.column_stack((xs, xs * 0, xs * 0)))
    self._path_offset_z = 1.22
    self._car_space_transform = np.eye(3)

  def _map_to_screen(self, x, y, z):
    return 1000.0 + 20.0 * y, 900.0 - 4.0 * x


def lead(**kw):
  d = dict(status=True, dRel=40.0, yRel=0.0, vLead=30.0, vRel=0.0, present=True, radar=True)
  d.update(kw)
  return SimpleNamespace(**d)


class SM(dict):
  def __init__(self, now, frame=11):
    super().__init__()
    self.valid, self.alive, self.recv_frame, self.recv_time = {}, {}, {}, {}
    for n in ("radarState", "modelV2", "carState", "selfdriveState", "extrinsicsCalibration", "frogpilotRadarState"):
      self.valid[n] = self.alive[n] = True
      self.recv_frame[n], self.recv_time[n] = frame, now
    self["radarState"] = SimpleNamespace(leadOne=lead(dRel=50.0, yRel=0.0), leadTwo=lead(present=False))
    self["carState"] = SimpleNamespace(vEgo=27.0, leftBlindspot=False, rightBlindspot=False)
    self["frogpilotRadarState"] = SimpleNamespace(leadLeft=lead(dRel=30.0, yRel=3.6, vLead=31.2928),
                                                  leadRight=lead(status=False))


FAKE_RL = SimpleNamespace(begin_scissor_mode=lambda *a: None, end_scissor_mode=lambda: None)


class TestAdjacentLeads(unittest.TestCase):
  def setUp(self):
    p = patch.dict(sys.modules, {"pyray": FAKE_RL})   # painter calls only; no GL context in unit tests
    p.start()
    self.addCleanup(p.stop)
    self.mod = load("lead_lockon")
    self.now = 100.0
    self.style = R()
    self.lock = self.mod.LeadLockOn(clock=lambda: self.now, style=self.style)
    self.sm = SM(self.now)
    self.r = FakeRenderer()

  def update(self, **kw):
    args = dict(enabled=True, engaged=True, longitudinal=True, adjacent=True, metric=False)
    args.update(kw)
    return self.lock.update(self.r, self.sm, 10, **args)

  def test_left_only_absolute_speed_mph_and_kph(self):
    self.update()
    self.assertEqual([(a.side, a.speed) for a in self.lock.adjacent], [(0, "70")])   # 31.2928 m/s = 70 mph
    self.update(metric=True)
    self.assertEqual(self.lock.adjacent[0].speed, "113")                             # 112.65 km/h, qRound
    self.assertEqual(self.lock.adjacent[0].v_lead, 31.2928)                          # absolute, never ego/relative

  def test_box_sized_by_drel_plus_abs_yrel_projected_at_minus_y(self):
    self.sm["radarState"].leadOne.present = False        # so the last projection is the adjacent one
    self.update()
    a = self.lock.adjacent[0]
    self.assertAlmostEqual(self.style.last_size_d, 30.0 + 3.6)                       # daily d_rel + |yRel|
    self.assertAlmostEqual(a.box.x + 20, 1000.0 + 20.0 * -3.6)                       # car-left lead -> screen left

  def test_both_sides_independent(self):
    self.sm["frogpilotRadarState"].leadRight = lead(dRel=25.0, yRel=-3.4, vLead=20.0)
    self.update()
    self.assertEqual(sorted(a.side for a in self.lock.adjacent), [0, 1])
    self.sm["frogpilotRadarState"].leadLeft.status = False
    self.update()
    self.assertEqual([a.side for a in self.lock.adjacent], [1])

  def test_below_min_speed_box_without_number(self):
    self.sm["frogpilotRadarState"].leadLeft.vLead = 2.0     # 4.5 mph -> 4 < ADJ_SPEED_MIN
    self.update()
    self.assertEqual(self.lock.adjacent[0].speed, "")

  def test_fail_closed_missing_stale_invalid_previous_drive_nonfinite(self):
    for mutate in (lambda: self.sm.valid.__setitem__("frogpilotRadarState", False),
                   lambda: self.sm.alive.__setitem__("frogpilotRadarState", False),
                   lambda: self.sm.recv_frame.__setitem__("frogpilotRadarState", 10),
                   lambda: self.sm.recv_time.__setitem__("frogpilotRadarState", self.now - 0.6),
                   lambda: setattr(self.sm["frogpilotRadarState"].leadLeft, "dRel", float("nan")),
                   lambda: setattr(self.sm["frogpilotRadarState"].leadLeft, "vLead", float("inf")),
                   lambda: setattr(self.sm["frogpilotRadarState"].leadLeft, "dRel", 0.0),
                   lambda: self.sm.pop("frogpilotRadarState")):
      self.setUp()
      mutate()
      self.update()
      self.assertEqual(self.lock.adjacent, [])

  def test_gates(self):
    self.update(adjacent=False)
    self.assertEqual(self.lock.adjacent, [])
    for kw in ({"engaged": False}, {"longitudinal": False}, {"enabled": False}, {"hide_marker": True}):
      self.update(**kw)
      self.assertEqual(self.lock.adjacent, [], kw)

  def test_paint_colour_rhd_and_primary_suppression(self):
    self.update()
    sides = self.lock.paint_adjacent(self.r, keepouts=[], label_keepouts=[1, 2], rhd=True, v_ego=27.0)
    self.assertEqual(sides, [0])
    self.assertEqual(self.style.locks[-1][1], ("adj", 30.0, 27.0))                    # leadDistanceColor(dRel, adjacent)
    self.assertEqual(self.style.speeds[-1], ("70", True, 2))
    a = self.lock.adjacent[0]
    self.assertEqual(self.lock.paint_adjacent(self.r, primary=a.box), [])             # never stacked on the leadOne box
    self.assertEqual(self.lock.paint_adjacent(self.r, keepouts=[a.box]), [])         # suppressed, not moved

  def test_layer_draws_adjacent_without_primary_and_returns_none(self):
    self.sm["radarState"].leadOne.present = False
    layer = self.mod.LeadLockOnLayer()
    layer.lock = self.lock
    frame = SimpleNamespace(full_alert=False, mici=False, model_renderer=self.r, sm=self.sm, started_frame=10,
                            redesign=True, engaged=True, longitudinal=True, hide_lead_marker=False, adjacent_leads=True,
                            is_metric=False, keepouts=[], label_keepouts=[], rhd=False)
    self.assertTrue(layer.enabled(frame))
    self.assertIsNone(layer.draw(frame))                # composer then flushes any stock leadOne chevron
    self.assertEqual(self.lock.adjacent_painted, [0])
    frame.adjacent_leads = False
    self.assertFalse(layer.enabled(frame))


class TestDistanceColour(unittest.TestCase):
  """redesign.lead_distance_color == daily bogpilot_redesign.cc leadDistanceColor (thresholds 2v/1v/0.5v, 3.58 m/s)."""
  def setUp(self):
    self.R = load("redesign")

  def c(self, d, adj, v):
    x = self.R.lead_distance_color(d, adj, v)
    return (x.r, x.g, x.b, x.a)

  def test_boundaries_primary_and_adjacent(self):
    v = 20.0                                             # FAR 40, MID 20, NEAR 10
    self.assertEqual(self.c(40.0, False, v), (255, 255, 255, 245))
    self.assertEqual(self.c(20.0, False, v), (255, 140, 0, 250))
    self.assertEqual(self.c(10.0, False, v), (240, 40, 40, 255))
    self.assertEqual(self.c(5.0, False, v), (240, 40, 40, 255))
    self.assertEqual(self.c(40.0, True, v), (150, 150, 155, 200))
    self.assertEqual(self.c(20.0, True, v), (190, 130, 80, 210))
    self.assertEqual(self.c(10.0, True, v), (185, 80, 80, 215))

  def test_slow_is_white_and_floors(self):
    self.assertEqual(self.c(1.0, False, 3.5), (255, 255, 255, 245))
    self.assertEqual(self.c(1.0, True, 3.5), (150, 150, 155, 200))
    self.assertEqual(self.c(2.0, False, 3.6), (240, 40, 40, 255))   # NEAR floor 2 m, MID floor 5 m


class TestStockDriverMonitor(unittest.TestCase):
  def test_stock_renderer_and_asset_byte_identical_to_pristine_0112(self):
    for rel, digest in STOCK_SHA256.items():
      self.assertEqual(hashlib.sha256((UI / rel).read_bytes()).hexdigest(), digest, rel)
    face = REPO / "openpilot/selfdrive/assets/icons/driver_face.png"
    if face.exists():
      self.assertEqual(hashlib.sha256(face.read_bytes()).hexdigest(), STOCK_FACE_PNG)

  def test_composer_never_loads_relocation(self):
    src = (ROOT / "hud_compose.py").read_text()
    self.assertNotIn('("driver_monitor", BP + "driver_monitor")', src)
    self.assertIn("self.dm.render(rect)", src)


class TestBsm(unittest.TestCase):
  def setUp(self):
    self.m = load("bsm_state")
    self.now = 50.0
    self.sm = SM(self.now)

  def test_sides_independent_both_off(self):
    cs = self.sm["carState"]
    for l, r in ((True, False), (False, True), (True, True), (False, False)):
      cs.leftBlindspot, cs.rightBlindspot = l, r
      self.assertEqual(self.m.blindspots(self.sm, 10, self.now), (l, r))

  def test_stale_missing_invalid_previous_drive(self):
    self.sm["carState"].leftBlindspot = True
    for mutate in (lambda: self.sm.recv_time.__setitem__("carState", self.now - 0.51),
                   lambda: self.sm.valid.__setitem__("carState", False),
                   lambda: self.sm.recv_frame.__setitem__("carState", 10),
                   lambda: self.sm.pop("carState")):
      self.setUp()
      self.sm["carState"].leftBlindspot = True if "carState" in self.sm else None
      mutate()
      self.assertEqual(self.m.blindspots(self.sm, 10, self.now), (False, False))

  def test_rhd_never_swaps_car_frame_sides(self):
    self.sm["carState"].leftBlindspot = True
    self.sm["driverMonitoringState"] = SimpleNamespace(isRHD=True)
    self.assertEqual(self.m.blindspots(self.sm, 10, self.now), (True, False))

  def test_policy_daily_formula(self):
    class Store:
      def __init__(self, custom, debug=False, boom=False):
        self.custom, self.debug, self.boom = custom, debug, boom
      def tuning_level(self):
        if self.boom:
          raise OSError("x")
        return 3
      def toggle_bool(self, k, level=None):
        return self.custom
      def get_bool(self, k, default=False):
        return self.debug
    P = self.m.BsmPolicy
    self.assertTrue(P(Store(True), clock=lambda: 0).enabled(True))
    self.assertFalse(P(Store(False), clock=lambda: 0).enabled(True))      # CustomUI off hides (daily)
    self.assertFalse(P(Store(True), clock=lambda: 0).enabled(False))      # BlindSpotPath off hides
    self.assertTrue(P(Store(False, debug=True), clock=lambda: 0).enabled(False))
    self.assertTrue(P(Store(True, boom=True), clock=lambda: 0).enabled(True))   # unreadable store: prior behaviour

  def test_model_fill_left_right_both_off_and_stale(self):
    draws = []
    sm, now = self.sm, [self.now]

    class Base:
      def __init__(self):
        self._rect = SimpleNamespace(x=0, y=0)
        x = np.array([0, 10, 20], dtype=np.float32)
        self._lane_lines = [SimpleNamespace(raw_points=np.column_stack((x, np.full(3, y), x * 0))) for y in (-5.4, -1.8, 1.8, 5.4)]
      def _draw_lane_lines(self):
        pass
      def _get_path_length_idx(self, x, d):
        return len(x) - 1
      def _map_line_to_polygon(self, *a):
        return np.array([[0, 0], [0, 10], [10, 10], [10, 0]], dtype=np.float32)

    class Flames:
      def __init__(self):
        self.trigger = SimpleNamespace(update=lambda *a: None)
      def update_and_paint(self, inputs, lanes):
        self.inputs = inputs
    env = adapter_namespace("bogpilot_model", {
      "ModelRenderer": Base, "MiciModelRenderer": Base, "FlameTracks": Flames, "FlameSideInput": lambda *a: a, "np": np,
      "rl": SimpleNamespace(Color=lambda *a: a), "toggles": SimpleNamespace(get=lambda _: True),
      "ui_state": SimpleNamespace(sm=sm, started_frame=10), "adjacent_leads": self.m.adjacent_leads,
      "blindspots": self.m.blindspots, "BsmPolicy": lambda: SimpleNamespace(enabled=lambda b: b),
      "time": SimpleNamespace(monotonic=lambda: now[0]), "draw_polygon": lambda *a: draws.append(a)})
    model = env["BogPilotModelRenderer"]()
    cs = sm["carState"]
    for l, r in ((True, False), (False, True), (True, True), (False, False)):
      cs.leftBlindspot, cs.rightBlindspot = l, r
      model._draw_lane_lines()
      self.assertEqual(model.bp_bsm_shown, (l, r))
    cs.leftBlindspot = True
    now[0] = self.now + 0.6                            # carState now stale
    model._draw_lane_lines()
    self.assertEqual(model.bp_bsm_shown, (False, False))


class TestPolicyAdjacentGate(unittest.TestCase):
  def test_adjacent_gate_is_daily_tracking_or_hlc(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_hud_compose import env, Log
    ns = env(SimpleNamespace(CP=None), {}, Log())

    class Store:
      def tuning_level(self):
        return 3
      def get_bool(self, k, default=None):
        return False
      def toggle_bool(self, k, level=None):
        return False
    for a, h, want in ((True, False, True), (False, True, True), (False, False, False)):
      fake = SimpleNamespace(onroad_toggles=lambda s, cp, a=a, h=h: SimpleNamespace(adjacent_lead_tracking=a, human_lane_changes=h))
      with patch.dict(sys.modules, {"openpilot.common.bogpilot_onroad_toggles": fake}):
        v = ns["PolicyToggles"](Store(), clock=lambda: 0.0).get()
      self.assertEqual(v["adjacent_leads"], want, (a, h))


class TestUiSubscribes(unittest.TestCase):
  def test_ui_state_subscribes_frogpilot_radar_state(self):
    self.assertIn('"frogpilotRadarState"', (UI / "ui_state.py").read_text())


if __name__ == "__main__":
  unittest.main()
