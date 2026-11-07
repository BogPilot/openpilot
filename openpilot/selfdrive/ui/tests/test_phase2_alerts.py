"""Focused contract tests; no rendering or Params initialization."""
import ast
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).parents[1] / "bogpilot" / "phase2_alerts.py"
spec = importlib.util.spec_from_file_location("phase2_alerts", MODULE_PATH)
alerts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alerts)


class TestPhase2Alerts(unittest.TestCase):
  def test_no_dormant_rows_exposed(self):
    self.assertEqual(alerts.ACTIVE_ALERT_ROWS, ())
    self.assertEqual(alerts.ACTIVE_ALERT_KEYS, ())
    self.assertFalse(alerts.has_active_alerts())

  def test_historical_rows_accounted_for(self):
    self.assertEqual({r[0] for r in alerts.OMITTED_ALERT_ROWS}, {
      "GoatScream", "GreenLightAlert", "LeadDepartingAlert", "LoudBlindspotAlert", "SpeedLimitChangedAlert"})
    self.assertTrue(all(title and reason for _, title, reason in alerts.OMITTED_ALERT_ROWS))

  def test_no_volume_or_parent_switch(self):
    self.assertTrue(all("Volume" not in row[0] for row in alerts.OMITTED_ALERT_ROWS))
    self.assertNotIn("CustomAlerts", alerts.ACTIVE_ALERT_KEYS)

  def test_no_imports_or_writes(self):
    tree = ast.parse(MODULE_PATH.read_text())
    self.assertFalse(any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree)))
    self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr.startswith("put") for n in ast.walk(tree)))

  def test_traceable_revisions(self):
    for revision in (alerts.HISTORICAL_REVISION, alerts.AUDITED_BASE):
      self.assertEqual(len(revision), 40)
      int(revision, 16)


if __name__ == "__main__":
  unittest.main()
