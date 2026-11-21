"""Lane widths are computed once per frame (flame_tracks._lane_width_profile + one np.interp).

The old per-call implementation is frozen in _flame_tracks_reference.py. Both are driven on the same inputs with every draw
call recorded: recorded real burn frames (data/flame_trail_recorded_burn.npz: the lane polygon, car point, view, burn
progress and clock the UI passed to paint_trail_from_car during a real left-side activation) and synthetic lanes.
Draw calls must match in order and count; floats within tolerance."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from openpilot.selfdrive.ui.onroad.bogpilot import flame_tracks as new
from openpilot.selfdrive.ui.onroad.bogpilot.tests import _flame_tracks_reference as old
from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_flame_trail_from_car import lane_polygon

DATA = Path(__file__).parent / "data" / "flame_trail_recorded_burn.npz"
VIEW = (0.0, 0.0, 2160.0, 1080.0)
RTOL, ATOL = 1e-5, 1e-3


def _plain(v):
  return (v.r, v.g, v.b, v.a) if hasattr(v, "r") else v


def record(mod, lane, anchor, view, t, now_ms):
  calls = []
  def rec(kind):
    return lambda *a, **k: calls.append((kind, tuple(_plain(x) for x in a), tuple(sorted(k.items()))))
  with mock.patch.object(mod, "line", rec("line")), mock.patch.object(mod, "fill_convex", rec("fill")), \
       mock.patch.object(mod, "fill_circle", rec("circle")):
    ok = mod.paint_trail_from_car(lane, anchor, view, t, now_ms)
  return ok, calls


def assert_same_draws(tc: unittest.TestCase, a, b):
  tc.assertEqual(a[0], b[0])
  tc.assertEqual(len(a[1]), len(b[1]))
  for (ka, aa, kwa), (kb, ab, kwb) in zip(a[1], b[1], strict=True):
    tc.assertEqual((ka, kwa), (kb, kwb))
    if ka == "fill":
      tc.assertEqual(len(aa[0]), len(ab[0]))
      np.testing.assert_allclose(np.asarray(aa[0], dtype=float), np.asarray(ab[0], dtype=float), rtol=RTOL, atol=ATOL)
      tc.assertEqual(aa[1:], ab[1:])
    else:
      for x, y in zip(aa, ab, strict=True):
        if isinstance(x, float) or isinstance(y, float):
          np.testing.assert_allclose(x, y, rtol=RTOL, atol=ATOL)
        else:
          tc.assertEqual(x, y)   # colours: identical bytes


class TestLaneWidthOnce(unittest.TestCase):
  def test_profile_matches_old_per_call_width(self):
    lanes = [lane_polygon(n) for n in (2, 3, 10, 33)]
    lanes.append(lane_polygon(10)[:-1])                       # odd point count: the last point is ignored, as before
    rng = np.random.default_rng(7)
    for lane in lanes:
      ys = rng.uniform(300.0, 1200.0, 64)
      got = new._lane_widths_at(new._lane_width_profile(lane), ys)
      want = np.array([old._lane_width_at_y(lane, float(y)) for y in ys])
      np.testing.assert_allclose(got, want, rtol=RTOL, atol=ATOL)
      for y in ys[:8]:
        self.assertAlmostEqual(new._lane_width_at_y(lane, float(y)), old._lane_width_at_y(lane, float(y)), delta=ATOL)

  def test_degenerate_lane_gives_zero_width(self):
    tiny = np.zeros((2, 2), dtype=np.float32)
    self.assertIsNone(new._lane_width_profile(tiny))
    np.testing.assert_array_equal(new._lane_widths_at(None, [1.0, 2.0]), [0.0, 0.0])
    self.assertEqual(new._lane_width_at_y(tiny, 5.0), old._lane_width_at_y(tiny, 5.0))

  def test_recorded_real_burn_frames_draw_identically(self):
    d = np.load(DATA)
    self.assertGreaterEqual(len(d["ts"]), 40)
    cuts = np.concatenate(([0], np.cumsum(d["lens"])))
    drew = 0
    for i in range(len(d["ts"])):
      lane = d["lanes"][cuts[i]:cuts[i + 1]]
      args = (lane, tuple(d["anchors"][i]), tuple(d["views"][i]), float(d["ts"][i]), float(d["nows"][i]))
      a, b = record(old, *args), record(new, *args)
      drew += bool(a[1])                                      # the very last frames of a burn can be empty
      assert_same_draws(self, a, b)
    self.assertGreaterEqual(drew, 50)

  def test_synthetic_lanes_across_the_whole_burn(self):
    for n in (4, 10, 33):
      lane = lane_polygon(n)
      for anchor in ((300.0, 760.0), (250.0, 995.0), (330.0, 560.0)):
        for t in np.linspace(0.0, 1.0, 41):
          for now in (0.0, 412.5, 77777.0):
            args = (lane, anchor, VIEW, float(t), now)
            assert_same_draws(self, record(old, *args), record(new, *args))

  def test_widths_are_not_rebuilt_per_segment(self):
    lane = lane_polygon(33)
    with mock.patch.object(new, "_lane_width_profile", wraps=new._lane_width_profile) as prof, \
         mock.patch.object(new, "_lane_widths_at", wraps=new._lane_widths_at) as at:
      record(new, lane, (300.0, 760.0), VIEW, 0.4, 5000.0)
    self.assertEqual(prof.call_count, 1)
    self.assertEqual(at.call_count, 1)


if __name__ == "__main__":
  unittest.main()
