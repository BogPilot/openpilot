"""BogPilot > Navigation > Maps (FrogPilot OSM downloader port): page rows, region screens, onroad rules, comma 4 cards.

No window: fonts / textures are stubbed as in test_comma4_menu_parity, the store is a fake Params, the OSM folder and mapd
params are tmp dirs, mapd kill / reboot / fetch are fakes. Nothing reaches the network, kills a process or reboots."""
import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pyray as rl

from openpilot.system.ui.lib.application import EXTRA_FONT_CHARS, gui_app

ATLAS = set(map(chr, range(32, 127))) | set(EXTRA_FONT_CHARS) | {"\n"}
KEYS = ("MapsSelected", "PreferredSchedule", "LastMapsUpdate", "SpeedLimitController")


class FakeParams:
  def __init__(self):
    self.data = {"SpeedLimitController": b"1"}

  def all_keys(self):
    return list(KEYS)

  def get(self, key):
    return self.data.get(key)

  def put(self, key, value):
    self.data[key] = str(value).encode()

  def remove(self, key):
    self.data.pop(key, None)


class MapsPageCase(unittest.TestCase):
  def setUp(self):
    self.tmp = Path(tempfile.mkdtemp(prefix="maps-page-"))
    os.environ["BOGPILOT_PARAMS_DIR"] = str(self.tmp / "bp")
    for name, value in (("font", lambda *a, **k: rl.Font()), ("texture", lambda *a, **k: rl.Texture())):
      p = mock.patch.object(gui_app, name, value)
      p.start()
      self.addCleanup(p.stop)
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.selfdrive.ui.bogpilot import map_data_page as P
    from openpilot.selfdrive.ui.bogpilot import onroad_policy as OP
    from openpilot.system.bogpilot.osm import map_data_controller as M
    from openpilot.system.bogpilot.osm import installer as I
    from openpilot.system.bogpilot.osm.memparams import MemParams
    from openpilot.system.bogpilot.osm.storage import OsmStorage
    from openpilot.system.bogpilot.osm.tests.test_installer import elf, fetcher, manifest_for
    self.P, self.M, self.OP = P, M, OP
    self.params = FakeParams()
    self.store = ParamStore(self.params)
    self.mem = MemParams(self.tmp / "d")
    self.storage = OsmStorage(self.tmp / "osm")
    self.storage.disk_free = lambda: 50 * 1024 ** 3
    blob = elf()
    man = manifest_for(blob)
    I.install(self.storage, man, fetcher(blob))
    self.drive = {"started": False, "parked": True}
    OP.set_state(OP.DriveState(started=lambda: self.drive["started"], parked=lambda: self.drive["parked"], engaged=lambda: False))
    self.addCleanup(OP.set_state, None)
    self.asked = []
    self.ctl = M.MapDataController(self.store, mem=self.mem, storage=self.storage, manifest=man, fetch=fetcher(blob),
                                   kill_mapd=lambda: None, reboot=lambda: None, spawn=lambda fn: fn(), sleep=lambda dt: None,
                                   monotonic=lambda: 100.0, now=lambda: datetime.datetime(2026, 11, 20, 12, 0, 0))
    self.page = P.MapDataLayout(self.store, self.ctl, online=lambda: True, parked=P.device_parked,
                                confirm=lambda *a, **k: self.asked.append(a), keep_awake=lambda on: None)
    self.page.show_event()
    self.page._update_state()

  def rows(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    return [rm.Row(i) for i in rm.static_rows(self.page)]


class TestMainPage(MapsPageCase):
  def test_rows_in_frogpilot_order_with_the_credit(self):
    titles = [r.title() for r in self.rows()]
    self.assertEqual(titles[1:], ["Automatically Update Maps", "Download Maps", "Last Updated", "Countries", "U.S. States",
                                  "Progress", "Time Elapsed", "Time Remaining", "Remove Maps", "Repair Map Downloads",
                                  "Use mapd v2", "Storage Used", "\u00a9 OpenStreetMap contributors"])
    self.assertIn("\u00a9", EXTRA_FONT_CHARS)

  def test_every_row_is_a_comma4_kind_and_draws_without_question_marks(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    screens = [()] + [(k,) for k in ("nations", "states")]
    screens += [(k, label) for k in ("nations", "states") for label, _ in self.page._groups(k)]
    for path in screens:
      if path:
        self.page.open_screen(path)
      for r in self.rows():
        self.assertNotEqual(r.kind, rm.UNSUPPORTED, (path, r.title()))
        for title, value in rm.card_labels(r):
          self.assertEqual(sorted(set(title + value) - ATLAS), [], (path, title, value))
      self.page.navigation_back() if path else None

  def test_region_screens_save_the_selection_and_back_steps_up(self):
    self.page.open_screen(("states",))
    self.assertEqual(self.page.navigation_title, "U.S. States")
    groups = [r.title() for r in self.rows() if r.button_text() == "OPEN" and r.title() not in ("Countries", "U.S. States")]
    self.assertIn("Northeast", groups)
    self.page.open_screen(("states", "United States - Northeast"))
    self.assertEqual(self.page.navigation_title, "Northeast")
    ri = self.page.region_rows["RI"]
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    self.assertTrue(rm.Row(ri).toggle())
    self.assertEqual(json.loads(self.params.data["MapsSelected"])["states"], ["RI"])
    self.assertTrue(self.page.navigation_back())
    self.assertEqual(self.page.navigation_title, "U.S. States")
    self.assertTrue(self.page.navigation_back())
    self.assertEqual(self.page.navigation_title, "Maps")
    self.assertFalse(self.page.navigation_back())
    self.assertEqual(self.page.rows["states"].action_item.value, "1 selected")


class TestWhileDriving(MapsPageCase):
  def pick(self):
    self.ctl.set_region("states", "RI", True)
    self.page._update_state()

  def test_download_can_start_while_driving(self):
    self.pick()
    self.drive.update(started=True, parked=False)
    self.page._update_state()
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    dl = rm.Row(self.page.rows["download"])
    self.assertTrue(dl.enabled())
    self.assertTrue(dl.press())
    self.assertEqual(json.loads(self.mem.get_text("OSMDownloadLocations"))["states"], ["RI"])

  def test_remove_and_repair_need_park_but_region_picks_do_not(self):
    self.pick()
    (self.storage.offline_dir / "40" / "-72").mkdir(parents=True)
    (self.storage.offline_dir / "40" / "-72" / "t").write_bytes(b"x")
    self.drive.update(started=True, parked=False)
    self.ctl._maps_checked = -1e9
    self.page._update_state()
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    self.assertFalse(rm.Row(self.page.rows["remove"]).enabled())
    self.assertFalse(rm.Row(self.page.rows["repair"]).enabled())
    self.page.open_screen(("nations", "Europe"))
    self.assertTrue(all(rm.Row(r).enabled() for r in self.page.region_rows.values()))
    self.page.navigation_back()
    self.page.navigation_back()
    self.drive.update(parked=True)
    self.page._update_state()
    self.assertTrue(rm.Row(self.page.rows["remove"]).enabled())

  def test_policy_classes(self):
    OP = self.OP
    self.assertEqual(OP.page_class("maps"), OP.ONROAD)
    self.assertEqual(OP.row_class("maps:download", "maps"), OP.ONROAD)
    self.assertEqual(OP.row_class("maps:remove", "maps"), OP.PARKED)
    self.assertEqual(OP.row_class("maps:repair", "maps"), OP.PARKED)
    self.assertEqual(OP.ROW_CLASS["downloads"], OP.PARKED)          # models and other downloads keep the Park rule
    self.assertFalse(OP.downloads_allowed(True, False))

  def test_storage_floor_stop_is_shown(self):
    from openpilot.system.bogpilot.osm import resume as RS
    self.pick()
    self.assertTrue(self.ctl.start_download(True, True))
    self.storage.disk_free = lambda: RS.SPACE_FLOOR_BYTES - 1
    self.assertEqual(RS.Resumer(self.mem, self.storage, online=lambda: True).step(), RS.NO_SPACE)
    self.page._update_state()
    self.assertEqual(self.page._view.download_value, self.M.NO_SPACE_TEXT)
    self.assertEqual(self.page._view.download_text, "DOWNLOAD")


class TestMenu(unittest.TestCase):
  def test_navigation_section_has_maps(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    nav = next(s for s in menu_sections() if s.key == "navigation")
    self.assertEqual([p.label for p in nav.pills], ["NAVIGATION", "MAPS"])
    maps = nav.pills[1]
    self.assertEqual([(pg.key, pg.title) for pg in maps.pages], [("maps", "Maps")])
    from openpilot.selfdrive.ui.bogpilot import map_data_page as P
    self.assertEqual(maps.pages[0].controls, P.CONTROLS)

  def test_help_entries_exist(self):
    from openpilot.selfdrive.ui.bogpilot import map_data_page as P
    from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve
    for key in set(P.HELP_KEYS):
      self.assertIsNotNone(resolve(key), key)


if __name__ == "__main__":
  unittest.main()


class TestSpeedLimitControllerRule(MapsPageCase):
  """Downloads (manual and scheduled) need the Speed Limit Controller on; the page says why."""

  def slc(self, on):
    self.params.data["SpeedLimitController"] = b"1" if on else b"0"
    self.ctl._slc_checked = -1e9          # skip the 1 s cache
    self.page._update_state()

  def test_slc_off_explains_and_locks_download_and_schedule(self):
    self.ctl.set_region("states", "RI", True)
    self.slc(False)
    p = self.page
    self.assertTrue(p.notice.is_visible)
    self.assertEqual(p.notice.title, self.M.SLC_OFF_TEXT)
    self.assertIn("only download while the Speed Limit Controller is on", p.rows["schedule"].description)   # row help
    self.assertFalse(p.rows["schedule"].action_item.enabled)
    self.assertFalse(p.rows["download"].action_item.enabled)
    self.assertEqual(p.rows["download"].action_item.value, self.M.SLC_OFF_SHORT)
    p._on_download()                                                   # a tap that slips through still starts nothing
    self.assertIsNone(self.mem.get("OSMDownloadLocations"))
    self.assertIsNone(self.ctl.dl.jobs.load())
    before = self.ctl.schedule()
    p._on_schedule(0 if before else 1)
    self.assertEqual(self.ctl.schedule(), before)

  def test_slc_on_hides_the_notice_and_allows_download(self):
    self.ctl.set_region("states", "RI", True)
    self.slc(True)
    self.assertFalse(self.page.notice.is_visible)
    self.assertTrue(self.page.rows["download"].action_item.enabled)
    self.assertTrue(self.page.rows["schedule"].action_item.enabled)

  def test_help_says_downloads_need_slc_and_scheduled_need_unmetered_wifi(self):
    from openpilot.selfdrive.ui.bogpilot import toggle_help as H
    e = H.HELP["PreferredSchedule"]
    sched = " ".join((e.what, e.when, e.note, e.default))
    self.assertIn("Speed Limit Controller", sched)
    self.assertIn("unmetered Wi-Fi", sched)
    self.assertIn("Weekly", sched)
    self.assertIn("Needs \"Speed Limit Controller\" on", self.P.DOWNLOAD_DESC)


class TestComma4Host(MapsPageCase):
  """The comma 4 PageHost around the Maps page (found while rendering it: PageHost stored its menu as self._layout, which
  hides Widget._layout(), so the first render() of any comma 4 BogPilot page raised TypeError)."""

  def host(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.layout import PageHost

    class Menu:
      def open_choice(self, source): pass
      def open_stepper(self, row): pass
      def page_note(self): return ""
    return PageHost(Menu(), ("maps", "maps"), self.page, "Maps")

  def test_page_host_keeps_the_widget_layout_method(self):
    from openpilot.system.ui.widgets.scroller import NavScroller
    h = self.host()
    self.assertNotIn("_layout", vars(h))
    self.assertIs(type(h)._layout, NavScroller._layout)

  def test_page_host_turns_the_maps_rows_into_cards(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    h = self.host()
    rows = rm.static_rows(self.page)          # no drawing (no window here), the parity test's walk
    try:
      h._sync_cards(rows)
    except OSError as e:          # the card widgets read params: native (AGNOS runner) only, as in test_comma4_menu_parity
      self.skipTest(f"needs built msgq / params ({type(e).__name__})")
    self.assertGreaterEqual(len(rows), 8)
    self.assertGreater(len(h._scroller._items), len(rows))      # header + at least one card per row
