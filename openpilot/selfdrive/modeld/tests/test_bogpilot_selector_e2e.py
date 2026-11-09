"""Driving Model page controller -> BogPilot store -> modeld launcher, end to end (fake modeld, real validation)."""
import os
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import alert, selection
from openpilot.common.tests import bogpilot_model_fixtures as fx
from openpilot.selfdrive.modeld import bogpilot_modeld as launcher
from openpilot.selfdrive.modeld.tests.test_bogpilot_modeld import STOCK_DIR, FakeModeld
from openpilot.selfdrive.ui.bogpilot.bogpilot_model_selector import ModelSelectorController


class TestSelectorEndToEnd(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)
    old = os.environ.get("BOGPILOT_MODELS_DIR")  # the launcher resolves models from the default models dir
    os.environ["BOGPILOT_MODELS_DIR"] = str(self.root)
    self.addCleanup(lambda: os.environ.pop("BOGPILOT_MODELS_DIR") if old is None else os.environ.__setitem__("BOGPILOT_MODELS_DIR", old))
    self.store = fx.MemStore()
    self.offroad = True
    self.ui = ModelSelectorController(lambda: self.offroad, self.store, self.root)

  def drive(self, **behave):
    m = FakeModeld(**behave)
    launcher.run(m, self.store)
    return m

  def test_default_only_page_and_stock_modeld(self):
    snap = self.ui.refresh()
    self.assertTrue(snap.only_default)
    m = self.drive()
    self.assertTrue(m.live.is_stock)
    self.assertEqual(self.store.writes, [])

  def test_ui_choice_is_used_on_the_next_start_only(self):
    d = fx.install_model(self.root, "m", name="Mine")
    first = self.drive()  # a drive that started before the choice was made
    self.assertTrue(first.live.is_stock)
    self.assertTrue(self.ui.select("m").ok)
    self.assertIs(first.live.is_stock, True)  # the running modeld is untouched by the UI change
    self.assertEqual(self.ui.snapshot.status, "Active: Default (stock) | Next drive: Mine")
    second = self.drive()
    self.assertEqual(second.live.pkl, d / "driving.pkl")
    self.assertEqual(self.ui.refresh().status, "Active: Mine")

  def test_onroad_ui_cannot_change_the_model(self):
    fx.install_model(self.root, "m")
    self.offroad = False
    self.assertFalse(self.ui.select("m").ok)
    self.assertTrue(self.drive().live.is_stock)

  def test_failure_shows_alert_page_notice_then_stock_then_retry(self):
    fx.install_model(self.root, "m", name="Mine")
    self.assertTrue(self.ui.select("m").ok)
    m = self.drive(fail_load=True)
    self.assertEqual(m.live.pkl, STOCK_DIR / "driving_tinygrad.pkl")
    snap = self.ui.refresh()
    self.assertIn("Mine", snap.notice)
    self.assertEqual(snap.notice, alert.current_alert(self.store)["text"])
    self.assertEqual(snap.status, "Active: Default (stock)")
    self.assertTrue(self.drive().live.is_stock)  # blocked, no retry loop
    self.assertTrue(self.ui.select("m").ok)  # explicit retry
    self.assertEqual(self.ui.snapshot.notice, "")
    self.assertFalse(self.drive().live.is_stock)

  def test_corrupted_after_selection_falls_back_and_page_says_why(self):
    d = fx.install_model(self.root, "m", name="Mine")
    self.assertTrue(self.ui.select("m").ok)
    b = bytearray((d / "driving.pkl").read_bytes())
    b[-1] ^= 1
    (d / "driving.pkl").write_bytes(bytes(b))
    self.assertTrue(self.drive().live.is_stock)
    self.assertIn("hash mismatch", self.ui.refresh().notice)
    self.assertTrue(self.ui.select("default").ok)
    self.assertEqual(self.ui.snapshot.notice, "")
    self.assertIsNone(self.store.raw(selection.KEY_SELECTION))


if __name__ == "__main__":
  unittest.main()
