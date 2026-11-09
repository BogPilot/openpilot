"""t994 INT: cross-lane contracts (every registered page key has a consumer-backed owner, no forbidden surfaces)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


class TestIntegrationContracts(unittest.TestCase):
  def test_alert_keys_never_written_by_ap1_profile(self):
    from openpilot.common.bogpilot_ap1_profile import NEVER_PROFILE_KEYS, AP1_PARAM_PROFILE
    from openpilot.selfdrive.ui.bogpilot.phase2_alerts import ACTIVE_ALERT_KEYS
    self.assertTrue(set(ACTIVE_ALERT_KEYS) <= set(NEVER_PROFILE_KEYS))
    for key in ACTIVE_ALERT_KEYS:
      self.assertNotIn(key, AP1_PARAM_PROFILE)

  def test_sidebar_visibility_params(self):
    from openpilot.selfdrive.ui.bogpilot.sidebar_metrics import metric_visibility_from_params

    class P:
      def __init__(self, **kw):
        self.d = kw

      def get_bool(self, k):
        return self.d.get(k)

    self.assertEqual(metric_visibility_from_params(P()), (True, True, True, False))
    self.assertEqual(metric_visibility_from_params(P(ShowCPU=False, ShowMemoryUsage=False, NumericalTemp=False, Fahrenheit=True)),
                     (False, False, False, True))
    src = (ROOT / "openpilot/selfdrive/ui/layouts/sidebar.py").read_text()
    self.assertIn("metric_visibility_from_params(self._params)", src)  # lane commit + patch applied atomically

  def test_registered_groups_and_pages(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import working_pages
    from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import active_groups
    groups = active_groups(working_pages())
    self.assertEqual([g[0] for g in groups], ["alerts_sounds", "vehicle", "system"] if not any(g[0] == "driving" for g in groups)
                     else [g[0] for g in groups])
    titles = {g[0]: [p.title for p in g[2]] for g in groups}
    self.assertEqual(titles["alerts_sounds"], ["Alert Volume Controller", "BogPilot Alerts"])
    self.assertIn("Stalk Controls", titles["vehicle"])
    self.assertNotIn("Wheel Controls", titles["vehicle"])
    self.assertEqual(titles["system"], ["Data", "Device Controls", "Utilities"])

  def test_forbidden_features_absent_from_runtime(self):
    pages = (ROOT / "openpilot/selfdrive/ui/layouts/settings/bogpilot.py").read_text()
    for forbidden in ("GoatScream", "AlwaysOnLateral", "ModelSelector", "model_selector", "TheBog"):
      self.assertNotIn(forbidden, pages)
    self.assertFalse((ROOT / "opendbc_repo/opendbc/car/tesla_ap1/aol_gate.py").exists())

  def test_driving_model_selector_registered_with_stock_safe_launcher(self):
    """t999: BogPilot's own Driving Model page is registered and modeld starts through the fallback-safe launcher."""
    pages = (ROOT / "openpilot/selfdrive/ui/layouts/settings/bogpilot.py").read_text()
    self.assertIn("bogpilot_model_selector", pages)
    self.assertNotIn("phase3_model", pages)  # the retired catalog/downloader UI stays unregistered
    pc = (ROOT / "openpilot/system/manager/process_config.py").read_text()
    self.assertIn("openpilot.selfdrive.modeld.bogpilot_modeld", pc)
    self.assertNotIn("phase3_modeld_launcher", pc)

  def test_stop_accel_rows_registered_t1003u(self):
    pages = (ROOT / "openpilot/selfdrive/ui/bogpilot/phase3_gas_brake.py").read_text()
    controls = pages.split("CONTROLS = (", 1)[1].split(")", 1)[0]
    self.assertIn('"StopAccel"', controls)
    self.assertIn('"StoppingDecelRate"', controls)

  def test_no_lane_artifacts_in_tree(self):
    for name in ("_lane_handoff", "lane_sysDevice", "minus_glyph_proof.png", "HANDOFF.md", "PROPOSED_shared.patch"):
      self.assertFalse((ROOT / name).exists(), name)

  def test_no_third_party_product_names_in_docs(self):
    text = (ROOT / "docs/bogpilot_c3x.md").read_text() + (ROOT / "README.md").read_text()
    self.assertIsNone(re.search(r"sunnypilot|dragonpilot|raspilot", text, re.I))


if __name__ == "__main__":
  unittest.main()
