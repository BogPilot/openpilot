"""selfdrived half of the Pre-AP brake rule: a brake press that only drops longitudinal does not disengage."""
import inspect
import unittest

from opendbc.car import structs
from openpilot.selfdrive.selfdrived import preap_brake, selfdrived


def cs(brake, standstill=False, lat_only=False):
  c = structs.CarState.new_message(brakePressed=brake, standstill=standstill)
  c.bogpilot.preapLatOnly = lat_only
  return c.as_reader()


class TestPreapBrake(unittest.TestCase):
  def test_stock_rule_is_unchanged_for_every_car_but_pre_ap(self):
    # preapLatOnly is False: rising edge always disengages; held at speed disengages; held at a standstill does not
    self.assertTrue(preap_brake.brake_disengages(cs(True), cs(False)))
    self.assertTrue(preap_brake.brake_disengages(cs(True), cs(True)))
    self.assertFalse(preap_brake.brake_disengages(cs(True, standstill=True), cs(True, standstill=True)))
    self.assertTrue(preap_brake.brake_disengages(cs(True, standstill=True), cs(False)))
    self.assertFalse(preap_brake.brake_disengages(cs(False), cs(False)))
    self.assertFalse(preap_brake.panda_controls_dropped_on_purpose(cs(True)))

  def test_a_press_that_only_drops_longitudinal_does_not_disengage(self):
    self.assertFalse(preap_brake.brake_disengages(cs(True, lat_only=True), cs(False)))
    self.assertFalse(preap_brake.brake_disengages(cs(True, lat_only=True), cs(True)))
    self.assertTrue(preap_brake.panda_controls_dropped_on_purpose(cs(True, lat_only=True)))
    self.assertTrue(preap_brake.panda_controls_dropped_on_purpose(cs(False, lat_only=True)))   # released, still lateral only until a pull

  def test_selfdrived_uses_the_helpers_and_the_gas_and_regen_rules_are_untouched(self):
    src = inspect.getsource(selfdrived.SelfdriveD)
    self.assertIn("brake_disengages(CS, self.CS_prev)", src)
    self.assertIn("panda_controls_dropped_on_purpose(CS)", src)
    self.assertIn("CS.gasPressed and not self.CS_prev.gasPressed and self.disengage_on_accelerator", src)
    self.assertIn("CS.regenBraking and (not self.CS_prev.regenBraking or not CS.standstill)", src)
    # the mismatch rule still counts everything else
    self.assertIn("self.mismatch_counter += 1", src)
    self.assertIn("self.mismatch_counter >= 200", src)


class TestNotArmedAlertExemption(unittest.TestCase):
  """"Cruise didn't arm" must never fire for the panda that is unarmed on purpose (lateral-only after a brake press)."""
  def test_selfdrived_passes_the_exemption_to_the_arm_watch(self):
    src = inspect.getsource(selfdrived.SelfdriveD.update_events)
    self.assertIn("dropped_on_purpose=panda_controls_dropped_on_purpose(CS)", src)

  def test_lateral_only_after_a_brake_press_never_raises_cruise_didnt_arm(self):
    from types import SimpleNamespace
    from openpilot.selfdrive.selfdrived.preap_arm import NOT_ARMED_FRAMES, PreapArmWatch
    watch = PreapArmWatch(SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS"))
    unarmed = [SimpleNamespace(controlsAllowed=False, safetyModel=1)]
    for _ in range(NOT_ARMED_FRAMES * 10):
      self.assertFalse(watch.update(True, unarmed, (), dropped_on_purpose=preap_brake.panda_controls_dropped_on_purpose(cs(True, lat_only=True))))
    # the same unarmed panda with no brake latch (a pull the panda never saw) does raise it
    raised = [watch.update(True, unarmed, (), dropped_on_purpose=preap_brake.panda_controls_dropped_on_purpose(cs(False))) for _ in range(NOT_ARMED_FRAMES)]
    self.assertTrue(raised[-1] and not any(raised[:-1]))


if __name__ == "__main__":
  unittest.main()
