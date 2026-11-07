"""Harness self-tests: fail-closed semantics (synthetic; no pyray/cereal needed)."""
import importlib.util
from pathlib import Path
import sys
import unittest

spec = importlib.util.spec_from_file_location("rc_ui_gate", Path(__file__).resolve().parents[1] / "rc_ui_gate.py")
G = importlib.util.module_from_spec(spec)
sys.modules["rc_ui_gate"] = G
spec.loader.exec_module(G)


class TestFailClosed(unittest.TestCase):
  def test_exit_codes(self):
    self.assertEqual(G.exit_code([]), 2)
    self.assertEqual(G.exit_code([{"status": G.PASS}, {"status": G.PENDING}]), 0)
    self.assertEqual(G.exit_code([{"status": G.PASS}, {"status": G.UNRUN}]), 2)
    self.assertEqual(G.exit_code([{"status": G.UNRUN}, {"status": G.FAIL}]), 1)

  def test_missing_module_is_unrun_not_pass(self):
    with self.assertRaises(G.Unrun):
      G.need("definitely_not_a_module_xyz")

  def test_missing_optional_is_pending(self):
    with self.assertRaises(G.Pending):
      G.optional("definitely_not_a_module_xyz")

  def test_required_cases_registered(self):
    for c in ("alert_last", "alert_last_with_failing_layers", "keepouts_and_no_occlusion", "native_dm_retained",
              "redesign_off_stock", "compact_rhd_dm", "runtime_freshness", "full_alert_native", "full_alert_hides_pill",
              "resize_narrow_fallback", "no_long", "stale_offroad_cleanup", "ext_pedals_arc_vs_alert"):
      self.assertIn(c, G.CASES)

  def test_pure_cases_pass_on_source_tree(self):
    res = {r["case"]: r for r in G.run([n for n, (k, _) in G.CASES.items() if k == "pure"])}
    for name, r in res.items():
      self.assertNotEqual(r["status"], G.FAIL, f"{name}: {r.get('detail')}")


class TestNativeDmFailureAdapter(unittest.TestCase):
  """SYNTHETIC gate-adapter tests; never a renderer/native execution claim."""
  def run_fixture(self, log=None, disabled=None):
    from types import SimpleNamespace
    from unittest.mock import patch
    e = SimpleNamespace(log=["stock_dm", "alert"] if log is None else log,
                        comp=SimpleNamespace(disabled={"lead_lockon", "lead_labels"} if disabled is None else disabled))
    with patch.object(G, "composer_env", return_value=e), patch.object(G, "run_frame"):
      G.alert_last_with_failing_layers()

  def test_current_native_dm_contract(self):
    self.run_fixture()

  def test_missing_peer_disable_rejected(self):
    with self.assertRaisesRegex(AssertionError, "failed layers"):
      self.run_fixture(disabled={"lead_lockon"})

  def test_missing_native_dm_rejected(self):
    with self.assertRaisesRegex(AssertionError, "native DM"):
      self.run_fixture(log=["alert"])

  def test_alert_not_last_rejected(self):
    with self.assertRaisesRegex(AssertionError, "alert not last"):
      self.run_fixture(log=["alert", "stock_dm"])

  def test_obsolete_relocation_rejected(self):
    with self.assertRaisesRegex(AssertionError, "obsolete relocation"):
      self.run_fixture(log=["driver_monitor", "stock_dm", "alert"])


if __name__ == "__main__":
  unittest.main()
