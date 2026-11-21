"""comma 4 steering arc (stock torque-bar geometry, raised, BogPilot colours) and the status / BSM border."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

import pyray as rl

from openpilot.selfdrive.ui.onroad.bogpilot import c4_arc as A
from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot import steering_arc as ARC

VIEW = rl.Rectangle(0, 0, C4.VIEW_W, C4.SCREEN_H)


def state(**kw):
  s = ARC.ArcState()
  for k, v in kw.items():
    setattr(s, k, v)
  return s


class TestGeometry(unittest.TestCase):
  def test_stock_curve_raised(self):
    g = A.geometry(state(torque=0.0), VIEW)
    self.assertAlmostEqual(g["cx"], VIEW.x + VIEW.width / 2 + 8)
    self.assertAlmostEqual(g["offset"], 22 + C4.ARC_RAISE_PX)
    self.assertAlmostEqual(g["cy"], VIEW.y + VIEW.height + 1200 - 22 - C4.ARC_RAISE_PX)
    self.assertAlmostEqual(g["thickness"], 14)
    self.assertEqual(g["bg"], (-90 - 12.7 / 2, -90 + 12.7 / 2))

  def test_full_torque_matches_stock_offsets(self):
    g = A.geometry(state(torque=-1.0), VIEW, raise_px=0)
    self.assertAlmostEqual(g["offset"], 26)
    self.assertAlmostEqual(g["thickness"], 56)
    self.assertAlmostEqual(g["fill"][1], -90 - 12.7 / 2)

  def test_band_sits_above_the_bottom(self):
    x0, y0, x1, y1 = A.band_bbox(A.geometry(state(), VIEW))
    self.assertLess(y1, VIEW.y + VIEW.height - 20)
    self.assertGreater(x0, VIEW.x)
    self.assertLess(x1, VIEW.x + VIEW.width)


class TestColours(unittest.TestCase):
  def test_driver_source_uses_angle_colours(self):
    c0, c1 = A.fill_colours(state(human=True, angle=200.0, alpha=1.0, torque=0.6))
    self.assertEqual(c0, ARC.human_angle_color(200.0) + (0.95,))
    self.assertEqual(c0, c1)

  def test_disengaged_is_faint_white(self):
    c0, _ = A.fill_colours(state(engaged_colors=False, alpha=0.55, torque=0.3))
    self.assertEqual(c0[:3], ARC.WHITE)
    self.assertAlmostEqual(c0[3], 0.35 * 0.55)
    self.assertAlmostEqual(A.bg_alpha(state(engaged_colors=False, alpha=0.55)), 0.15 * 0.55)

  def test_engaged_high_torque_goes_yellow_orange(self):
    c0, c1 = A.fill_colours(state(engaged_colors=True, alpha=1.0, torque=1.0))
    self.assertEqual(tuple(round(v) for v in c0[:3]), ARC.YELLOW)
    self.assertEqual(tuple(round(v) for v in c1[:3]), ARC.ORANGE)


class TestBorder(unittest.TestCase):
  def test_colours(self):
    self.assertEqual(A.border_colour("engaged", False), (0x16, 0x7F, 0x40, 255))
    self.assertEqual(A.border_colour("override", False), (0x89, 0x92, 0x8D, 255))
    self.assertIsNone(A.border_colour("disengaged", False))
    self.assertEqual(A.border_colour("engaged", True), A.TRAFFIC_RED)
    self.assertEqual(A.border_colour("override", True), A.BORDER_OVERRIDE)

  def test_bsm_rule(self):
    self.assertEqual(A.bsm_halves(True, False, True, True, False, False), (True, False))
    self.assertIsNone(A.bsm_halves(True, False, False, True, False, False))   # no BSM on this car
    self.assertIsNone(A.bsm_halves(True, False, True, False, False, False))   # toggle off
    self.assertIsNone(A.bsm_halves(True, True, True, True, True, False))      # full-screen alert
    self.assertIsNone(A.bsm_halves(False, True, True, True, False, True))     # critical alert
    self.assertIsNone(A.bsm_halves(False, False, True, True, False, False))

  def paint(self, colour, bsm):
    calls = []
    with mock.patch("openpilot.selfdrive.ui.onroad.bogpilot.style.stroke_rounded",
                    lambda r, rad, w, c: calls.append(("stroke", r, rad, w, (c.r, c.g, c.b, c.a)))), \
         mock.patch.object(rl, "begin_scissor_mode", lambda *a: calls.append(("scissor", a))), \
         mock.patch.object(rl, "end_scissor_mode", lambda: calls.append(("end",))), \
         mock.patch.object(rl, "draw_rectangle_rec", lambda r, c: calls.append(("bar", (r.x, r.y, r.width, r.height), (c.r, c.g, c.b, c.a)))):
      out = A.paint_border(VIEW, colour, bsm)
    return out, calls

  def test_thin_green_border_inside_the_view(self):
    out, calls = self.paint(A.BORDER_ENGAGED, None)
    s = [c for c in calls if c[0] == "stroke"]
    self.assertEqual(len(s), 1)
    _, r, rad, w, col = s[0]
    self.assertEqual(w, C4.BORDER_W)
    self.assertEqual(col, A.BORDER_ENGAGED)
    self.assertAlmostEqual(r.x, VIEW.x + w / 2)
    self.assertAlmostEqual(r.x + r.width, VIEW.x + VIEW.width - w / 2)
    self.assertFalse([c for c in calls if c[0] == "bar"])

  def test_left_bsm_half_red_and_edge_bar(self):
    out, calls = self.paint(A.BORDER_ENGAGED, (True, False))
    strokes = [c for c in calls if c[0] == "stroke"]
    self.assertEqual([c[4] for c in strokes], [A.BORDER_ENGAGED, A.BSM_RED])
    sc = [c for c in calls if c[0] == "scissor"]
    self.assertEqual(sc[0][1], (int(VIEW.x), int(VIEW.y), int(VIEW.width / 2), int(VIEW.height)))
    self.assertEqual(sc[-1][1], (int(VIEW.x), int(VIEW.y), int(VIEW.width), int(VIEW.height)))   # view clip restored
    bars = [c for c in calls if c[0] == "bar"]
    self.assertEqual(bars, [("bar", (VIEW.x, VIEW.y, 5, VIEW.height), A.BSM_EDGE_BAR)])
    order = [c[0] if c[0] != "stroke" else c[4] for c in calls if c[0] in ("bar", "stroke")]
    self.assertEqual(order, [A.BORDER_ENGAGED, "bar", A.BSM_RED])   # the edge bar sits under the red half
    self.assertIn("BSM border (left half)", out)

  def test_bsm_shown_when_disengaged(self):
    out, calls = self.paint(None, (False, True))
    strokes = [c for c in calls if c[0] == "stroke"]
    self.assertEqual([c[4] for c in strokes], [A.BSM_RED])
    bars = [c for c in calls if c[0] == "bar"]
    self.assertEqual(bars[0][1][0], VIEW.x + VIEW.width - 5)


class TestMiciHook(unittest.TestCase):
  def setUp(self):
    from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_hud as H
    self.H = H

  def fake(self, ok=True):
    calls = []
    ns = NS(bp_c4_arc_ok=ok, _bp_c4_arc=ARC.ArcState(), bp_c4_layout={}, _bp_c4_arc_failed=False,
            _torque_bar=NS(render=lambda r: calls.append("stock bar")),
            _draw_model_source=lambda r: calls.append("model source"))
    return ns, calls

  def test_bogpilot_arc_replaces_torque_bar(self):
    ns, calls = self.fake()
    with mock.patch.object(A, "paint", lambda s, r: calls.append("arc") or {"steering arc": (0, 0, 1, 1)}):
      self.H.BogPilotMiciHudRenderer._bp_render_c4_stock(ns, VIEW)
    self.assertEqual(calls, ["arc", "model source"])
    self.assertEqual(ns.bp_c4_layout["arc"], "bogpilot")

  def test_paint_failure_falls_back_to_stock(self):
    ns, calls = self.fake()
    def boom(s, r):
      raise ValueError("x")
    with mock.patch.object(A, "paint", boom):
      self.H.BogPilotMiciHudRenderer._bp_render_c4_stock(ns, VIEW)
    self.assertEqual(calls, ["stock bar", "model source"])
    self.assertTrue(ns._bp_c4_arc_failed)
    self.assertEqual(ns.bp_c4_layout["arc"], "stock")

  def test_no_inputs_keeps_stock(self):
    ns, calls = self.fake(ok=False)
    self.H.BogPilotMiciHudRenderer._bp_render_c4_stock(ns, VIEW)
    self.assertEqual(calls, ["stock bar", "model source"])


if __name__ == "__main__":
  unittest.main()


class TestCommandedAngleOnC4(unittest.TestCase):
  """The comma 4 arc is the same ArcState as the 3X: an engaged legacy-Tesla frame with roll fills from the command."""

  def test_engaged_fill_follows_command_not_roll(self):
    cp = NS(brand="tesla_ap1", wheelbase=2.959, centerToFront=1.33, steerRatio=15.4, rotationalInertiaPerMass=2.0,
            tireStiffnessFrontPerMass=15.0, tireStiffnessRearPerMass=20.0, maxLateralAccel=3.2)
    fn = ARC.make_commanded_curvature_fn(cp)
    ctrl = NS(curvature=-0.0001, desiredCurvature=-0.0001, lateralControlState=NS(which=lambda: "angleState"))
    car = NS(vEgo=13.0, steeringAngleDeg=0.2)
    cc = NS(latActive=True, actuators=NS(steeringAngleDeg=0.3))
    co = NS(actuatorsOutput=NS(torque=0.0, steeringAngleDeg=0.3))
    vp = NS(roll=0.052)
    fills = {}
    for name, f in (("before", None), ("after", fn)):
      st = ARC.ArcState()
      for _ in range(80):
        st.update(ARC.inputs_from_messages(ctrl, car, cc, co, vp, 3.2, "engaged", False, f))
      fills[name] = A.geometry(st, VIEW)["fill"]
    span = lambda f: f[1] - f[0]
    self.assertLess(span(fills["before"]), -0.3)           # roll pulled the old fill left
    self.assertLess(abs(span(fills["after"])), 0.05)       # now ~ the straight wheel
