import datetime
import json

from openpilot.system.bogpilot.osm import regions as R
from openpilot.system.bogpilot.osm.downloads import (SCHEDULE_MONTHLY, SCHEDULE_NEVER, SCHEDULE_WEEKLY, DownloadController, date_label,
                                                      parse_progress, scheduled_update_due)
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import RESERVE_BYTES, OsmStorage

SEL = R.parse_selection('{"states":["WY"]}')
SUNDAY = datetime.datetime(2026, 11, 8, 12, 0)       # Nov 8 2026 is a Sunday
MONDAY = datetime.datetime(2026, 11, 9, 12, 0)
FIRST = datetime.datetime(2026, 12, 1, 12, 0)        # a Tuesday


def test_date_label():
  assert date_label(datetime.date(2026, 11, 1)) == "November 1st, 2026"
  assert date_label(datetime.date(2026, 11, 2)) == "November 2nd, 2026"
  assert date_label(datetime.date(2026, 11, 3)) == "November 3rd, 2026"
  assert date_label(datetime.date(2026, 11, 11)) == "November 11th, 2026"
  assert date_label(datetime.date(2026, 11, 12)) == "November 12th, 2026"
  assert date_label(datetime.date(2026, 11, 13)) == "November 13th, 2026"
  assert date_label(datetime.date(2026, 11, 22)) == "November 22nd, 2026"


def test_schedule_matrix_matches_097():
  e = R.Selection()
  assert not scheduled_update_due(SUNDAY, SCHEDULE_WEEKLY, False, None, e)          # nothing selected
  assert scheduled_update_due(MONDAY, SCHEDULE_NEVER, False, None, SEL)              # first download is always due
  assert not scheduled_update_due(SUNDAY, SCHEDULE_NEVER, True, None, SEL)           # Manually never auto-updates
  assert scheduled_update_due(SUNDAY, SCHEDULE_WEEKLY, True, None, SEL)
  assert not scheduled_update_due(MONDAY, SCHEDULE_WEEKLY, True, None, SEL)
  assert scheduled_update_due(FIRST, SCHEDULE_MONTHLY, True, None, SEL)
  assert not scheduled_update_due(MONDAY, SCHEDULE_MONTHLY, True, None, SEL)
  assert not scheduled_update_due(SUNDAY, SCHEDULE_WEEKLY, True, date_label(SUNDAY.date()), SEL)   # once per day
  assert scheduled_update_due(SUNDAY, SCHEDULE_WEEKLY, True, "November 1st, 2026", SEL)


def ctl(tmp_path, free=10 * 1024 ** 3):
  st = OsmStorage(tmp_path / "osm")
  st.disk_free = lambda: free
  return MemParams(tmp_path / "d"), st


def test_can_start_messages(tmp_path):
  mem, st = ctl(tmp_path)
  c = DownloadController(mem, st)
  assert c.can_start(R.Selection(), True, True, True) == (False, "Select a region first")
  assert c.can_start(SEL, False, True, True) == (False, "Offline...")
  assert c.can_start(SEL, True, False, True) == (False, "Not parked")
  assert c.can_start(SEL, True, True, False) == (False, "Map downloader not installed")
  assert c.can_start(SEL, True, True, True) == (True, "")
  mem2, st2 = ctl(tmp_path / "low", free=RESERVE_BYTES + 1024)
  assert DownloadController(mem2, st2).can_start(SEL, True, True, True) == (False, "Not enough storage")


def test_start_cancel_progress_lifecycle(tmp_path):
  mem, st = ctl(tmp_path)
  c = DownloadController(mem, st)
  assert not c.progress().active and not c.progress().done
  assert c.start(SEL)
  assert json.loads(mem.get_text("OSMDownloadLocations")) == {"nations": [], "states": ["WY"]}
  assert c.progress().active
  mem.put("OSMDownloadProgress", json.dumps({"total_files": 6, "downloaded_files": 2}))
  p = c.progress()
  assert p.active and not p.done and p.percent == 33
  mem.put("OSMDownloadLocations", "")                 # mapd empties it when finished (even if a cell was skipped)
  p = c.progress()
  assert p.done and not p.active
  c.cancel()
  assert c.progress() == c.progress().__class__(False, False)
  assert mem.get("OSMDownloadProgress") is None and mem.get("OSMDownloadLocations") is None


def test_start_empty_selection_refused(tmp_path):
  mem, st = ctl(tmp_path)
  assert not DownloadController(mem, st).start(R.Selection())
  assert mem.get("OSMDownloadLocations") is None


def test_progress_parse_fail_closed():
  assert parse_progress(None) == (0, 0)
  assert parse_progress("nope") == (0, 0)
  assert parse_progress('{"total_files":"x"}') == (0, 0)
  assert parse_progress('{"total_files":-3,"downloaded_files":-1}') == (0, 0)
  assert parse_progress('[1]') == (0, 0)
