import math
import unittest

from openpilot.selfdrive.ui.bogpilot import sidebar_metrics as SM
from openpilot.selfdrive.ui.bogpilot.sidebar_metrics import ModeldLoad, Reading, modeld_load_level, modeld_load_reading


class TestModeldLoadSeverity(unittest.TestCase):
  def test_severity_thresholds(self):
    for percent, level in [(0, "good"), (63, "good"), (79, "good"), (80, "warning"), (99, "warning"),
                           (100, "warning"), (101, "danger"), (250, "danger")]:
      with self.subTest(percent=percent):
        self.assertEqual(modeld_load_level(percent), level)

  def test_frame_drop_is_red_at_any_load(self):
    self.assertEqual(modeld_load_level(10, True), "danger")
    self.assertEqual(modeld_load_reading(63.0, True, live=True), Reading("63%", "danger"))

  def test_reading_text_and_levels(self):
    self.assertEqual(modeld_load_reading(63.4, False, live=True), Reading("63%", "good"))
    self.assertEqual(modeld_load_reading(84.0, False, live=True), Reading("84%", "warning"))
    self.assertEqual(modeld_load_reading(112.0, False, live=True), Reading("112%", "danger"))

  def test_unusable_value_is_grey_dash_never_zero(self):
    for bad in (None, float("nan"), float("inf"), -1.0, "50", True):
      with self.subTest(bad=bad):
        self.assertEqual(modeld_load_reading(bad, False, live=True), Reading())


class TestModeldLoadTracker(unittest.TestCase):
  def test_offroad_or_not_publishing_is_grey_dash(self):
    self.assertEqual(modeld_load_reading(63.0, False, live=False), Reading("--", "unknown"))
    m = ModeldLoad()
    self.assertEqual(m.reading(now=0.0), Reading())                       # nothing received yet (offroad)
    m.update(0.030, 0.030, 0.0, now=1.0)
    self.assertEqual(m.reading(now=1.2).level, "good")
    self.assertEqual(m.reading(now=1.0 + SM.MODELD_STALE_S + 0.01), Reading())   # modeld stopped publishing

  def test_value_is_max_of_model_and_driver_over_50ms(self):
    m = ModeldLoad()
    m.update(0.025, 0.040, 0.0, now=0.0)
    self.assertEqual(m.reading(now=0.0), Reading("80%", "warning"))
    m = ModeldLoad()
    m.update(0.0316, None, 0.0, now=0.0)                      # driver monitoring absent: model alone
    self.assertEqual(m.reading(now=0.0), Reading("63%", "good"))
    m = ModeldLoad()
    m.update(None, 0.056, 0.0, now=0.0)
    self.assertEqual(m.reading(now=0.0), Reading("112%", "danger"))

  def test_frame_drop_turns_red_then_holds_then_clears(self):
    m = ModeldLoad()
    m.update(0.030, 0.030, 0.0, now=0.0)
    m.update(0.030, 0.030, 2.5, now=0.05)
    self.assertEqual(m.reading(now=0.06).level, "danger")
    self.assertEqual(m.reading(now=0.05 + SM.MODELD_DROP_HOLD_S - 0.01).level, "danger")
    m.update(0.030, 0.030, 0.0, now=0.05 + SM.MODELD_DROP_HOLD_S + 0.01)
    self.assertEqual(m.reading(now=0.05 + SM.MODELD_DROP_HOLD_S + 0.02).level, "good")

  def test_smoothing_ignores_a_single_spike_but_follows_a_sustained_change(self):
    m = ModeldLoad()
    t = 0.0
    for _ in range(40):
      m.update(0.030, 0.030, 0.0, now=t)
      t += 0.05
    m.update(0.080, 0.030, 0.0, now=t)                        # one 160 percent frame
    self.assertEqual(m.reading(now=t).level, "good")
    for _ in range(60):                                       # 3 s sustained at 90 percent
      t += 0.05
      m.update(0.045, 0.030, 0.0, now=t)
    self.assertEqual(m.reading(now=t).level, "warning")
    self.assertTrue(85 <= int(m.reading(now=t).value[:-1]) <= 90)

  def test_garbage_inputs_do_not_raise_or_poison_state(self):
    m = ModeldLoad()
    m.update(float("nan"), "x", "y", now=0.0)
    self.assertEqual(m.reading(now=0.0), Reading())
    m.update(0.030, 0.030, 0.0, now=0.1)
    m.update(math.inf, -1, None, now=0.15)
    self.assertEqual(m.reading(now=0.15), Reading("60%", "good"))


class TestModeldChipSlot(unittest.TestCase):
  def test_existing_keys_and_saved_values_keep_their_meaning(self):
    self.assertEqual(SM.CHIP_KEYS, ("ShowCPU", "ShowGPU"))
    self.assertEqual(SM.slot_choices({"ShowGPU": True})[0], "gpu")
    self.assertEqual(SM.slot_choices({"ShowCPU": True, "ShowGPU": True})[0], "cpu")
    self.assertEqual(SM.slot_choices({"ShowCPU": True})[0], "cpu")
    self.assertEqual(SM.slot_choices({})[0], "cpu")
    self.assertEqual(SM.slot_choices({"ShowGPU": True, "ModeldChip": False})[0], "gpu")

  def test_modeld_chip_wins_only_when_chosen(self):
    self.assertEqual(SM.slot_choices({"ShowGPU": True, "ModeldChip": True})[0], "modeld")
    self.assertEqual(SM.slot_choices({"ShowCPU": True, "ModeldChip": True})[0], "modeld")

  def test_flag_comes_from_the_file_choice_and_junk_means_off(self):
    on = lambda key: "modeld"   # noqa: E731
    self.assertTrue(SM.slot_flags(lambda k: False, None, on)["ModeldChip"])
    for text in ("auto", "", "MODELD", None, 3):
      self.assertFalse(SM.slot_flags(lambda k: False, None, lambda key, t=text: t)["ModeldChip"], text)
    def boom(key):
      raise OSError(key)
    self.assertFalse(SM.slot_flags(lambda k: False, None, boom)["ModeldChip"])
    self.assertFalse(SM.slot_flags(lambda k: False)["ModeldChip"])   # callers that pass no file reader (older code paths)

  def test_cycle_order_and_writes(self):
    self.assertEqual(SM.CHIP_CYCLE, ("cpu", "gpu", "modeld"))
    self.assertEqual([SM.next_chip(c) for c in ("cpu", "gpu", "modeld", "junk")], ["gpu", "modeld", "cpu", "cpu"])
    self.assertEqual(SM.chip_writes("modeld"), {"ShowCPU": False, "ShowGPU": False})
    self.assertEqual(SM.chip_writes("gpu"), {"ShowCPU": False, "ShowGPU": True})
    self.assertEqual(SM.chip_file_value("modeld"), "modeld")
    self.assertEqual(SM.chip_file_value("cpu"), "auto")
    self.assertEqual(SM.chip_file_value("gpu"), "auto")

  def test_onroad_middle_box_accepts_modeld(self):
    self.assertEqual(SM.vehicle_slot_choice("modeld"), "modeld")
    self.assertEqual(SM.vehicle_slot_shown("modeld", True), "modeld")
    self.assertEqual(SM.vehicle_slot_shown("modeld", False), "vehicle")   # NO PANDA still takes the box back

  def test_file_choice_registered_and_reset(self):
    from openpilot.common.bogpilot_toggles import FILE_CHOICES
    from openpilot.system.bogpilot.toggle_reset import FILE_CHOICE_RESET_KEYS
    self.assertEqual(FILE_CHOICES["SidebarChipSlot"], ("auto", ("auto", "modeld")))
    self.assertIn("SidebarChipSlot", FILE_CHOICE_RESET_KEYS)
    self.assertIn("modeld", FILE_CHOICES["SidebarVehicleSlot"][1])


if __name__ == "__main__":
  unittest.main()
