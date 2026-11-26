"""comma 4 HUD: pill contents, personality button states (stripes, Traffic Mode, take control), tap handling and the
device gate in the mici HUD renderer (headless: draw calls are recorded, not rendered)."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot import c4_paint as C4P
from openpilot.selfdrive.ui.onroad.bogpilot import lead_labels as LL


class Rec:
  def __init__(self):
    self.calls = []

  def __call__(self, name):
    def f(*a, **k):
      self.calls.append((name, a, k))
    return f

  def named(self, name):
    return [c for c in self.calls if c[0] == name]


def record(module_names):
  rec = Rec()
  patches = [mock.patch.object(C4P, n, rec(n)) for n in module_names]
  patches.append(mock.patch.object(C4P.rl, "draw_line_ex", rec("line")))
  patches.append(mock.patch.object(C4P.rl, "draw_rectangle_rec", rec("rowfill")))
  return rec, patches


class TestPill(unittest.TestCase):
  def run_pill(self, **kw):
    inp = dict(set_speed="70", speed="65", unit="MPH", engaged=True, show_limit=True, limit="\u2013")
    inp.update(kw)
    rec, patches = record(["panel", "_centred"])
    for p in patches:
      p.start()
    try:
      out = C4P.paint_pill(C4P.PillInputs(**inp))
    finally:
      for p in patches:
        p.stop()
    return out, rec

  def test_one_pill_set_speed_and_limit(self):
    out, rec = self.run_pill()
    self.assertEqual(out["speed pill"], C4.PILL)
    self.assertEqual(out["limit tile"], C4.PILL_LIMIT)
    texts = [c[1][0] for c in rec.named("_centred")]
    self.assertEqual(texts, ["70", "MAX", "65", "MPH", "LIMIT", "\u2013"])

  def test_max_label_colour_follows_engagement(self):
    _, on = self.run_pill(engaged=True)
    _, off = self.run_pill(engaged=False)
    col = lambda rec: [c[1][4] for c in rec.named("_centred") if c[1][0] == "MAX"][0]
    self.assertEqual((col(on).r, col(on).g, col(on).b), (61, 220, 151))
    self.assertEqual(col(off).a, 150)

  def test_limit_hidden_when_policy_off(self):
    out, rec = self.run_pill(show_limit=False)
    self.assertNotIn("limit tile", out)
    self.assertNotIn("LIMIT", [c[1][0] for c in rec.named("_centred")])


class TestPersonalityButton(unittest.TestCase):
  def run_button(self, personality, traffic, take):
    rec, patches = record(["fill_circle", "stroke_circle", "fill_rounded", "_gradient_disc"])
    for p in patches:
      p.start()
    try:
      out = C4P.paint_personality_button(personality, traffic, take)
    finally:
      for p in patches:
        p.stop()
    return out, rec

  def stripes(self, rec):
    return [c for c in rec.named("fill_rounded") if abs(c[1][0].width - C4.PERSONALITY_STRIPE_W) < 1e-6]

  def test_position_and_stripes(self):
    for pers, n in ((0, 1), (1, 2), (2, 3)):
      out, rec = self.run_button(pers, False, False)
      self.assertEqual(out["personality button"], C4.personality_rect())
      self.assertEqual(len(self.stripes(rec)), n)
      self.assertEqual(rec.named("_gradient_disc"), [])
    out, rec = self.run_button(None, False, False)
    self.assertEqual(len(self.stripes(rec)), 0)

  def test_stripes_centred_on_button(self):
    _, rec = self.run_button(2, False, False)
    ys = [c[1][0].y + c[1][0].height / 2 for c in self.stripes(rec)]
    self.assertEqual(ys, [C4.PERSONALITY_CY - 8, C4.PERSONALITY_CY, C4.PERSONALITY_CY + 8])

  def test_traffic_mode_one_red_stripe(self):
    _, rec = self.run_button(2, True, False)
    s = self.stripes(rec)
    self.assertEqual(len(s), 1)
    self.assertEqual((s[0][1][2].r, s[0][1][2].g, s[0][1][2].b), (232, 70, 80))

  def test_take_control_orange_white_stripes_red_mark(self):
    out, rec = self.run_button(1, False, True)
    g = rec.named("_gradient_disc")
    self.assertEqual(len(g), 1)
    self.assertEqual((g[0][1][3], g[0][1][4]), (C4P.CRIT_TOP, C4P.CRIT_BOTTOM))
    self.assertTrue(all(c[1][2].r == c[1][2].g == c[1][2].b == 255 and c[1][2].a == 255 for c in self.stripes(rec)))
    self.assertIn("take-control !", out)
    reds = [c for c in rec.named("fill_rounded") if (c[1][2].r, c[1][2].g, c[1][2].b) == (224, 32, 42)]
    whites = [c for c in rec.named("fill_rounded") if c[1][0].width in (10.0,) and c[1][2].a == 255]
    self.assertEqual(len(reds), 2)
    self.assertEqual(len(whites), 2)
    m = out["take-control !"]
    self.assertTrue(m[0] >= C4.personality_rect()[0] and m[3] <= C4.PERSONALITY_CY + 20)


def hud_module():
  from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_hud as H
  return H


class TestTapAndGate(unittest.TestCase):
  def setUp(self):
    self.H = hud_module()

  def fake(self, c4=True, pers=2, traffic=False):
    data = None if pers is None else LL.PersonalityData(pers, traffic, "x")
    return NS(bp_c4=c4, bp_c4_rec=False, _bp_c4_personality=lambda: (data, traffic))

  def tap(self, hud, x, y):
    writes = []
    hit = self.H.BogPilotMiciHudRenderer.bp_c4_handle_tap(hud, x, y, write=lambda k, v: writes.append((k, v)))
    return hit, writes

  def test_tap_steps_down_like_the_stalk(self):
    for cur, new in ((2, 1), (1, 0), (0, 2)):
      hit, w = self.tap(self.fake(pers=cur), C4.PERSONALITY_CX, C4.PERSONALITY_CY)
      self.assertTrue(hit)
      self.assertEqual(w, [("LongitudinalPersonality", new)])

  def test_tap_outside_or_not_comma4(self):
    self.assertEqual(self.tap(self.fake(), 100, 100), (False, []))
    self.assertEqual(self.tap(self.fake(c4=False), C4.PERSONALITY_CX, C4.PERSONALITY_CY), (False, []))

  def test_tap_traffic_or_unknown_consumed_no_write(self):
    self.assertEqual(self.tap(self.fake(traffic=True), C4.PERSONALITY_CX, C4.PERSONALITY_CY), (True, []))
    self.assertEqual(self.tap(self.fake(pers=None), C4.PERSONALITY_CX, C4.PERSONALITY_CY), (True, []))

  def test_no_stock_wheel_or_max_box_on_comma4(self):
    ns = NS(bp_c4=True)
    self.assertIsNone(self.H.BogPilotMiciHudRenderer._draw_steering_wheel(ns, None))
    self.assertIsNone(self.H.BogPilotMiciHudRenderer._draw_set_speed(ns, None))

  def test_wide_renderer_has_no_comma4_path(self):
    self.assertFalse(hasattr(self.H.BogPilotHudRenderer, "_bp_render_c4"))
    self.assertFalse(hasattr(self.H.BogPilotHudRenderer, "bp_c4_handle_tap"))


if __name__ == "__main__":
  unittest.main()
