"""Flame tracks that start at the passing car and run down the lane (flame_tracks.paint_trail_from_car).

Needs pyray importable (no window): every draw call is replaced by a recorder. The model-side projection
(BlindspotOverlay._bp_adjacent_points) is tested through the same import-stripped adapter as test_release_adapters.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from openpilot.selfdrive.ui.onroad.bogpilot import flame_tracks as ft
from openpilot.selfdrive.ui.onroad.bogpilot.flame_tracks_logic import DURATION_MS, TRIGGER_SPEED_MS, FlameSideInput

VIEW = (0.0, 0.0, 2160.0, 1080.0)
BOTTOM = VIEW[1] + VIEW[3]
FAST = TRIGGER_SPEED_MS + 5.0


def lane_polygon(n: int = 10, near_y: float = 1000.0, far_y: float = 520.0) -> np.ndarray:
  """Adjacent-lane polygon in the 0.11.2 _map_line_to_polygon order: left edge near -> far, then right edge far -> near."""
  ys = np.linspace(near_y, far_y, n)
  left = np.column_stack((np.linspace(100.0, 420.0, n), ys))
  right = np.column_stack((np.linspace(700.0, 470.0, n), ys))
  return np.concatenate((left, right[::-1]), axis=0).astype(np.float32)


class _Draws:
  def __init__(self):
    self.lines, self.fills, self.circles = [], [], []

  def patches(self):
    return (mock.patch.object(ft, "line", lambda *a, **k: self.lines.append(a)),
            mock.patch.object(ft, "fill_convex", lambda *a, **k: self.fills.append(a)),
            mock.patch.object(ft, "fill_circle", lambda *a, **k: self.circles.append(a)))


class _Burn:
  """Drives a real FlameTrigger to a left-side ignition, then lets tests step through the burn."""
  def __init__(self, tracks: ft.FlameTracks, lane: np.ndarray):
    self.tracks, self.lanes, self.now = tracks, [lane, lane], 1000.0

  def step(self, red_left: bool = False, dt: float = 50.0):
    self.now += dt
    inputs = [FlameSideInput(red_left, True, FAST), FlameSideInput(False, False, 0.0)]
    self.tracks.update_and_paint(inputs, self.lanes, self.now)

  def ignite(self):
    self.step(red_left=True)
    self.step(red_left=False)   # fill-off edge with a fast lead in the window -> burn starts this frame
    assert self.tracks.trigger.active(0)


class TestTrailGeometry(unittest.TestCase):
  def test_trail_runs_from_screen_bottom_up_to_the_car(self):
    car = (300.0, 760.0)
    tracks = ft.trail_tracks(lane_polygon(), car, BOTTOM)
    self.assertEqual(len(tracks), 2)
    for tr in tracks:
      self.assertEqual(len(tr), ft.TRAIL_SAMPLES)
      self.assertAlmostEqual(float(tr[0][1]), BOTTOM, delta=1.0)          # index 0 on the screen bottom
      self.assertTrue(np.all(np.diff(tr[:, 1]) < 0))                       # strictly up the screen toward the car
    top_mid = (tracks[0][-1] + tracks[1][-1]) / 2.0
    np.testing.assert_allclose(top_mid, car, atol=1e-3)                     # trail start is the car point

  def test_low_car_is_extended_not_a_fallback(self):
    lane = lane_polygon()
    car = (250.0, 995.0)   # below every lane point but the nearest
    self.assertLess(int(np.count_nonzero(ft._lane_track(lane, 0.3)[:, 1] >= car[1] - 2.0)), 2)
    tracks = ft.trail_tracks(lane, car, BOTTOM)
    self.assertIsNotNone(tracks)
    np.testing.assert_allclose((tracks[0][-1] + tracks[1][-1]) / 2.0, car, atol=1e-3)
    self.assertAlmostEqual(float(tracks[0][0][1]), BOTTOM, delta=1.0)
    d = _Draws()
    with d.patches()[0], d.patches()[1], d.patches()[2]:
      self.assertTrue(ft.paint_trail_from_car(lane, car, VIEW, 0.5, 0.0))
    self.assertTrue(d.lines)

  def test_missing_geometry_paints_nothing(self):
    d = _Draws()
    with d.patches()[0], d.patches()[1], d.patches()[2]:
      self.assertFalse(ft.paint_trail_from_car(np.empty((0, 2), np.float32), (300.0, 760.0), VIEW, 0.5, 0.0))
      self.assertFalse(ft.paint_trail_from_car(lane_polygon(), None, VIEW, 0.5, 0.0))
      self.assertFalse(ft.paint_trail_from_car(lane_polygon(), (300.0, 760.0), None, 0.5, 0.0))
    self.assertEqual((d.lines, d.fills, d.circles), ([], [], []))

  def test_front_runs_down_from_the_car_then_burns_out_from_the_car_end(self):
    last = ft.TRAIL_SAMPLES - 1
    self.assertEqual(ft.trail_span(0.0), (last, last))                     # nothing lit at ignition, only the flash
    lo_prev = last
    for t in np.linspace(0.01, ft.TRAIL_FRONT_FRAC, 12):
      lo, hi = ft.trail_span(float(t))
      self.assertEqual(hi, last)                                           # lit part always touches the car
      self.assertLessEqual(lo, lo_prev)                                    # front moves down toward index 0
      lo_prev = lo
    self.assertEqual(ft.trail_span(ft.TRAIL_FRONT_FRAC), (0, last))        # full trail, car to screen bottom
    self.assertEqual(ft.trail_span(ft.TRAIL_BURNOUT_FROM), (0, last))
    hi_prev = last
    for t in np.linspace(ft.TRAIL_BURNOUT_FROM + 0.01, 1.0, 12):
      lo, hi = ft.trail_span(float(t))
      self.assertEqual(lo, 0)                                              # the screen-bottom end burns last
      self.assertLessEqual(hi, hi_prev)                                    # burn-out moves down from the car end
      hi_prev = hi
    self.assertEqual(ft.trail_span(1.0), (0, 0))

  def test_ring_flash_at_the_car_only_at_ignition(self):
    car = (300.0, 760.0)
    d = _Draws()
    with d.patches()[0], d.patches()[1], d.patches()[2]:
      ft.paint_trail_from_car(lane_polygon(), car, VIEW, 0.0, 0.0)
    self.assertEqual([c[:2] for c in d.circles], [car])
    d = _Draws()
    with d.patches()[0], d.patches()[1], d.patches()[2]:
      ft.paint_trail_from_car(lane_polygon(), car, VIEW, ft.TRAIL_FLASH_FRAC + 0.05, 0.0)
    self.assertEqual(d.circles, [])


class TestFlameTracksAnchor(unittest.TestCase):
  def setUp(self):
    self.calls = []
    self.patches = [
      mock.patch.object(ft, "toggles", SimpleNamespace(get=lambda _: True)),
      mock.patch.object(ft, "paint_trail_from_car", lambda lane, anchor, view, t, now: self.calls.append(("car", anchor, t)) or True),
      mock.patch.object(ft, "paint_tracks", lambda lane, t, now: self.calls.append(("base", None, t))),
    ]
    for p in self.patches:
      p.start()
    self.tracks = ft.FlameTracks()
    self.tracks.view = VIEW
    self.burn = _Burn(self.tracks, lane_polygon())

  def tearDown(self):
    for p in self.patches:
      p.stop()

  def test_anchor_is_the_car_point_at_ignition(self):
    # float32 like the projected points from _map_to_screen; 771.25 is exact in float32
    self.tracks.targets = [np.array([329.0, 771.25], np.float32), None]
    self.burn.ignite()
    self.assertEqual(self.tracks.ignition_point[0], (329.0, 771.25))
    self.assertEqual(self.calls[-1][:2], ("car", (329.0, 771.25)))
    self.assertEqual(self.calls[-1][2], 0.0)

  def test_follow_mode_tracks_the_car(self):
    self.tracks.targets = [(329.0, 771.2), None]
    self.burn.ignite()
    for p in ((405.0, 757.5), (447.3, 732.6), (955.5, 597.5)):
      self.tracks.targets = [p, None]
      self.burn.step()
      self.assertEqual(self.calls[-1][:2], ("car", p))
    self.assertEqual(self.tracks.ignition_point[0], (329.0, 771.2))       # ignition capture is not rewritten

  def test_fixed_mode_keeps_the_ignition_point(self):
    with mock.patch.object(ft, "TRAIL_FOLLOWS_CAR", False):
      self.tracks.targets = [(329.0, 771.2), None]
      self.burn.ignite()
      self.tracks.targets = [(955.5, 597.5), None]
      self.burn.step()
      self.assertEqual(self.calls[-1][:2], ("car", (329.0, 771.2)))
      self.tracks.targets = [None, None]
      self.burn.step()
      self.assertEqual(self.calls[-1][:2], ("car", (329.0, 771.2)))

  def test_no_car_point_at_ignition_uses_base_tracks_for_the_whole_burn(self):
    self.tracks.targets = [None, None]
    self.burn.ignite()
    self.tracks.targets = [(405.0, 757.5), None]                            # car appears later in the same burn
    while self.tracks.trigger.active(0):
      self.burn.step()
    kinds = {c[0] for c in self.calls}
    self.assertEqual(kinds, {"base"})
    self.assertGreater(len(self.calls), DURATION_MS // 50 - 2)

  def test_dropped_car_point_uses_base_tracks_for_that_frame_only(self):
    self.tracks.targets = [(329.0, 771.2), None]
    self.burn.ignite()
    self.tracks.targets = [None, None]
    self.burn.step()
    self.assertEqual(self.calls[-1][0], "base")
    self.tracks.targets = [(np.nan, 700.0), None]                           # non-finite counts as no point
    self.burn.step()
    self.assertEqual(self.calls[-1][0], "base")
    self.tracks.targets = [(450.0, 730.0), None]
    self.burn.step()
    self.assertEqual(self.calls[-1][:2], ("car", (450.0, 730.0)))

  def test_new_burn_recaptures_the_ignition_point(self):
    self.tracks.targets = [(329.0, 771.2), None]
    self.burn.ignite()
    while self.tracks.trigger.active(0):
      self.burn.step()
    self.tracks.targets = [(600.0, 700.0), None]
    self.burn.ignite()
    self.assertEqual(self.tracks.ignition_point[0], (600.0, 700.0))

  def test_toggle_off_draws_nothing(self):
    self.tracks.targets = [(329.0, 771.2), None]
    with mock.patch.object(ft, "toggles", SimpleNamespace(get=lambda _: False)):
      self.burn.step(red_left=True)
      self.burn.step(red_left=False)
      for _ in range(10):
        self.burn.step()
      self.assertFalse(self.tracks.trigger.active(0))
    self.assertEqual(self.calls, [])


class TestToggleOffRealPaint(unittest.TestCase):
  def test_toggle_off_no_draw_calls(self):
    d = _Draws()
    tracks = ft.FlameTracks()
    tracks.view, tracks.targets = VIEW, [(300.0, 760.0), None]
    burn = _Burn(tracks, lane_polygon())
    with mock.patch.object(ft, "toggles", SimpleNamespace(get=lambda _: False)), d.patches()[0], d.patches()[1], d.patches()[2]:
      burn.step(red_left=True)
      for _ in range(20):
        burn.step()
    self.assertEqual((d.lines, d.fills, d.circles), ([], [], []))


ROOT = Path(__file__).resolve().parents[1]


def adapter_namespace(name, env):
  """Same import-stripped module load as test_release_adapters.adapter_namespace."""
  tree = ast.parse((ROOT / f"{name}.py").read_text())
  tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
  exec(compile(tree, str(ROOT / f"{name}.py"), "exec"), env)
  return env


class TestModelAdjacentPoints(unittest.TestCase):
  """BlindspotOverlay._bp_adjacent_points with the import-stripped adapter used by test_release_adapters."""

  def setUp(self):
    proj = []
    self.proj = proj

    class Base:
      def __init__(self, *a, **k):
        x = np.linspace(0.0, 100.0, 11)
        self._path = SimpleNamespace(raw_points=np.column_stack((x, np.zeros(11), np.full(11, 0.5))))
        self._path_offset_z = 1.2
        self._car_space_transform = np.eye(3)
        self._rect = SimpleNamespace(x=0, y=0, width=2160, height=1080)
      def _map_to_screen(self, x, y, z):
        proj.append((x, y, z))
        return (1000.0 + 10 * y, 900.0 - 3 * x)

    env = adapter_namespace("bogpilot_model", {
      "ModelRenderer": Base, "MiciModelRenderer": Base, "FlameTracks": lambda: SimpleNamespace(), "FlameSideInput": lambda *a: a,
      "np": np, "rl": SimpleNamespace(Color=lambda *a: a), "toggles": SimpleNamespace(get=lambda _: True),
      "ui_state": SimpleNamespace(sm=None, started_frame=0), "adjacent_leads": None, "blindspots": None,
      "BsmPolicy": lambda: SimpleNamespace(enabled=lambda b, cp=None: b), "time": __import__("time"), "draw_polygon": None})
    self.model = env["BogPilotModelRenderer"]()

  @staticmethod
  def sm(left, right):
    lead = lambda d, y: SimpleNamespace(dRel=d, yRel=y)
    return {"bogpilotRadarState": SimpleNamespace(leadLeft=lead(*left), leadRight=lead(*right))}

  def test_projects_lead_at_drel_minus_yrel_path_height(self):
    pts = self.model._bp_adjacent_points(self.sm((15.2, 4.1), (30.0, -3.5)), [(True, 50.0), (True, 45.0)])
    np.testing.assert_allclose(pts[0], (1000.0 - 41.0, 900.0 - 45.6), atol=1e-3)
    np.testing.assert_allclose(pts[1], (1000.0 + 35.0, 900.0 - 90.0), atol=1e-3)
    self.assertEqual(self.proj[0], (15.2, -4.1, 0.5 + 1.2))

  def test_fails_closed(self):
    m = self.model
    self.assertEqual(m._bp_adjacent_points(self.sm((15.0, 4.0), (15.0, -4.0)), [(False, 0.0), (False, 0.0)]), [None, None])
    self.assertEqual(m._bp_adjacent_points(self.sm((150.0, 4.0), (-1.0, -4.0)), [(True, 50.0), (True, 50.0)]), [None, None])
    self.assertEqual(m._bp_adjacent_points(self.sm((float("nan"), 4.0), (15.0, float("inf"))), [(True, 50.0), (True, 50.0)]), [None, None])
    m._car_space_transform = -np.eye(3)                                     # behind the camera
    self.assertEqual(m._bp_adjacent_points(self.sm((15.0, 4.0), (15.0, -4.0)), [(True, 50.0), (True, 50.0)]), [None, None])
    del m._path
    self.assertEqual(m._bp_adjacent_points(self.sm((15.0, 4.0), (15.0, -4.0)), [(True, 50.0), (True, 50.0)]), [None, None])


if __name__ == "__main__":
  unittest.main()
