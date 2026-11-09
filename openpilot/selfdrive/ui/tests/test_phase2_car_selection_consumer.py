"""Contract: selected_fingerprint only fills None; detection always wins when present."""
import unittest
from openpilot.selfdrive.ui.bogpilot import phase2_car_selection as cs
from openpilot.selfdrive.ui.tests.test_phase2_car_selection import FakeParams, PLATFORMS


class TestSelectionConsumerContract(unittest.TestCase):
  def test_ui_to_store_to_selected_fingerprint(self):
    p = FakeParams()
    self.assertTrue(cs.apply_choice(p, cs.AP1_S, offroad=True))
    self.assertEqual(cs.selected_fingerprint(p, None, PLATFORMS), (cs.AP1_S_PLATFORM, True))
    # detection wins over force
    self.assertEqual(cs.selected_fingerprint(p, "TOYOTA_RAV4", PLATFORMS), ("TOYOTA_RAV4", False))
    self.assertEqual(cs.selected_fingerprint(p, cs.AP1_S_PLATFORM, PLATFORMS), (cs.AP1_S_PLATFORM, False))
    self.assertTrue(cs.apply_choice(p, cs.AUTO, offroad=True))
    self.assertEqual(cs.selected_fingerprint(p, None, PLATFORMS), (None, False))
    self.assertEqual(cs.selected_fingerprint(p, "TOYOTA_RAV4", PLATFORMS), ("TOYOTA_RAV4", False))


if __name__ == "__main__":
  unittest.main()
