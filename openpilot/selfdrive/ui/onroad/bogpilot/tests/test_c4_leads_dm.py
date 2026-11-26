"""comma 4 lead boxes (scaled box, gauge clearance, speed label placement, data from the lock-on core, painter) and
the driver-monitor icon move. Headless."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot import c4_paint as C4P
from openpilot.selfdrive.ui.onroad.bogpilot import c4_leads as CL


class TestLeadBox(unittest.TestCase):
  def test_scaled_from_wide_box(self):
    x0, y0, x1, y1 = C4.lead_box(238.0, 134.0, 40.0)
    self.assertAlmostEqual(x1 - x0, 29.5015, places=3)       # design primary box width at 40 m
    self.assertAlmostEqual((y1 - y0) / (x1 - x0), 0.86)
    self.assertAlmostEqual((x0 + x1) / 2, 238.0)

  def test_clamped_inside_view(self):
    x0, _, x1, y1 = C4.lead_box(470.0, 260.0, 10.0)
    self.assertLessEqual(x1, C4.VIEW_W - C4.LEAD_EDGE + 1e-9)
    self.assertLessEqual(y1, C4.SCREEN_H - C4.LEAD_EDGE + 1e-9)

  def test_keeps_clear_of_gauge(self):
    g = C4.gauge_rect()
    box = C4.lead_box(20.0, 150.0, 24.0, gauge=g)
    self.assertGreaterEqual(box[0], g[2] + 1 - 1e-9)
    free = C4.lead_box(20.0, 150.0, 24.0)
    self.assertLess(free[0], g[2])
    high = C4.lead_box(20.0, 60.0, 24.0, gauge=g)            # above the gauge: not pushed
    self.assertEqual(high, C4.lead_box(20.0, 60.0, 24.0))


class TestSpeedLabel(unittest.TestCase):
  box = (223.0, 112.0, 253.0, 137.0)

  def test_above_centred(self):
    r, where = C4.speed_label_rect(self.box, 46, 28)
    self.assertEqual(where, "above")
    self.assertEqual(r, (215.0, 81.0, 261.0, 109.0))

  def test_slides_right_past_keepouts(self):
    box = (49.0, 131.0, 83.0, 160.0)
    r, _ = C4.speed_label_rect(box, 38, 23, keepouts=[C4.gauge_rect()])
    self.assertGreaterEqual(r[0], C4.gauge_rect()[2] + C4.LABEL_SLIDE_MARGIN)

  def test_below_in_alert_zone(self):
    r, where = C4.speed_label_rect(self.box, 46, 28, alert_zone=C4.ALERT_TEXT_ZONE)
    self.assertEqual(where, "below")
    self.assertEqual((r[1], r[3]), (140.0, 168.0))

  def test_beside_during_user_prompt(self):
    r, where = C4.speed_label_rect(self.box, 46, 28, alert_zone=C4.ALERT_TEXT_ZONE, side_mode=True, side="primary")
    self.assertEqual(where, "beside")
    self.assertEqual(r[0], 256.0)
    self.assertGreaterEqual(r[1], C4.ALERT_TEXT_ZONE[3] + 2)
    left, _ = C4.speed_label_rect((60.0, 120.0, 90.0, 146.0), 38, 23, alert_zone=C4.ALERT_TEXT_ZONE, side_mode=True,
                                  side="left")
    self.assertEqual(left[2], 57.0)

  def test_label_size(self):
    self.assertEqual(C4.label_size(30, 24), (30 + 2 * 8, 28))
    self.assertEqual(C4.label_size(20, 20), (20 + 2 * 6, 23))


class TestTurnIntentKeepout(unittest.TestCase):
  def test_bbox(self):
    self.assertEqual(tuple(round(v, 6) for v in C4.turn_intent_bbox(0.0)), C4.turn_intent_rect())
    b = C4.turn_intent_bbox(30.0)
    self.assertGreater(b[2], C4.turn_intent_rect()[2])        # rotated clockwise: swings right and down
    r, _ = C4.speed_label_rect((47.5, 132.2, 80.1, 160.2), 37, 23, keepouts=[C4.turn_intent_bbox(0.0)],
                               alert_zone=C4.ALERT_TEXT_ZONE)
    self.assertGreaterEqual(r[0], C4.turn_intent_rect()[2] + C4.LABEL_SLIDE_MARGIN)


class FakeLock:
  def __init__(self, target, adjacent):
    self._t, self.adjacent, self.kw = target, adjacent, None

  def update(self, renderer, sm, started_frame, **kw):
    self.kw = kw
    return self._t


def R(x, y, w, h):
  return NS(x=x, y=y, width=w, height=h)


class TestComma4Leads(unittest.TestCase):
  def test_engagement_not_a_condition_and_order(self):
    adj = [NS(side=0, box=R(50, 130, 30, 26), d_rel=24.0, speed="68"), NS(side=1, box=R(357, 120, 31, 27), d_rel=31.0, speed="")]
    t = NS(box=R(223, 112, 30, 25), d_rel=40.0, v_ego=29.0)
    lock = FakeLock(t, adj)
    leads = CL.Comma4Leads(lock=lock)
    lead_one = NS(present=True, dRel=40.0, vLead=27.7, vRel=-1.3, radar=True)
    sm = {"radarState": NS(leadOne=lead_one), "carState": NS(vEgo=29.0)}
    out, v = leads.update(None, sm, 0, longitudinal=True, adjacent=True, hide_marker=False, metric=False, gauge=None)
    self.assertNotIn("engaged", lock.kw)          # the core's gate decides; engagement is not a condition there
    self.assertEqual(lock.kw["enabled"], True)
    self.assertEqual(lock.kw["local"], True)
    self.assertEqual([d.key for d in out], ["left", "right", "primary"])
    self.assertEqual(out[2].speed, "62")
    self.assertEqual(out[2].accent, "amber")
    self.assertEqual(out[1].speed, "")
    self.assertEqual(v, 29.0)

  def test_core_owns_the_engagement_gate(self):
    import inspect
    from openpilot.selfdrive.ui.onroad.bogpilot.lead_lockon import LeadLockOn
    self.assertIsNone(inspect.signature(LeadLockOn.update).parameters["engaged"].default)

  def test_style_box_uses_gauge(self):
    st = CL.Comma4LeadStyle()
    with mock.patch.object(CL.Comma4LeadStyle, "rect", staticmethod(lambda x, y, w, h: (x, y, x + w, y + h))):
      st.gauge = C4.gauge_rect()
      b = st.lead_lock_box(20.0, 150.0, 24.0, C4.VIEW_W, C4.SCREEN_H, 0.0)
    self.assertGreaterEqual(b[0], C4.gauge_rect()[2] + 1 - 1e-9)


class TestPaintLeads(unittest.TestCase):
  def test_boxes_and_labels(self):
    calls = []
    rec = lambda name: (lambda *a, **k: calls.append((name, a)))
    leads = [CL.LeadDraw("left", (50.0, 130.0, 84.0, 159.0), 24.0, "68", None),
             CL.LeadDraw("primary", (223.0, 112.0, 253.0, 137.0), 40.0, "62", "amber")]
    with mock.patch.object(C4P, "paint_lead_box", rec("box")), mock.patch.object(C4P, "paint_speed_label", rec("label")), \
         mock.patch.object(C4P, "label_text_width", lambda t, px: 10.0 * len(t)), \
         mock.patch.object(CL.Comma4LeadStyle, "lead_distance_color", staticmethod(lambda d, a, v: NS(r=150, g=150, b=155, a=200))), \
         mock.patch.object(C4P, "C", lambda *c: c):
      out = C4P.paint_leads(leads, 29.0)
    self.assertEqual([c[0] for c in calls], ["box", "label", "box", "label"])
    self.assertIn("lead box (adjacent left)", out)
    self.assertIn("lead speed label", out)
    self.assertEqual(calls[3][1][5], "amber")
    self.assertIsNone(calls[1][1][5])
    with mock.patch.object(C4P, "paint_lead_box", rec("box")), mock.patch.object(C4P, "paint_speed_label", rec("label")), \
         mock.patch.object(C4P, "label_text_width", lambda t, px: 10.0 * len(t)), \
         mock.patch.object(CL.Comma4LeadStyle, "lead_distance_color", staticmethod(lambda d, a, v: NS(r=1, g=1, b=1, a=1))), \
         mock.patch.object(C4P, "C", lambda *c: c):
      out = C4P.paint_leads(leads, 29.0, alert_zone=C4.ALERT_TEXT_ZONE, side_mode=True)
    self.assertIn("lead speed label (beside)", out)


class TestDriverMonitorIcon(unittest.TestCase):
  def test_position_centred_on_spot(self):
    self.assertEqual(C4.dm_position(), (412.0, 6.0))

  def test_alert_hides_stock_rule_kept(self):
    from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_hud as H
    hud = NS()
    scr = NS(x=0, y=0)
    self.assertEqual(H.BogPilotMiciHudRenderer.bp_c4_dm(hud, True, False, scr), (True, 412.0, 6.0))
    self.assertEqual(H.BogPilotMiciHudRenderer.bp_c4_dm(hud, True, True, scr)[0], False)
    self.assertEqual(H.BogPilotMiciHudRenderer.bp_c4_dm(hud, False, False, scr)[0], False)   # stock: hidden when disengaged


class TestLeadsUnderAlerts(unittest.TestCase):
  """comma 4: a stock alert on screen hides the lead / adjacent-lead boxes and their speeds; no alert draws them
  through the shared lock-on gate; the 3X renderer has no comma 4 lead path."""

  def fake(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.c4_leads import LeadDraw
    calls = []
    leads = [LeadDraw("left", (50.0, 130.0, 84.0, 159.0), 24.0, "68", None),
             LeadDraw("primary", (223.0, 112.0, 253.0, 137.0), 40.0, "62", None)]

    class Leads:
      def update(self, *a, **k):
        calls.append(("update", k))
        return leads, 29.0
    hud = NS(bp_c4=True, bp_c4_lead_layout={"stale": 1}, _bp_c4_leads=Leads(),
             _bp_c4_lead_policy=NS(get=lambda: {"adjacent_leads": True, "hide_lead_marker": False}),
             bp_c4_gauge=None,
             _turn_intent=NS(_turn_intent_alpha_filter=NS(x=0.0), _turn_intent_rotation_filter=NS(x=0.0)),
             _bp_c4_alert=lambda shown: (C4.ALERT_TEXT_ZONE if shown else None, False))
    return hud, calls

  def run_leads(self, alert_shown):
    from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_hud as H
    hud, calls = self.fake()
    painted = []
    with mock.patch.object(C4P, "paint_leads", lambda leads, *a, **k: painted.append(leads) or {"lead box (primary)": (0, 0, 1, 1)}):
      H.BogPilotMiciHudRenderer.bp_c4_render_leads(hud, NS(_rect=NS(x=0.0, y=0.0)), alert_shown)
    return hud, calls, painted

  def test_alert_hides_lead_and_adjacent_boxes(self):
    hud, calls, painted = self.run_leads(True)
    self.assertEqual((calls, painted), ([], []))
    self.assertEqual(hud.bp_c4_lead_layout, {})

  def test_no_alert_draws_them(self):
    hud, calls, painted = self.run_leads(False)
    self.assertEqual(len(calls), 1)
    self.assertEqual([d.key for d in painted[0]], ["left", "primary"])
    self.assertIn("lead box (primary)", hud.bp_c4_lead_layout)

  def test_3x_renderer_has_no_comma4_lead_path(self):
    from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_hud as H
    self.assertFalse(hasattr(H.BogPilotHudRenderer, "bp_c4_render_leads"))
    self.assertFalse(hasattr(H.BogPilotHudRenderer, "bp_c4_dm"))


if __name__ == "__main__":
  unittest.main()
