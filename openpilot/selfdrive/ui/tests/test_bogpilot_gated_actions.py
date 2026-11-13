"""D2: BogPilot gated list actions (selfdrive/ui/bogpilot/gated_actions.py). Stock list_view.py is not changed.

No window is opened: the tests drive the callbacks and the release handler directly, the same paths Widget.render
uses after its `if self.enabled` touch gate (system/ui/widgets/__init__.py)."""
import ast
import re
import unittest
from pathlib import Path
from unittest import mock

import pyray as rl

from openpilot.system.ui.lib.application import MousePos, gui_app
from openpilot.system.ui.widgets.list_view import (BUTTON_HEIGHT, RIGHT_ITEM_PADDING, DualButtonAction, ListItem,
                                                   MultipleButtonAction)
from openpilot.selfdrive.ui.bogpilot.gated_actions import (GatedDualButtonAction, GatedMultipleButtonAction,
                                                           gated_dual_button_item, gated_multiple_button_item)

UI = Path(__file__).resolve().parents[1]


class Lock:
  def __init__(self, on=False):
    self.on = on

  def __call__(self):
    return self.on


def tap(action, i):
  """Release inside button i of a MultipleButtonAction laid out at (0, 0, w, 200)."""
  y = (200 - BUTTON_HEIGHT) / 2 + BUTTON_HEIGHT / 2
  action._handle_mouse_release(MousePos(i * (action.button_width + RIGHT_ITEM_PADDING) + action.button_width / 2, y))


class NoWindow(unittest.TestCase):
  """Widgets look up fonts at construction; no window is opened here (same patch as test_bogpilot_model_alert.py)."""
  def setUp(self):
    patcher = mock.patch.object(gui_app, "font", lambda *a, **k: rl.Font())
    patcher.start()
    self.addCleanup(patcher.stop)
    self.calls = []


class TestGatedDualButton(NoWindow):
  def setUp(self):
    super().setUp()
    self.calls = []
    self.lock = Lock(False)
    self.a = GatedDualButtonAction("-", "+", lambda: self.calls.append("L"), lambda: self.calls.append("R"), enabled=self.lock)

  def test_is_stock_subclass(self):
    self.assertIsInstance(self.a, DualButtonAction)

  def test_locked_buttons_disabled_and_refuse(self):
    self.assertFalse(self.a.enabled)
    self.assertFalse(self.a.left_button.enabled)
    self.assertFalse(self.a.right_button.enabled)
    self.a.left_button._click_callback()
    self.a.right_button._click_callback()
    self.assertEqual(self.calls, [])

  def test_unlock_follows_every_frame(self):
    self.lock.on = True
    self.assertTrue(self.a.left_button.enabled and self.a.right_button.enabled)
    self.a.left_button._click_callback()
    self.a.right_button._click_callback()
    self.assertEqual(self.calls, ["L", "R"])
    self.lock.on = False   # going onroad again
    self.assertFalse(self.a.left_button.enabled)
    self.a.right_button._click_callback()
    self.assertEqual(self.calls, ["L", "R"])

  def test_bool_enabled_and_no_callback(self):
    a = GatedDualButtonAction("a", "b", None, None, enabled=False)
    self.assertFalse(a.left_button.enabled)
    self.assertIsNone(a.left_button._click_callback)

  def test_stock_gap_still_present_in_stock(self):
    """Documents why the subclass exists: stock DualButtonAction leaves its buttons enabled while locked."""
    s = DualButtonAction("a", "b", None, None, enabled=False)
    self.assertFalse(s.enabled)
    self.assertTrue(s.left_button.enabled)

  def test_factory(self):
    item = gated_dual_button_item("-", "+", lambda: None, lambda: None, enabled=False)
    self.assertIsInstance(item, ListItem)
    self.assertIsInstance(item.action_item, GatedDualButtonAction)
    self.assertFalse(item.action_item.right_button.enabled)


class TestGatedMultipleButton(NoWindow):
  def make(self, enabled, source=None, selected=0):
    self.calls = []
    a = GatedMultipleButtonAction(["A", "B", "C"], 150, selected, callback=self.calls.append, enabled=enabled,
                                  selected_source=source)
    a.set_rect(rl.Rectangle(0, 0, 3 * 150 + 2 * RIGHT_ITEM_PADDING, 200))
    return a

  def test_is_stock_subclass(self):
    self.assertIsInstance(self.make(True), MultipleButtonAction)

  def test_locked_tap_no_callback_no_highlight_move(self):
    a = self.make(Lock(False), selected=0)
    tap(a, 2)
    self.assertEqual(self.calls, [])
    self.assertEqual(a.selected_button, 0)

  def test_unlocked_tap_matches_stock(self):
    a = self.make(Lock(True), selected=0)
    s = MultipleButtonAction(["A", "B", "C"], 150, 0, callback=lambda i: None)
    s.set_rect(rl.Rectangle(0, 0, 3 * 150 + 2 * RIGHT_ITEM_PADDING, 200))
    tap(a, 2)
    tap(s, 2)
    self.assertEqual(self.calls, [2])
    self.assertEqual(a.selected_button, s.selected_button)

  def test_refused_write_shows_stored_choice(self):
    stored = {"v": 1}

    def refuse(i):   # the editor refuses: nothing stored
      self.calls.append(i)
    a = GatedMultipleButtonAction(["A", "B", "C"], 150, 1, callback=refuse, enabled=True, selected_source=lambda: stored["v"])
    a.set_rect(rl.Rectangle(0, 0, 490, 200))
    tap(a, 2)
    self.assertEqual(self.calls, [2])
    self.assertEqual(a.selected_button, 1)

  def test_accepted_write_shows_new_choice(self):
    stored = {"v": 0}
    a = GatedMultipleButtonAction(["A", "B", "C"], 150, 0, callback=lambda i: stored.update(v=i), enabled=True,
                                  selected_source=lambda: stored["v"])
    a.set_rect(rl.Rectangle(0, 0, 490, 200))
    tap(a, 1)
    self.assertEqual((stored["v"], a.selected_button), (1, 1))

  def test_bad_source_never_raises(self):
    a = self.make(True, source=lambda: [].index(3), selected=2)
    a._sync_selected()
    self.assertEqual(a.selected_button, 2)
    b = self.make(True, source=lambda: 7, selected=1)   # out of range: stock set_selected_button ignores it
    self.assertEqual(b.selected_button, 1)

  def test_factory(self):
    item = gated_multiple_button_item("t", "d", ["A", "B"], 1, button_width=100, enabled=False)
    self.assertIsInstance(item.action_item, GatedMultipleButtonAction)
    self.assertFalse(item.action_item.enabled)
    self.assertEqual(item.action_item.selected_button, 1)


class WeatherStore:
  def __init__(self, value):
    self.value = value

  def get(self, key, default=None):
    return self.value if key == "BogPilotManualWeather" else default


class TestStoppingWeatherRowShowsStored(NoWindow):
  """Stopping > Weather > Manual Weather Condition: the highlight is the stored choice, even after a locked tap."""
  def build(self, store, can_edit):
    from openpilot.selfdrive.ui.bogpilot import gated_actions
    from openpilot.selfdrive.ui.bogpilot import phase3_stopping_settings as st
    made, real = [], gated_actions.gated_multiple_button_item

    def spy(*args, **kwargs):
      made.append(real(*args, **kwargs))
      return made[-1]
    row = st.Row(st.MANUAL_WEATHER_KEY, "Manual Weather Condition", "condition", description="d")
    with mock.patch.object(st.StoppingSettingsModel, "rows", lambda self, page="root": [row]), \
         mock.patch.object(gated_actions, "gated_multiple_button_item", spy):
      st.StoppingSettingsLayout(store, None, None, can_edit=can_edit, start_page="weather")
    self.assertEqual(len(made), 1)
    return made[0].action_item, list(st.MANUAL_WEATHER)

  def test_follows_store(self):
    store = WeatherStore("rain")
    a, choices = self.build(store, lambda: False)
    self.assertEqual(a.selected_button, choices.index("rain"))
    store.value = "snow"          # changed elsewhere (another page / restore)
    a._sync_selected()            # what _render does every frame
    self.assertEqual(a.selected_button, choices.index("snow"))

  def test_locked_tap_keeps_stored(self):
    a, choices = self.build(WeatherStore("rain_storm"), lambda: False)
    a.set_rect(rl.Rectangle(0, 0, 5 * 135 + 4 * RIGHT_ITEM_PADDING, 200))
    tap(a, 0)
    self.assertEqual(a.selected_button, choices.index("rain_storm"))

  def test_unknown_stored_value_keeps_build_index(self):
    a, _ = self.build(WeatherStore("hail"), lambda: False)
    a._sync_selected()
    self.assertEqual(a.selected_button, 0)


# Every BogPilot settings panel that had a locked-row UI bug (an earlier locked-row audit, rows 1-4, 6, 8, 9, 15,
# 17, 19), plus the already-gated long-accel and stopping choice rows, now builds its rows from gated_actions.
PANELS = {
  "layouts/settings/phase3_speed_control_settings.py": 3,
  "layouts/settings/phase3_long_accel_settings.py": 3,
  "bogpilot/phase3_following.py": 2,
  "bogpilot/phase3_stalk_controls.py": 2,
  "bogpilot/phase3_stopping_settings.py": 3,
  "bogpilot/phase3_steering_tuning.py": 2,   # one shared value-row factory call and one section reset factory call
  "bogpilot/phase3_lanechange.py": 2,
  "bogpilot/phase2_sounds.py": 2,   # the volume value rows and the section reset row
}
STOCK = re.compile(r"(?<![A-Za-z_])(dual_button_item|multiple_button_item|DualButtonAction|MultipleButtonAction)\s*\(")
GATED = ("gated_dual_button_item", "gated_multiple_button_item", "GatedDualButtonAction", "GatedMultipleButtonAction",
         "gated_value_step_item", "GatedValueStepAction", "reset_section_item")


class TestPanelsUseGatedActions(unittest.TestCase):
  def test_no_stock_dual_or_multiple_in_bogpilot_panels(self):
    files = list((UI / "bogpilot").glob("*.py")) + [UI / p for p in PANELS if p.startswith("layouts/")]
    for f in files:
      if f.name == "gated_actions.py":
        continue
      self.assertIsNone(STOCK.search(f.read_text()), f)

  def test_every_gated_call_passes_a_lock(self):
    for rel, n in PANELS.items():
      tree = ast.parse((UI / rel).read_text())
      calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "id", None) in GATED]
      self.assertEqual(len(calls), n, rel)
      for c in calls:
        locked = any(k.arg == "enabled" for k in c.keywords)
        follows = None
        if not locked:   # long-accel / stopping choice rows lock via item.action_item.set_enabled(...) right after
          follows = re.search(r"item\.action_item\.set_enabled\(", (UI / rel).read_text().split("\n", c.lineno)[-1][:400])
        self.assertTrue(locked or follows, f"{rel}:{c.lineno}")

  def test_stock_actions_not_patched(self):
    """D2 option 2: the fix lives here, not in list_view.py (its Dual/Multiple actions stay v0.11.2 code)."""
    import inspect
    src = (UI.parents[1] / "system/ui/widgets/list_view.py").read_text()
    self.assertNotIn("gated", src.lower())
    self.assertNotIn("set_enabled", inspect.getsource(DualButtonAction))
    self.assertNotIn("self.enabled", inspect.getsource(MultipleButtonAction._handle_mouse_release))


if __name__ == "__main__":
  unittest.main()
