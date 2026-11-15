"""comma 4 layout: the shared three-bar gauge in the comma 4 spot, lane-change arrow placement and modes, the stock turn intent over
the personality button, and the record button (geometry, painter, tap). Headless: draw calls are recorded."""
import math
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3
from openpilot.selfdrive.ui.onroad.bogpilot import c4_paint as C4P


class Rec:
  def __init__(self):
    self.calls = []

  def __call__(self, name):
    def f(*a, **k):
      self.calls.append((name, a, k))
    return f

  def named(self, name):
    return [c for c in self.calls if c[0] == name]


def recording(names, rl_names=()):
  rec = Rec()
  ps = [mock.patch.object(C4P, n, rec(n)) for n in names] + [mock.patch.object(C4P.rl, n, rec(n)) for n in rl_names]
  return rec, ps


def run(ps, fn, *a, **k):
  for p in ps:
    p.start()
  try:
    return fn(*a, **k)
  finally:
    for p in ps:
      p.stop()


class TestGaugePainter(unittest.TestCase):
  def test_shared_painter_in_the_comma4_spot(self):
    calls = []
    g = G3.gauge_state(0.5, -11.0, 1.0, True, accel_by_op=True)
    with mock.patch.object(G3, "paint_gauge3", lambda rect, gg, scale=1.0: calls.append((rect, gg, scale))):
      out = C4P.paint_gauge(g)
    self.assertEqual(calls, [((8, 112, 40, 76), g, C4.GAUGE_SCALE)])
    self.assertEqual(out["3-bar gauge"], (8, 112, 48, 188))
    st = out["gauge_state"]
    self.assertEqual(st["src"], [G3.DRIVER, G3.OP, G3.OP])
    self.assertAlmostEqual(st["fills"][1], 0.2)
    self.assertEqual(st["colours"][2], list(G3.GAUGE3_PALETTE[(G3.ACCEL, G3.OP)]))


class TestArrows(unittest.TestCase):
  def test_texture_origin_puts_core_on_spot(self):
    self.assertEqual(C4.arrow_tex_origin(-1), (8 - 14, 68 - 14))
    self.assertEqual(C4.arrow_core_rect(1), (419.0, 68, 465.0, 107))
    self.assertEqual(C4.arrow_tex_origin(1), (419.0 - 13, 54))

  def test_modes(self):
    self.assertEqual(C4.ARROWS_WITH_STOCK_LC_ALERT, "overlap")
    self.assertTrue(C4.arrow_visible(-1, True))
    self.assertFalse(C4.arrow_visible(-1, True, "hide"))
    self.assertTrue(C4.arrow_visible(1, False, "hide"))
    self.assertFalse(C4.arrow_visible(0, False))
    self.assertIn(C4.ARROWS_WITH_STOCK_LC_ALERT, C4.ARROW_MODES)

  def test_arrow_painter_mirrors_right(self):
    rec, ps = recording([], ["draw_texture_pro"])
    tex = NS(width=73, height=67)
    run(ps, C4P.paint_arrow, tex, -1)
    run(ps, C4P.paint_arrow, tex, 1)
    l, r = rec.named("draw_texture_pro")
    self.assertGreater(l[1][1].width, 0)
    self.assertLess(r[1][1].width, 0)
    self.assertEqual((r[1][2].x, r[1][2].y, r[1][2].width, r[1][2].height), (406.0, 54, 73, 67))

  def test_turn_intent_over_button(self):
    self.assertEqual(C4.turn_intent_rect(), (6.0, 169.0, 50.0, 187.0))
    rec, ps = recording([], ["draw_texture_pro"])
    tex = NS(width=50, height=20)
    self.assertEqual(run(ps, C4P.paint_turn_intent, tex, tex, -1, 0.0, 0.0), {})
    out = run(ps, C4P.paint_turn_intent, tex, tex, -1, 1.0, 12.0)
    c = rec.named("draw_texture_pro")[0][1]
    self.assertEqual((c[2].x, c[2].y), (28, 212))
    self.assertEqual((c[3].x, c[3].y, c[4]), (22.0, 43.0, 12.0))
    self.assertIn("turn intent (over button)", out)


class TestRecordButton(unittest.TestCase):
  def test_matches_v2_ring(self):
    self.assertEqual((C4.REC_CX, C4.REC_CY, C4.REC_D), (508, 212, 40))
    rr, sw, dot = C4.record_ring()
    self.assertAlmostEqual(rr, 19.354838, places=5)
    self.assertAlmostEqual(sw, 0.967741, places=5)
    self.assertAlmostEqual(dot, 7.6)
    self.assertEqual(C4.record_rect(), (488.0, 192.0, 528.0, 232.0))

  def test_idle_painter(self):
    rec, ps = recording(["fill_circle", "stroke_circle", "fill_rounded"], ["draw_ring"])
    run(ps, C4P.paint_record_button, "idle", 0.5)
    fc, sc = rec.named("fill_circle"), rec.named("stroke_circle")
    self.assertEqual([(c[1][0], c[1][1]) for c in fc], [(508, 212), (508, 212)])
    self.assertAlmostEqual(fc[0][1][2], 19.354838, places=5)
    self.assertEqual((fc[0][1][3].r, fc[0][1][3].g, fc[0][1][3].b, fc[0][1][3].a), (14, 17, 22, 190))
    self.assertAlmostEqual(sc[0][1][3], 0.967741, places=5)
    self.assertEqual(sc[0][1][4].a, 60)
    self.assertEqual((fc[1][1][3].r, fc[1][1][3].g, fc[1][1][3].b, fc[1][1][3].a), (225, 60, 60, 240))
    self.assertEqual(rec.named("draw_ring"), [])

  def test_recording_painter(self):
    rec, ps = recording(["fill_circle", "stroke_circle", "fill_rounded"], ["draw_ring"])
    run(ps, C4P.paint_record_button, "recording", 1.0)
    rr, sw, sq, sr = C4.record_ring_recording()
    self.assertAlmostEqual(rec.named("stroke_circle")[0][1][3], sw)
    self.assertAlmostEqual(rec.named("fill_rounded")[0][1][0].width, sq)

  def test_tap(self):
    from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_hud as H
    writes = []
    w = lambda k, v: writes.append(k)
    hud = NS(bp_c4=True, bp_c4_rec=True, _bp_c4_personality=lambda: (None, False))
    self.assertTrue(H.BogPilotMiciHudRenderer.bp_c4_handle_tap(hud, 508, 212, write=w))
    self.assertEqual(writes, ["ScreenRecorderToggle"])
    hud.bp_c4_rec = False
    self.assertFalse(H.BogPilotMiciHudRenderer.bp_c4_handle_tap(hud, 508, 212, write=w))
    self.assertEqual(writes, ["ScreenRecorderToggle"])


if __name__ == "__main__":
  unittest.main()
