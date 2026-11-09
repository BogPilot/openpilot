"""t994 INT: preservation regressions from review (nonzero legacy store must survive ensure/load)."""
import json
import tempfile
import unittest
from pathlib import Path

from openpilot.system.bogpilot import drive_tracking as dt


class FakeParams:
  def __init__(self, raw=None):
    self.d = {} if raw is None else {"FrogPilotStats": raw}
    self.puts = 0

  def get(self, k, *a, **kw):
    return self.d.get(k)

  def put(self, k, v, *a, **kw):
    self.d[k] = v
    self.puts += 1


class TestPreservation(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.hist = Path(self.tmp.name) / "DriveHistory"

  def test_legacy_nonzero_store_without_resetstats_keeps_counters(self):
    legacy = {"Disengages": 7, "Engages": 9, "Overrides": 3, "FrogPilotDrives": 11, "FrogPilotMeters": 1234.5,
              "FrogPilotSeconds": 600.0, "TotalEvents": 5}
    s = dt.load_stats(json.dumps(legacy))
    for k in ("Disengages", "Engages", "Overrides", "FrogPilotDrives", "TotalEvents"):
      self.assertEqual(s[k], legacy[k], k)
    self.assertEqual(s["FrogChirps"], 0)

  def test_ensure_does_not_rewrite_complete_valid_store(self):
    p = FakeParams()
    dt.ensure_stats_stores(p, history_path=self.hist)
    self.assertEqual(p.puts, 1)
    p.puts = 0
    out = dt.ensure_stats_stores(p, history_path=self.hist)
    self.assertEqual(p.puts, 0)
    self.assertEqual(out["stats"], "preserved")

  def test_startup_runs_ensure_stats_stores_so_fresh_install_shows_zeros(self):
    """t994 INT: manager startup (after_defaults) initialises FrogPilotStats + DriveHistory; trackd is registered."""
    from openpilot.system.manager import bogpilot_startup as bs
    p = FakeParams()
    res = bs.after_defaults(p, file_root=Path(self.tmp.name))
    self.assertFalse([e for e in res.errors if e.startswith("drive-stats")], res.errors)
    self.assertTrue(any(e.startswith("drive-stats:") for e in res.events), res.events)
    stats = json.loads(p.d["FrogPilotStats"])
    self.assertEqual(set(stats), set(dt.load_stats(None)) - {"_corrupt_source"})
    self.assertTrue(all(v == 0 for v in stats.values() if isinstance(v, (int, float)) and not isinstance(v, bool)), stats)
    self.assertTrue((Path(self.tmp.name) / "DriveHistory").exists())
    root = Path(__file__).resolve().parents[3]
    self.assertIn('PythonProcess("bogpilot_trackd"', (root / "system/manager/process_config.py").read_text())
    self.assertIn("after_defaults(params, startup=startup)", (root / "system/manager/manager.py").read_text())

  def test_ensure_fresh_creates_valid_zero(self):
    p = FakeParams()
    out = dt.ensure_stats_stores(p, history_path=self.hist)
    self.assertEqual(out["stats"], "created")
    s = json.loads(p.d["FrogPilotStats"])
    self.assertEqual((s["FrogPilotDrives"], s["FrogPilotMeters"], s["FrogPilotSeconds"]), (0, 0.0, 0.0))


if __name__ == "__main__":
  unittest.main()
