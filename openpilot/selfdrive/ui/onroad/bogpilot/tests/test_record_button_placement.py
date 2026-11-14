"""Record button: one fixed spot centred between the pedal bars' rect and the personality label, the same with the
pedals gate on or off; RHD mirrors; the tap rect is the rect the button is drawn in; no overlaps (headless)."""
import ast
import unittest
from pathlib import Path

import pyray as rl

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load

ST = load("style")
R = load("redesign")
PED = load("pedals")
HERE = Path(__file__).resolve().parents[1]
DESIGN_W, DESIGN_H = 2160.0, 1080.0
# content rects on the 2160x1080 screen (border 30): sidebar hidden and sidebar open (the narrowest wide layout)
LAYOUTS = [(30, 30, 2100, 1020), (330, 30, 1800, 1020)]
P = 3   # rects are float32 (pyray)


def layout(c):
  content = rl.Rectangle(*c)
  s = min(1.0, content.width / DESIGN_W, content.height / DESIGN_H)
  return content, s, content.width / s


def hud_compose_constants():
  tree = ast.parse((HERE / "hud_compose.py").read_text())
  out = {}
  for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
      if isinstance(node.value, ast.Constant):
        out[node.targets[0].id] = node.value.value
  return out


def pill_and_band(content, s, rhd):
  """Mirror of hud_compose's personality placement (screen space)."""
  off = ST.DM_CORNER_OFF
  px = content.x + (content.width - off if rhd else off)
  py = content.y + content.height - off
  p = R.personality_rect(rhd, content.width / s)
  w, h = p.width * s, p.height * s
  pill = (px - w / 2, py - h / 2, w, h)
  band = (pill[0], pill[1] - ST.PILL_LABEL_SPACE, w, h + ST.PILL_LABEL_SPACE)
  return pill, band


def bars_screen(content, s, ww, rhd):
  x, y, w, h = PED.pedal_rect(ww, rhd)
  return (content.x + x * s, content.y + y * s, w * s, h * s)


def overlap(a, b, margin=0.0):
  return (a[0] < b[0] + b[2] + margin and b[0] < a[0] + a[2] + margin and
          a[1] < b[1] + b[3] + margin and b[1] < a[1] + a[3] + margin)


def t(r):
  return (r.x, r.y, r.width, r.height)


class TestRecordButtonPlacement(unittest.TestCase):
  def test_corner_offset_matches_hud_compose(self):
    k = hud_compose_constants()
    self.assertEqual(ST.DM_CORNER_OFF, k["UI_BORDER"] + k["DM_BTN"] // 2)
    self.assertIn("off = UI_BORDER + DM_BTN // 2", (HERE / "hud_compose.py").read_text())
    self.assertEqual(ST.REC_CX, ST.DM_CORNER_OFF)   # the button already shares the corner's x

  def test_label_constants_used_by_paint_personality(self):
    src = (HERE / "redesign.py").read_text()
    self.assertIn("PILL_LABEL_SPACE - PILL_LABEL_PAD), PILL_LABEL_SIZE", " ".join(src.split()).replace("( ", "("))

  def test_centre_is_midpoint_between_bars_and_label(self):
    for c in LAYOUTS:
      content, s, ww = layout(c)
      for rhd in (False, True):
        hit = ST.record_hit_rect(content, s, ww, rhd)
        bars = bars_screen(content, s, ww, rhd)
        label_top = content.y + ST.pill_label_text_top(s, content.height)
        above = hit.y + hit.height / 2 - ST.REC_DIAMETER / 2 - (bars[1] + bars[3])  # drawn button is REC_DIAMETER
        below = label_top - (hit.y + hit.height / 2 + ST.REC_DIAMETER / 2)
        self.assertAlmostEqual(above, below, places=P, msg=(c, rhd))
        self.assertGreater(above, 10, (c, rhd))

  def test_known_values_on_the_main_layout(self):
    content, s, ww = layout(LAYOUTS[0])
    self.assertAlmostEqual(ST.record_center_y(s, content.height), 723.456, places=2)
    self.assertAlmostEqual(content.y + ST.pill_label_text_top(s, content.height), 824.19, places=1)
    hit = ST.record_hit_rect(content, s, ww, False)
    self.assertAlmostEqual(hit.y + hit.height / 2, 713.26, places=1)

  def test_bar_geometry_has_one_source(self):
    # the button uses pedals.pedal_rect (the bars' layout rect); style's copies of the bar constants must agree
    for ww in (1905.9, 2223.5):
      for rhd in (False, True):
        _x, y, _w, h = PED.pedal_rect(ww, rhd)
        self.assertEqual(y + h, ST.STACK_BOTTOM + ST.PEDAL_GAP + ST.PEDAL_H)
    self.assertEqual((PED.STACK_BOTTOM, PED.PEDAL_GAP, PED.PEDAL_H, PED.EDGE), (ST.STACK_BOTTOM, ST.PEDAL_GAP, ST.PEDAL_H, ST.EDGE))

  def test_same_spot_with_the_pedals_gate_on_and_off(self):
    # the position takes no gate input at all, and the HUD passes none: drawn and tap rect are one rect
    import inspect
    self.assertEqual(list(inspect.signature(ST.record_hit_rect).parameters), ["content", "scale", "widget_w", "rhd"])
    self.assertEqual(list(inspect.signature(ST.record_center_y).parameters), ["scale", "content_h"])
    src = (HERE / "bogpilot_hud.py").read_text()
    body = src[src.index("_pol, rec = self._bp_extras.get"):src.index("def _draw_set_speed")]
    self.assertNotIn("bp_pedals", body)
    for c in LAYOUTS:
      content, s, ww = layout(c)
      for rhd in (False, True):
        rects = []
        for _gate in (True, False):   # bars drawn / bars hidden: the HUD calls the same function with the same inputs
          rects.append(t(ST.record_hit_rect(content, s, ww, rhd)))
        self.assertEqual(rects[0], rects[1], (c, rhd))

  def test_rhd_mirrors_and_size_and_x_unchanged(self):
    for c in LAYOUTS:
      content, s, ww = layout(c)
      lhd, rhd = ST.record_hit_rect(content, s, ww, False), ST.record_hit_rect(content, s, ww, True)
      self.assertAlmostEqual(lhd.y, rhd.y, places=P)
      self.assertAlmostEqual((lhd.x + lhd.width / 2) - content.x, content.x + content.width - (rhd.x + rhd.width / 2), places=P)
      self.assertAlmostEqual(lhd.width, ST.REC_HIT * s, places=P)
      self.assertAlmostEqual(lhd.height, ST.REC_HIT * s, places=P)
      self.assertAlmostEqual(lhd.x + lhd.width / 2, content.x + ST.REC_CX, places=P)   # x as before (screen px from the edge)

  def test_tap_rect_is_the_drawn_rect(self):
    from openpilot.system.ui.widgets import Widget
    drawn = []

    class Probe(Widget):
      def _render(self, rect):
        drawn.append(rect)

    R_paint = []
    orig = R.fill_circle, R.stroke_circle
    R.fill_circle = lambda cx, cy, r, col: R_paint.append((cx, cy, r))
    R.stroke_circle = lambda *a, **k: None
    try:
      content, s, ww = layout(LAYOUTS[0])
      for rhd in (False, True):
        hit = ST.record_hit_rect(content, s, ww, rhd)
        w = Probe()
        w.render(hit)
        self.assertEqual(t(w._hit_rect), t(hit))
        self.assertEqual(t(drawn[-1]), t(hit))
        R_paint.clear()
        R.paint_record_button(drawn[-1], False, 0.0)
        cx, cy, _r = R_paint[0]
        self.assertAlmostEqual(cx, hit.x + hit.width / 2, places=P)
        self.assertAlmostEqual(cy, hit.y + hit.height / 2, places=P)
        self.assertTrue(rl.check_collision_point_rec(rl.Vector2(cx, cy), w._hit_rect))
    finally:
      R.fill_circle, R.stroke_circle = orig

  def test_hud_uses_the_one_rect_for_tap_draw_and_keepout(self):
    src = (HERE / "bogpilot_hud.py").read_text()
    self.assertIn("hit = record_hit_rect(rect, scale, widget_w, self.bp_rhd)", src)
    self.assertIn("self._bp_rec_btn.render(hit)", src)
    self.assertNotIn("REC_CY", src)

  def test_no_overlaps_where_the_bars_show(self):
    for c in LAYOUTS:
      content, s, ww = layout(c)
      for rhd in (False, True):
        hit = t(ST.record_hit_rect(content, s, ww, rhd))
        bars = bars_screen(content, s, ww, rhd)
        pill, band = pill_and_band(content, s, rhd)
        self.assertFalse(overlap(hit, bars), (c, rhd))
        # personality label band (pill variant, any label text / traffic colour): clear of the lead-label margin
        self.assertFalse(overlap(hit, band, margin=8), (c, rhd))
        # stock DM in the corner (no personality pill variant)
        dm = (pill[0] + pill[2] / 2 - 96, pill[1] + pill[3] / 2 - 96, 192, 192)
        self.assertFalse(overlap(hit, dm), (c, rhd))
        # inside the content rect
        self.assertTrue(hit[0] >= content.x and hit[0] + hit[2] <= content.x + content.width)


if __name__ == "__main__":
  unittest.main()
