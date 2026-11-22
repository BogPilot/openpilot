"""Driving-model choice per drive: a modeld restart keeps the drive's model, a mid-drive choice waits, and every bad
input falls back to the exact stock model."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, alert, launcher, resolve, selection
from openpilot.common.tests import bogpilot_model_fixtures as fx
from openpilot.common.tests.test_bogpilot_model_launcher import STOCK_DIR, FakeModeld

OFF = lambda: True  # noqa: E731
ON = lambda: False  # noqa: E731


def drive(n: int, started: float) -> resolve.DriveContext:
  return resolve.DriveContext(f"boot-a:{n}", started)


class Base(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name) / "models"
    self.root.mkdir()
    self.store = fx.MemStore()
    old = os.environ.get("BOGPILOT_MODELS_DIR")
    os.environ["BOGPILOT_MODELS_DIR"] = str(self.root)
    self.addCleanup(lambda: os.environ.pop("BOGPILOT_MODELS_DIR") if old is None else os.environ.__setitem__("BOGPILOT_MODELS_DIR", old))

  def start(self, d, **behave):
    m = FakeModeld(**behave)
    launcher.run(m, self.store, drive=d)
    return m

  def model_of(self, m) -> str:
    return STOCK_ID if m.live.is_stock else m.live.pkl.parent.name


class TestDefaultUnchanged(Base):
  def test_no_selection_with_a_drive_is_unpatched_stock_and_writes_nothing(self):
    m = FakeModeld()
    original = (m.ModelState, m.modeld_pkl_path, m.MODELS_DIR)
    launcher.run(m, self.store, drive=drive(1, time.time()))
    self.assertEqual((m.ModelState, m.modeld_pkl_path, m.MODELS_DIR), original)
    self.assertEqual((m.live.pkl, m.live.warp), (STOCK_DIR / "driving_tinygrad.pkl", STOCK_DIR / "driving_warp_1928x1208_tinygrad.pkl"))
    self.assertEqual(m.main_calls, 1)
    self.assertEqual(self.store.writes, [])

  def test_no_drive_context_is_the_previous_behaviour(self):
    fx.install_model(self.root, "a")
    selection.select("a", OFF, self.store, self.root)
    self.assertEqual(self.model_of(self.start(None)), "a")
    self.assertNotIn("latch", selection.read_state(self.store))


class TestDeferral(Base):
  def setUp(self):
    super().setUp()
    fx.install_model(self.root, "a")
    fx.install_model(self.root, "b")

  def test_onroad_select_is_refused_and_writes_nothing(self):
    r = selection.select("a", ON, self.store, self.root)
    self.assertFalse(r.ok)
    self.assertIn("offroad", r.message)
    self.assertEqual(self.store.writes, [])

  def test_pick_made_onroad_has_no_effect_until_next_offroad_to_onroad(self):
    """A mid-drive pick, refused or forced into the store, stays off until the next onroad transition."""
    selection.select("a", OFF, self.store, self.root)
    first = drive(1, time.time() + 5)
    self.assertEqual(self.model_of(self.start(first)), "a")
    refused = selection.select("b", ON, self.store, self.root)
    self.assertFalse(refused.ok)
    self.assertEqual(selection.read_selection(self.store)[0].id, "a")
    self.assertEqual(self.model_of(self.start(first)), "a")
    # Forced write during the drive (a bug or another process): the latch still holds A.
    selection.select("b", OFF, self.store, self.root)
    self.assertEqual(selection.read_selection(self.store)[0].id, "b")
    self.assertEqual(self.model_of(self.start(first)), "a")
    next_drive = drive(2, time.time() + 10)
    self.assertNotEqual(next_drive.token, first.token)
    self.assertEqual(self.model_of(self.start(next_drive)), "b")

  def test_restart_in_the_same_drive_keeps_the_latched_model(self):
    selection.select("a", OFF, self.store, self.root)
    d = drive(1, time.time() + 5)  # drive started after the choice
    self.assertEqual(self.model_of(self.start(d)), "a")
    # a later write (another process, a restored backup...) during the drive
    selection.select("b", OFF, self.store, self.root)
    self.assertEqual(self.model_of(self.start(d)), "a")  # manager restarts modeld mid-drive
    self.assertEqual(self.model_of(self.start(drive(2, time.time() + 5))), "b")  # next drive

  def test_choice_made_during_a_default_drive_waits_for_the_next_drive(self):
    d = drive(1, time.time() - 5)
    self.assertEqual(self.model_of(self.start(d)), STOCK_ID)
    selection.select("a", OFF, self.store, self.root)  # recorded after the drive started
    m = self.start(d)
    self.assertEqual(self.model_of(m), STOCK_ID)
    self.assertIs(m.ModelState, m.OriginalModelState)
    self.assertIsNone(alert.current_alert(self.store))  # deferral is not a failure
    self.assertEqual(self.model_of(self.start(drive(2, time.time() + 5))), "a")

  def test_choice_removed_mid_drive_keeps_the_drive_model_then_default(self):
    selection.select("a", OFF, self.store, self.root)
    d = drive(1, time.time() + 5)
    self.assertEqual(self.model_of(self.start(d)), "a")
    self.store.remove(selection.KEY_SELECTION)
    self.assertEqual(self.model_of(self.start(d)), "a")
    self.assertEqual(self.model_of(self.start(drive(2, time.time() + 5))), STOCK_ID)

  def test_corrupt_selection_mid_drive_keeps_the_latched_model(self):
    selection.select("a", OFF, self.store, self.root)
    d = drive(1, time.time() + 5)
    self.start(d)
    self.store.put(selection.KEY_SELECTION, "{not json")
    self.assertEqual(self.model_of(self.start(d)), "a")

  def test_unreadable_latch_falls_back_to_stock_with_alert(self):
    selection.select("a", OFF, self.store, self.root)
    d = drive(1, time.time() + 5)
    self.start(d)
    st = selection.read_state(self.store)
    st["latch"]["sel"] = {"v": 9}
    self.store.put(selection.KEY_STATE, json.dumps(st))
    self.assertEqual(self.model_of(self.start(d)), STOCK_ID)
    self.assertIn("unreadable", selection.read_state(self.store)["fallback"]["reason"])

  def test_record_without_time_is_treated_as_chosen_before_the_drive(self):
    selection.select("a", OFF, self.store, self.root)
    rec = json.loads(self.store.raw(selection.KEY_SELECTION))
    rec.pop("t")
    self.store.put(selection.KEY_SELECTION, json.dumps(rec))
    self.assertEqual(self.model_of(self.start(drive(1, time.time() - 5))), "a")

  def test_select_records_its_time(self):
    before = time.time()
    selection.select("a", OFF, self.store, self.root)
    sel, corrupt = selection.read_selection(self.store)
    self.assertFalse(corrupt)
    self.assertGreaterEqual(sel.t, round(before, 3) - 0.001)


class TestFailClosedAtDriveStart(Base):
  def assert_stock_alert(self, m, contains):
    self.assertEqual(self.model_of(m), STOCK_ID)
    a = alert.current_alert(self.store)
    self.assertIsNotNone(a)
    self.assertIn(contains, a["text"])

  def test_bad_sha_falls_back(self):
    d = fx.install_model(self.root, "a")
    selection.select("a", OFF, self.store, self.root)
    (d / "driving.pkl").write_bytes(fx.driving_pickle_bytes() + b"x")
    self.assert_stock_alert(self.start(drive(1, time.time() + 5)), "Default (stock)")

  def test_missing_file_falls_back(self):
    d = fx.install_model(self.root, "a")
    selection.select("a", OFF, self.store, self.root)
    os.replace(d / "driving.pkl", Path(self.tmp.name) / "moved.pkl")
    self.assert_stock_alert(self.start(drive(1, time.time() + 5)), "missing")

  def test_corrupt_selection_json_falls_back(self):
    self.store.put(selection.KEY_SELECTION, "{not json")
    self.assert_stock_alert(self.start(drive(1, time.time() + 5)), "unreadable")

  def test_unknown_model_id_falls_back(self):
    self.store.put(selection.KEY_SELECTION, json.dumps({"v": 1, "id": "gone", "pin_model": "ab" * 32, "pin_manifest": "cd" * 32}))
    m = self.start(drive(1, time.time() + 5))
    self.assertEqual(self.model_of(m), STOCK_ID)
    self.assertIn("no longer installed", selection.read_state(self.store)["fallback"]["reason"])

  def test_load_failure_falls_back_and_the_drive_stays_stock(self):
    fx.install_model(self.root, "a")
    selection.select("a", OFF, self.store, self.root)
    d = drive(1, time.time() + 5)
    self.assert_stock_alert(self.start(d, fail_load=True), "load or first inference failed")
    self.assertEqual(self.model_of(self.start(d)), STOCK_ID)  # blocked until chosen again


class TestDriveContext(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.p = Path(self.tmp.name) / "IsOffroad"
    self.boot = Path(self.tmp.name) / "boot_id"
    self.boot.write_text("1111-2222\n")

  def ctx(self):
    return resolve.drive_context(str(self.p), str(self.boot))

  def test_onroad_gives_a_stable_token(self):
    self.p.write_text("0")
    os.utime(self.p, ns=(1_000_000_000_000, 1_000_000_000_000))
    a, b = self.ctx(), self.ctx()
    self.assertEqual(a, b)
    self.assertTrue(a.token.startswith("1111-2222:"))
    self.assertAlmostEqual(a.started, 1000.0)

  def test_new_onroad_transition_gives_a_new_token(self):
    self.p.write_text("0")
    os.utime(self.p, ns=(1_000_000_000_000, 1_000_000_000_000))
    a = self.ctx()
    os.utime(self.p, ns=(2_000_000_000_000, 2_000_000_000_000))
    self.assertNotEqual(a.token, self.ctx().token)

  def test_offroad_missing_or_unreadable_gives_none(self):
    self.p.write_text("1")
    self.assertIsNone(self.ctx())
    self.assertIsNone(resolve.drive_context(str(Path(self.tmp.name) / "nope"), str(self.boot)))
    self.p.write_text("0")
    self.assertIsNone(resolve.drive_context(str(self.p), str(Path(self.tmp.name) / "noboot")))

  def test_launcher_main_passes_the_drive_context(self):
    src = Path(launcher.__file__).read_text()
    self.assertIn("drive = resolve.drive_context()", src)
    self.assertIn("return run(m, demo=demo, drive=drive)", src)


if __name__ == "__main__":
  unittest.main()
