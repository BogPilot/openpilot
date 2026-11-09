"""Native focused tests for Car Selection; temporary Params only."""
import unittest

from openpilot.selfdrive.ui.bogpilot import phase2_car_selection as cs


class FakeParams:
  def __init__(self):
    self.v = {}
  def get(self, key):
    return self.v.get(key)
  def get_bool(self, key):
    val = self.v.get(key, False)
    if isinstance(val, str):
      return val in ("1", "true", "True")
    return bool(val)
  def put(self, key, value, block=False):
    self.v[key] = value
  def put_bool(self, key, value, block=False):
    self.v[key] = bool(value)
  def remove(self, key):
    self.v.pop(key, None)


PLATFORMS = {"TESLA_AP1_MODELS": object(), "MOCK": object(), "TOYOTA_RAV4": object()}


class TestPhase2CarSelection(unittest.TestCase):
  def setUp(self):
    self.p = FakeParams()

  def test_default_is_auto(self):
    self.assertEqual(cs.current_choice(self.p), cs.AUTO)
    self.assertEqual(cs.choice_label(self.p), "Auto")
    self.assertFalse(self.p.get_bool(cs.FORCE_KEY))
    self.assertEqual(cs.selected_fingerprint(self.p, None, PLATFORMS), (None, False))
    self.assertEqual(cs.selected_fingerprint(self.p, "TOYOTA_RAV4", PLATFORMS), ("TOYOTA_RAV4", False))

  def test_apply_model_s_sets_params_but_detection_wins(self):
    self.assertTrue(cs.apply_choice(self.p, cs.AP1_S, offroad=True))
    self.assertEqual(self.p.get(cs.MODEL_KEY), cs.AP1_S_PLATFORM)
    self.assertEqual(self.p.get(cs.MAKE_KEY), cs.AP1_S_MAKE)
    self.assertEqual(self.p.get(cs.MODEL_NAME_KEY), cs.AP1_S_DOC)
    self.assertTrue(self.p.get_bool(cs.FORCE_KEY))
    self.assertEqual(cs.current_choice(self.p), cs.AP1_S)
    # SAFETY: positively detected different car ALWAYS wins (ForceFingerprint ignored)
    self.assertEqual(cs.selected_fingerprint(self.p, "TOYOTA_RAV4", PLATFORMS), ("TOYOTA_RAV4", False))
    # Only when detection failed
    self.assertEqual(cs.selected_fingerprint(self.p, None, PLATFORMS), (cs.AP1_S_PLATFORM, True))

  def test_detected_ap1_wins_even_when_forced(self):
    cs.apply_choice(self.p, cs.AP1_S, offroad=True)
    # detected AP1 + forced = detected wins (used_saved False)
    self.assertEqual(cs.selected_fingerprint(self.p, cs.AP1_S_PLATFORM, PLATFORMS),
                     (cs.AP1_S_PLATFORM, False))

  def test_auto_clears(self):
    cs.apply_choice(self.p, cs.AP1_S, offroad=True)
    self.assertTrue(cs.apply_choice(self.p, cs.AUTO, offroad=True))
    self.assertFalse(bool(cs._text(self.p.get(cs.MODEL_KEY))))
    self.assertFalse(self.p.get_bool(cs.FORCE_KEY))
    self.assertEqual(cs.current_choice(self.p), cs.AUTO)
    self.assertEqual(cs.selected_fingerprint(self.p, None, PLATFORMS), (None, False))

  def test_onroad_refuses_writes(self):
    self.assertFalse(cs.apply_choice(self.p, cs.AP1_S, offroad=False))
    self.assertIsNone(self.p.get(cs.MODEL_KEY))

  def test_model_x_refused_no_invented_platform(self):
    self.assertFalse(cs.apply_choice(self.p, cs.AP1_X, offroad=True))
    self.assertIsNone(self.p.get(cs.MODEL_KEY))
    self.assertNotIn(cs.AP1_X, cs.available_choices())
    self.assertIn("unavailable", cs.CHOICE_LABELS[cs.AP1_X].lower())

  def test_invalid_saved_platform_ignored(self):
    self.p.put(cs.MODEL_KEY, "NOT_A_REAL_PLATFORM")
    self.p.put_bool(cs.FORCE_KEY, True)
    self.assertEqual(cs.selected_fingerprint(self.p, None, PLATFORMS), (None, False))
    self.assertEqual(cs.selected_fingerprint(self.p, "TOYOTA_RAV4", PLATFORMS), ("TOYOTA_RAV4", False))

  def test_saved_without_force_still_fills_none_only(self):
    self.p.put(cs.MODEL_KEY, cs.AP1_S_PLATFORM)
    self.p.put_bool(cs.FORCE_KEY, False)
    self.assertEqual(cs.selected_fingerprint(self.p, None, PLATFORMS), (cs.AP1_S_PLATFORM, True))
    self.assertEqual(cs.selected_fingerprint(self.p, "TOYOTA_RAV4", PLATFORMS), ("TOYOTA_RAV4", False))

  def test_valid_platform_helper(self):
    self.assertTrue(cs.valid_platform(cs.AP1_S_PLATFORM, PLATFORMS))
    self.assertFalse(cs.valid_platform("MOCK", PLATFORMS))
    self.assertFalse(cs.valid_platform("", PLATFORMS))

  def test_labels_document_none_only(self):
    self.assertIn("next time the car starts", cs.CHOICE_DESCRIPTIONS[cs.AUTO])
    self.assertIn("automatic detection returns no car", cs.CHOICE_DESCRIPTIONS[cs.AP1_S])
    self.assertIn("positively detected", cs.CHOICE_DESCRIPTIONS[cs.AP1_S])


if __name__ == "__main__":
  unittest.main()
