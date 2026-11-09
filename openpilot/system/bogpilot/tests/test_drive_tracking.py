"""DriveHistory ledger + FrogPilotStats producer tests (lane t994-driveStats)."""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.common import bogpilot_toggles
from openpilot.system.bogpilot import drive_tracking as dt

NOW = datetime.datetime(2026, 4, 11, 16, 0, 0, tzinfo=datetime.UTC)
DAY_A, DAY_B = "2026-04-07", "2026-04-11"  # synthetic fixture days
REPO_FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeParams(dict):
  def get(self, key, *a, **k):
    return super().get(key)

  def put(self, key, val, block=None):
    self[key] = val

  def get_param_path(self, key=""):
    return str(self.get("_param_root", Path("/tmp")) / key)


@pytest.fixture(autouse=True)
def bp_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(bogpilot_toggles, "BOGPILOT_DIR", tmp_path)
  monkeypatch.setattr(dt, "TIMEZONE_NAME_PATH", tmp_path / "missing-timezone")
  return tmp_path


def msgs(v=10.0, standstill=False, state="enabled", enabled=True, lat=True, long=True,
         alert="", experimental=False, personality="standard", cruise=60.0):
  return (
    SimpleNamespace(vEgo=v, standstill=standstill, vCruiseCluster=cruise),
    SimpleNamespace(state=state, enabled=enabled, alertType=alert, experimentalMode=experimental, personality=personality),
    SimpleNamespace(latActive=lat, longActive=long),
  )


def test_fresh_install_zeros_not_unavailable(bp_dir):
  params = FakeParams()
  status = dt.ensure_stats_stores(params, history_path=bp_dir / "DriveHistory")
  assert status["stats"] == "created"
  assert status["history"] == "created"
  s = json.loads(params["FrogPilotStats"])
  assert s["FrogPilotDrives"] == 0 and s["FrogPilotMeters"] == 0.0 and s["FrogPilotSeconds"] == 0.0
  assert json.loads((bp_dir / "DriveHistory").read_text()) == {}

  from openpilot.selfdrive.ui.bogpilot.offroad_stats import cumulative_row, past_week_row
  row = cumulative_row(params["FrogPilotStats"], False)
  assert row.available and (row.drives, row.distance, row.hours) == (0, 0, 0)
  week = past_week_row((bp_dir / "DriveHistory").read_bytes(), False, datetime.date(2026, 4, 11))
  assert week.available and week.drives == 0


def test_never_overwrite_existing_history_with_zeros(bp_dir):
  hist = bp_dir / "DriveHistory"
  payload = {DAY_A: {"routes": 4, "meters": 1000.0, "seconds": 600.0}}
  hist.write_text(json.dumps(payload))
  params = FakeParams(FrogPilotStats=json.dumps({"FrogPilotDrives": 4, "FrogPilotMeters": 1000, "FrogPilotSeconds": 600}))
  status = dt.ensure_stats_stores(params, history_path=hist)
  assert status["history"] == "preserved"
  assert status["stats"] == "preserved"
  assert json.loads(hist.read_text()) == payload
  s = json.loads(params["FrogPilotStats"])
  assert s["FrogPilotDrives"] == 4 and s["FrogPilotMeters"] == 1000


def test_corrupt_history_backup_and_recover(bp_dir):
  hist = bp_dir / "DriveHistory"
  hist.write_text("NOT JSON {{{")
  status = dt.ensure_stats_stores(FakeParams(), history_path=hist)
  assert status["history"] == "recovered"
  assert json.loads(hist.read_text()) == {}
  backups = [p for p in bp_dir.glob("DriveHistory.corrupt.*") if not p.name.endswith(".reason")]
  assert backups
  assert any(p.name.endswith(".reason") for p in bp_dir.iterdir())


def test_corrupt_stats_gets_zeros_after_backup(bp_dir):
  params = FakeParams(_param_root=bp_dir)
  (bp_dir / "FrogPilotStats").write_text("{bad")
  params["FrogPilotStats"] = "{bad"
  status = dt.ensure_stats_stores(params, history_path=bp_dir / "DriveHistory")
  assert status["stats"] == "recovered"
  s = json.loads(params["FrogPilotStats"])
  assert s["FrogPilotDrives"] == 0
  assert list(bp_dir.glob("FrogPilotStats.corrupt.*"))


def test_add_drive_history_atomic_merge_and_prune(bp_dir):
  p = bp_dir / "DriveHistory"
  dt.add_drive_history(datetime.date(2026, 3, 19), routes=1, meters=5.0, seconds=2.0, path=p)
  dt.add_drive_history(datetime.date(2026, 4, 7), routes=1, meters=5.0, seconds=2.0, path=p)
  dt.add_drive_history(datetime.date(2026, 4, 11), routes=1, meters=100.0, seconds=60.0, path=p)
  dt.add_drive_history(datetime.date(2026, 4, 7), routes=1, meters=1.0, seconds=1.0, path=p)
  h = json.loads(p.read_text())
  assert set(h) == {DAY_A, DAY_B}
  assert h[DAY_B] == {"routes": 1, "meters": 100.0, "seconds": 60.0}
  assert h[DAY_A] == {"routes": 2, "meters": 6.0, "seconds": 3.0}


def test_timezone_fallbacks(bp_dir, monkeypatch):
  assert str(dt.bogpilot_timezone(lambda k: "Europe/Berlin")) == "Europe/Berlin"
  (bp_dir / "tz").write_text("Asia/Tokyo\n")
  monkeypatch.setattr(dt, "TIMEZONE_NAME_PATH", bp_dir / "tz")
  assert str(dt.bogpilot_timezone(lambda k: None)) == "Asia/Tokyo"
  assert str(dt.bogpilot_timezone(lambda k: "Not/AZone")) == "Asia/Tokyo"


def test_load_stats_migration_and_zeros():
  s = dt.load_stats(json.dumps({"TotalLateralTime": 5, "TotalEvents": {"x": 1}, "unknown": 1,
                                "PersonalityTimes": {"Standard": 1, "unknown": 2}, "CurrentMonthsKilometers": 3}))
  s.pop("_corrupt_source", None)
  assert s["LateralTime"] == 5 and s["TotalLateralTime"] == 5 and s["TotalEvents"] == {"x": 1}  # INT: never drop saved keys
  assert s["PersonalityTimes"] == {"Standard": 1}
  assert s["ResetStats"] is True and s["Engages"] == 0
  assert s["FrogPilotDrives"] == 0 and s["FrogPilotMeters"] == 0.0 and s["FrogPilotSeconds"] == 0.0
  kept = dt.load_stats(json.dumps({"ResetStats": True, "Engages": 7, "GoatScreams": 3,
                                   "FrogPilotDrives": 2, "FrogPilotMeters": 10, "FrogPilotSeconds": 20,
                                   "WeatherTimes": {"rain": 1}}))
  kept.pop("_corrupt_source", None)
  assert kept["Engages"] == 7 and kept["FrogPilotDrives"] == 2
  bad = dt.load_stats("not json")
  assert bad["_corrupt_source"] is True and bad["FrogPilotDrives"] == 0


def test_drive_credit_and_counters(bp_dir):
  params = FakeParams(Timezone="America/New_York")
  t = dt.DriveTracker(params, history_path=bp_dir / "DriveHistory")
  t.update(NOW, True, *msgs(state="disabled", enabled=False, lat=False, long=False))
  for _ in range(int(70 / dt.DT_MDL)):
    t.update(NOW, True, *msgs(alert="promptDriverDistracted/permanent"))
  assert json.loads(params["FrogPilotStats"]).get("FrogPilotDrives") == 0
  t.update(NOW, True, *msgs(v=0.0, standstill=True))
  s = json.loads(params["FrogPilotStats"])
  assert s["FrogPilotDrives"] == 1 and s["Engages"] == 1 and s["TotalEvents"] == {"promptDriverDistracted": 1}
  assert s["Month"] == 4 and s["ModelTimes"][dt.MODEL_NAME] == pytest.approx(70.1, abs=0.1)
  assert s["PersonalityTimes"]["Standard"] > 69 and s["FrogPilotMeters"] == pytest.approx(700, rel=0.01)
  assert s["EngagedSeconds"] == pytest.approx(70.05, abs=0.2)
  h = json.loads((bp_dir / "DriveHistory").read_text())
  assert h[DAY_B]["routes"] == 1 and h[DAY_B]["meters"] == pytest.approx(700, rel=0.01)
  for _ in range(int(61 / dt.DT_MDL)):
    t.update(NOW, True, *msgs())
  t.update(NOW, True, *msgs(v=0.0, standstill=True))
  h = json.loads((bp_dir / "DriveHistory").read_text())
  assert h[DAY_B]["routes"] == 1 and h[DAY_B]["seconds"] > 130
  t.update(NOW, True, *msgs(state="disabled", enabled=False))
  t.update(NOW, True, *msgs(state="overriding"))
  s = t.stats
  assert s["Disengages"] == 1 and s["Overrides"] == 1 and s["Engages"] == 2


def test_no_credit_without_engagement_or_valid_clock(bp_dir):
  params = FakeParams()
  t = dt.DriveTracker(params, history_path=bp_dir / "DriveHistory")
  (bp_dir / "DriveHistory").unlink()
  for _ in range(int(61 / dt.DT_MDL)):
    t.update(NOW, True, *msgs(state="disabled", enabled=False, lat=False, long=False))
  t.update(NOW, True, *msgs(v=0.0, standstill=True, state="disabled", enabled=False))
  assert not (bp_dir / "DriveHistory").exists() and t.stats["FrogPilotDrives"] == 0
  t2 = dt.DriveTracker(FakeParams(), history_path=bp_dir / "DriveHistory2", initialize_stores=False)
  for _ in range(int(61 / dt.DT_MDL)):
    t2.update(NOW, False, *msgs())
  t2.update(NOW, False, *msgs(v=0.0, standstill=True))
  assert not (bp_dir / "DriveHistory2").exists()
  assert t2.history_routes == 1 and t2.stats["FrogPilotDrives"] == 1
  for _ in range(int(61 / dt.DT_MDL)):
    t2.update(NOW, True, *msgs())
  t2.update(NOW, True, *msgs(v=0.0, standstill=True))
  day = dt.local_day(NOW, dt.bogpilot_timezone(None)).isoformat()
  assert json.loads((bp_dir / "DriveHistory2").read_text())[day]["routes"] == 1


def test_replay_fixture_engaged_70s(bp_dir):
  fixture = json.loads((REPO_FIXTURES / "replay_engaged_70s.json").read_text())
  params = FakeParams(Timezone=fixture["timezone"])
  t = dt.DriveTracker(params, history_path=bp_dir / "DriveHistory")
  now = datetime.datetime.fromisoformat(fixture["now_utc"])
  for tick in fixture["ticks"]:
    car_state = SimpleNamespace(vEgo=tick["vEgo"], standstill=tick["standstill"], vCruiseCluster=tick["vCruiseCluster"])
    sd = SimpleNamespace(state=tick["state"], enabled=tick["enabled"], alertType=tick["alertType"],
                         experimentalMode=tick["experimentalMode"], personality=tick["personality"])
    cc = SimpleNamespace(latActive=tick["latActive"], longActive=tick["longActive"])
    t.update(now, fixture["time_validated"], car_state, sd, cc)
  s = json.loads(params["FrogPilotStats"])
  exp = fixture["expect"]
  assert s["FrogPilotDrives"] == exp["FrogPilotDrives"]
  assert exp["min_FrogPilotMeters"] <= s["FrogPilotMeters"] <= exp["max_FrogPilotMeters"]
  h = json.loads((bp_dir / "DriveHistory").read_text())
  assert h[exp["history_day"]]["routes"] == exp["history_routes"]


def test_glyph_placeholder_is_en_dash_not_em_dash():
  # Read card source without importing pyray.
  openpilot_root = Path(dt.__file__).resolve().parents[2]
  src = (openpilot_root / "selfdrive/ui/widgets/bogpilot_stats.py").read_text(encoding="utf-8")
  assert "\u2013" in src  # EN DASH
  assert "\u2014" not in src  # EM DASH must not remain


def test_process_registered_and_non_blocking_for_selfdrived():
  # INT t994: trackd is registered (onroad) and selfdrived must not treat it as a safety-critical process.
  openpilot_root = Path(dt.__file__).resolve().parents[2]
  src = (openpilot_root / "system/manager/process_config.py").read_text(encoding="utf-8")
  assert 'PythonProcess("bogpilot_trackd", "openpilot.system.bogpilot.drive_tracking", only_onroad)' in src
  sd = (openpilot_root / "selfdrive/selfdrived/selfdrived.py").read_text(encoding="utf-8")
  assert "NON_ESSENTIAL_PROCESSES" in sd and "bogpilot_trackd" in sd
