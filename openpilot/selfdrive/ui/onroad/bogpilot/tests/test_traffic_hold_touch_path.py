"""Personality-button hold end to end: raylib touch state -> MouseState -> Widget mouse dispatch ->
AugmentedRoadView press/release -> HudComposer -> OnroadDistanceButtonPressed (real Params) -> card's
TrafficModeHold -> carState.bogpilot -> bogpilotCarState -> the HUD's reader and button.

Only the finger and the clock are simulated: raylib's edge flags are rebuilt the way PollInputEvents builds them
(one poll sees a press or a release edge, the next does not), MouseState runs its real change filter at ~140 Hz,
the widget its real _process_mouse_events once per UI frame (20 Hz), and card its 100 Hz consumer.
On the road, holds never registered; carState.bogpilot.trafficModeEnabled stayed false on every sample.
"""
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

import pyray as rl

from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.common.traffic_mode_hold import TrafficModeHold
from openpilot.selfdrive.car.bogpilot_card import bogpilot_car_state
from openpilot.selfdrive.ui.onroad.augmented_road_view import AugmentedRoadView
from openpilot.selfdrive.ui.onroad.bogpilot import hud_compose as HC
from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_border_dm_button import Base, SM, TestDmAndButton, composer
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import MouseState, gui_app
from openpilot.system.ui.widgets import Widget

PRESSED = "OnroadDistanceButtonPressed"
TICK = 0.001
UI_PERIOD, CARD_PERIOD, MOUSE_PERIOD = 0.050, 0.010, 1 / 140


class Finger:
  """The touch controller as raylib reports it for slot 0."""

  def __init__(self):
    self.cur = self.want = False
    self.pressed = self.released = False
    self.x = self.y = 0.0

  def put_down(self, x, y):
    self.want, self.x, self.y = True, x, y

  def move(self, x, y):
    self.x, self.y = x, y

  def lift(self):
    self.want = False

  def poll(self):
    self.pressed = self.want and not self.cur
    self.released = self.cur and not self.want
    self.cur = self.want


class StubSM:
  """SubMaster stand-in for the one topic TrafficModeReader reads."""

  def __init__(self, msg, recv_time):
    self.msg = msg
    self.valid = self.alive = {"bogpilotCarState": True}
    self.recv_time = {"bogpilotCarState": recv_time}

  def update(self, _timeout):
    pass

  def __getitem__(self, _name):
    return self.msg


class Rig:
  def __init__(self, test, traffic=False):
    self.t = 0.0
    self.finger = Finger()
    f = self.finger
    self._rl = (rl.get_touch_position, rl.is_mouse_button_pressed, rl.is_mouse_button_released, rl.is_mouse_button_down)
    rl.get_touch_position = lambda slot: rl.Vector2(f.x, f.y)
    rl.is_mouse_button_pressed = lambda slot: slot == 0 and f.pressed
    rl.is_mouse_button_released = lambda slot: slot == 0 and f.released
    rl.is_mouse_button_down = lambda slot: slot == 0 and f.cur
    self.mouse = MouseState()
    self.params = Params()
    self.params.put_bool(PRESSED, False, True)
    self.params.put("LongitudinalPersonality", 1, True)
    ui_state.sm = SM(personality=1)
    self.composer = composer()
    self.composer.clock = lambda: self.t
    self.frame = TestDmAndButton().frame(traffic=traffic)
    self.composer._keepouts(self.frame, True)
    self.composer.frame = self.frame
    pill = self.frame.personality_rect
    self.centre = (pill.x + pill.width / 2, pill.y + pill.height / 2)
    self.sidebar_clicks = 0
    view = AugmentedRoadView.__new__(AugmentedRoadView)
    Widget.__init__(view)
    view.close = lambda: None   # CameraView.__del__ closes GL resources that this rig never opens
    view._rect = rl.Rectangle(0, 0, 2160, 1080)
    view._hud_compose = self.composer
    view._hud_renderer = SimpleNamespace(user_interacting=lambda: False)
    view.set_click_callback(self._sidebar)
    self.view = view
    self.hold = TrafficModeHold()
    self.traffic = False
    self.next_ui = self.next_card = self.next_mouse = 0.0
    test.addCleanup(self.restore)

  def _sidebar(self):
    self.sidebar_clicks += 1

  def restore(self):
    rl.get_touch_position, rl.is_mouse_button_pressed, rl.is_mouse_button_released, rl.is_mouse_button_down = self._rl
    gui_app._mouse_events = []

  def run(self, seconds):
    end = self.t + seconds
    while self.t < end - 1e-9:
      if self.t >= self.next_mouse:
        self.next_mouse += MOUSE_PERIOD
        self.finger.poll()
        self.mouse._handle_mouse_event()
      if self.t >= self.next_ui:
        self.next_ui += UI_PERIOD
        gui_app._mouse_events = self.mouse.get_events()
        Widget._process_mouse_events(self.view)
      if self.t >= self.next_card:
        self.next_card += CARD_PERIOD
        # card.state_update: the same two lines
        self.traffic = self.hold.update_button(self.params.get_bool(PRESSED), self.t)
        self.frame.traffic_mode = self.traffic
      self.t += TICK

  def touch(self, seconds, pos=None, jitter=False):
    x, y = pos or self.centre
    self.finger.put_down(x, y)
    n = int(seconds / 0.1)
    for i in range(n):
      self.run(0.1)
      if jitter:
        self.finger.move(x + (i % 3) - 1, y + (i % 2))
    self.run(seconds - n * 0.1)
    self.finger.lift()
    self.run(0.2)

  def personality(self):
    return self.params.get("LongitudinalPersonality")


class TestTrafficHoldTouchPath(Base):
  def rig(self, **kw):
    return Rig(self, **kw)

  def test_tap_cycles_personality_and_never_toggles_traffic(self):
    r = self.rig()
    r.touch(0.2)
    self.assertEqual(int(r.personality()), 0)          # standard -> aggressive, like the stalk
    self.assertFalse(r.traffic)
    self.assertFalse(r.params.get_bool(PRESSED))
    self.assertEqual(r.sidebar_clicks, 0)

  def test_hold_just_under_one_second_is_a_tap(self):
    r = self.rig()
    r.touch(0.8)
    self.assertEqual(int(r.personality()), 0)
    self.assertFalse(r.traffic)

  def test_hold_of_one_second_and_more_toggles_traffic_mode_without_stepping(self):
    for seconds in (1.1, 1.5, 2.5, 4.0):
      with self.subTest(seconds=seconds):
        r = self.rig()
        r.touch(seconds)
        self.assertTrue(r.traffic, seconds)
        self.assertEqual(int(r.personality()), 1)      # no step
        self.assertFalse(r.params.get_bool(PRESSED))
        self.assertEqual(r.sidebar_clicks, 0)

  def test_hold_toggles_while_openpilot_is_disengaged(self):
    # the logged personality taps were all made disengaged (carControl.longActive false 146 s to 267 s); the old gate
    # needed longActive, so nothing here could have toggled. card now has no engagement input at all.
    r = self.rig()
    r.touch(1.2)
    self.assertTrue(r.traffic)

  def test_toggle_fires_while_still_held_once(self):
    r = self.rig()
    r.finger.put_down(*r.centre)
    r.run(0.95)
    self.assertFalse(r.traffic)
    r.run(0.25)
    self.assertTrue(r.traffic)                         # fired at 1.0 s with the finger still down
    r.run(2.0)
    self.assertTrue(r.traffic)                         # no second toggle while held

  def test_second_hold_leaves_traffic_mode(self):
    r = self.rig()
    r.touch(1.2)
    r.frame.traffic_mode = True
    r.touch(1.2)
    self.assertFalse(r.traffic)

  def test_finger_jitter_inside_the_button_still_holds(self):
    r = self.rig()
    r.touch(1.5, jitter=True)
    self.assertTrue(r.traffic)

  def test_press_outside_the_button_is_the_sidebar_and_never_traffic(self):
    r = self.rig()
    r.touch(1.5, pos=(1000.0, 500.0))
    self.assertFalse(r.traffic)
    self.assertEqual(r.sidebar_clicks, 1)
    self.assertFalse(r.params.get_bool(PRESSED))

  def test_tap_in_traffic_mode_is_consumed_and_does_not_step(self):
    r = self.rig(traffic=True)
    r.hold.enabled = True
    r.touch(0.2)
    self.assertEqual(int(r.personality()), 1)
    self.assertTrue(r.traffic)
    self.assertEqual(r.sidebar_clicks, 0)

  def test_latch_survives_unchanged_stalk_and_follows_a_stalk_change(self):
    r = self.rig()
    r.touch(1.2)
    self.assertTrue(r.traffic)
    r.hold.apply_stalk(False)                          # first ready stalk reading is a change: the stalk owns it
    self.assertFalse(r.hold.enabled)
    r.touch(1.2)
    self.assertTrue(r.hold.enabled)
    r.hold.apply_stalk(False)                          # same stalk command: the hold's state stays
    self.assertTrue(r.hold.enabled)
    r.hold.apply_stalk(True)                           # detent 1
    self.assertTrue(r.hold.enabled)
    r.hold.apply_stalk(False)
    self.assertFalse(r.hold.enabled)

  def test_card_mirror_and_hud_reader_see_the_toggle(self):
    r = self.rig()
    r.touch(1.2)
    cs = messaging.new_message("carState").carState
    cs.bogpilot.trafficModeEnabled = r.traffic
    msg = bogpilot_car_state(cs)
    self.assertTrue(msg.trafficModeEnabled)
    now = 100.0
    sm = StubSM(msg, now - 0.02)
    self.assertIs(HC.TrafficModeReader(sm).read(now, 50.0), True)
    cs.bogpilot.trafficModeEnabled = False
    sm.msg = bogpilot_car_state(cs)
    self.assertIs(HC.TrafficModeReader(sm).read(now, 50.0), False)

  def test_card_feeds_the_hold_from_the_ui_param_with_no_engagement_gate(self):
    src = (Path(__file__).resolve().parents[5] / "selfdrive/car/card.py").read_text()
    self.assertRegex(src, r'trafficModeEnabled = self\.traffic_mode_hold\.update_button\(\s*self\.params\.get_bool\("OnroadDistanceButtonPressed"\), time\.monotonic\(\)\)')
    self.assertFalse(re.search(r"update_button\([^)]*long_active", src))
    ui = (Path(__file__).resolve().parents[5] / "selfdrive/ui/onroad/bogpilot/hud_compose.py").read_text()
    self.assertIn('Params().put_bool("OnroadDistanceButtonPressed"', ui)
    for name in ("handle_button_press", "handle_button_release"):
      self.assertIn(name, (Path(__file__).resolve().parents[5] / "selfdrive/ui/onroad/augmented_road_view.py").read_text())


if __name__ == "__main__":
  unittest.main()
