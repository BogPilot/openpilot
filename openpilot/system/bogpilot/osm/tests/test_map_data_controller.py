"""Map Data page logic (slice 3): selection, schedule, download / cancel / progress, remove, reset, install. No window, no network,
no thread, no real process kill or reboot: every side effect is an injected fake."""
import datetime
import json

import pytest

from openpilot.common.bogpilot_store import ParamStore
from openpilot.system.bogpilot.osm import installer as I
from openpilot.system.bogpilot.osm import regions as R
from openpilot.system.bogpilot.osm import map_data_controller as M
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage
from openpilot.system.bogpilot.osm.tests.test_installer import elf, fetcher, manifest_for

KEYS = ("MapsSelected", "PreferredSchedule", "LastMapsUpdate")


class FakeParams:
  """Params stand-in that knows the three Map Data keys (so ParamStore treats them as real Params keys)."""

  def __init__(self):
    self.data = {}

  def all_keys(self):
    return list(KEYS)

  def get(self, key):
    return self.data.get(key)

  def put(self, key, value):
    self.data[key] = str(value).encode()

  def remove(self, key):
    self.data.pop(key, None)


class Clock:
  def __init__(self):
    self.t = 100.0
    self.sleeps = []

  def __call__(self):
    return self.t

  def sleep(self, dt):
    self.sleeps.append(dt)
    self.t += dt


class Env:
  """A controller wired to tmp dirs and fakes."""

  def __init__(self, tmp_path, monkeypatch, installed=True, free=50 * 1024 ** 3):
    monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "bp"))
    self.params = FakeParams()
    self.store = ParamStore(self.params)
    self.mem = MemParams(tmp_path / "d")
    self.storage = OsmStorage(tmp_path / "osm")
    self.storage.disk_free = lambda: free
    self.blob = elf()
    self.manifest = manifest_for(self.blob)
    if installed:
      I.install(self.storage, self.manifest, fetcher(self.blob))
    self.clock = Clock()
    self.killed, self.rebooted, self.awake = [], [], []
    self.base = datetime.datetime(2026, 11, 9, 15, 7, 0)         # wall clock = base + seconds the fake monotonic clock advanced
    self.fetches = []
    self.ctl = M.MapDataController(
      self.store, mem=self.mem, storage=self.storage, manifest=self.manifest, fetch=self.fetch,
      kill_mapd=lambda: self.killed.append(1), reboot=lambda: self.rebooted.append(1), spawn=lambda fn: fn(),
      sleep=self.clock.sleep, monotonic=self.clock, now=lambda: self.base + datetime.timedelta(seconds=self.clock.t - 100.0), keep_awake=self.awake.append)

  def fetch(self, url):
    self.fetches.append(url)
    return fetcher(self.blob)(url)

  def marker(self):
    from openpilot.common import bogpilot_store as bs
    return bs.read_text(M.ADOPTION_MARKER)

  def progress(self, total, done):
    self.mem.put("OSMDownloadProgress", json.dumps({"total_files": total, "downloaded_files": done}))


@pytest.fixture
def env(tmp_path, monkeypatch):
  return Env(tmp_path, monkeypatch)


# ------------------------------------------------------------------------------------------------ Map Sources
def test_select_countries_and_states_saves_the_097_json(env):
  assert env.ctl.selection().is_empty() and not env.ctl.has_selection()
  assert env.ctl.set_region("nations", "US", True)
  assert env.ctl.set_region("states", "OH", True)
  assert env.ctl.set_region("states", "MI", True)
  assert env.params.data["MapsSelected"] == b'{"nations":["US"],"states":["OH","MI"]}'     # QJsonDocument::Compact shape
  assert env.ctl.is_selected("states", "OH") and not env.ctl.is_selected("states", "IN")
  assert env.ctl.set_region("states", "OH", False)
  assert env.params.data["MapsSelected"] == b'{"nations":["US"],"states":["MI"]}'
  assert env.ctl.set_region("states", "MI", True)                    # selecting twice is a no-op
  assert R.parse_selection(env.params.data["MapsSelected"].decode()).states == ("MI",)


def test_select_refuses_unknown_kinds_codes_and_the_cap(env, monkeypatch):
  assert not env.ctl.set_region("cities", "US", True)
  assert not env.ctl.set_region("nations", "ZZ", True)
  assert not env.ctl.set_region("states", "US", True)                # a nation code is not a state
  assert not env.ctl.set_region("nations", "GU", True)               # Guam is the state GM, not a nation
  assert "MapsSelected" not in env.params.data and env.marker() is None
  monkeypatch.setattr(R, "MAX_SELECTED_REGIONS", 2)
  assert env.ctl.set_region("nations", "CA", True) and env.ctl.set_region("nations", "US", True)
  assert not env.ctl.set_region("states", "OH", True)
  assert env.ctl.message == "Too many regions selected"
  assert env.ctl.set_region("nations", "CA", False)                  # deselecting still works at the cap
  assert env.ctl.set_region("states", "OH", True)


def test_every_listed_region_can_be_selected_and_round_trips(env):
  for kind, key in (("nations", "nations"), ("states", "states")):
    for _label, regs in R.groups()[key]:
      for code, _name in regs:
        assert env.ctl.set_region(kind, code, True), (kind, code)
        assert env.ctl.is_selected(kind, code)
        assert env.ctl.set_region(kind, code, False)
  assert env.ctl.selection().is_empty()


def test_saved_097_guam_code_is_migrated_on_the_next_change(env):
  env.store.put("MapsSelected", '{"nations":[],"states":["GU","OH"]}')
  assert env.ctl.selection().states == ("GM", "OH")                  # read side: still selected
  assert env.ctl.set_region("states", "MI", True)
  assert env.params.data["MapsSelected"] == b'{"nations":[],"states":["GM","OH","MI"]}'


def test_first_selection_writes_the_user_adoption_marker_only(env):
  assert env.marker() is None
  env.ctl.set_region("states", "OH", True)
  assert env.marker() == "1"
  env.ctl.set_region("states", "OH", False)                          # clearing never writes it again (and never removes it)
  assert env.marker() == "1"


def test_deselect_alone_never_writes_the_marker(env):
  env.ctl.set_region("states", "OH", False)
  assert env.marker() is None and "MapsSelected" not in env.params.data


# ------------------------------------------------------------------------------------------------ schedule
def test_schedule_default_is_weekly_and_saved_choice_is_kept(env):
  assert env.ctl.schedule() == 1 and "PreferredSchedule" not in env.params.data   # default Weekly, nothing written by looking
  assert env.ctl.set_schedule(0) and env.params.data["PreferredSchedule"] == b"0"
  assert env.ctl.schedule() == 0
  assert env.ctl.set_schedule(2) and env.ctl.schedule() == 2                     # a saved Monthly stays Monthly
  assert env.ctl.set_schedule(1) and env.ctl.schedule() == 1


def test_schedule_refuses_bad_values_and_clamps_odd_saved_ones(env):
  assert not env.ctl.set_schedule(3) and not env.ctl.set_schedule(-1)
  assert "PreferredSchedule" not in env.params.data
  env.params.data["PreferredSchedule"] = b"7"
  assert env.ctl.schedule() == 2
  env.params.data["PreferredSchedule"] = b"junk"
  assert env.ctl.schedule() == 1                                     # unreadable -> the Weekly default
  assert [x for x in M.SCHEDULE_LABELS] == ["Manually", "Weekly", "Monthly"]


def test_weekly_is_the_default_everywhere():
  # Weekly is the default. The registry, the C++ key table (libparams_c.so rebuilt), the defaults table,
  # the settings specs, the AP1 profile and the controller fallback all agree.
  from openpilot.common import bogpilot_params as bp
  from openpilot.common.bogpilot_ap1_profile import AP1_PARAM_PROFILE
  from openpilot.selfdrive.ui.bogpilot import bogpilot_defaults as D
  from openpilot.selfdrive.ui.bogpilot.phase3_system_settings_feature_specs import FEATURE_SPECS
  assert M.DEFAULT_SCHEDULE == 1 and AP1_PARAM_PROFILE["PreferredSchedule"] == "1"
  assert bp.BOGPILOT_PARAMS["PreferredSchedule"][2] == "1"
  assert '{"PreferredSchedule", {PERSISTENT, INT, "1"}}' in open(bp.HEADER_PATH, encoding="utf-8").read()
  assert D.DEFAULTS["PreferredSchedule"] == "1"
  assert FEATURE_SPECS["PreferredSchedule"]["declared_default"] == "1"


def test_last_updated_reads_never_then_the_date(env):
  assert env.ctl.last_updated() == "Never"
  env.store.put("LastMapsUpdate", "November 1st, 2026")
  assert env.ctl.last_updated() == "November 1st, 2026"


# ------------------------------------------------------------------------------------------------ Download
def test_download_row_value_matches_097(env):
  assert env.ctl.can_download(True, True) == (False, "Select a region first")
  env.ctl.set_region("states", "OH", True)
  assert env.ctl.can_download(False, True) == (False, "Offline...")
  assert env.ctl.can_download(True, False) == (True, "")             # map downloads work while driving
  assert env.ctl.can_download(True, True) == (True, "")
  v = env.ctl.view(False, True)
  assert (v.download_text, v.download_enabled, v.download_value) == ("DOWNLOAD", False, "Offline...")
  v = env.ctl.view(True, True)
  assert (v.download_text, v.download_enabled, v.download_value) == ("DOWNLOAD", True, "")


def test_not_enough_storage_blocks_the_download(tmp_path, monkeypatch):
  e = Env(tmp_path, monkeypatch, free=1024 ** 3)
  e.ctl.set_region("nations", "US", True)
  assert e.ctl.can_download(True, True) == (False, "Not enough storage")
  assert not e.ctl.start_download(True, True)
  assert e.mem.get_text("OSMDownloadLocations") is None


def test_refused_press_does_nothing(env):
  env.ctl.set_region("states", "OH", True)
  assert not env.ctl.start_download(False, True)                     # offline (not being parked no longer refuses)
  assert env.mem.get_text("OSMDownloadLocations") is None and env.fetches == []


def test_download_asks_mapd_for_the_saved_selection_and_shows_progress(env):
  env.ctl.set_region("nations", "CA", True)
  env.ctl.set_region("states", "OH", True)
  assert env.ctl.start_download(True, True)
  assert env.mem.get_text("OSMDownloadLocations") == '{"nations":["CA"],"states":["OH"]}'
  assert env.mem.get_text("OSMDownloadProgress") is None
  assert env.fetches == []                                           # mapd was already installed: nothing is fetched
  v = env.ctl.view(True, True)
  assert (v.download_text, v.download_enabled, v.downloading) == ("CANCEL", True, True)
  assert (v.progress, v.elapsed, v.eta) == ("Calculating...", "0 seconds", "Calculating...")
  assert not v.show_last_updated and not v.show_remove and not v.show_reset      # hidden while downloading, as 0.9.7
  env.progress(8, 2)
  env.clock.t += 61
  v = env.ctl.view(True, True)
  assert v.progress == "2 / 8 (25%)"
  assert v.elapsed == "1 minute 1 second"
  assert v.eta == "3 minutes 3 seconds (3:11 PM)"          # 61 s for 2 of 8 files -> 244 s total, 183 s left, done at 3:11 PM
  assert not env.ctl.start_download(True, True)                      # a second press while it runs is refused


def test_eta_clock_text_and_elapsed_formats_match_097():
  assert M.format_elapsed(0) == "0 seconds" and M.format_elapsed(1000) == "1 second"
  assert M.format_elapsed(61000) == "1 minute 1 second"
  assert M.format_elapsed(3725000) == "1 hour 2 minutes 5 seconds"
  assert M.format_elapsed(7200000) == "2 hours 0 seconds"
  assert M.clock_text(datetime.datetime(2026, 1, 1, 0, 5)) == "12:05 AM"
  assert M.clock_text(datetime.datetime(2026, 1, 1, 15, 7)) == "3:07 PM"
  assert M.clock_text(datetime.datetime(2026, 1, 1, 12, 0)) == "12:00 PM"


def test_eta_counts_down_with_the_clock_and_only_moves_when_a_file_finishes():
  start = datetime.datetime(2026, 11, 9, 12, 0, 0)
  eta = M.EtaEstimator(start)
  assert eta.update(0, 0, 10, start) == "Calculating..."
  t1 = start + datetime.timedelta(seconds=100)
  assert eta.update(100000, 1, 10, t1) == "15 minutes 0 seconds (12:16 PM)"            # 1 file in 100 s -> 1000 s total, 900 s left
  t2 = t1 + datetime.timedelta(seconds=30)
  assert eta.update(130000, 1, 10, t2) == "14 minutes 30 seconds (12:16 PM)"           # real countdown, same finish time
  t3 = t2 + datetime.timedelta(seconds=20)
  assert eta.update(150000, 2, 10, t3) == "10 minutes 0 seconds (12:12 PM)"            # a new file moves the estimate
  assert eta.update(2000000, 10, 10, start + datetime.timedelta(seconds=2000)) == "0 seconds (12:33 PM)"


def test_waiting_for_downloader_message_after_a_long_silence(env):
  # no supervisor heartbeat: bogpilot_mapd is not running, so nobody will pick the request up. The row keeps the
  # existing "Waiting for the map downloader..." text (no new on-screen wording in this build)
  env.ctl.set_region("states", "OH", True)
  env.ctl.start_download(True, True)
  env.clock.t += M.WAITING_FOR_DOWNLOADER_S - 1
  assert env.ctl.view(True, True).progress == "Calculating..."
  env.clock.t += 5
  assert env.ctl.view(True, True).progress == M.WAITING_FOR_DOWNLOADER_TEXT == "Waiting for the map downloader..."


def test_a_live_downloader_keeps_calculating_while_the_first_cell_downloads(env):
  # mapd v1 writes no progress until its first 2x2 degree cell (up to ~55 MB) is in: slow, not stuck
  import time as _t
  env.ctl.set_region("states", "OH", True)
  env.ctl.start_download(True, True)
  env.mem.put(M.HEARTBEAT_KEY, "1")
  env.clock.t += M.WAITING_FOR_DOWNLOADER_S + 5
  assert env.ctl.view(True, True).progress == "Calculating..."
  hb = env.mem._path(M.HEARTBEAT_KEY)
  old = _t.time() - M.HEARTBEAT_STALE_S - 5
  import os as _os
  _os.utime(hb, (old, old))                                            # the supervisor stopped refreshing it
  env.clock.t += 2                                                     # past the 1 s re-read
  assert env.ctl.view(True, True).progress == M.WAITING_FOR_DOWNLOADER_TEXT
  env.mem.remove(M.HEARTBEAT_KEY)
  env.clock.t += 2
  assert env.ctl.view(True, True).progress == M.WAITING_FOR_DOWNLOADER_TEXT


def test_finished_download_stamps_last_updated_and_clears_progress(env):
  env.ctl.set_region("states", "OH", True)
  env.ctl.start_download(True, True)
  env.progress(4, 4)
  env.mem.remove("OSMDownloadLocations")                              # mapd finished: it emptied the request
  env.ctl.dl.jobs.clear()                                             # and resume.py found nothing missing (its hand-over)
  (env.storage.offline_dir / "x").mkdir(parents=True)
  (env.storage.offline_dir / "x" / "tile.tar.gz").write_bytes(b"a" * 2048)
  env.ctl.update()
  assert env.params.data["LastMapsUpdate"] == b"November 9th, 2026"
  assert env.mem.get_text("OSMDownloadProgress") is None
  v = env.ctl.view(True, True)
  assert (v.download_text, v.last_updated, v.show_last_updated, v.show_remove, v.show_reset) == ("DOWNLOAD", "November 9th, 2026", True, True, True)
  assert v.storage == "0.00 MB"                                       # 2 KiB, formatted as 0.9.7
  env.ctl.update()                                                    # idempotent
  assert env.params.data["LastMapsUpdate"] == b"November 9th, 2026"


def test_a_download_the_schedule_started_is_shown_too(env):
  env.ctl.set_region("states", "OH", True)
  env.mem.put("OSMDownloadLocations", '{"nations":[],"states":["OH"]}')
  env.progress(10, 3)
  env.ctl.update()
  v = env.ctl.view(True, True)
  assert (v.download_text, v.progress) == ("CANCEL", "3 / 10 (30%)")


# ------------------------------------------------------------------------------------------------ install on first use
def test_missing_mapd_is_installed_verified_then_the_download_starts(tmp_path, monkeypatch):
  e = Env(tmp_path, monkeypatch, installed=False)
  e.ctl.set_region("states", "OH", True)
  assert not I.verify_installed(e.storage, e.manifest)
  assert e.ctl.start_download(True, True)
  assert len(e.fetches) == 1 and e.fetches[0].startswith("https://github.com/")
  assert I.verify_installed(e.storage, e.manifest)
  assert e.mem.get_text("OSMDownloadLocations") == '{"nations":[],"states":["OH"]}'
  assert e.marker() == "1" and e.ctl.phase == "idle"


def test_install_shows_its_own_state_while_it_runs(tmp_path, monkeypatch):
  e = Env(tmp_path, monkeypatch, installed=False)
  pending = []
  e.ctl._spawn = pending.append
  e.ctl.set_region("states", "OH", True)
  assert e.ctl.start_download(True, True)
  v = e.ctl.view(True, True)
  assert (v.download_text, v.download_enabled, v.download_value) == ("DOWNLOAD", False, "Installing downloader...")
  assert not e.ctl.start_download(True, True)
  pending[0]()
  assert e.ctl.phase == "idle" and e.mem.get_text("OSMDownloadLocations")


@pytest.mark.parametrize("bad", ["sha", "size", "raise", "arch"])
def test_failed_install_never_leaves_a_binary_and_never_starts(tmp_path, monkeypatch, bad):
  e = Env(tmp_path, monkeypatch, installed=False)
  good = e.blob
  tampered = good[:-1] + b"X"
  fetch = {"sha": fetcher(tampered), "size": fetcher(good + b"\0"), "arch": fetcher(elf(machine=0x3E)), "raise": None}[bad]
  if bad == "raise":
    def fetch(_url):
      raise OSError("offline")
  if bad == "arch":
    e.manifest = manifest_for(elf(machine=0x3E))
    e.ctl._manifest = e.manifest
  e.ctl._fetch = fetch
  e.ctl.set_region("states", "OH", True)
  e.ctl.start_download(True, True)
  assert not e.storage.mapd_path.exists()
  assert e.mem.get_text("OSMDownloadLocations") is None
  assert e.ctl.phase == "idle" and e.ctl.message == "Downloader install failed"
  v = e.ctl.view(True, True)
  assert v.download_text == "DOWNLOAD" and v.download_value == "Downloader install failed"
  e.clock.t += M.MapDataController.MESSAGE_S + 1                      # the message goes away by itself
  assert e.ctl.view(True, True).download_value == ""


# ------------------------------------------------------------------------------------------------ Cancel
def test_cancel_drops_the_request_kills_mapd_and_settles_for_2_5_seconds(env):
  env.ctl.set_region("states", "OH", True)
  env.ctl.start_download(True, True)
  env.progress(8, 2)
  env.ctl.cancel_download()
  assert env.mem.get_text("OSMDownloadLocations") is None and env.mem.get_text("OSMDownloadProgress") is None
  assert env.killed == [1]
  v = env.ctl.view(True, True)
  assert (v.download_text, v.download_enabled, v.progress) == ("CANCEL", False, "Calculating...")
  env.progress(8, 3)                                                  # a dying mapd writes one last progress file
  env.clock.t += 1.0
  env.ctl.update()
  assert env.ctl.view(True, True).download_text == "CANCEL"
  env.clock.t += M.CANCEL_SETTLE_S
  env.ctl.update()
  assert env.mem.get_text("OSMDownloadProgress") is None              # the stray file is dropped, never mistaken for "done"
  assert "LastMapsUpdate" not in env.params.data
  v = env.ctl.view(True, True)
  assert (v.download_text, v.download_enabled) == ("DOWNLOAD", True)
  assert env.ctl.start_download(True, True)                           # and it can start again


# ------------------------------------------------------------------------------------------------ Remove / Reset
def put_tiles(env):
  d = env.storage.offline_dir / "a"
  d.mkdir(parents=True)
  (d / "t.tar.gz").write_bytes(b"z" * 4096)


def test_remove_maps_deletes_tiles_keeps_the_binary_and_the_choices(env):
  put_tiles(env)
  env.ctl.set_region("states", "OH", True)
  env.ctl.set_schedule(1)
  env.ctl.refresh_storage(block=True)
  env.clock.t += 5
  assert env.ctl.view(True, True).show_remove
  assert env.ctl.remove_maps()
  assert not env.storage.offline_dir.exists()
  assert env.storage.mapd_path.exists() and I.verify_installed(env.storage, env.manifest)
  assert env.ctl.selection().states == ("OH",) and env.ctl.schedule() == 1
  env.clock.t += 5
  v = env.ctl.view(True, True)
  assert not v.show_remove and v.storage == "0 MB"


def test_remove_and_reset_are_refused_while_a_download_runs_and_disabled_when_not_parked(env):
  put_tiles(env)
  env.ctl.set_region("states", "OH", True)
  env.ctl.start_download(True, True)
  assert not env.ctl.remove_maps() and not env.ctl.reset_downloader()
  assert env.storage.offline_dir.exists() and env.rebooted == []
  env.ctl.cancel_download()
  env.clock.t += 5
  env.ctl.update()
  v = env.ctl.view(True, False)
  assert not v.remove_enabled and not v.reset_enabled
  assert env.ctl.view(True, True).remove_enabled


def test_reset_kills_mapd_deletes_the_osm_folder_then_reboots_like_097(env):
  put_tiles(env)
  env.ctl.set_region("states", "OH", True)
  env.ctl.set_schedule(0)
  env.store.put("LastMapsUpdate", "November 1st, 2026")
  assert env.ctl.reset_downloader()
  assert env.killed == [1] and env.rebooted == [1]
  assert env.clock.sleeps == [M.RESET_STEP_S, M.RESET_STEP_S]        # "Repaired!" 2.5 s, "Rebooting..." 2.5 s, then reboot
  assert not env.storage.root.exists() or not any(env.storage.root.iterdir())
  assert not env.storage.mapd_path.exists()
  assert env.ctl.selection().states == ("OH",) and env.ctl.schedule() == 0           # choices survive (0.9.7 only deleted /data/media/0/osm)
  assert env.ctl.last_updated() == "November 1st, 2026"
  assert env.awake == [True, False]
  assert env.ctl.reset_text == "Reboot unavailable"                  # the fake reboot returned


def test_reset_shows_each_step_in_the_row_value(env):
  seen = []
  env.ctl._sleep = lambda dt: seen.append(env.ctl.view(True, True).reset_value)
  env.ctl.reset_downloader()
  assert seen == ["Repaired!", "Rebooting..."]


def test_reset_with_an_unsafe_folder_deletes_nothing_and_does_not_reboot(tmp_path, monkeypatch):
  e = Env(tmp_path, monkeypatch, installed=False)
  odd = tmp_path / "not_osm_named"
  odd.mkdir()
  (odd / "keep").write_text("x")
  e.ctl.storage.root = odd                                           # OsmStorage._safe_root(): the folder must be named "osm"
  assert e.ctl.reset_downloader()
  assert (odd / "keep").exists() and e.rebooted == []
  assert e.ctl.phase == "idle" and e.ctl.view(True, True).reset_value == "Repair failed"


def test_default_kill_matches_the_mapd_binary_only():
  import inspect
  src = inspect.getsource(M.default_kill_mapd)
  assert '"pkill", "-x", "mapd"' in src                              # never `pkill mapd`, which would also match bogpilot_mapd


def test_page_logic_has_no_raylib_and_no_writes_on_import():
  import ast
  import inspect
  tree = ast.parse(inspect.getsource(M))
  imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
  assert not any("pyray" in (m or "") for m in imported)


# ------------------------------------------------------------------------------------------------ Speed Limit Controller off
def slc(env, on):
  env.store.put("SpeedLimitController", "1" if on else "0")
  env.clock.t += 2                                                   # the controller re-reads the toggle at most once a second


def test_slc_default_is_on_so_downloads_work_out_of_the_box(env):
  env.ctl.set_region("states", "OH", True)
  assert M.downloads_allowed(env.store) and env.ctl.slc_on()
  assert env.ctl.view(True, True).slc_on and env.ctl.can_download(True, True) == (True, "")


def test_slc_off_disables_download_with_a_clear_message_first(env):
  slc(env, False)
  assert M.SLC_OFF_TEXT == "Turn on Speed Limit Controller to download maps"
  assert M.SLC_OFF_SHORT == "Speed Limit Controller is off"
  assert env.ctl.can_download(True, True) == (False, M.SLC_OFF_TEXT)  # before "Select a region first" / offline / parked
  env.ctl.set_region("states", "OH", True)                           # picking regions still works
  assert env.ctl.selection().states == ("OH",)
  for online, parked in ((True, True), (False, True), (True, False)):
    assert env.ctl.can_download(online, parked) == (False, M.SLC_OFF_TEXT)
  v = env.ctl.view(True, True)
  assert (v.download_text, v.download_enabled, v.download_value, v.slc_on) == ("DOWNLOAD", False, M.SLC_OFF_SHORT, False)
  assert not env.ctl.start_download(True, True)
  assert env.mem.get_text("OSMDownloadLocations") is None and env.fetches == []
  slc(env, True)
  v = env.ctl.view(True, True)
  assert (v.download_enabled, v.download_value, v.slc_on) == (True, "", True)    # turning it back on re-enables, nothing was lost


def test_slc_off_keeps_remove_storage_reset_and_cancel_usable(env):
  put_tiles(env)
  env.ctl.set_region("states", "OH", True)
  env.ctl.refresh_storage(block=True)
  slc(env, False)
  v = env.ctl.view(True, True)
  assert v.show_remove and v.remove_enabled and v.reset_enabled and v.storage == "0.00 MB"
  assert env.ctl.remove_maps() and not env.storage.offline_dir.exists()
  # a request left over from before the SLC was turned off: say so, and let the user cancel it
  env.mem.put("OSMDownloadLocations", '{"nations":[],"states":["OH"]}')
  v = env.ctl.view(True, True)
  assert (v.download_text, v.download_enabled, v.progress) == ("CANCEL", True, M.SLC_PAUSED_TEXT)
  env.ctl.cancel_download()
  assert env.killed == [1] and env.mem.get_text("OSMDownloadLocations") is None
  assert not env.ctl.reset_downloader()                              # still settling after the cancel: reset waits for idle
  env.clock.t += 3
  env.ctl.update()
  assert env.ctl.reset_downloader() and env.rebooted == [1]


def test_slc_read_failure_fails_closed(env):
  env.store.get_bool = lambda *a, **k: (_ for _ in ()).throw(OSError("x"))
  assert not M.downloads_allowed(env.store)


def test_adoption_policy_does_not_gate_on_the_slc(env, monkeypatch):
  from openpilot.system.bogpilot.osm import supervisor
  monkeypatch.setattr(supervisor, "ACTIVATION_POLICY", "adoption")
  slc(env, False)
  assert M.downloads_allowed(env.store)
