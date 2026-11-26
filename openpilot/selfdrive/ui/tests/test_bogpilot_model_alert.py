"""Driving-model fallback reaches the home-screen offroad alert list (UI -> store state -> alert widget)."""
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import alert, selection
from openpilot.common.tests import bogpilot_model_fixtures as fx

SRC = Path(__file__).resolve().parents[1] / "widgets/offroad_alerts.py"


class TestModelAlertWiring(unittest.TestCase):
  def test_widget_source_reads_the_bogpilot_alert(self):
    s = SRC.read_text()
    self.assertIn("BOGPILOT_MODEL_ALERT_KEY", s)
    self.assertIn("from openpilot.common.bogpilot_models.alert import current_alert", s)
    self.assertEqual(alert.ALERT_KEY, "BogPilot_ModelFallback")

  def test_widget_shows_alert_after_fallback_and_clears_when_user_selects_default(self):
    from unittest import mock
    try:
      # hosts without /sys/firmware/devicetree (docker/VM) pretend to be a tizi so gui_app imports; nothing is rendered
      with mock.patch("openpilot.common.hardware.comma.hardware.get_device_type", lambda: "tizi"):
        from openpilot.selfdrive.ui.widgets import offroad_alerts as oa
        import pyray as rl
        from openpilot.system.ui.lib.application import gui_app
    except Exception as e:  # pyray / device stack not available on this host
      self.skipTest(f"raylib widgets unavailable: {type(e).__name__}")
    store = fx.MemStore()
    with tempfile.TemporaryDirectory() as t:
      fx.install_model(Path(t), "m", name="Fancy")
      self.assertTrue(selection.select("m", lambda: True, store, Path(t)).ok)
      sel = selection.read_selection(store)[0]
      selection.record_fallback(store, sel, "Fancy", "hash mismatch (file changed or corrupt)", "validate")
      real = alert.current_alert
      alert.current_alert = lambda store_=None: real(store)
      try:
        with mock.patch.object(gui_app, "font", lambda *a: rl.Font()):
          w = oa.OffroadAlert()
        before = w.refresh()
        mine = next(a for a in w.sorted_alerts if a.key == oa.BOGPILOT_MODEL_ALERT_KEY)
        self.assertTrue(mine.visible)
        self.assertIn("Fancy", mine.text)
        self.assertEqual(mine.severity, 1)
        self.assertGreaterEqual(before, 1)
        self.assertTrue(selection.select("default", lambda: True, store, Path(t)).ok)
        after = w.refresh()
        self.assertFalse(mine.visible)
        self.assertEqual(after, before - 1)
      finally:
        alert.current_alert = real


if __name__ == "__main__":
  unittest.main()
