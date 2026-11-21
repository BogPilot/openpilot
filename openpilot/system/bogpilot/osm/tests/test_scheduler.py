"""Scheduled map updates (consumer of PreferredSchedule): decisions, once-a-day, car/online/space gates, finish stamping."""
import datetime
import json

import pytest

from openpilot.common.bogpilot_store import ParamStore
from openpilot.system.bogpilot.osm import scheduler as SC
from openpilot.system.bogpilot.osm import supervisor as S
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage
from openpilot.system.bogpilot.osm.tests.test_map_data_controller import FakeParams
from openpilot.system.bogpilot.osm.tests.test_supervisor import Clock, FakeProc, installed

SUN = datetime.datetime(2026, 11, 8, 3, 0)      # a Sunday
MON = datetime.datetime(2026, 11, 9, 3, 0)      # a Monday
FIRST = datetime.datetime(2026, 12, 1, 3, 0)    # the 1st (a Tuesday)
SEL = '{"nations":[],"states":["OH"]}'


class Rig:
  def __init__(self, tmp_path, monkeypatch, now=MON, offroad=True, online=True, free=50 * 1024 ** 3, has_maps=True, unmetered=True):
    monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "bp"))
    self.params = FakeParams()
    self.store = ParamStore(self.params)
    self.mem = MemParams(tmp_path / "d")
    self.storage = OsmStorage(tmp_path / "osm")
    self.storage.disk_free = lambda: free
    if has_maps:
      (self.storage.offline_dir / "a").mkdir(parents=True)
      (self.storage.offline_dir / "a" / "t").write_bytes(b"x")
    self.now, self.offroad, self.online, self.unmetered = now, offroad, online, unmetered
    self.store.put("MapsSelected", SEL)
    self.sched = SC.UpdateScheduler(self.store, self.mem, self.storage, now=lambda: self.now,
                                    online=lambda: self.online, offroad=lambda: self.offroad, unmetered=lambda: self.unmetered)

  def requested(self):
    return self.mem.get_text("OSMDownloadLocations")


@pytest.fixture
def rig(tmp_path, monkeypatch):
  return Rig(tmp_path, monkeypatch)


def test_weekly_is_the_default_and_runs_on_sunday_only(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=MON)
  assert "PreferredSchedule" not in r.params.data                    # nothing saved: the Weekly default applies
  assert r.sched.tick() == "not_due" and r.requested() is None
  r.now = FIRST                                                      # the 1st (a Tuesday) is not a Weekly day
  assert r.sched.tick() == "not_due"
  r.now = SUN
  assert r.sched.tick() == "started" and r.requested() == SEL


def test_saved_monthly_still_runs_on_the_first_only(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=MON)
  r.store.put("PreferredSchedule", 2)
  assert r.sched.tick() == "not_due" and r.requested() is None
  r.now = SUN
  assert r.sched.tick() == "not_due"
  r.now = FIRST
  assert r.sched.tick() == "started" and r.requested() == SEL


def test_explicit_weekly_runs_on_sunday_only(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=MON)
  r.store.put("PreferredSchedule", 1)
  assert r.sched.tick() == "not_due"
  r.now = SUN
  assert r.sched.tick() == "started"


def test_manual_never_updates_existing_maps(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=SUN)
  r.store.put("PreferredSchedule", 0)
  for now in (SUN, FIRST, MON):
    r.now = now
    assert r.sched.tick() == "not_due"
  assert r.requested() is None


def test_first_download_is_due_on_any_day_even_when_manual(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=MON, has_maps=False)          # nothing downloaded and Last Updated never set (0.9.7)
  r.store.put("PreferredSchedule", 0)
  assert r.sched.tick() == "started"


def test_removed_maps_are_not_fetched_again_by_the_first_download_rule(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=MON, has_maps=False)
  r.store.put("LastMapsUpdate", "November 1st, 2026")              # it was downloaded once, then the user pressed Remove
  r.store.put("PreferredSchedule", 0)
  assert r.sched.tick() == "not_due" and r.requested() is None
  r.store.put("PreferredSchedule", 1)                                # Weekly: not before the next Sunday
  assert r.sched.tick() == "not_due"


def test_no_regions_means_nothing_to_do(rig):
  rig.store.put("MapsSelected", '{"nations":[],"states":[]}')
  rig.now = FIRST
  assert rig.sched.tick() == "no_regions"


def test_never_while_driving_offline_or_without_space(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=SUN, offroad=False)
  assert r.sched.tick() == "onroad" and r.requested() is None
  r.offroad, r.online = True, False
  assert r.sched.tick() == "offline"
  r.online = True
  r.storage.disk_free = lambda: 1024 ** 3
  assert r.sched.tick() == "no_space"
  r.storage.disk_free = lambda: 50 * 1024 ** 3
  assert r.sched.tick() == "started"                                 # blocked ticks did not burn the day's attempt


def test_slc_off_means_no_scheduled_or_first_download(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=SUN, has_maps=False)             # first download is due on any day ...
  r.store.put("SpeedLimitController", "0")                           # ... but not while the Speed Limit Controller is off
  assert r.sched.tick() == "slc_off" and r.requested() is None
  r.now = MON
  r.store.put("PreferredSchedule", 1)
  assert r.sched.tick() == "slc_off"
  r.store.put("SpeedLimitController", "1")                           # back on: it runs, the blocked ticks burned nothing
  assert r.sched.tick() == "started" and r.requested() == SEL


def test_slc_off_still_stamps_a_finished_download_and_never_starts_one(tmp_path, monkeypatch):
  r = Rig(tmp_path, monkeypatch, now=SUN)
  r.sched.tick()
  r.store.put("SpeedLimitController", "0")
  r.mem.put("OSMDownloadProgress", json.dumps({"total_files": 1, "downloaded_files": 1}))
  r.mem.remove("OSMDownloadLocations")
  r.sched.dl.jobs.clear()                                            # resume.py hand-over
  assert r.sched.tick() == "finished"                                # a download that ended is recorded whatever the SLC says


def test_one_request_per_calendar_day_then_again_next_due_day(rig):
  rig.now = SUN
  assert rig.sched.tick() == "started"
  rig.mem.remove("OSMDownloadLocations")                             # mapd finished without writing progress (nothing to fetch)
  rig.sched.dl.jobs.clear()
  assert rig.sched.tick() == "already_tried"
  rig.now = SUN + datetime.timedelta(days=7)                         # next Sunday
  assert rig.sched.tick() == "started"


def test_running_download_is_never_doubled_and_finish_is_stamped(rig):
  rig.now = SUN
  assert rig.sched.tick() == "started"
  rig.mem.put("OSMDownloadProgress", json.dumps({"total_files": 4, "downloaded_files": 1}))
  assert rig.sched.tick() == "running"
  rig.mem.remove("OSMDownloadLocations")
  rig.sched.dl.jobs.clear()
  assert rig.sched.tick() == "finished"
  assert rig.params.data["LastMapsUpdate"] == b"November 8th, 2026"
  assert rig.mem.get_text("OSMDownloadProgress") is None
  assert rig.sched.tick() == "not_due"                               # stamped today -> no second run


def test_unreadable_schedule_uses_the_weekly_default(rig):
  rig.params.data["PreferredSchedule"] = b"junk"
  rig.now = SUN
  assert rig.sched.tick() == "started"


def test_default_offroad_fails_closed(monkeypatch):
  import sys
  monkeypatch.setitem(sys.modules, "openpilot.common.params", None)  # import fails -> not offroad -> no scheduled download
  assert SC.default_offroad() is False


# ------------------------------------------------------------------------------------------------ supervisor hook
def test_supervisor_ticks_the_scheduler_once_a_minute_and_survives_its_errors(tmp_path):
  st, _ = installed(tmp_path)
  mem = MemParams(tmp_path / "d")
  clk = Clock()
  ticks = []

  class Sched:
    def tick(self):
      ticks.append(clk.t)
      if len(ticks) == 2:
        raise RuntimeError("boom")
      return "not_due"

  import openpilot.system.bogpilot.osm.supervisor as sup
  from openpilot.system.bogpilot.osm.tests.test_installer import manifest_for
  man = manifest_for(st.mapd_path.read_bytes())
  orig = sup.installer.load_manifest
  sup.installer.load_manifest = lambda *a, **k: man
  try:
    res = S.run(st, mem, popen=lambda c, **kw: FakeProc(exits_after=10 ** 9), sm=None, sleep=clk.sleep, monotonic=clk, max_ticks=3000,
                scheduler=Sched())
  finally:
    sup.installer.load_manifest = orig
  assert res["launches"] >= 1 and len(ticks) >= 3
  gaps = [b - a for a, b in zip(ticks, ticks[1:])]
  assert all(g >= S.SCHEDULE_TICK_S - 1 for g in gaps)


def test_automatic_updates_only_on_unmetered_wifi(tmp_path, monkeypatch):
  # As upstream FrogPilot, a due scheduled update waits for unmetered Wi-Fi, never the hotspot / mobile data
  r = Rig(tmp_path, monkeypatch, now=SUN, unmetered=False)
  r.store.put("PreferredSchedule", 1)
  assert r.sched.tick() == "metered" and r.requested() is None
  r.unmetered = True
  assert r.sched.tick() == "started" and r.requested()


def test_unmetered_wifi_detection(monkeypatch):
  from openpilot.common import hardware as H
  from openpilot.common.hardware.base import NetworkType

  class HW:
    def __init__(self, nt, metered):
      self.nt, self.metered = nt, metered

    def get_network_type(self):
      return self.nt

    def get_network_metered(self, nt):
      return self.metered

  for nt, metered, want in ((NetworkType.wifi, False, True), (NetworkType.ethernet, False, True), (NetworkType.wifi, True, False),
                            (NetworkType.cell4G, False, False), (NetworkType.cell5G, True, False), (NetworkType.none, False, False)):
    monkeypatch.setattr(H, "HARDWARE", HW(nt, metered))
    assert SC.default_unmetered_wifi() is want, (nt, metered)

  class Broken:
    def get_network_type(self):
      raise OSError("no dbus")
  monkeypatch.setattr(H, "HARDWARE", Broken())
  assert SC.default_unmetered_wifi() is False                         # fail closed: no automatic download


def test_manual_download_ignores_the_metered_rule(tmp_path, monkeypatch):
  # the scheduler's Wi-Fi rule is not part of the manual path: DownloadController.start has no network-type check
  import inspect
  from openpilot.system.bogpilot.osm import downloads, map_data_controller
  for mod in (downloads, map_data_controller):
    src = inspect.getsource(mod)
    assert "metered" not in src and "unmetered" not in src, mod.__name__
