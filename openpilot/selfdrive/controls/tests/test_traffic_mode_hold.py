"""1.0 s on-screen personality-button hold that toggles Traffic Mode."""
import unittest

from openpilot.common.traffic_mode_hold import ONROAD_TRAFFIC_HOLD, TrafficModeHold


class TestTrafficModeHold(unittest.TestCase):
  def test_hold_threshold_is_one_second(self):
    self.assertEqual(ONROAD_TRAFFIC_HOLD, 1.0)

  def test_brief_press_does_not_toggle(self):
    h = TrafficModeHold()
    h.update_button(True, 0.0)
    self.assertFalse(h.update_button(True, 0.999))
    self.assertFalse(h.update_button(False, 1.0))

  def test_one_second_hold_enters_traffic_mode(self):
    h = TrafficModeHold()
    h.update_button(True, 0.0)
    self.assertTrue(h.update_button(True, 1.0))
    self.assertTrue(h.update_button(False, 1.1))

  def test_hold_fires_once_per_press(self):
    h = TrafficModeHold()
    h.update_button(True, 0.0)
    self.assertTrue(h.update_button(True, 1.0))
    self.assertTrue(h.update_button(True, 3.0))  # still held: do not toggle again
    self.assertTrue(h.update_button(False, 3.1))

  def test_second_hold_exits_traffic_mode(self):
    h = TrafficModeHold()
    h.update_button(True, 0.0)
    h.update_button(True, 1.0)
    h.update_button(False, 1.1)
    h.update_button(True, 2.0)
    self.assertFalse(h.update_button(True, 3.0))
    self.assertFalse(h.update_button(False, 3.1))

  def test_hold_enters_traffic_mode_while_disengaged(self):
    # on the road the personality taps were made disengaged; the 0.9.7 longActive gate would have swallowed a hold
    h = TrafficModeHold()
    h.update_button(True, 0.0)
    self.assertTrue(h.update_button(True, 1.0))

  def test_hold_exits_stalk_traffic_mode(self):
    h = TrafficModeHold()
    h.apply_stalk(True)
    self.assertTrue(h.enabled)
    h.update_button(True, 0.0)
    self.assertFalse(h.update_button(True, 1.0))

  def test_update_button_has_no_engagement_argument(self):
    import inspect
    self.assertEqual(list(inspect.signature(TrafficModeHold.update_button).parameters), ["self", "pressed", "now"])

  def test_stalk_detent_one_turns_traffic_mode_on(self):
    h = TrafficModeHold()
    h.apply_stalk(None)
    self.assertFalse(h.enabled)
    h.apply_stalk(True)
    self.assertTrue(h.enabled)
    h.apply_stalk(False)
    self.assertFalse(h.enabled)

  def test_hold_sticks_until_the_next_stalk_move(self):
    h = TrafficModeHold()
    h.apply_stalk(True)
    h.update_button(True, 0.0)
    self.assertFalse(h.update_button(True, 1.0))
    h.update_button(False, 1.1)
    h.apply_stalk(True)  # same stalk command: leave the hold's exit in place
    self.assertFalse(h.enabled)
    h.apply_stalk(False)
    self.assertFalse(h.enabled)
    h.apply_stalk(True)  # rolling back to detent 1 turns it on again
    self.assertTrue(h.enabled)


if __name__ == "__main__":
  unittest.main()
