"""t994 INT: the Utilities "Reset BogPilot Settings to Defaults" row must restore SHIPPING defaults.

Uses the REAL registry/overlay tables (review BLOCKER: the lane tests mocked reset_defaults()).
"""
import unittest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.system.bogpilot import toggle_reset as tr_mod


class TestShippingDefaults(unittest.TestCase):
  def test_shipping_on_features_stay_on(self):
    v = tr_mod.shipping_defaults()
    for key in ("GreenLightAlert", "LeadDepartingAlert", "AdjacentLeadsUI"):
      self.assertEqual(v[key], "1", key)

  def test_stock_reset_is_still_stock(self):
    v = tr_mod.reset_defaults()
    for key in ("GreenLightAlert", "LeadDepartingAlert", "AdjacentLeadsUI"):
      self.assertEqual(v[key], "0", key)

  def test_shipping_policy_overlays(self):
    v = tr_mod.shipping_defaults()
    self.assertEqual(v["NudgelessLaneChange"], "0")
    self.assertEqual(v["AlwaysOnLateral"], "0")
    self.assertEqual(v["AlertVolumeControl"], "0")
    self.assertIsNone(v["TuningLevel"])
    self.assertTrue(all(val == "101" for k, val in v.items() if k.endswith("Volume")))

  def test_matches_registry_default_column(self):
    v = tr_mod.shipping_defaults()
    for key in ("ScreenRecorder", "BlindSpotPath"):
      if key in v and key in BOGPILOT_PARAMS and key not in tr_mod.PARAM_OVERRIDES:
        self.assertEqual(v[key], BOGPILOT_PARAMS[key][2], key)

  def test_never_touches_identity_or_auth(self):
    v = tr_mod.shipping_defaults()
    for key in ("DongleId", "CarVin", "SecOCKey", "CalibrationParams", "CarModel", "ForceFingerprint"):
      self.assertNotIn(key, v)


class TestAdoptionMarkersClearedOnReset(unittest.TestCase):
  """INT-B1 (review): a reset device must not keep gas/brake adoption markers (it would drive differently from a fresh install)."""
  MARKERS = ("Phase3LongAccelProfilesEnabled", "Phase3AdvancedLongEnabled", "Phase3CEMEnabled",
             "Phase3StoppedDistanceEnabled", "Phase3ForceStopsEnabled", "Phase3ManualWeatherEnabled",
             "Phase3StopAccelEnabled", "Phase3StoppingRateEnabled")

  def test_both_reset_tables_unset_markers(self):
    for table in (tr_mod.shipping_defaults(), tr_mod.reset_defaults()):
      for key in self.MARKERS:
        self.assertIn(key, table)
        self.assertIsNone(table[key], key)

  def test_markers_are_backed_up_with_settings(self):
    from openpilot.system.bogpilot import settings_backup
    for key in self.MARKERS:
      self.assertIn(key, settings_backup.FILE_KEYS)

  def test_reset_removes_marker_files(self):
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
      for key in self.MARKERS:
        (Path(d) / key).write_text("1")

      class P:
        removed = []
        def all_keys(self): return [tr_mod.REQUEST_KEY]
        def get_bool(self, k): return True
        def remove(self, k): self.removed.append(k)
        def get(self, k): return None
      result = tr_mod.reset_requested(P(), d, backup=lambda: True)
      self.assertEqual(result.status, "completed", result.error)
      for key in self.MARKERS:
        self.assertFalse((Path(d) / key).exists(), key)


if __name__ == "__main__":
  unittest.main()
