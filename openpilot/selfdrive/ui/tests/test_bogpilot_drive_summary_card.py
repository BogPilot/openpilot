"""Drive Summary card: drawing, home wiring and dismissal."""
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pyray as rl

from openpilot.selfdrive.ui.bogpilot.drive_summary import DriveSummary, DriveSummaryController, Phase

TITLES = ["% of Drive With openpilot Engaged", "Drive Distance", "Drive Time", '% of Drive In "Experimental Mode"']


class FakeParams:
  def __init__(self, values=None):
    self.values = values or {}

  def get(self, name):
    return self.values.get(name)

  def get_bool(self, name):
    return bool(self.values.get(name, False))


def ready_controller(summary):
  c = DriveSummaryController(lambda: None)
  c.phase, c.summary = Phase.READY, summary
  return c


def draw(card, rect):
  from openpilot.selfdrive.ui.widgets import bogpilot_drive_summary as widget
  with patch.object(widget, "gui_label") as label, patch.object(widget.rl, "draw_rectangle_rounded"):
    card._render(rect)
  return label.call_args_list


class TestDriveSummaryCard(unittest.TestCase):
  def test_four_boxes_with_values_imperial(self):
    from openpilot.selfdrive.ui.widgets.bogpilot_drive_summary import DriveSummaryCard
    card = DriveSummaryCard(ready_controller(DriveSummary(3725, 2794, 931, 1609.344 * 41.6)), FakeParams())
    rect = rl.Rectangle(0, 0, 1005, 895)
    calls = draw(card, rect)
    texts = [c.args[1] for c in calls]
    self.assertIn("Drive Summary", texts)
    for title in TITLES:
      self.assertIn(title, texts)
    for value in ("75%", "42 miles", "1 hour 2 minutes", "24%", "Tap to close"):
      self.assertIn(value, texts)
    for c in calls:
      r = c.args[0]
      self.assertTrue(r.x >= 0 and r.y >= 0 and r.x + r.width <= rect.width + 0.01 and r.y + r.height <= rect.height + 0.01)

  def test_metric_and_singular_units(self):
    from openpilot.selfdrive.ui.widgets.bogpilot_drive_summary import DriveSummaryCard
    card = DriveSummaryCard(ready_controller(DriveSummary(60, 60, 0, 1000)), FakeParams({"IsMetric": True}))
    texts = [c.args[1] for c in draw(card, rl.Rectangle(0, 0, 1005, 895))]
    for value in ("100%", "1 kilometer", "1 minute", "0%"):
      self.assertIn(value, texts)

  def test_waiting_and_no_drive_show_dashes_not_zeros(self):
    from openpilot.selfdrive.ui.widgets.bogpilot_drive_summary import DriveSummaryCard
    for phase, footer in ((Phase.WAITING, "Saving drive stats..."),
                          (Phase.NO_DRIVE, "No drive recorded. Drives count once openpilot engages.")):
      c = DriveSummaryController(lambda: None)
      c.phase = phase
      texts = [call.args[1] for call in draw(DriveSummaryCard(c, FakeParams()), rl.Rectangle(0, 0, 1005, 895))]
      self.assertEqual(texts.count("–"), 4)
      self.assertIn(footer, texts)
      self.assertNotIn("0%", texts)

  def test_tap_dismisses(self):
    from openpilot.selfdrive.ui.widgets.bogpilot_drive_summary import DriveSummaryCard
    c = ready_controller(DriveSummary(60, 30, 0, 0))
    card = DriveSummaryCard(c, FakeParams())
    card._click_callback()
    self.assertEqual(c.phase, Phase.HIDDEN)


class TestHomeWiring(unittest.TestCase):
  def _home(self):
    from openpilot.selfdrive.ui.layouts import home
    obj = home.HomeLayout.__new__(home.HomeLayout)
    obj.params = FakeParams()
    obj.left_column_rect = rl.Rectangle(0, 0, 1005, 895)
    obj._stats_widget = MagicMock()
    obj._drive_summary_card = MagicMock()
    return home, obj

  def test_card_replaces_stats_only_while_visible(self):
    home, obj = self._home()
    obj._drive_summary = ready_controller(DriveSummary(60, 30, 0, 0))
    obj._render_left_column()
    obj._drive_summary_card.render.assert_called_once_with(obj.left_column_rect)
    obj._stats_widget.render.assert_not_called()
    obj._drive_summary.dismiss()
    obj._render_left_column()
    obj._stats_widget.render.assert_called_once_with(obj.left_column_rect)

  def test_onroad_offroad_transition_drives_the_card(self):
    home, obj = self._home()
    store = {"BogPilotStats": json.dumps({"TrackedTime": 100, "LateralTime": 10})}
    obj._drive_summary = DriveSummaryController(lambda: store["BogPilotStats"])
    with patch.object(home, "ui_state", SimpleNamespace(started=True)):
      obj._on_offroad_transition()
    self.assertFalse(obj._drive_summary.visible)
    store["BogPilotStats"] = json.dumps({"TrackedTime": 700, "LateralTime": 460, "BogPilotMeters": 9000})
    with patch.object(home, "ui_state", SimpleNamespace(started=False)):
      obj._on_offroad_transition()
    self.assertEqual(obj._drive_summary.phase, Phase.READY)
    self.assertEqual(obj._drive_summary.summary.engaged_pct, 75)

  def test_source_registers_transition_and_screen_timeout(self):
    from openpilot.selfdrive.ui.layouts import home
    source = Path(home.__file__).read_text()
    self.assertIn("ui_state.add_offroad_transition_callback(self._on_offroad_transition)", source)
    self.assertIn("device.add_interactive_timeout_callback(self._drive_summary.dismiss)", source)
    self.assertIn("self._stats_widget.render(self.left_column_rect)", source)


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestDriveSummaryNativeRender(unittest.TestCase):
  def test_renders_every_phase(self):
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.selfdrive.ui.widgets.bogpilot_drive_summary import DriveSummaryCard
    gui_app.init_window("BogPilot drive summary render")
    rect = rl.Rectangle(40, 145, 1005, 895)
    for phase, summary in ((Phase.READY, DriveSummary(3725, 2794, 931, 66950)), (Phase.WAITING, None), (Phase.NO_DRIVE, None)):
      c = DriveSummaryController(lambda: None)
      c.phase, c.summary = phase, summary
      card = DriveSummaryCard(c, FakeParams())
      rl.begin_drawing()
      try:
        rl.clear_background(rl.BLACK)
        card.render(rect)
      finally:
        rl.end_drawing()
      self.assertEqual(c.phase, phase)


if __name__ == "__main__":
  unittest.main()
