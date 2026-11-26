"""Confidence ball on the big (C3X) onroad UI: logic, settings, composer tail, view ordering, input and pixels.

Pure tests (no pyray): the 0.9.7 / stock math, colours and geometry, the always-shown rule, the disengaged / override
colour rule (never the engaged palette), defaults and settings parsing, the HudComposer deferred tail (exactly one alert
per frame, alert last, even when render() raises early) and the keepout hook.
View tests (need pyray importable, no window): AugmentedRoadView._render with recording fakes: draw-call order against
the pre-change order, full-screen alert keeps the plain order with no ball, scissor pairs always balanced, taps never
reach the ball.
Native tests (RAYLIB_BACKEND=headless): the real Appearance rows write the store and the real renderer reads it, draw
calls land where the geometry says, a failure disables only the ball, and the content area is pixel-identical to the
pre-change order with the ball off.
"""
from __future__ import annotations

import math
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from openpilot.selfdrive.ui.onroad.bogpilot import confidence_ball_logic as L
from openpilot.selfdrive.ui.onroad.bogpilot.tests import test_hud_compose as H

STATUSES = ("DISENGAGED", "ENGAGED", "OVERRIDE")
NOT_ENGAGED = ("DISENGAGED", "OVERRIDE")
SWEEP = [i / 20.0 for i in range(-10, 31)]   # -0.5 .. 1.5, wider than the filter can ever reach


# ------------------------------------------------------------------------------------------------------------ logic
class TestMath(unittest.TestCase):
  def test_confidence_formula_and_empty_lists(self):
    self.assertAlmostEqual(L.model_confidence([0.1, 0.3], [0.2, 0.05]), (1 - 0.3) * (1 - 0.2))
    self.assertEqual(L.model_confidence([0.0], [0.0]), 1.0)
    self.assertEqual(L.model_confidence([], [0.0]), 0.0)     # no data reads as 0 (Python `max(x or [1])`, stock / 0.9.7)
    self.assertEqual(L.model_confidence(None, None), 0.0)
    self.assertEqual(L.model_confidence([1.0], [0.0]), 0.0)

  def test_engaged_colors_match_stock_and_097(self):
    self.assertEqual(L.ball_colors("ENGAGED", 0.51), ((0, 255, 204, 255), (0, 255, 38, 255)))
    self.assertEqual(L.ball_colors("ENGAGED", 0.5), ((255, 200, 0, 255), (255, 115, 0, 255)))   # strictly above 0.5
    self.assertEqual(L.ball_colors("ENGAGED", 0.21), ((255, 200, 0, 255), (255, 115, 0, 255)))
    self.assertEqual(L.ball_colors("ENGAGED", 0.2), ((255, 0, 21, 255), (255, 0, 89, 255)))
    self.assertEqual(L.ball_colors("ENGAGED", -0.3), ((255, 0, 21, 255), (255, 0, 89, 255)))

  def test_override_uses_the_stock_muted_ball_and_disengaged_the_slate_to_white_ball(self):
    # override: stock mici confidence_ball.py:68-70, 0.9.7 confidence_ball.h:120-121
    self.assertEqual(L.ball_colors("OVERRIDE", 0.9), ((255, 255, 255, 255), (82, 82, 82, 255)))
    # disengaged: slate grey at high confidence, white at low, shaded top to bottom by 82/255 (DIVERGENCES.md);
    # unknown statuses keep the stock dark ball
    self.assertEqual(L.ball_colors("DISENGAGED", 1.0), ((112, 128, 144, 255), (36, 41, 46, 255)))
    self.assertEqual(L.ball_colors("DISENGAGED", 0.0), ((255, 255, 255, 255), (82, 82, 82, 255)))
    self.assertEqual(L.ball_colors("LATERAL_ONLY", 0.9), ((50, 50, 50, 255), (13, 13, 13, 255)))
    # only ENGAGED counts as engaged (stock mici rule); anything unknown gets the dark ball
    self.assertTrue(L.engaged_status("ENGAGED"))
    for s in ("DISENGAGED", "OVERRIDE", "LATERAL_ONLY", "", "engaged"):
      self.assertFalse(L.engaged_status(s), s)
      self.assertNotIn(L.ball_colors(s, 0.9), L.ENGAGED_PALETTE, s)

  def test_geometry_matches_097(self):
    self.assertEqual((L.STRIP_WIDTH, L.RADIUS, L.MARGIN, L.RC, L.REREAD_S), (60, 27.0, 3.0, 0.5, 2.0))
    h = 1080.0
    self.assertEqual(L.ball_center_y(1.0, h), 30.0)                 # top: radius + margin
    self.assertEqual(L.ball_center_y(0.0, h), h - 30.0)             # bottom, still fully on screen
    self.assertEqual(L.ball_center_x(0, 2160, right=False), 30.0)   # left strip, centred on the border / camera line
    self.assertEqual(L.ball_center_x(0, 2160, right=True), 2130.0)
    self.assertEqual(L.strip_x(0, 2160, True), 2100)

  def test_scanlines_form_a_disc(self):
    rows = L.circle_scanlines()
    self.assertEqual(len(rows), 54)
    self.assertAlmostEqual(max(r[1] for r in rows), 27.0, delta=0.05)
    self.assertLess(rows[0][1], 12)
    self.assertEqual(L.lerp_color((0, 255, 204, 255), (0, 255, 38, 255), 0.0), (0, 255, 204, 255))
    self.assertEqual(L.lerp_color((0, 255, 204, 255), (0, 255, 38, 255), 1.0), (0, 255, 38, 255))


class TestAlwaysShown(unittest.TestCase):
  """Maintainer rule: the ball shows in every state while the toggle is on (stock / 0.9.7 slide it out when disengaged)."""

  def state(self):
    return L.ConfidenceBallState(lambda: True, lambda: False, lambda: 0.0, 0.05)

  def test_starts_on_screen_at_the_bottom(self):
    st = self.state()
    self.assertEqual(L.START, 0.0)
    self.assertEqual(st.filter.x, 0.0)
    self.assertLessEqual(L.ball_center_y(st.filter.x, 1080) + L.RADIUS, 1080)

  def test_drawn_in_every_status_and_never_slides_out(self):
    for status in STATUSES:
      st = self.state()
      for _ in range(200):
        self.assertTrue(st.update(True, status, [0.0], [0.0]), status)
      self.assertGreater(st.filter.x, 0.99, status)                 # height follows the model in every status
      for _ in range(200):
        st.update(True, status, [], [])                              # no model data: confidence 0
      self.assertGreaterEqual(st.filter.x, 0.0, status)              # bottom, never below the screen
      self.assertLess(st.filter.x, 0.01, status)

  def test_disengaged_case_follows_the_model_in_height_and_colour(self):
    st = self.state()
    for _ in range(200):
      self.assertTrue(st.update(True, "DISENGAGED", [0.05], [0.05]))
    x = st.filter.x
    self.assertAlmostEqual(x, 0.95 * 0.95, places=2)
    c = L.disengaged_color(x)
    self.assertEqual(L.ball_colors("DISENGAGED", x), (c, L.shade(c)))
    self.assertLess(L.ball_center_y(x, 1080), 140)                  # high: the height is shown, the colour is near slate
    self.assertTrue(all(abs(a - b) <= 15 for a, b in zip(c, L.SLATE, strict=True)), c)

  def test_not_started_or_toggle_off_is_not_drawn(self):
    self.assertFalse(self.state().update(False, "ENGAGED", [0.0], [0.0]))
    off = L.ConfidenceBallState(lambda: False, lambda: False, lambda: 0.0, 0.05)
    for status in STATUSES:
      self.assertFalse(off.update(True, status, [0.0], [0.0]))


class TestNeverEngagedPaletteWhenNotEngaged(unittest.TestCase):
  """Safety review condition: DISENGAGED / OVERRIDE never use teal, green, orange (or red) - nothing that reads as active."""

  def test_sweep_of_confidence_values(self):
    for status in NOT_ENGAGED:
      for x in SWEEP:
        colors = L.ball_colors(status, x)
        self.assertNotIn(colors, L.ENGAGED_PALETTE, (status, x))
        for c in colors:
          self.assertNotIn(c, [cc for pal in L.ENGAGED_PALETTE for cc in pal], (status, x))

  def test_missing_model_data(self):
    for status in NOT_ENGAGED:
      st = L.ConfidenceBallState(lambda: True, lambda: False, lambda: 0.0, 0.05)
      for _ in range(100):
        self.assertTrue(st.update(True, status, None, None))
      colors = L.ball_colors(status, st.filter.x)
      self.assertNotIn(colors, L.ENGAGED_PALETTE, status)
      self.assertEqual(colors, (L.WHITE, L.shade(L.WHITE)) if status == "DISENGAGED" else L.OVERRIDE)   # no data: low confidence
      self.assertAlmostEqual(L.ball_center_y(st.filter.x, 1080), 1080 - 30.0, delta=1.0)   # bottom
    st = L.ConfidenceBallState(lambda: True, lambda: False, lambda: 0.0, 0.05)
    for _ in range(100):
      st.update(True, "ENGAGED", None, None)
    self.assertEqual(L.ball_colors("ENGAGED", st.filter.x), L.RED)   # engaged + no data: stock red, low

  def test_status_switches_change_colour_only(self):
    st = L.ConfidenceBallState(lambda: True, lambda: False, lambda: 0.0, 0.05)
    for _ in range(200):
      st.update(True, "ENGAGED", [0.0], [0.0])
    x = st.filter.x
    self.assertEqual(L.ball_colors("ENGAGED", x), L.GREEN)
    st.update(True, "DISENGAGED", [0.0], [0.0])
    self.assertAlmostEqual(st.filter.x, x, places=2)                  # no slide on disengage
    self.assertEqual(L.ball_colors("DISENGAGED", st.filter.x), (L.SLATE, L.shade(L.SLATE)))


class TestDisengagedSlateToWhite(unittest.TestCase):
  """DISENGAGED ball colour follows confidence: slate grey (112,128,144) when high, white when low, smooth in between;
  the ENGAGED colours are exactly the stock values, unchanged."""

  def test_endpoints(self):
    self.assertEqual(L.SLATE, (112, 128, 144, 255))
    self.assertEqual(L.WHITE, (255, 255, 255, 255))
    for x in (1.0, 1.2, 1.5, float("inf")):
      self.assertEqual(L.ball_colors("DISENGAGED", x), (L.SLATE, L.shade(L.SLATE)), x)
    for x in (0.0, -0.2, -0.5, float("-inf")):
      self.assertEqual(L.ball_colors("DISENGAGED", x), (L.WHITE, L.shade(L.WHITE)), x)
    self.assertEqual(L.disengaged_color(0.5), (184, 192, 200, 255))      # halfway: per-channel midpoint, rounded

  def test_monotonic_and_smooth(self):
    xs = [i / 1000.0 for i in range(-100, 1101)]
    prev = None
    for x in xs:
      top, bottom = L.ball_colors("DISENGAGED", x)
      self.assertEqual(bottom, L.shade(top), x)                             # shaded: bottom = top * 82/255
      self.assertEqual(top[3], 255, x)
      if prev is not None:
        for c, p, lo in zip(top[:3], prev[:3], L.SLATE[:3], strict=True):
          self.assertLessEqual(c, p, x)                                     # only ever darker as confidence rises
          self.assertGreaterEqual(c, lo, x)
          self.assertLessEqual(p - c, 1, x)                                 # no jumps: at most 1 level per 0.001
      prev = top
    self.assertEqual(len({L.disengaged_color(i / 1000.0) for i in range(1001)}) > 100, True)

  def test_engaged_colours_unchanged(self):
    self.assertEqual(L.GREEN, ((0, 255, 204, 255), (0, 255, 38, 255)))
    self.assertEqual(L.ORANGE, ((255, 200, 0, 255), (255, 115, 0, 255)))
    self.assertEqual(L.RED, ((255, 0, 21, 255), (255, 0, 89, 255)))
    self.assertEqual(L.OVERRIDE, ((255, 255, 255, 255), (82, 82, 82, 255)))
    for x in SWEEP:
      want = L.GREEN if x > 0.5 else L.ORANGE if x > 0.2 else L.RED
      self.assertEqual(L.ball_colors("ENGAGED", x), want, x)

  def test_disengaged_never_engaged_palette_or_override(self):
    engaged = {c for pal in L.ENGAGED_PALETTE for c in pal}
    for i in range(-100, 1101):
      c = L.disengaged_color(i / 1000.0)
      self.assertNotIn(c, engaged, i)


class TestDisengagedShading(unittest.TestCase):
  """Maintainer-approved stock shading for the DISENGAGED ball: bottom = top * 82/255 (the stock OVERRIDE ball's ratio,
  mici/onroad/confidence_ball.py:68-70) at every confidence; ENGAGED and OVERRIDE unchanged."""

  # mockup levels: disengage prob -> (top, bottom) colours and the hex sampled at cy - r + 3, cy, cy + r - 3
  LEVELS = {"high": (0.0, ("#708090", "#24292E"), ("#6B7A8A", "#49545E", "#282D33")),
            "mid": (1 - 0.5 ** 0.5, ("#B8C0C8", "#3B3E40"), ("#B0B8BF", "#787E83", "#414446")),
            "low": (0.9, ("#FEFEFE", "#525252"), ("#F6F6F6", "#AAAAAA", "#5D5D5D"))}

  @staticmethod
  def hexs(c):
    return "#%02X%02X%02X" % tuple(c[:3])

  def test_shade_is_the_stock_override_ratio(self):
    self.assertEqual(L.SHADE, 82 / 255)
    self.assertEqual(L.shade(L.OVERRIDE[0]), L.OVERRIDE[1])
    self.assertEqual(L.shade(L.SLATE), (36, 41, 46, 255))
    for i in range(-100, 1101):
      top, bottom = L.ball_colors("DISENGAGED", i / 1000.0)
      self.assertEqual(bottom, tuple(int(round(ch * 82 / 255)) for ch in top[:3]) + (255,), i)
      self.assertTrue(all(b <= t for t, b in zip(top, bottom, strict=True)), i)   # darker at the bottom

  def test_levels_match_the_mockup(self):
    for level, (prob, ends, samples) in self.LEVELS.items():
      st = L.ConfidenceBallState(lambda: True, lambda: False, lambda: 1e9, 0.05)
      for _ in range(300):
        st.update(True, "DISENGAGED", [prob], [prob])
      x = st.filter.x
      top, bottom = L.ball_colors("DISENGAGED", x)
      self.assertEqual((self.hexs(top), self.hexs(bottom)), ends, level)
      cy = L.ball_center_y(x, 1080)
      y0 = cy - L.RADIUS
      for want, y in zip(samples, (cy - L.RADIUS + 3, cy, cy + L.RADIUS - 3), strict=True):
        i = int(math.floor(int(y) + 0.5 - y0))           # the 1 px scanline covering pixel row int(y), or a neighbour
        near = {self.hexs(L.lerp_color(top, bottom, (j + 0.5) / (2 * L.RADIUS))) for j in (i - 1, i, i + 1)}
        self.assertIn(want, near, (level, y))

  def test_engaged_and_override_unchanged(self):
    for x in SWEEP:
      self.assertEqual(L.ball_colors("OVERRIDE", x), ((255, 255, 255, 255), (82, 82, 82, 255)), x)
      want = L.GREEN if x > 0.5 else L.ORANGE if x > 0.2 else L.RED
      self.assertEqual(L.ball_colors("ENGAGED", x), want, x)
      self.assertEqual(L.ball_colors("LATERAL_ONLY", x), L.DARK, x)


class TestSettingsParsing(unittest.TestCase):
  def test_097_defaults(self):
    self.assertTrue(L.TOGGLE_DEFAULT)
    self.assertEqual(L.SIDE_DEFAULT, "left")
    self.assertTrue(L.parse_toggle(None))
    self.assertFalse(L.parse_side_right(None))

  def test_toggle_read_rules_match_097(self):
    for off in ("0", "false", "off", " OFF \n", "False"):
      self.assertFalse(L.parse_toggle(off), off)
    for on in ("1", "true", "on", "ON"):
      self.assertTrue(L.parse_toggle(on), on)
    for junk in ("", "maybe", "2"):
      self.assertTrue(L.parse_toggle(junk), junk)       # unknown = default (on)

  def test_side_read_rules_match_097(self):
    self.assertTrue(L.parse_side_right("right"))
    self.assertTrue(L.parse_side_right(" Right\n"))
    for other in ("left", "", "up", "1"):
      self.assertFalse(L.parse_side_right(other), other)

  def test_rereads_every_two_seconds_only(self):
    clock = {"t": 0.0}
    reads = {"toggle": 0}
    val = {"on": True}

    def read_toggle():
      reads["toggle"] += 1
      return val["on"]

    st = L.ConfidenceBallState(read_toggle, lambda: False, lambda: clock["t"], 0.05)
    self.assertTrue(st.update(True, "ENGAGED", [0.0], [0.0]))
    val["on"] = False
    clock["t"] = 1.9
    self.assertTrue(st.update(True, "ENGAGED", [0.0], [0.0]))      # still cached
    clock["t"] = 2.1
    self.assertFalse(st.update(True, "ENGAGED", [0.0], [0.0]))     # re-read
    self.assertEqual(reads["toggle"], 2)

  def test_store_not_ready_defaults_on_left(self):
    def boom():
      raise OSError("store not ready")
    st = L.ConfidenceBallState(boom, boom, lambda: 0.0, 0.05)
    self.assertTrue(st.update(True, "ENGAGED", [0.0], [0.0]))
    self.assertTrue(st.enabled)
    self.assertFalse(st.right)

  def test_registry_defaults_agree(self):
    from openpilot.common.bogpilot_store import registry_default
    from openpilot.common.bogpilot_toggles import FILE_CHOICES, FILE_TOGGLES
    self.assertTrue(FILE_TOGGLES["ConfidenceBall"][0])
    self.assertEqual(registry_default("ConfidenceBall"), "1")
    self.assertEqual(FILE_CHOICES["ConfidenceBallSide"][0], "left")
    self.assertEqual(registry_default("ConfidenceBallSide"), "left")

  def test_tuning_level_is_minimal_like_097(self):
    from openpilot.selfdrive.ui.bogpilot import tuning_level
    self.assertEqual(tuning_level.row_level("ConfidenceBall"), tuning_level.MINIMAL)
    self.assertEqual(tuning_level.row_level("ConfidenceBallSide"), tuning_level.MINIMAL)
    self.assertTrue(tuning_level.row_visible("ConfidenceBall", 0))

  def test_help_entries(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import shipping_defaults
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
    for key in ("ConfidenceBall", "ConfidenceBallSide"):
      self.assertIn(key, HELP)
      self.assertTrue(HELP[key].what.isascii() and "<" not in HELP[key].what)
    self.assertTrue(HELP["ConfidenceBall"].default.startswith("On"))
    self.assertEqual(HELP["ConfidenceBall"].default_param, "ConfidenceBall")
    self.assertTrue(HELP["ConfidenceBallSide"].default.startswith("Left"))
    self.assertNotIn("slides out", HELP["ConfidenceBall"].what)       # always shown now
    self.assertTrue(shipping_defaults()["ConfidenceBall"] in (True, "1", 1))

  def test_appearance_rows_first_and_peers(self):
    import openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals as bv
    self.assertEqual(bv.VISUAL_KEYS[0], "ConfidenceBall")
    self.assertIn("ConfidenceBall", bv.APPEARANCE_KEYS)
    self.assertEqual([k for k, _ in bv.TREE[:2]], ["ConfidenceBall", bv.SIDE_KEY])
    self.assertEqual(bv.TREE[0][1], ())
    self.assertEqual(bv.SIDE_CHOICES, ("left", "right"))


class TestEdgeAndKeepout(unittest.TestCase):
  def test_pick_edge(self):
    self.assertIs(L.pick_edge(False), False)
    self.assertIs(L.pick_edge(True), True)
    self.assertIs(L.pick_edge(False, blocked_left=True), True)       # flames on the left: ride the right edge
    self.assertIs(L.pick_edge(True, blocked_right=True), False)
    self.assertIs(L.pick_edge(False, blocked_right=True), False)     # the other edge burning is no reason to move
    self.assertIs(L.pick_edge(True, blocked_left=True), True)
    self.assertIsNone(L.pick_edge(False, True, True))                # both edges burning: hidden until one is free
    self.assertIsNone(L.pick_edge(True, True, True))

  def test_strip_rect(self):
    self.assertEqual(L.strip_rect(0, 0, 2160, 1080, False), (0, 0, 60.0, 1080))
    self.assertEqual(L.strip_rect(0, 0, 2160, 1080, True), (2100, 0, 60.0, 1080))

  def test_reset_returns_the_side_to_left(self):
    from openpilot.common.bogpilot_toggles import FILE_CHOICES
    from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import shipping_defaults as ui_shipping
    from openpilot.system.bogpilot import toggle_reset as tr
    self.assertEqual(FILE_CHOICES["ConfidenceBallSide"][0], "left")
    self.assertIn("ConfidenceBallSide", tr.FILE_CHOICE_RESET_KEYS)
    for values in (tr.reset_defaults(), tr.shipping_defaults(), ui_shipping()):
      self.assertEqual(values["ConfidenceBallSide"], "left")
      self.assertIn(values["ConfidenceBall"], ("1", True))


# --------------------------------------------------------------------------------------------- composer deferred tail
class Raiser:
  def __init__(self, calls, name):
    self.calls, self.name = calls, name

  def render(self, rect):
    self.calls.append(self.name + "!")
    raise RuntimeError(self.name)


class RaisingModel(H.FakeModel):
  def render(self, rect):
    self.calls.append("model!")
    raise RuntimeError("model")


class TailBase(H.Base):
  def runTest(self):
    pass

  def deferred(self, c, rect=None):
    """One frame the way AugmentedRoadView drives it: arm, render (may raise), then the tail."""
    rect = rect or self.rect
    c.begin_frame(defer_alert=True)
    raised = False
    try:
      c.render(rect)
    except RuntimeError:
      raised = True
    c.render_tail(rect)
    return raised

  def alert_draws(self):
    return self.calls.count("alert") + self.calls.count("stock_alert_paint")

  def dm_draws(self):
    return self.calls.count("stock_dm") + self.calls.count("stock_dm!")


class TestTailAlwaysDrawsTheAlert(TailBase):
  """CB1 (test 5b): render_tail() draws the alert whenever the frame was deferred, even when render() raised BEFORE it reached
  the point where it would have drawn the alert. It works from per-frame counters, not from a flag set late in render()."""

  def check(self, c, stock=False):
    raised = self.deferred(c)
    self.assertTrue(raised)
    self.assertEqual(self.alert_draws(), 1, list(self.calls))
    self.assertEqual(self.dm_draws(), 1, list(self.calls))
    if stock:
      self.assertEqual(self.calls[-2:], ["alert", "stock_dm"])          # stock order kept
    else:
      self.assertEqual(self.calls[-1], "alert")                         # alert last

  def test_toggle_read_raises(self):
    c = self.composer()
    c.toggle_get = lambda k: (_ for _ in ()).throw(RuntimeError("toggle"))
    self.check(c)
    self.assertIsNone(c._redesign_frame)                                # unknown frame: driver monitor, then alert

  def test_build_frame_raises(self):
    self.policy = SimpleNamespace(get=lambda: (_ for _ in ()).throw(RuntimeError("policy")))
    self.check(self.composer())

  def test_model_raises(self):
    self.check(self.composer(model=RaisingModel(self.calls)))

  def test_hud_raises(self):
    c = self.composer()
    c.hud = Raiser(self.calls, "hud")
    self.check(c)

  def test_dm_raises_is_not_retried_and_the_alert_still_draws(self):
    c = self.composer()
    c.dm = Raiser(self.calls, "stock_dm")
    self.check(c)
    self.assertEqual(self.calls.count("stock_dm!"), 1)

  def test_stock_frame_model_raises(self):
    self.toggles["RedesignUI"] = False
    self.check(self.composer(model=RaisingModel(self.calls)), stock=True)
    self.assertEqual(list(self.calls), ["model!", "alert", "stock_dm"])

  def test_stock_frame_hud_raises(self):
    self.toggles["RedesignUI"] = False
    c = self.composer()
    c.hud = Raiser(self.calls, "hud")
    self.check(c, stock=True)

  def test_no_pending_flag_left(self):
    self.assertFalse(hasattr(self.ns["HudComposer"], "_pending_tail"))


class TestExactlyOneAlertPerFrame(TailBase):
  """CB2: one alert draw per frame on every path; a second render_tail() is a no-op; the counters reset each frame."""

  def test_redesign_deferred(self):
    c = self.composer()
    self.deferred(c)
    self.assertEqual(list(self.calls), ["model", "hud", "stock_dm", "alert"])
    self.assertEqual(c._alert_draws, 1)
    c.render_tail(self.rect)
    self.assertEqual(self.alert_draws(), 1)

  def test_stock_deferred(self):
    self.toggles["RedesignUI"] = False
    c = self.composer()
    self.deferred(c)
    self.assertEqual(list(self.calls), ["model", "hud", "alert", "stock_dm"])
    self.assertEqual(c.order, ["model", "hud", "alert", "stock_dm"])
    c.render_tail(self.rect)
    self.assertEqual(self.alert_draws(), 1)

  def test_alert_renderer_raises_uses_the_stock_painter_once(self):
    c = self.composer(alert=H.FakeAlert(self.calls, raises=True))
    self.deferred(c)
    self.assertEqual(self.calls.count("stock_alert_paint"), 1)
    self.assertEqual(self.calls.count("alert"), 0)
    self.assertEqual(c._alert_draws, 1)
    self.assertEqual(c.order[-1], "stock_alert")

  def test_three_frames(self):
    c = self.composer()
    for _ in range(3):
      self.calls.clear()
      self.deferred(c)
      self.assertEqual(self.alert_draws(), 1)

  def test_unarmed_render_is_unchanged_and_tail_is_a_no_op(self):
    for redesign, expected in ((True, ["model", "hud", "stock_dm", "alert"]), (False, ["model", "hud", "alert", "stock_dm"])):
      self.calls.clear()
      self.toggles["RedesignUI"] = redesign
      c = self.composer()
      c.render(self.rect)                                               # legacy caller: never armed
      c.render_tail(self.rect)
      self.assertEqual(list(self.calls), expected)

  def test_every_raise_path_counts_one(self):
    makers = (lambda: self.composer(model=RaisingModel(self.calls)),)
    for redesign in (True, False):
      for make in makers:
        self.calls.clear()
        self.toggles["RedesignUI"] = redesign
        self.deferred(make())
        self.assertEqual(self.alert_draws(), 1, (redesign, list(self.calls)))


class TestContentOrderMatchesPreChange(TailBase):
  """CB3 (composer level): a deferred frame plus its tail paints the same sequence as the unarmed (pre-change) render()."""

  def configs(self):
    yield "stock", False, lambda: {}
    yield "redesign_no_peers", True, lambda: {}
    yield "redesign_full_stack", True, lambda: {"lead_lockon": H.Layer(self.calls, "lead_lockon", {"lead_chevron"}),
                                                 "lead_labels": H.Layer(self.calls, "lead_labels")}

  def test_same_sequence_deferred_or_not(self):
    for name, redesign, layers in self.configs():
      for alert in (None, SimpleNamespace(size=H.SMALL), SimpleNamespace(size=H.MID), SimpleNamespace(size=H.FULL)):
        self.toggles["RedesignUI"] = redesign
        self.calls.clear()
        self.composer(layers(), alert=H.FakeAlert(self.calls, alert)).render(self.rect)
        plain = list(self.calls)
        self.calls.clear()
        self.deferred(self.composer(layers(), alert=H.FakeAlert(self.calls, alert)))
        self.assertEqual(list(self.calls), plain, (name, alert))

  def test_pre_change_goldens(self):
    # the sequences test_hud_compose.TestOrder pins for the pre-change render()
    golden = {"stock": ["model", "hud", "alert", "stock_dm"], "redesign_no_peers": ["model", "hud", "stock_dm", "alert"],
              "redesign_full_stack": ["model", "lead_lockon", "hud", "lead_labels", "stock_dm", "alert"]}
    for name, redesign, layers in self.configs():
      self.toggles["RedesignUI"] = redesign
      self.calls.clear()
      self.deferred(self.composer(layers()))
      self.assertEqual(list(self.calls), golden[name], name)


class TestFullAlertPending(TailBase):
  def test_sizes_and_errors(self):
    for alert, expected in ((None, False), (SimpleNamespace(size=H.SMALL), False), (SimpleNamespace(size=H.MID), False),
                            (SimpleNamespace(size=H.FULL), True)):
      c = self.composer(alert=H.FakeAlert(self.calls, alert))
      self.assertIs(c.full_alert_pending(), expected, alert)
    c = self.composer()
    c.alert.get_alert = lambda sm: (_ for _ in ()).throw(RuntimeError("x"))
    self.assertTrue(c.full_alert_pending())                              # error -> plain order, no ball

  def test_begin_frame_cannot_raise_and_resets(self):
    bare = object.__new__(self.ns["HudComposer"])                        # even without __init__
    bare.begin_frame(defer_alert=True)
    self.assertEqual((bare._defer, bare._alert_draws, bare._dm_drawn, bare._redesign_frame, bare.frame, bare.order),
                     (True, 0, False, None, None, []))


class TestNoOverlap(unittest.TestCase):
  """The ball (54 px, 3..57 px from its screen edge) never overlaps the driving-personality button, the stock driver monitor
  icon, the experimental button, the speed capsule / accel graph, or an adjacent-lead box."""

  def setUp(self):
    class Harness(H.Base):
      def runTest(self):
        pass
    self.h = Harness()
    self.h.setUp()

  def frame(self, right_edge: bool, rhd: bool):
    h = self.h
    if rhd:
      h.state.sm["driverMonitoringState"].isRHD = True
    c = h.composer()
    rect = h.rect
    strip = H.Rect(*L.strip_rect(rect.x - 30, rect.y - 30, rect.width + 60, rect.height + 60, right_edge))
    c.extra_keepouts = lambda r: [strip]
    c.render(rect)
    return c.frame, strip, rect

  def ball_box(self, rect, right_edge: bool):
    cx = L.ball_center_x(rect.x - 30, rect.width + 60, right_edge)
    return H.Rect(cx - L.RADIUS, rect.y - 30, 2 * L.RADIUS, rect.height + 60)    # the ball at any height

  def test_ball_clears_every_hud_reservation_all_layouts(self):
    for rhd in (False, True):
      for right_edge in (False, True):
        f, strip, rect = self.frame(right_edge, rhd)
        ball = self.ball_box(rect, right_edge)
        self.assertIsNotNone(f.personality_rect)
        self.assertIsNotNone(f.stock_dm_rect)
        for name, r in {"personality": f.personality_rect, "dm": f.stock_dm_rect}.items():
          self.assertFalse(H.overlaps(ball, r), (name, rhd, right_edge))
        for k in f.keepouts:
          if k is strip:
            continue
          self.assertFalse(H.overlaps(ball, k), (k.t(), rhd, right_edge))
        self.assertIn(strip, f.keepouts)
        self.assertIn(strip, f.label_keepouts)
        self.assertIn(strip, f.base_keepouts)

  def test_without_the_hook_nothing_changes(self):
    # base keepouts = the cluster layout's (capsule, plus the accel graph only when ShowAccelGraph is on) + the experimental button
    for show_graph, expected in ((False, 2), (True, 3)):
      self.h.toggles["ShowAccelGraph"] = show_graph
      c = self.h.composer()
      self.assertIsNone(c.extra_keepouts)
      c.render(self.h.rect)
      self.assertEqual(len(c.frame.layout.keepouts()) + 1, expected, show_graph)
      self.assertEqual(len(c.frame.base_keepouts), expected, show_graph)

  def test_hook_defaults_to_none_on_the_class(self):
    c = self.h.composer()
    self.assertIsNone(type(c).extra_keepouts)
    bare = object.__new__(type(c))
    self.assertIsNone(bare.extra_keepouts)

  def test_failing_hook_never_breaks_the_hud(self):
    for show_graph in (False, True):
      self.h.toggles["ShowAccelGraph"] = show_graph
      plain = self.h.composer()
      plain.render(self.h.rect)
      c = self.h.composer()
      c.extra_keepouts = lambda r: (_ for _ in ()).throw(RuntimeError("boom"))
      c.render(self.h.rect)
      want = [k.t() for k in plain.frame.base_keepouts]
      got = [k.t() for k in c.frame.base_keepouts]
      self.assertEqual(len(got), len(want), show_graph)
      for i, (g, w) in enumerate(zip(got, want)):
        self.assertEqual(g, w, (show_graph, i))

  def test_adjacent_lead_boxes_keep_out_of_the_strip(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load
    ll = load("lead_labels")
    for right_edge in (False, True):
      f, strip, rect = self.frame(right_edge, False)
      view = (rect.x, rect.y, rect.width, rect.height)
      edge_x = rect.x + 8 if not right_edge else rect.x + rect.width - 8 - 120
      box = (edge_x, 400, 120, 46)
      self.assertTrue(ll.clear(box, view, ()), "stock clamp accepts the box")
      self.assertFalse(ll.clear(box, view, [strip]), "with the ball strip it is refused, never drawn under the ball")
      inside = (strip.x + (62 if not right_edge else -100), 400, 120, 46)
      self.assertFalse(ll.clear(inside, view, [strip]))


# ------------------------------------------------------------------------------------------- view ordering (fakes)
class FakeRl:
  """Records every draw / scissor call AugmentedRoadView and the ball make (no window needed)."""
  BLACK = (0, 0, 0, 255)

  def __init__(self, calls, raise_on_bsm=False):
    self.calls, self.raise_on_bsm, self._rounded = calls, raise_on_bsm, 0

  @staticmethod
  def Rectangle(x=0, y=0, w=0, h=0):
    return H.Rect(x, y, w, h)

  @staticmethod
  def Color(*c):
    return tuple(c)

  def begin_scissor_mode(self, *a):
    self.calls.append("scissor_begin")

  def end_scissor_mode(self):
    self.calls.append("scissor_end")

  def draw_rectangle_lines_ex(self, *a):
    self.calls.append("border_frame")

  def draw_rectangle_rounded_lines_ex(self, *a):
    self._rounded += 1
    if self._rounded > 1:                       # 1st = status border, then one per blind-spot side
      self.calls.append("bsm_side")
      if self.raise_on_bsm:
        raise RuntimeError("bsm draw")
      return
    self.calls.append("border")

  def draw_rectangle_rec(self, *a):
    if not self.calls or self.calls[-1] != "ball":
      self.calls.append("ball")                 # one entry per ball (it draws 54 scanlines)


class _Status:
  def __init__(self, name):
    self.name = name


class ViewBase(TailBase):
  """AugmentedRoadView._render driven with recording fakes and the synthetic composer from test_hud_compose."""

  def setUp(self):
    super().setUp()
    try:
      from openpilot.selfdrive.ui.onroad import augmented_road_view as arv
      from openpilot.selfdrive.ui.onroad.bogpilot import confidence_ball as cb
    except Exception as e:   # pragma: no cover - host without pyray / cereal
      self.skipTest(f"onroad view not importable here: {type(e).__name__}")
    self.arv, self.cb = arv, cb

  def view(self, composer, ball_on=True, ball_fails=False, status="ENGAGED", rl=None, bsm=None):
    arv, cb = self.arv, self.cb
    self.fake_rl = rl or FakeRl(self.calls)
    v = arv.AugmentedRoadView.__new__(arv.AugmentedRoadView)
    v._switch_stream_if_needed = lambda sm: None
    v._update_calibration = lambda: None
    v.model_renderer = SimpleNamespace()                  # no flames object: _flame_sides() -> (False, False)
    composer.border_color = lambda base: base
    composer.bsm_border = lambda: bsm
    composer.BSM_BORDER_RGBA = (255, 0, 0, 255)
    v._hud_compose = composer
    v._confidence_ball = cb.ConfidenceBallRenderer(read_toggle=lambda: ball_on, read_side=lambda: False, clock=lambda: 1e9, fps=20.0)
    if ball_fails:
      v._confidence_ball._draw_ball = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ball"))
    self.ui = SimpleNamespace(started=True, sm={}, status=_Status(status))   # hashable: BORDER_COLORS.get(status, ...)
    self._patches = [mock.patch.object(arv, "rl", self.fake_rl), mock.patch.object(cb, "rl", self.fake_rl),
                     mock.patch.object(arv, "ui_state", self.ui),
                     mock.patch.object(arv.CameraView, "_render", lambda s, r: self.calls.append("camera"))]
    return v

  def run_frame(self, v):
    for p in self._patches:
      p.start()
    try:
      v._render(H.Rect(0, 0, 2160, 1080))
    finally:
      for p in self._patches:
        p.stop()

  def content(self):
    """The content-area draws in order (scissor, border and ball removed)."""
    skip = {"scissor_begin", "scissor_end", "border_frame", "border", "bsm_side", "ball"}
    return [c for c in self.calls if c not in skip]


# pre-change (previous release baseline 27e82a496) AugmentedRoadView._render with the same fakes: scissor, camera, composer (alert inside), end, border
RC7_GOLDEN = {
  True: ["scissor_begin", "camera", "model", "hud", "stock_dm", "alert", "scissor_end", "border_frame", "border"],
  False: ["scissor_begin", "camera", "model", "hud", "alert", "stock_dm", "scissor_end", "border_frame", "border"],
}


class TestViewOrder(ViewBase):
  def test_alert_is_the_last_draw_and_ball_is_under_it(self):
    for redesign in (True, False):
      self.calls.clear()
      self.toggles["RedesignUI"] = redesign
      self.run_frame(self.view(self.composer()))
      self.assertEqual(self.calls[-2], "alert" if redesign else "stock_dm", list(self.calls))
      self.assertEqual(self.calls[-1], "scissor_end")
      self.assertLess(self.calls.index("border"), self.calls.index("ball"))
      self.assertLess(self.calls.index("ball"), self.calls.index("alert"))
      self.assertEqual(self.calls.count("alert"), 1)

  def test_ball_drawn_with_redesign_on_and_off_and_in_every_status(self):
    for redesign in (True, False):
      for status in STATUSES:
        self.calls.clear()
        self.toggles["RedesignUI"] = redesign
        v = self.view(self.composer(), status=status)
        self.run_frame(v)
        self.assertIn("ball", self.calls, (redesign, status))
        top = v._confidence_ball.last_draw[2]
        if status != "ENGAGED":
          self.assertNotIn(top, [pal[0] for pal in L.ENGAGED_PALETTE], (redesign, status))

  def test_disengaged_ball_is_drawn_white_at_the_bottom_with_no_model_data(self):
    v = self.view(self.composer(), status="DISENGAGED")
    self.run_frame(v)
    x, y, top, bottom = v._confidence_ball.last_draw
    self.assertEqual((top, bottom), (L.WHITE, L.shade(L.WHITE)))           # no data = confidence 0 = white top
    self.assertAlmostEqual(y, 1080 - 30.0, delta=0.5)

  def test_full_screen_alert_keeps_the_plain_order_and_hides_the_ball(self):
    for redesign in (True, False):
      self.calls.clear()
      self.toggles["RedesignUI"] = redesign
      v = self.view(self.composer(alert=H.FakeAlert(self.calls, SimpleNamespace(size=H.FULL))))
      self.run_frame(v)
      self.assertEqual(list(self.calls), RC7_GOLDEN[redesign], redesign)
      self.assertNotIn("ball", self.calls)
      self.assertIsNone(v._confidence_ball.last_draw)
      self.assertEqual(v._confidence_ball.keepouts(H.Rect(30, 30, 2100, 1020)), [])

  def test_full_alert_check_failing_falls_back_to_the_plain_order(self):
    c = self.composer()
    c.full_alert_pending = lambda: True                     # what it returns on any error
    self.run_frame(self.view(c))
    self.assertEqual(list(self.calls), RC7_GOLDEN[True])


class TestBallOffOrFailingMatchesPreChange(ViewBase):
  """CB3: with the ball off or failing, the content-area draws equal the pre-change (previous release baseline) sequence; the only change is that
  the alert tail sits after the border, in its own scissor pair."""

  def test_sequences(self):
    for redesign in (True, False):
      for kw in ({"ball_on": False}, {"ball_fails": True}):
        for alert in (None, SimpleNamespace(size=H.SMALL), SimpleNamespace(size=H.MID)):
          self.calls.clear()
          self.toggles["RedesignUI"] = redesign
          self.run_frame(self.view(self.composer(alert=H.FakeAlert(self.calls, alert)), **kw))
          rc7 = [c for c in RC7_GOLDEN[redesign] if c not in ("scissor_begin", "scissor_end", "border_frame", "border")]
          self.assertEqual(self.content(), rc7, (redesign, kw, alert))
          self.assertNotIn("ball", self.calls)
          tail = ["alert"] if redesign else ["alert", "stock_dm"]
          self.assertEqual(self.calls[-len(tail) - 2:], ["scissor_begin"] + tail + ["scissor_end"])

  def test_ball_off_gives_the_hud_its_keepouts_back(self):
    v = self.view(self.composer(), ball_on=False)
    self.run_frame(v)
    self.assertEqual(v._confidence_ball.keepouts(H.Rect(30, 30, 2100, 1020)), [])


class TestScissorAlwaysBalanced(ViewBase):
  """CB5: both scissor pairs (content + tail) and each blind-spot border pair end on every path."""

  def balanced(self):
    self.assertEqual(self.calls.count("scissor_begin"), self.calls.count("scissor_end"), list(self.calls))

  def test_normal_frame_two_pairs_full_alert_one(self):
    self.run_frame(self.view(self.composer()))
    self.balanced()
    self.assertEqual(self.calls.count("scissor_begin"), 2)
    self.calls.clear()
    self.run_frame(self.view(self.composer(alert=H.FakeAlert(self.calls, SimpleNamespace(size=H.FULL)))))
    self.balanced()
    self.assertEqual(self.calls.count("scissor_begin"), 1)                # the pre-change count

  def test_raises_everywhere(self):
    def composer_raising_model():
      return self.composer(model=RaisingModel(self.calls))

    def composer_raising_tail():
      c = self.composer()
      c.dm = Raiser(self.calls, "stock_dm")
      self.toggles["RedesignUI"] = False                     # the stock driver monitor is drawn by the tail
      return c

    cases = (("model", composer_raising_model, {}), ("ball", self.composer, {"ball_fails": True}),
             ("tail", composer_raising_tail, {}))
    for name, make, kw in cases:
      self.calls.clear()
      self.toggles["RedesignUI"] = True
      v = self.view(make(), **kw)
      try:
        self.run_frame(v)
      except RuntimeError:
        pass
      self.balanced()
      self.assertEqual(self.alert_draws(), 1, name)

  def test_border_raises_the_alert_still_draws(self):
    c = self.composer()
    v = self.view(c)
    v._draw_border = lambda rect: (_ for _ in ()).throw(RuntimeError("border"))
    with self.assertRaises(RuntimeError):
      self.run_frame(v)
    self.balanced()
    self.assertEqual(self.alert_draws(), 1)

  def test_blind_spot_border_pair(self):
    for raise_on_bsm in (False, True):
      self.calls.clear()
      rl = FakeRl(self.calls, raise_on_bsm=raise_on_bsm)
      v = self.view(self.composer(), rl=rl, bsm=(True, False))
      try:
        self.run_frame(v)
      except RuntimeError:
        self.assertTrue(raise_on_bsm)
      self.assertIn("bsm_side", self.calls)
      self.balanced()
      self.assertEqual(self.alert_draws(), 1)


class TestBallTakesNoInput(ViewBase):
  """CB4: the renderer is not a Widget, has no mouse handlers, and a tap on the ball strip reaches the view exactly as before."""

  def test_not_a_widget(self):
    from openpilot.system.ui.widgets import Widget
    ball = self.cb.ConfidenceBallRenderer(read_toggle=lambda: True, read_side=lambda: False, clock=lambda: 0.0, fps=20.0)
    self.assertNotIsInstance(ball, Widget)
    for name in ("_handle_mouse_press", "_handle_mouse_release", "_process_mouse_events", "set_rect", "_child"):
      self.assertFalse(hasattr(ball, name), name)

  def test_tap_on_the_ball_goes_to_the_view(self):
    c = self.composer()
    v = self.view(c)
    self.run_frame(v)
    before = (v._confidence_ball.last_draw, v._confidence_ball.state.filter.x)
    clicks = []
    v._click_callback = lambda: clicks.append(1)
    v._hud_renderer = SimpleNamespace(user_interacting=lambda: False)
    c.handle_button_press = lambda pos: False                # the ball strip is not the personality button
    c.handle_button_release = lambda pos: False
    x, y = v._confidence_ball.last_draw[:2]
    v._handle_mouse_press(SimpleNamespace(x=x, y=y))
    v._handle_mouse_release(SimpleNamespace(x=x, y=y))
    self.assertEqual(clicks, [1])                             # sidebar toggle, as before
    self.assertEqual((v._confidence_ball.last_draw, v._confidence_ball.state.filter.x), before)

  def test_view_never_forwards_events_to_the_ball(self):
    import inspect
    src = inspect.getsource(self.arv.AugmentedRoadView._handle_mouse_press) + \
      inspect.getsource(self.arv.AugmentedRoadView._handle_mouse_release)
    self.assertNotIn("_confidence_ball", src)


class TestViewWiring(ViewBase):
  def test_source_wiring(self):
    import inspect
    src = inspect.getsource(self.arv.AugmentedRoadView)
    self.assertIn("self._confidence_ball = ConfidenceBallRenderer()", src)
    self.assertIn("self._hud_compose.extra_keepouts = self._confidence_ball.keepouts", src)
    self.assertIn("self._hud_compose.begin_frame(defer_alert=True)", src)
    self.assertLess(src.index("self._hud_compose.begin_frame(defer_alert=True)"), src.index("self._hud_compose.render(self._content_rect)"))
    self.assertLess(src.index("self._draw_border(rect)\n"), src.index("self._confidence_ball.render("))

  def test_flame_sides(self):
    class Trigger:
      def __init__(self, a):
        self.a = a

      def active(self, i):
        return self.a[i]
    view = SimpleNamespace(model_renderer=SimpleNamespace(_flames=SimpleNamespace(trigger=Trigger((True, False)))))
    self.assertEqual(self.arv.AugmentedRoadView._flame_sides(view), (True, False))
    view = SimpleNamespace(model_renderer=SimpleNamespace())
    self.assertEqual(self.arv.AugmentedRoadView._flame_sides(view), (False, False))


_WINDOW = {"opened": False, "saved": None}


def tearDownModule():
  """Close the raylib window if this module opened it and put gui_app back as it was, so later test modules (toggle help,
  settings, ...) open their own window with their own size and config flags instead of inheriting this one."""
  if not _WINDOW["opened"]:
    return
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  try:
    if rl.is_window_ready():
      gui_app.close()
  finally:
    w, h, sw, sh, stack = _WINDOW["saved"]
    gui_app._width, gui_app._height, gui_app._scaled_width, gui_app._scaled_height = w, h, sw, sh
    gui_app._nav_stack[:] = stack
    if stack:
      stack[-1].set_enabled(True)
    NativeBase._window_base = None
    _WINDOW["opened"], _WINDOW["saved"] = False, None


# ------------------------------------------------------------------------------------------------- native (headless)
@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires native headless raylib")
class NativeBase(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.tmp = tempfile.mkdtemp(prefix="confidence-ball-")
    os.environ["BOGPILOT_PARAMS_DIR"] = os.path.join(cls.tmp, "bp")
    os.makedirs(os.environ["BOGPILOT_PARAMS_DIR"], exist_ok=True)
    import openpilot.common.hardware.comma.hardware as comma_hw
    if not os.path.exists("/sys/firmware/devicetree/base/model"):
      comma_hw.get_device_type = lambda: "pc"
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.system.ui.widgets import Widget

    class Base(Widget):
      def _render(self, rect):
        pass
    cls.rl, cls.gui_app = rl, gui_app
    if not rl.is_window_ready() and _WINDOW["saved"] is None:   # remember gui_app as found, for tearDownModule
      _WINDOW["saved"] = (gui_app._width, gui_app._height, gui_app._scaled_width, gui_app._scaled_height, list(gui_app._nav_stack))
    if not gui_app.big_ui() and not rl.is_window_ready():
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    if not rl.is_window_ready():                 # one window per process, shared by the native classes
      gui_app.init_window("confidence ball")
      _WINDOW["opened"] = True
      NativeBase._window_base = Base()
      gui_app.push_widget(NativeBase._window_base)

  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.selfdrive.ui.tests.test_phase2_visuals_theme import FakeParams
    self.typed = {}
    self.store = ParamStore(FakeParams(self.typed))
    for name in os.listdir(os.environ["BOGPILOT_PARAMS_DIR"]):
      os.remove(os.path.join(os.environ["BOGPILOT_PARAMS_DIR"], name))

  def layout(self):
    import openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals as bv
    return bv.BogPilotVisualsLayout(store=self.store, keys=bv.APPEARANCE_KEYS)

  def ball(self, clock=lambda: 1e9):
    from openpilot.selfdrive.ui.onroad.bogpilot import confidence_ball as cb
    return cb.ConfidenceBallRenderer(clock=clock, fps=20.0)

  @staticmethod
  def sm(brake=(0.0,), steer=(0.0,)):
    meta = SimpleNamespace(disengagePredictions=SimpleNamespace(brakeDisengageProbs=list(brake), steerOverrideProbs=list(steer)))
    return {"modelV2": SimpleNamespace(meta=meta)}

  def draw(self, ball, status="ENGAGED", frames=1, sm=None, started=True):
    rl = self.rl
    rect = rl.Rectangle(0, 0, 2160, 1080)
    out = False
    for _ in range(frames):
      rl.begin_drawing()
      try:
        out = ball.render(rect, started, status, sm if sm is not None else self.sm())
      finally:
        rl.end_drawing()
    return out


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires native headless raylib")
class TestNative(NativeBase):
  # ---- Appearance rows ----
  def test_rows_are_first_on_the_page_with_help_and_defaults(self):
    lay = self.layout()
    items = list(lay._scroller._items)
    self.assertIs(items[0], lay._toggles["ConfidenceBall"])
    self.assertIs(items[1], lay._side)
    self.assertEqual(items[0].help_key, "ConfidenceBall")
    self.assertEqual(items[1].help_key, "ConfidenceBallSide")
    self.assertTrue(items[0].action_item.get_state())                 # default: on
    self.assertEqual(lay._side.action_item.get_selected_button(), 0)  # default: Left
    self.assertEqual(self.typed, {})                                    # opening the page writes nothing
    self.assertEqual(os.listdir(os.environ["BOGPILOT_PARAMS_DIR"]), [])

  def test_ui_to_store_to_consumer_toggle(self):
    lay = self.layout()
    self.assertTrue(self.draw(self.ball()))
    tog = lay._toggles["ConfidenceBall"].action_item.toggle
    tog.set_state(False)
    tog._callback(False)                                              # the real Toggle click path
    self.assertEqual(self.store.raw("ConfidenceBall"), "0")
    with open(os.path.join(os.environ["BOGPILOT_PARAMS_DIR"], "ConfidenceBall")) as f:
      self.assertEqual(f.read(), "0")
    self.assertEqual(self.typed, {})                                   # file toggle: never Params
    for status in STATUSES:
      self.assertFalse(self.draw(self.ball(), status=status), status)  # off hides it in every status
    tog.set_state(True)
    tog._callback(True)
    self.assertTrue(self.draw(self.ball()))

  def test_ui_to_store_to_consumer_side(self):
    lay = self.layout()
    ball = self.ball()
    self.assertTrue(self.draw(ball))
    self.assertEqual(ball.last_draw[0], 30.0)                           # default: left edge
    lay._side.action_item.callback(1)                                   # Right button
    self.assertEqual(self.store.get("ConfidenceBallSide"), "right")
    ball2 = self.ball()
    self.assertTrue(self.draw(ball2))
    self.assertEqual(ball2.last_draw[0], 2130.0)
    lay._side.action_item.callback(0)
    ball3 = self.ball()
    self.draw(ball3)
    self.assertEqual(ball3.last_draw[0], 30.0)
    lay.refresh()
    self.assertEqual(lay._side.action_item.get_selected_button(), 0)

  def test_saved_values_are_preserved_and_shown(self):
    self.store.put("ConfidenceBallSide", "right")
    self.store.put_bool("ConfidenceBall", False)
    lay = self.layout()
    self.assertFalse(lay._toggles["ConfidenceBall"].action_item.get_state())
    self.assertEqual(lay._side.action_item.get_selected_button(), 1)

  # ---- renderer ----
  def test_draw_geometry_and_colors_follow_the_model(self):
    ball = self.ball()
    self.assertTrue(self.draw(ball, frames=200, sm=self.sm((0.05,), (0.05,))))
    x, y, top, bottom = ball.last_draw
    self.assertEqual(top, (0, 255, 204, 255))
    self.assertAlmostEqual(y, L.ball_center_y(ball.state.filter.x, 1080), places=3)
    self.assertLess(y, 140)
    self.draw(ball, frames=200, sm=self.sm((0.5,), (0.5,)))            # 0.25: orange
    self.assertEqual(ball.last_draw[2], (255, 200, 0, 255))
    self.draw(ball, frames=200, sm=self.sm((0.9,), (0.9,)))            # 0.01: red, low
    self.assertEqual(ball.last_draw[2], (255, 0, 21, 255))
    self.draw(ball, status="OVERRIDE", frames=1, sm=self.sm((0.0,), (0.0,)))
    self.assertEqual(ball.last_draw[2], (255, 255, 255, 255))

  def test_always_drawn_when_disengaged_and_hidden_when_not_started(self):
    ball = self.ball()
    self.draw(ball, frames=200)
    self.assertTrue(self.draw(ball, status="DISENGAGED", frames=200))
    x, y, top, bottom = ball.last_draw
    self.assertLess(y + L.RADIUS, 1080)                                   # on screen, at the model's height (high here)
    self.assertLess(y, 140)
    self.assertEqual((top, bottom), L.ball_colors("DISENGAGED", ball.state.filter.x))
    self.assertEqual(bottom, L.shade(top))
    self.assertTrue(all(abs(a - b) <= 15 for a, b in zip(top, L.SLATE, strict=True)), top)   # high: near slate
    self.assertTrue(self.draw(ball, status="DISENGAGED", frames=200, sm={}))   # no model data: bottom, white
    self.assertAlmostEqual(ball.last_draw[1], 1080 - 30.0, delta=1.0)
    self.assertEqual(ball.last_draw[2], L.WHITE)
    self.assertFalse(self.draw(ball, started=False))
    self.assertIsNone(ball.last_draw)

  def test_draws_real_scanlines_and_never_black_corners(self):
    rl = self.rl
    calls = []
    original = rl.draw_rectangle_rec
    rl.draw_rectangle_rec = lambda rec, color: calls.append((rec.x, rec.y, rec.width, rec.height, color.r, color.g, color.b, color.a))
    try:
      self.draw(self.ball(), frames=1, sm=self.sm())
    finally:
      rl.draw_rectangle_rec = original
    self.assertGreater(len(calls), 40)
    self.assertTrue(all(c[3] == 1 for c in calls))
    self.assertTrue(all(c[7] == 255 and (c[4], c[5], c[6]) != (0, 0, 0) for c in calls))
    xs = [c[0] for c in calls] + [c[0] + c[2] for c in calls]
    self.assertGreaterEqual(min(xs), 30 - 27 - 0.01)
    self.assertLessEqual(max(xs), 30 + 27 + 0.01)                       # inside the 60 px strip

  def test_failure_disables_only_the_ball(self):
    ball = self.ball()
    ball._draw_ball = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    self.assertFalse(self.draw(ball))
    self.assertTrue(ball.failed)
    self.assertFalse(self.draw(ball))
    self.assertEqual(ball.keepouts(self.rl.Rectangle(30, 30, 2100, 1020)), [])

  def test_keepouts_follow_the_ball(self):
    ball = self.ball()
    self.assertEqual(ball.keepouts(self.rl.Rectangle(30, 30, 2100, 1020)), [])
    self.draw(ball)
    k = ball.keepouts(self.rl.Rectangle(30, 30, 2100, 1020))
    self.assertEqual([(r.x, r.y, r.width, r.height) for r in k], [(0, 0, 60.0, 1080)])
    with open(os.path.join(os.environ["BOGPILOT_PARAMS_DIR"], "ConfidenceBallSide"), "w") as f:
      f.write("right")
    ball2 = self.ball()
    self.draw(ball2)
    k = ball2.keepouts(self.rl.Rectangle(30, 30, 2100, 1020))
    self.assertEqual([(r.x, r.y, r.width, r.height) for r in k], [(2100, 0, 60.0, 1080)])
    self.draw(ball2, started=False)
    self.assertEqual(ball2.keepouts(self.rl.Rectangle(30, 30, 2100, 1020)), [])
    ball2.hide()
    self.assertEqual(ball2.keepouts(self.rl.Rectangle(30, 30, 2100, 1020)), [])
    with open(os.path.join(os.environ["BOGPILOT_PARAMS_DIR"], "ConfidenceBall"), "w") as f:
      f.write("0")
    ball3 = self.ball()
    self.draw(ball3)
    self.assertEqual(ball3.keepouts(self.rl.Rectangle(30, 30, 2100, 1020)), [])

  def test_flame_track_moves_the_ball_to_the_other_edge(self):
    rl = self.rl
    rect = rl.Rectangle(0, 0, 2160, 1080)

    def at(ball, blocked):
      rl.begin_drawing()
      try:
        out = ball.render(rect, True, "ENGAGED", self.sm(), blocked)
      finally:
        rl.end_drawing()
      return out, (ball.last_draw[0] if ball.last_draw else None)
    ball = self.ball()
    self.assertEqual(at(ball, (False, False)), (True, 30.0))
    self.assertEqual(at(ball, (True, False)), (True, 2130.0))
    self.assertEqual(at(ball, (False, True)), (True, 30.0))
    self.assertEqual(at(ball, (True, True)), (False, None))
    self.assertEqual(ball.keepouts(rl.Rectangle(30, 30, 2100, 1020)), [])
    self.assertEqual(at(ball, (False, False)), (True, 30.0))


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires native headless raylib")
class TestPixelsMatchPreChange(NativeBase):
  """CB3 pixels: with the ball off (or failing), the frame AugmentedRoadView paints is byte-identical to the pre-change order
  (scissor -> camera -> composer with the alert inside -> end -> border), for alert none / small / mid / full, RedesignUI on
  and off, blind-spot border on and off. Synthetic components that really draw; no camera."""

  def components(self, calls, alert_size):
    rl = self.rl

    class Paint:
      def __init__(self, name, fn):
        self.name, self.fn = name, fn

      def render(self, rect):
        calls.append(self.name)
        self.fn(rect)

    class Alert(Paint):
      def get_alert(self, sm):
        return None if alert_size is None else SimpleNamespace(size=alert_size)

      def _get_alert_rect(self, rect, size):
        return rect

    def alert_paint(r):
      if alert_size == H.FULL:
        rl.draw_rectangle_rec(r, rl.Color(200, 20, 20, 230))            # full: the whole content rect, translucent
      elif alert_size is not None:
        h = 200 if alert_size == H.SMALL else 300
        rl.draw_rectangle_rec(rl.Rectangle(r.x + 40, r.y + r.height - h - 40, r.width - 80, h), rl.Color(20, 20, 200, 230))
    model = Paint("model", lambda r: rl.draw_rectangle_rec(rl.Rectangle(r.x + 500, r.y + 300, 1100, 700), rl.Color(60, 160, 60, 255)))
    model.bp_defer_primary_lead, model.bp_pending_primary, model.bp_traffic_red = False, None, False
    hud = Paint("hud", lambda r: rl.draw_rectangle_rec(rl.Rectangle(r.x + 900, r.y + 20, 300, 120), rl.Color(240, 240, 240, 255)))
    dm = Paint("stock_dm", lambda r: rl.draw_circle(int(r.x + 126), int(r.y + r.height - 126), 96, rl.Color(30, 30, 30, 255)))
    return model, hud, Alert("alert", alert_paint), dm

  def frame_png(self, redesign, alert_size, bsm, proposed, ball_kw):
    from openpilot.selfdrive.ui.onroad import augmented_road_view as arv
    from openpilot.selfdrive.ui.onroad.bogpilot import confidence_ball as cb
    rl = self.rl
    h = TailBase()
    h.setUp()
    h.toggles["RedesignUI"] = redesign
    model, hud, alert, dm = self.components(h.calls, alert_size)
    c = h.ns["HudComposer"](model, hud, alert, dm, layers={}, policy=h.policy, traffic=h.traffic, clock=lambda: 100.0,
                            state=h.state, toggle_get=lambda k: h.toggles[k])
    c.border_color = lambda base: base
    c.bsm_border = lambda: bsm
    c.BSM_BORDER_RGBA = (255, 0, 0, 255)
    v = arv.AugmentedRoadView.__new__(arv.AugmentedRoadView)
    v._switch_stream_if_needed = lambda sm: None
    v._update_calibration = lambda: None
    v.model_renderer = SimpleNamespace()
    v._hud_compose = c
    v._confidence_ball = cb.ConfidenceBallRenderer(read_toggle=lambda: ball_kw.get("ball_on", False), read_side=lambda: False,
                                                   clock=lambda: 1e9, fps=20.0)
    if ball_kw.get("ball_fails"):
      v._confidence_ball._draw_ball = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ball"))
    rect = rl.Rectangle(0, 0, 2160, 1080)
    camera = lambda s, r: rl.draw_rectangle_rec(r, rl.Color(90, 110, 130, 255))
    ui = SimpleNamespace(started=True, sm={}, status=_Status("ENGAGED"))
    self.__class__._n = getattr(self.__class__, "_n", 0) + 1
    path = os.path.join(self.tmp, f"px_{self.__class__._n:04d}.png")
    with mock.patch.object(arv, "ui_state", ui), mock.patch.object(arv.CameraView, "_render", camera):
      # Own 2160x1080 framebuffer per frame, so the result never depends on which test opened the shared window or its size.
      target = rl.load_render_texture(2160, 1080)
      try:
        rl.begin_texture_mode(target)
        try:
          rl.clear_background(rl.BLACK)
          if proposed:
            v._render(rect)
          else:                                                        # the pre-change _render body, verbatim order
            v._content_rect = rl.Rectangle(rect.x + 30, rect.y + 30, rect.width - 60, rect.height - 60)
            rl.begin_scissor_mode(30, 30, 2100, 1020)
            camera(v, v._content_rect)
            c.render(v._content_rect)                                  # unarmed: alert inside, as before
            rl.end_scissor_mode()
            v._draw_border(rect)
          rl.rl_draw_render_batch_active()                             # flush queued draws before the read-back
        finally:
          rl.end_texture_mode()
        img = rl.load_image_from_texture(target.texture)
        try:
          self.assertEqual((img.width, img.height), (2160, 1080))
          # Render textures are stored bottom-up: image row y is frame row 1079 - y. Both frames are read the same way, so no
          # flip is needed for the comparison. Guard: the status border ring covers x 0..30; frame (15, 540) is on its left edge.
          px = rl.get_image_color(img, 15, 1079 - 540)
          want = (255, 0, 0) if (bsm and bsm[0]) else tuple(getattr(arv.BORDER_COLORS.get(ui.status, arv.BORDER_COLORS[arv.UIStatus.DISENGAGED]), k) for k in "rgb")
          self.assertEqual((px.r, px.g, px.b), want, ("border pixel", redesign, alert_size, bsm, proposed, ball_kw))
          rl.export_image(img, path)
        finally:
          rl.unload_image(img)
      finally:
        rl.unload_render_texture(target)
    with open(path, "rb") as f:
      return f.read()

  def test_frames_are_byte_identical_with_the_ball_off_or_failing(self):
    probe_none = self.frame_png(True, None, None, False, {})
    probe_full = self.frame_png(True, H.FULL, None, False, {})
    if probe_none == probe_full:
      self.skipTest("this backend does not rasterize filled shapes; run the pixel check on the GL VM")
    for redesign in (True, False):
      for alert_size in (None, H.SMALL, H.MID, H.FULL):
        for bsm in (None, (True, False), (False, True)):
          for ball_kw in ({"ball_on": False}, {"ball_on": True, "ball_fails": True}):
            before = self.frame_png(redesign, alert_size, bsm, False, ball_kw)
            after = self.frame_png(redesign, alert_size, bsm, True, ball_kw)
            self.assertEqual(before, after, (redesign, alert_size, bsm, ball_kw))


# ---- second alert read per frame (full_alert_pending) changes no alert state ----
_ALERT_SEQUENCE = (None, H.SMALL, H.MID, H.FULL, H.FULL, None, H.FULL, H.SMALL, H.MID, None, H.FULL, H.FULL, H.SMALL, None)


def _plain_state(obj):
  return {k: v for k, v in vars(obj).items() if isinstance(v, (bool, int, float, str, type(None), tuple))}


class TestSecondAlertReadChangesNoComposerState(TailBase):
  """full_alert_pending() is a second get_alert read per frame. Across alert transitions (none / small / mid / full,
  held full, full to none and back) it changes no composer state and no draw: a composer that also runs it before,
  during and after every frame gives the same draw calls and the same per-frame state as one that never runs it."""

  def two_composers(self, redesign):
    out = []
    for _ in range(2):
      h = TailBase()
      h.setUp()
      h.toggles["RedesignUI"] = redesign
      alert = H.FakeAlert(h.calls, None)
      out.append((h, h.composer(alert=alert), alert))
    return out

  def test_same_draws_and_state_with_and_without_the_extra_read(self):
    for redesign in (True, False):
      (h1, c1, a1), (h2, c2, a2) = self.two_composers(redesign)
      for i, size in enumerate(_ALERT_SEQUENCE):
        where = (redesign, i, size)
        a1.alert = a2.alert = None if size is None else SimpleNamespace(size=size)
        h1.calls.clear()
        h2.calls.clear()
        h1.deferred(c1)                                                  # never reads twice
        c2.begin_frame(defer_alert=True)
        before = _plain_state(c2)
        self.assertEqual(c2.full_alert_pending(), size == H.FULL, where)
        self.assertEqual(_plain_state(c2), before, where)
        c2.render(h2.rect)
        mid = _plain_state(c2)
        c2.full_alert_pending()
        self.assertEqual(_plain_state(c2), mid, where)
        c2.render_tail(h2.rect)
        end = _plain_state(c2)
        c2.full_alert_pending()
        self.assertEqual(_plain_state(c2), end, where)
        self.assertEqual(h1.calls, h2.calls, where)
        self.assertEqual(_plain_state(c1), _plain_state(c2), where)
        self.assertEqual(h1.calls.count("alert") + h1.calls.count("stock_alert_paint"), 1, where)


def _snap(o, portable, depth=0, seen=None):
  """Structural snapshot. portable=False keeps object identity (same-instance before/after); portable=True drops it
  (two instances compared)."""
  seen = set() if seen is None else seen
  if isinstance(o, (bool, int, float, str, bytes, type(None))):
    return o
  if isinstance(o, (list, tuple)):
    return (type(o).__name__,) + tuple(_snap(x, portable, depth + 1, seen) for x in o)
  if isinstance(o, dict):
    items = sorted(o.items(), key=lambda kv: repr(kv[0]))
    return ("dict",) + tuple((repr(k), _snap(v, portable, depth + 1, seen)) for k, v in items)
  if all(hasattr(o, a) for a in ("x", "y", "width", "height")):
    try:
      return ("rect", float(o.x), float(o.y), float(o.width), float(o.height))
    except Exception:
      pass
  if id(o) in seen:
    return ("seen", type(o).__name__) if portable else ("seen", type(o).__name__, id(o))
  d = None
  if not callable(o) and depth < 4:
    try:
      d = vars(o)
    except TypeError:
      d = None
  if d is not None:
    seen.add(id(o))
    return (type(o).__name__, _snap(d, portable, depth + 1, seen))
  return (type(o).__name__,) if portable else (type(o).__name__, id(o))


class _SM(dict):
  def __init__(self):
    super().__init__()
    self.recv_frame, self.recv_time, self.updated = {}, {}, {}
    self.locked = False

  def __setitem__(self, k, v):
    if self.locked:
      raise AssertionError("SubMaster written during an alert read")
    super().__setitem__(k, v)

  def snapshot(self):
    return (dict(self.recv_frame), dict(self.recv_time), dict(self.updated), {k: id(v) for k, v in self.items()})


def _selfdrive_state(size, text1, status, alert_type, enabled=True):
  from openpilot.cereal import messaging
  m = messaging.new_message("selfdriveState")
  s = m.selfdriveState
  s.enabled = enabled
  s.alertSize = size
  s.alertText1 = text1
  s.alertText2 = "detail" if text1 else ""
  s.alertStatus = status
  s.alertType = alert_type
  return m.as_reader().selfdriveState


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires native headless raylib")
class TestSecondAlertReadChangesNoRendererState(NativeBase):
  """The same check against the real alert renderer (BogPilotAlertRenderer over the stock AlertRenderer), real
  selfdriveState messages and the real HudComposer.full_alert_pending, over: every alert size, a held full alert, a
  stale full alert, an old alert from before onroad, startup-pending, lost communication (critical timeout, then
  reboot) and recovery. Alert sounds, alert timers and start frames are owned by selfdrived's AlertManager and soundd,
  which only the selfdriveState message connects to the UI; the UI side only reads it. So: the extra read leaves the
  renderer, ui_state and the SubMaster unchanged, publishes nothing, the UI alert modules create no AlertManager or
  publisher, and a renderer that gets the extra read every frame ends each frame in the same state as one that does not."""

  STEPS = (
    # name, size, text1, status, alert type, updated, recv_frame, age of last selfdriveState (s), clock (s), enabled
    ("none", "none", "", "normal", "", True, 101, 0.0, 20.0, True),
    ("small", "small", "Small", "normal", "a/small", True, 102, 0.0, 20.05, True),
    ("mid", "mid", "Mid", "userPrompt", "b/mid", True, 103, 0.0, 20.10, True),
    ("full", "full", "Full", "critical", "c/full", True, 104, 0.0, 20.15, True),
    ("full held", "full", "Full", "critical", "c/full", True, 105, 0.0, 20.20, True),
    ("full stale", "full", "Full", "critical", "c/full", False, 105, 1.0, 21.20, True),
    ("full to small", "small", "Small", "normal", "a/small", True, 106, 0.0, 21.25, True),
    ("none again", "none", "", "normal", "", True, 107, 0.0, 21.30, True),
    ("old alert", "small", "Old", "normal", "o/old", True, 99, 0.0, 21.35, True),
    ("startup pending", "none", "", "normal", "", False, 99, 30.0, 30.0, True),
    ("critical timeout", "none", "", "normal", "", False, 108, 6.0, 40.0, True),
    ("reboot", "none", "", "normal", "", False, 108, 20.0, 54.0, True),
    ("recover full", "full", "Back", "critical", "c/back", True, 109, 0.0, 54.05, True),
    ("recover none", "none", "", "normal", "", True, 110, 0.0, 54.10, True),
  )

  def expected(self, ar, name, text1):
    return {"none": None, "none again": None, "recover none": None, "old alert": None,
            "startup pending": ar.ALERT_STARTUP_PENDING, "critical timeout": ar.ALERT_CRITICAL_TIMEOUT,
            "reboot": ar.ALERT_CRITICAL_REBOOT}.get(name, text1)

  def test_extra_read_changes_no_state_across_transitions(self):
    import inspect
    from openpilot.cereal import messaging
    from openpilot.selfdrive.ui.onroad import alert_renderer as ar
    from openpilot.selfdrive.ui.onroad.bogpilot import alert_banner as ab
    from openpilot.selfdrive.ui.onroad.bogpilot import hud_compose as hc
    rl = self.rl
    for mod in (ar, ab, hc):
      src = inspect.getsource(mod)
      self.assertNotIn("AlertManager(", src, mod.__name__)
      self.assertNotIn("PubMaster(", src, mod.__name__)
    sm = _SM()
    ui = SimpleNamespace(sm=sm, started=True, started_frame=100, started_time=0.0)
    clock = [0.0]
    rect = rl.Rectangle(30, 30, 2100, 1020)
    with mock.patch.object(ar, "ui_state", ui), mock.patch.object(ab, "ui_state", ui), \
         mock.patch.object(ar, "time", SimpleNamespace(monotonic=lambda: clock[0])), \
         mock.patch.object(ar, "COMMA_HARDWARE", True), \
         mock.patch.object(messaging.PubMaster, "send") as sends:
      plain = ab.BogPilotAlertRenderer(redesign_fn=lambda: True)
      probed = ab.BogPilotAlertRenderer(redesign_fn=lambda: True)
      oracle = ab.BogPilotAlertRenderer(redesign_fn=lambda: True)          # expectations only; plain never reads twice

      def paint(r):
        rl.begin_drawing()
        try:
          r.render(rect)
        finally:
          rl.end_drawing()

      def state():
        return (_snap(probed, False), sm.snapshot(), dict(vars(ui)))

      def extra_read():
        sm.locked = True
        try:
          return hc.HudComposer.full_alert_pending(SimpleNamespace(alert=probed, state=SimpleNamespace(sm=sm)))
        finally:
          sm.locked = False

      for name, size, text1, status, atype, updated, frame, age, now, enabled in self.STEPS:
        sm.locked = False
        sm["selfdriveState"] = _selfdrive_state(size, text1, status, atype, enabled)
        sm.updated["selfdriveState"] = updated
        sm.recv_frame["selfdriveState"] = frame
        sm.recv_time["selfdriveState"] = now - age
        clock[0] = now

        want = self.expected(ar, name, text1)
        got = oracle.get_alert(sm)
        if isinstance(want, str):
          self.assertEqual(got.text1, want, name)
        else:
          self.assertIs(got, want, name)

        paint(plain)
        before = state()
        full = extra_read()
        self.assertEqual(state(), before, name)
        self.assertEqual(full, got is not None and got.size == hc.FULL, name)
        paint(probed)
        after = state()
        extra_read()
        self.assertEqual(state(), after, name)

        self.assertEqual(plain.plan, probed.plan, name)
        self.assertEqual(_snap(plain, True), _snap(probed, True), name)
      self.assertEqual(sends.call_count, 0)


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires native headless raylib")
class TestBallOnPixels(NativeBase):
  """Ball ON, real pixels, rendered off-screen into its own 2160x1080 render texture with the same flush and read-back as
  TestPixelsMatchPreChange. DISENGAGED and ENGAGED x left and right edge x high / mid / low model confidence (model data present,
  no flame track, no alert). The centre pixel (renderer.last_draw, Y flipped for the bottom-up texture) must equal EXACTLY the
  colour of the ball's own 1 px scanline at that pixel row, or of the adjacent scanline one row either way (the rows sit at
  sub-pixel heights); no per-channel tolerance. Disengaged = slate (high) to white (low) shaded by 82/255, engaged = the engaged palette.
  The ball is on the chosen edge strip and the same strip on the other edge shows none of the ball's colours."""

  CONFIDENCE = {"high": 0.0, "mid": 0.5, "low": 0.9}   # disengage probability -> confidence 1.0 / 0.25 / 0.01

  def render(self, status, right, prob):
    from openpilot.selfdrive.ui.onroad import augmented_road_view as arv
    from openpilot.selfdrive.ui.onroad.bogpilot import confidence_ball as cb
    rl = self.rl
    h = TailBase()
    h.setUp()
    h.toggles["RedesignUI"] = True
    model, hud, alert, dm = TestPixelsMatchPreChange.components(self, h.calls, None)
    c = h.ns["HudComposer"](model, hud, alert, dm, layers={}, policy=h.policy, traffic=h.traffic, clock=lambda: 100.0,
                            state=h.state, toggle_get=lambda k: h.toggles[k])
    c.border_color = lambda base: base
    c.bsm_border = lambda: None
    c.BSM_BORDER_RGBA = (255, 0, 0, 255)
    v = arv.AugmentedRoadView.__new__(arv.AugmentedRoadView)
    v._switch_stream_if_needed = lambda sm: None
    v._update_calibration = lambda: None
    v.model_renderer = SimpleNamespace()
    v._hud_compose = c
    ball = cb.ConfidenceBallRenderer(read_toggle=lambda: True, read_side=lambda: right, clock=lambda: 1e9, fps=20.0)
    v._confidence_ball = ball
    sm = self.sm(brake=(prob,), steer=(prob,))
    brake, steer = ball._model_probs(sm)
    for _ in range(200):                                               # settle the height filter on this model output
      ball.state.update(True, status.name, brake, steer)
    rect = rl.Rectangle(0, 0, 2160, 1080)
    camera = lambda s, r: rl.draw_rectangle_rec(r, rl.Color(90, 110, 130, 255))
    ui = SimpleNamespace(started=True, sm=sm, status=status)
    with mock.patch.object(arv, "ui_state", ui), mock.patch.object(arv.CameraView, "_render", camera):
      target = rl.load_render_texture(2160, 1080)
      try:
        rl.begin_texture_mode(target)
        try:
          rl.clear_background(rl.BLACK)
          v._render(rect)
          rl.rl_draw_render_batch_active()
        finally:
          rl.end_texture_mode()
        img = rl.load_image_from_texture(target.texture)
      finally:
        rl.unload_render_texture(target)
    try:
      self.assertEqual((img.width, img.height), (2160, 1080))

      def px(x, y):                                                    # frame (x, y) -> bottom-up texture row 1079 - y
        col = rl.get_image_color(img, int(x), 1079 - int(y))
        return (col.r, col.g, col.b, col.a)
      self.assertIsNotNone(ball.last_draw)
      cx, cy, top, bottom = ball.last_draw
      opp_cx = L.ball_center_x(0, 2160, not right)
      y0 = cy - L.RADIUS
      rows = range(max(0, int(y0)), min(1080, int(y0 + 2 * L.RADIUS) + 1))
      pixels = {"centre": px(cx, cy), "up": px(cx, cy - 10), "down": px(cx, cy + 10),
                "s_top": px(cx, cy - L.RADIUS + 3), "s_mid": px(cx, cy), "s_bottom": px(cx, cy + L.RADIUS - 3),
                "opposite": [px(opp_cx, r) for r in rows]}
    finally:
      rl.unload_image(img)
    return ball, pixels

  @staticmethod
  def scanline(top, bottom, cy, y):
    """Colours of the scanline covering frame pixel row y (and its neighbours) for a ball centred at cy."""
    y0 = cy - L.RADIUS
    i = int(math.floor(int(y) + 0.5 - y0))
    n = int(2 * L.RADIUS)
    return {L.lerp_color(top, bottom, (j + 0.5) / (2 * L.RADIUS)) for j in (i - 1, i, i + 1) if 0 <= j < n}

  def test_ball_on_colours_and_edge(self):
    from openpilot.selfdrive.ui.onroad import augmented_road_view as arv
    seen = set()
    for status in (arv.UIStatus.DISENGAGED, arv.UIStatus.ENGAGED):
      for right in (False, True):
        for level, prob in self.CONFIDENCE.items():
          where = (status.name, "right" if right else "left", level)
          ball, p = self.render(status, right, prob)
          cx, cy, top, bottom = ball.last_draw
          x = ball.state.filter.x
          self.assertEqual((top, bottom), L.ball_colors(status.name, x), where)
          if status.name == "DISENGAGED":
            c = L.disengaged_color(x)
            self.assertEqual((top, bottom), (c, L.shade(c)), where)
            if level == "high":
              self.assertEqual(top, L.SLATE, where)
          else:
            self.assertIn((top, bottom), L.ENGAGED_PALETTE, where)
          seen.add((status.name, (top, bottom)))
          self.assertEqual(ball.edge_right, right, where)
          self.assertEqual(cx, L.ball_center_x(0, 2160, right), where)
          self.assertAlmostEqual(cy, L.ball_center_y(x, 1080), places=6, msg=where)
          sx = L.strip_x(0, 2160, right)
          self.assertTrue(sx <= cx - L.RADIUS and cx + L.RADIUS <= sx + L.STRIP_WIDTH, where)
          self.assertIn(p["centre"], self.scanline(top, bottom, cy, cy), (where, p["centre"]))
          self.assertIn(p["up"], self.scanline(top, bottom, cy, cy - 10), (where, p["up"]))
          self.assertIn(p["down"], self.scanline(top, bottom, cy, cy + 10), (where, p["down"]))
          gradient = {L.lerp_color(top, bottom, (j + 0.5) / (2 * L.RADIUS)) for j in range(int(2 * L.RADIUS))}
          self.assertFalse(gradient & set(p["opposite"]), (where, "ball colour on the opposite edge"))
    # engaged covered green, orange and red; disengaged: three different shaded pairs, lighter as confidence falls
    self.assertEqual({pal for s, pal in seen if s == "ENGAGED"}, set(L.ENGAGED_PALETTE))
    dis = {pal for s, pal in seen if s == "DISENGAGED"}
    self.assertEqual(len(dis), 3)
    self.assertIn((L.SLATE, L.shade(L.SLATE)), dis)

  # maintainer-approved shaded mockup: disengage prob -> (top, middle, bottom) sampled at cy - r + 3, cy, cy + r - 3
  MOCKUP = {"high": (0.0, ("#6B7A8A", "#49545E", "#282D33")), "mid": (1 - 0.5 ** 0.5, ("#B0B8BF", "#787E83", "#414446")),
            "low": (0.9, ("#F6F6F6", "#AAAAAA", "#5D5D5D"))}

  def test_disengaged_shaded_pixels_match_the_mockup(self):
    from openpilot.selfdrive.ui.onroad import augmented_road_view as arv
    for level, (prob, want) in self.MOCKUP.items():
      for right in (False, True):
        ball, p = self.render(arv.UIStatus.DISENGAGED, right, prob)
        got = tuple("#%02X%02X%02X" % c[:3] for c in (p["s_top"], p["s_mid"], p["s_bottom"]))
        self.assertEqual(got, want, (level, right))

  def test_engaged_and_override_pixels_unchanged(self):
    from openpilot.selfdrive.ui.onroad import augmented_road_view as arv
    for status, want in ((arv.UIStatus.ENGAGED, L.GREEN), (arv.UIStatus.OVERRIDE, L.OVERRIDE)):
      ball, p = self.render(status, False, 0.0)
      cx, cy, top, bottom = ball.last_draw
      self.assertEqual((top, bottom), want, status.name)
      for k, y in (("s_top", cy - L.RADIUS + 3), ("s_mid", cy), ("s_bottom", cy + L.RADIUS - 3)):
        self.assertIn(p[k], self.scanline(top, bottom, cy, y), (status.name, k))


if __name__ == "__main__":
  unittest.main()
