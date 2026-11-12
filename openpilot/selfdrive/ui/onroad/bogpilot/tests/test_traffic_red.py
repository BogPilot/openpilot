"""Traffic Mode red: the border and the path use TRAFFIC_RED only while engaged with longitudinal and Traffic Mode on.

0.9.7 reference (04d560f3): ui.cc STATUS_TRAFFIC_MODE_ENABLED = traffic_mode_enabled and enabled, after the override
check; setPathEdgeColors paints the status colour. The production composer and model-renderer methods are used.
"""
import unittest
from types import SimpleNamespace

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.selfdrive.ui.onroad.bogpilot import hud_compose as HC
from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_model as BM
from openpilot.selfdrive.ui.onroad.bogpilot.style import TRAFFIC_RED, TRAFFIC_PATH_GRADIENT

GREEN = rl.Color(0x16, 0x7F, 0x40, 0xFF)


def composer(lkas=False, **frame):
  c = HC.HudComposer.__new__(HC.HudComposer)
  c.alert = SimpleNamespace(hud_state=lambda: SimpleNamespace(lkas_fault=lkas))
  c.disabled = set()
  f = dict(traffic_mode=True, engaged=True, longitudinal=True, full_alert=False, alert=None)
  f.update(frame)
  c.frame = SimpleNamespace(**f)
  return c


def same(a, b):
  return (a.r, a.g, a.b, a.a) == (b.r, b.g, b.b, b.a)


class TestTrafficRed(unittest.TestCase):
  def setUp(self):
    self._status = ui_state.status
    ui_state.status = UIStatus.ENGAGED

  def tearDown(self):
    ui_state.status = self._status

  def test_red_only_when_engaged_longitudinal_and_traffic_on(self):
    self.assertTrue(composer().traffic_red())
    self.assertFalse(composer(traffic_mode=False).traffic_red())
    self.assertFalse(composer(traffic_mode=None).traffic_red())           # unknown / stale topic
    self.assertFalse(composer(engaged=False).traffic_red())
    self.assertFalse(composer(longitudinal=False).traffic_red())
    c = composer(); c.frame = None                                         # RedesignUI off: no frame
    self.assertFalse(c.traffic_red())

  def test_override_and_disengaged_status_keep_their_colour(self):
    for status in (UIStatus.OVERRIDE, UIStatus.DISENGAGED):
      ui_state.status = status
      self.assertFalse(composer().traffic_red(), status)

  def test_border_colour_priority(self):
    self.assertTrue(same(composer().border_color(GREEN), TRAFFIC_RED))
    self.assertTrue(same(composer(traffic_mode=False).border_color(GREEN), GREEN))
    flash = composer(lkas=True).border_color(GREEN)                        # LKAS-fault flash still wins
    self.assertFalse(same(flash, GREEN))
    self.assertFalse(same(flash, TRAFFIC_RED))

  def test_red_is_the_daily_traffic_red(self):
    self.assertEqual((TRAFFIC_RED.r, TRAFFIC_RED.g, TRAFFIC_RED.b, TRAFFIC_RED.a), (201, 34, 49, 255))

  def test_path_gradient_is_prebuilt_red_with_the_stock_alpha_shape(self):
    g = TRAFFIC_PATH_GRADIENT
    self.assertEqual([(c.r, c.g, c.b) for c in g.colors], [(201, 34, 49)] * 3)
    self.assertEqual([c.a for c in g.colors], [102, 89, 0])
    self.assertEqual((g.start, g.end, g.stops), ((0.0, 1.0), (0.0, 0.0), [0.0, 0.5, 1.0]))


class FakeFilter:
  def __init__(self):
    self.updates = []

  def update(self, v):
    self.updates.append(v)


class TestPathColour(unittest.TestCase):
  def renderer(self, red, experimental=False, points=True):
    r = BM.BogPilotModelRenderer.__new__(BM.BogPilotModelRenderer)
    r.bp_traffic_red = red
    r._experimental_mode = experimental
    r._longitudinal_control = True
    r._blend_filter = FakeFilter()
    r._rect = rl.Rectangle(0, 0, 100, 100)
    r._path = SimpleNamespace(projected_points=SimpleNamespace(size=3 if points else 0))
    return r

  def run_path(self, r):
    calls, stock = [], []
    sm = {"longitudinalPlan": SimpleNamespace(allowThrottle=True)}
    orig_draw, orig_super = BM.draw_polygon, BM.ModelRenderer._draw_path
    BM.draw_polygon = lambda rect, pts, color=None, gradient=None: calls.append(gradient)
    BM.ModelRenderer._draw_path = lambda self, s: stock.append(1)
    try:
      r._draw_path(sm)
    finally:
      BM.draw_polygon, BM.ModelRenderer._draw_path = orig_draw, orig_super
    return calls, stock

  def test_traffic_red_draws_the_cached_gradient_and_not_the_stock_path(self):
    r = self.renderer(True)
    calls, stock = self.run_path(r)
    self.assertEqual(len(calls), 1)
    self.assertIs(calls[0], TRAFFIC_PATH_GRADIENT)       # same object every frame: no per-frame allocation
    self.assertEqual(stock, [])
    self.assertEqual(r._blend_filter.updates, [1])           # throttle blend filter keeps tracking

  def test_otherwise_stock_path(self):
    for r in (self.renderer(False), self.renderer(True, experimental=True), self.renderer(True, points=False)):
      calls, stock = self.run_path(r)
      self.assertEqual((calls, stock), ([], [1]))

  def test_default_flag_is_off(self):
    self.assertFalse(BM.BogPilotModelRenderer.bp_traffic_red)


class TestWiring(unittest.TestCase):
  def test_compose_sets_the_flag_before_the_model_draws_and_the_view_uses_border_color(self):
    from pathlib import Path
    ui = Path(HC.__file__).parents[2]
    hc = Path(HC.__file__).read_text()
    self.assertLess(hc.index("self.model.bp_traffic_red = self.traffic_red()"), hc.index("      self.model.render(rect)"))
    view = (ui / "onroad/augmented_road_view.py").read_text()
    self.assertIn("self._hud_compose.border_color(BORDER_COLORS.get(", view)
    self.assertNotIn("border_color = self._hud_compose.border_override() or", view)

  def test_comma_lead_box_is_untouched(self):
    from pathlib import Path
    src = Path(BM.__file__).read_text()
    self.assertNotIn("TRAFFIC_RED", src.split("class BlindspotOverlay")[1].split("class BogPilotModelRenderer")[0])


if __name__ == "__main__":
  unittest.main()
