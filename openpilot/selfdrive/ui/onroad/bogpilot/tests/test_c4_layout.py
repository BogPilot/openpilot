"""comma 4 layout: device gate, element positions, lane-change arrow and visibility rules, the shared three-bar gauge in the comma 4 spot."""
import unittest
from types import SimpleNamespace as NS

from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3


def overlap(a, b):
  return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class FakeSM:
  def __init__(self, device_type=None):
    self.seen = {"deviceState": device_type is not None}
    self._ds = NS(deviceType=device_type)

  def __getitem__(self, k):
    return self._ds


class TestGate(unittest.TestCase):
  def test_only_comma4_device_type(self):
    self.assertTrue(C4.is_comma4("mici"))
    for d in ("tici", "tizi", "pc", "unknown", "", None, 3):
      self.assertFalse(C4.is_comma4(d), d)

  def test_device_state_wins_over_hardware(self):
    self.assertTrue(C4.comma4_device(FakeSM("mici"), fallback_device_type="pc"))
    self.assertFalse(C4.comma4_device(FakeSM("tizi"), fallback_device_type="mici"))

  def test_hardware_fallback_before_device_state(self):
    self.assertTrue(C4.comma4_device(FakeSM(None), fallback_device_type="mici"))
    self.assertFalse(C4.comma4_device(FakeSM(None), fallback_device_type="tizi"))

  def test_bad_submaster_fails_to_hardware(self):
    self.assertFalse(C4.comma4_device(object(), fallback_device_type="tici"))


class TestPositions(unittest.TestCase):
  def test_screen(self):
    self.assertEqual((C4.SCREEN_W, C4.SCREEN_H, C4.VIEW_W), (536, 240, 476))

  def test_personality_button(self):
    self.assertEqual(C4.personality_rect(), (8, 192, 48, 232))
    self.assertEqual(C4.personality_tap_rect(), (4, 188, 52, 236))

  def test_gauge_hard_left_above_button(self):
    g = C4.gauge_rect()
    self.assertEqual(g, (8, 112, 48, 188))
    self.assertEqual(g[0], C4.personality_rect()[0])
    gap = C4.personality_rect()[1] - g[3]
    self.assertTrue(0 < gap <= 6, gap)
    bars = C4.gauge_bar_rects()
    self.assertEqual([b[2] - b[0] for b in bars], [12, 12, 12])
    self.assertEqual([bars[1][0] - bars[0][2], bars[2][0] - bars[1][2]], [2, 2])

  def test_record_button_side_panel(self):
    self.assertEqual(C4.record_rect(), (488, 192, 528, 232))
    self.assertGreaterEqual(C4.record_rect()[0], C4.VIEW_W)
    rr, w, dot = C4.record_ring()
    self.assertAlmostEqual(rr, 19.354838, places=5)
    self.assertAlmostEqual(w, 0.967741, places=5)
    self.assertAlmostEqual(dot, 7.6, places=6)

  def test_arrows_under_pill_and_dm(self):
    left, right = C4.arrow_core_rect(-1), C4.arrow_core_rect(1)
    self.assertEqual(left, (8, 68, 54, 107))
    self.assertEqual(right, (419.0, 68, 465.0, 107))
    self.assertGreater(left[1], C4.PILL[3])
    self.assertGreater(right[1], C4.DM_ICON[3])
    self.assertAlmostEqual((right[0] + right[2]) / 2, (C4.DM_ICON[0] + C4.DM_ICON[2]) / 2)
    for r in (left, right):
      self.assertFalse(overlap(r, C4.gauge_rect()))

  def test_no_overlaps(self):
    rects = {"pill": C4.PILL, "dm": C4.DM_ICON, "gauge": C4.gauge_rect(), "button": C4.personality_rect(),
             "rec": C4.record_rect(), "arrowL": C4.arrow_core_rect(-1), "arrowR": C4.arrow_core_rect(1)}
    names = list(rects)
    for i, a in enumerate(names):
      for b in names[i + 1:]:
        self.assertFalse(overlap(rects[a], rects[b]), (a, b))
    for k, r in rects.items():
      if k != "rec":
        self.assertLessEqual(r[2], C4.VIEW_W, k)


class TestLaneChangeArrow(unittest.TestCase):
  def test_events_only(self):
    a = C4.LaneChangeArrow()
    self.assertEqual(a.update([]), 0)
    self.assertEqual(a.update(["preLaneChangeLeft"]), -1)
    self.assertEqual(a.update(["laneChange"]), -1)
    self.assertEqual(a.update([]), 0)
    self.assertEqual(a.update(["preLaneChangeRight"]), 1)
    self.assertEqual(a.update(["laneChange"]), 1)

  def test_lane_change_without_pre_uses_model_direction(self):
    a = C4.LaneChangeArrow()
    self.assertEqual(a.update(["laneChange"], "right"), 1)
    a = C4.LaneChangeArrow()
    self.assertEqual(a.update(["laneChange"], "none"), 0)

  def test_blinker_alone_shows_nothing(self):
    # the arrow takes event names only; a blinker never produces one of these events by itself
    a = C4.LaneChangeArrow()
    self.assertEqual(a.update(["steerSaturated", "driverDistracted2"]), 0)


class TestVisibility(unittest.TestCase):
  def test_no_alert_all_on(self):
    v = C4.visibility(False, False)
    self.assertTrue(v.pill and v.gauge and v.dm and v.leads)

  def test_take_control_hides_constant(self):
    v = C4.visibility(True, True)
    for k in ("pill", "gauge", "dm", "leads"):
      self.assertEqual(getattr(v, k), k not in C4.TAKE_CONTROL_HIDES, k)
    self.assertTrue(v.take_control)

  def test_alerts_hide_the_leads_too(self):
    self.assertFalse(C4.visibility(True, True).leads)
    self.assertFalse(C4.visibility(True, False).leads)
    self.assertTrue(C4.visibility(False, False).leads)
    self.assertEqual(C4.TAKE_CONTROL_HIDES, C4.OTHER_ALERT_HIDES)

  def test_other_alert(self):
    v = C4.visibility(True, False)
    self.assertFalse(v.pill or v.gauge or v.dm or v.leads)


class TestSharedGauge(unittest.TestCase):
  """The comma 4 gauge is the shared pedal_gauge3 gauge (state, colours, painter) in the comma 4 spot."""

  def test_palette_is_the_t4_colours(self):
    P = G3.GAUGE3_PALETTE
    self.assertEqual((P[(G3.BRAKE, G3.DRIVER)], P[(G3.BRAKE, G3.OP)]), ((0xC6, 0x28, 0x28), (0xB5, 0x83, 0x8D)))
    self.assertEqual((P[(G3.REGEN, G3.DRIVER)], P[(G3.REGEN, G3.OP)]), ((0x2E, 0x8B, 0xFF), (0x8F, 0xB3, 0xE0)))
    self.assertEqual((P[(G3.ACCEL, G3.DRIVER)], P[(G3.ACCEL, G3.OP)]), ((0x3D, 0xDC, 0x97), (0x5E, 0x8A, 0x72)))

  def test_shared_bar_split_matches_the_comma4_bars(self):
    bars = [(x, y, x + w, y + h) for x, y, w, h in G3.bar_rects(C4.gauge_xywh())]
    for a, b in zip(bars, C4.gauge_bar_rects(), strict=True):
      for u, v in zip(a, b, strict=True):
        self.assertAlmostEqual(u, v)

  def test_regen_full_scale(self):
    self.assertEqual(G3.regen_full_scale_kw("TESLA_AP1_MODELS"), -55.0)
    self.assertAlmostEqual(G3.gauge_state(0, -27.5, 0, False).regen, 0.5)


if __name__ == "__main__":
  unittest.main()
