"""Experimental Mode purple border (3X composer and comma 4): the steering-arc purple while engaged and Experimental
Mode is on. Precedence: LKAS-fault flash > Traffic Mode / regen-limit red > purple > stock colour. Override and
disengaged keep their stock colours."""
import unittest
from types import SimpleNamespace
from unittest import mock

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.selfdrive.ui.onroad.bogpilot import hud_compose as HC
from openpilot.selfdrive.ui.onroad.bogpilot import c4_arc as A
from openpilot.selfdrive.ui.onroad.bogpilot import steering_arc as ARC
from openpilot.selfdrive.ui.onroad.bogpilot.style import TRAFFIC_RED
from openpilot.selfdrive.ui.onroad.augmented_road_view import BORDER_COLORS

PURPLE = ARC.PURPLE
rgb = lambda c: (c.r, c.g, c.b, c.a)   # noqa: E731


def composer(traffic=False, lkas=False, regen=False):
  c = HC.HudComposer.__new__(HC.HudComposer)
  c.alert = SimpleNamespace(hud_state=lambda: SimpleNamespace(lkas_fault=lkas))
  c.disabled = set()
  c.frame = SimpleNamespace(traffic_mode=traffic, engaged=True, longitudinal=True, full_alert=False, alert=None, sm={})
  c.regen_red = lambda: regen
  return c


class TestPurple(unittest.TestCase):
  def setUp(self):
    self._status, self._sm = ui_state.status, ui_state.sm
    self.addCleanup(setattr, ui_state, "status", self._status)
    self.addCleanup(setattr, ui_state, "sm", self._sm)

  def setup(self, status, experimental):
    ui_state.status = status
    ui_state.sm = {"selfdriveState": SimpleNamespace(experimentalMode=experimental)}

  def test_constant_is_the_steering_arc_purple(self):
    self.assertEqual(PURPLE, (150, 100, 255))
    self.assertEqual(A.BORDER_EXPERIMENTAL, PURPLE + (255,))
    self.assertEqual(A.BORDER_EXPERIMENTAL[:3], A.ARC.PURPLE)

  def test_3x_every_state(self):
    for status, base in BORDER_COLORS.items():
      for exp in (False, True):
        self.setup(status, exp)
        want = PURPLE + (255,) if (exp and status == UIStatus.ENGAGED) else rgb(base)
        self.assertEqual(rgb(composer().border_color(base)), want, (status, exp))

  def test_3x_precedence(self):
    base = BORDER_COLORS[UIStatus.ENGAGED]
    self.setup(UIStatus.ENGAGED, True)
    self.assertEqual(rgb(composer(traffic=True).border_color(base)), rgb(TRAFFIC_RED))   # Traffic Mode red wins
    self.assertEqual(rgb(composer(regen=True).border_color(base)), rgb(TRAFFIC_RED))     # regen-limit red wins
    flash = composer(lkas=True).border_color(base)                                         # LKAS-fault flash wins
    self.assertNotEqual(rgb(flash), PURPLE + (255,))
    self.assertNotEqual(rgb(flash), rgb(TRAFFIC_RED))
    self.setup(UIStatus.ENGAGED, False)
    self.assertEqual(rgb(composer(traffic=True).border_color(base)), rgb(TRAFFIC_RED))

  def test_3x_missing_selfdrive_state_is_stock(self):
    ui_state.status = UIStatus.ENGAGED
    ui_state.sm = {}
    base = BORDER_COLORS[UIStatus.ENGAGED]
    self.assertEqual(rgb(composer().border_color(base)), rgb(base))

  def test_c4_every_state(self):
    for status in ("engaged", "override", "disengaged"):
      for traffic in (False, True):
        for exp in (False, True):
          got = A.border_colour(status, traffic, exp)
          if status == "disengaged":
            want = None
          elif status == "override":
            want = A.BORDER_OVERRIDE
          elif traffic:
            want = A.TRAFFIC_RED
          else:
            want = A.BORDER_EXPERIMENTAL if exp else A.BORDER_ENGAGED
          self.assertEqual(got, want, (status, traffic, exp))

  def test_c4_default_arg_keeps_old_behaviour(self):
    self.assertEqual(A.border_colour("engaged", False), A.BORDER_ENGAGED)

  def test_c4_hud_passes_experimental(self):
    import inspect
    from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_hud
    src = inspect.getsource(bogpilot_hud.BogPilotMiciHudRenderer._bp_c4_border)
    self.assertIn("selfdriveState", src)
    self.assertIn("experimental)", src)


if __name__ == "__main__":
  unittest.main()
