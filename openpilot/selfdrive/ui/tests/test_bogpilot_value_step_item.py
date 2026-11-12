"""Shared value row and section reset row (selfdrive/ui/bogpilot/gated_actions.py). No window is opened: the tests drive
the callbacks and the release handler directly, as test_bogpilot_gated_actions.py does."""
import unittest
from unittest import mock

import pyray as rl
from openpilot.system.ui.lib.application import MousePos, gui_app
from openpilot.system.ui.widgets.list_view import BUTTON_HEIGHT, RIGHT_ITEM_PADDING, ButtonAction, ListItem
from openpilot.selfdrive.ui.bogpilot.gated_actions import (MINUS, RESET_SECTION_TITLE, GatedMultipleButtonAction,
                                                           GatedValueStepAction, gated_multiple_button_item,
                                                           gated_value_step_item, reset_section_item)
from openpilot.selfdrive.ui.bogpilot.gated_actions import RESET_FAILED_TEXT


class Lock:
  def __init__(self, on=False):
    self.on = on

  def __call__(self):
    return self.on


def tap(action, i):
  y = (200 - BUTTON_HEIGHT) / 2 + BUTTON_HEIGHT / 2
  action._handle_mouse_release(MousePos(i * (action.button_width + RIGHT_ITEM_PADDING) + action.button_width / 2, y))


def place(item):
  a = item.action_item
  a.set_rect(rl.Rectangle(0, 0, len(a.buttons) * a.button_width + (len(a.buttons) - 1) * RIGHT_ITEM_PADDING, 200))
  return a


class NoWindow(unittest.TestCase):
  def setUp(self):
    patcher = mock.patch.object(gui_app, "font", lambda *a, **k: rl.Font())
    patcher.start()
    self.addCleanup(patcher.stop)
    self.calls = []


class TestLayout(NoWindow):
  def test_minus_value_plus_with_ascii_minus(self):
    item = gated_value_step_item("t", "d", "5", enabled=True)
    self.assertIsInstance(item, ListItem)
    a = item.action_item
    self.assertIsInstance(a, GatedValueStepAction)
    self.assertIsInstance(a, GatedMultipleButtonAction)
    self.assertEqual(a.buttons, ["-", "5", "+"])
    self.assertEqual(MINUS, "\u002d")
    self.assertNotIn("\u2212", "".join(str(b) for b in a.buttons))
    self.assertEqual(a.value_index, 1)
    self.assertEqual(a.button_width, 150)

  def test_optional_leading_slot(self):
    a = gated_value_step_item("t", "d", lambda: "Auto", leading=["Mute"], enabled=True).action_item
    self.assertEqual([b if isinstance(b, str) else b() for b in a.buttons], ["Mute", "-", "Auto", "+"])
    self.assertEqual(a.value_index, 2)

  def test_per_button_callbacks_and_value_ignores_taps(self):
    item = gated_value_step_item("t", "d", "5", lambda: self.calls.append("minus"), lambda: self.calls.append("plus"),
                                 leading=["Mute"], on_leading=lambda i: self.calls.append(("lead", i)), enabled=True)
    a = place(item)
    for i in range(4):
      tap(a, i)
    self.assertEqual(self.calls, [("lead", 0), "minus", "plus"])

  def test_raw_index_callback_like_gated_multiple(self):
    a = place(gated_value_step_item("t", "d", "5", leading=["Mute"], callback=self.calls.append, enabled=True))
    for i in range(4):
      tap(a, i)
    self.assertEqual(self.calls, [0, 1, 2, 3])

  def test_no_button_stays_selected_without_selected_index(self):
    a = place(gated_value_step_item("t", "d", "5", lambda: None, lambda: None, enabled=True))
    self.assertEqual(a.selected_button, -1)
    tap(a, 2)
    self.assertEqual(a.selected_button, -1)


class TestHintAndHighlight(NoWindow):
  def test_hint_text(self):
    self.assertEqual(gated_value_step_item("t", "d", "60%", default_text="Auto").action_item.hint_text, "default: Auto")
    stored = {"d": "15 mph"}
    a = gated_value_step_item("t", "d", "5", default_text=lambda: stored["d"]).action_item
    self.assertEqual(a.hint_text, "default: 15 mph")
    stored["d"] = "20 mph"
    self.assertEqual(a.hint_text, "default: 20 mph")
    self.assertEqual(gated_value_step_item("t", "d", "5").action_item.hint_text, "")

  def test_highlight_follows_is_default(self):
    state = {"at_default": True}
    a = gated_value_step_item("t", "d", "5", is_default=lambda: state["at_default"]).action_item
    self.assertFalse(a.highlighted)
    state["at_default"] = False
    self.assertTrue(a.highlighted)
    self.assertFalse(gated_value_step_item("t", "d", "5").action_item.highlighted)

  def test_bad_sources_never_raise(self):
    def broken():
      raise KeyError("missing")
    a = gated_value_step_item("t", "d", "5", default_text=broken, is_default=broken).action_item
    self.assertEqual(a.hint_text, "")
    self.assertFalse(a.highlighted)


class TestGatingParity(NoWindow):
  """Same lock, grey and hide behaviour as gated_multiple_button_item for every state."""

  def pair(self, lock, selected=1):
    self.got = {"step": [], "multi": []}
    step = gated_value_step_item("t", "d", "5", leading=["Mute"], callback=self.got["step"].append, selected_index=selected,
                                 enabled=lock)
    multi = gated_multiple_button_item("t", "d", ["Mute", "-", "5", "+"], selected, button_width=150,
                                       callback=self.got["multi"].append, enabled=lock)
    place(step)
    place(multi)
    return step, multi

  def test_locked_dims_and_ignores_taps(self):
    step, multi = self.pair(Lock(False))
    self.assertEqual((step.action_item.enabled, multi.action_item.enabled), (False, False))
    for i in range(4):
      tap(step.action_item, i)
      tap(multi.action_item, i)
    self.assertEqual(self.got, {"step": [], "multi": []})
    self.assertEqual(step.action_item.selected_button, multi.action_item.selected_button)

  def test_unlock_follows_every_frame_and_taps_match(self):
    lock = Lock(False)
    step, multi = self.pair(lock)
    lock.on = True
    self.assertEqual((step.action_item.enabled, multi.action_item.enabled), (True, True))
    for i in (3, 1, 0):
      tap(step.action_item, i)
      tap(multi.action_item, i)
      self.assertEqual(step.action_item.selected_button, multi.action_item.selected_button)
    self.assertEqual(self.got["step"], self.got["multi"])
    lock.on = False
    tap(step.action_item, 3)
    tap(multi.action_item, 3)
    self.assertEqual(self.got["step"], [3, 1, 0])
    self.assertEqual(self.got["step"], self.got["multi"])

  def test_greyed_row(self):
    for lock in (True, False):
      step, multi = self.pair(lock)
      for item in (step, multi):
        item.set_enabled(False)
      self.assertEqual((step.enabled, multi.enabled), (False, False))
      self.assertEqual(step.action_item.enabled, multi.action_item.enabled)

  def test_hidden_row(self):
    step, multi = self.pair(True)
    for item in (step, multi):
      item.set_visible(False)
    self.assertEqual((step.is_visible, multi.is_visible), (False, False))
    for item in (step, multi):
      item.set_visible(True)
      item.set_level_gate(lambda: False)
    self.assertEqual((step.is_visible, multi.is_visible), (False, False))
    for item in (step, multi):
      item.set_level_gate(lambda: True)
    self.assertEqual((step.is_visible, multi.is_visible), (True, True))

  def test_bool_lock(self):
    step, multi = self.pair(False)
    self.assertEqual((step.action_item.enabled, multi.action_item.enabled), (False, False))


class MockParams:
  def __init__(self, data):
    self.data = dict(data)
    self.writes = []

  def put(self, key, value):
    self.writes.append((key, value))
    self.data[key] = value


class TestResetSectionRow(NoWindow):
  def setUp(self):
    super().setUp()
    self.params = MockParams({"A": "7", "B": "8", "Other": "9"})
    self.asked = []
    self.done = []

  def make(self, lock=True, defaults=None):
    return reset_section_item(defaults if defaults is not None else {"A": "1", "B": "2"}, self.params.put, enabled=lock,
                              request_confirm=lambda text, yes: self.asked.append((text, yes)),
                              on_done=lambda: self.done.append(1))

  def test_row(self):
    item = self.make()
    self.assertEqual(item.title, RESET_SECTION_TITLE)
    self.assertEqual(RESET_SECTION_TITLE, "Reset section to defaults")
    self.assertIsInstance(item.action_item, ButtonAction)
    self.assertEqual(item.action_item.text, "RESET")

  def test_confirm_required(self):
    item = self.make()
    item.callback()
    self.assertEqual(len(self.asked), 1)
    self.assertEqual(self.params.writes, [])          # nothing written before the yes
    self.assertEqual(self.done, [])

  def test_yes_writes_only_listed_keys_with_defaults(self):
    item = self.make()
    item.callback()
    self.asked[0][1]()
    self.assertEqual(self.params.writes, [("A", "1"), ("B", "2")])
    self.assertEqual(self.params.data, {"A": "1", "B": "2", "Other": "9"})
    self.assertEqual(self.done, [1])

  def test_failed_write_is_reported_and_stops(self):
    told = []
    def write(key, value):
      if key == "B":
        raise OSError("store unavailable")
      self.params.put(key, value)
    item = reset_section_item({"A": "1", "B": "2", "C": "3"}, write, enabled=True,
                              request_confirm=lambda text, yes: self.asked.append((text, yes)),
                              on_done=lambda: self.done.append(1), report_failure=told.append)
    item.callback()
    self.asked[0][1]()
    self.assertEqual(self.params.writes, [("A", "1")])   # stops at the failing key; C left alone
    self.assertEqual(told, [RESET_FAILED_TEXT])
    self.assertEqual(self.done, [1])                     # the page still refreshes

  def test_no_answer_writes_nothing(self):
    item = self.make()
    item.callback()
    item.callback()
    self.assertEqual(len(self.asked), 2)
    self.assertEqual(self.params.writes, [])

  def test_locked_row_does_not_ask(self):
    item = self.make(lock=Lock(False))
    self.assertFalse(item.action_item.enabled)
    item.callback()
    self.assertEqual(self.asked, [])
    self.assertEqual(self.params.writes, [])

  def test_lock_rechecked_at_yes(self):
    lock = Lock(True)
    item = self.make(lock=lock)
    item.callback()
    lock.on = False                                   # the car started while the dialog was up
    self.asked[0][1]()
    self.assertEqual(self.params.writes, [])
    self.assertEqual(self.done, [])

  def test_defaults_callable_read_at_yes(self):
    table = {"A": "1"}
    item = self.make(defaults=lambda: dict(table))
    item.callback()
    table["A"] = "3"
    self.asked[0][1]()
    self.assertEqual(self.params.writes, [("A", "3")])


if __name__ == "__main__":
  unittest.main()
