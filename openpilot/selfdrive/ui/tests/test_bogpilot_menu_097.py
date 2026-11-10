"""0.9.7-style BogPilot menu (t1024) and the Bog to the Future row (t1025).

Pure tests (no window): the section / pill / page mapping, Tuning Level filtering, saved-choice preservation, the flame tracks
file round trip. Native tests (RAYLIB_BACKEND=headless): the real panel at 2160x1080, every pill opening its page, taps on the
Tuning Level control, help on every row. Set T1024_SHOTS=/dir to also write the screenshots.
"""
import os
import tempfile
import unittest

EXPECTED_ROWS = (
  ("alerts_sounds", "Alerts and Sounds", ("MANAGE",)),
  ("driving", "Driving Controls", ("DRIVING MODEL", "GAS / BRAKE", "STEERING")),
  ("navigation", "Navigation", ("NAVIGATION",)),
  ("system", "System Settings", ("DATA", "DEVICE CONTROLS", "UTILITIES")),
  ("theme", "Appearance", ("APPEARANCE",)),
  ("vehicle", "Vehicle Settings", ("VEHICLE SETTINGS", "WHEEL CONTROLS")),
)


def _fake_device_type():
  if not os.path.exists("/sys/firmware/devicetree/base/model"):
    import openpilot.common.hardware.comma.hardware as comma_hw
    comma_hw.get_device_type = lambda: "pc"


class MemoryParams:
  def __init__(self):
    self.data = {}
    self.writes = 0

  def all_keys(self):
    return []

  def get(self, key):
    return self.data.get(key)

  def put(self, key, value):
    self.writes += 1
    self.data[key] = str(value)

  def remove(self, key):
    self.writes += 1
    self.data.pop(key, None)


class MenuCase(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.tmp = tempfile.mkdtemp(prefix="menu097-")
    os.environ["BOGPILOT_PARAMS_DIR"] = os.path.join(cls.tmp, "bp")
    os.makedirs(os.environ["BOGPILOT_PARAMS_DIR"], exist_ok=True)
    _fake_device_type()

  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
    for name in os.listdir(os.environ["BOGPILOT_PARAMS_DIR"]):
      os.remove(os.path.join(os.environ["BOGPILOT_PARAMS_DIR"], name))
    self.params = MemoryParams()
    self.store = ParamStore(self.params)
    self.writes = {"n": 0}
    for name in ("put", "put_bool", "remove"):
      original = getattr(self.store, name)

      def wrapper(*a, _o=original, **k):
        self.writes["n"] += 1
        return _o(*a, **k)
      setattr(self.store, name, wrapper)
    tl.set_store(self.store)
    self.tl = tl

  def tearDown(self):
    self.tl.set_store(None)

  @staticmethod
  def radar_reads(read_toggle):
    """The radar producer's reader (BOGPILOT_DIR is fixed at import, so point it at the test directory)."""
    from pathlib import Path
    from unittest import mock
    from openpilot.common import bogpilot_toggles
    with mock.patch.object(bogpilot_toggles, "BOGPILOT_DIR", Path(os.environ["BOGPILOT_PARAMS_DIR"])):
      return read_toggle("BSMFlameTracks", True)

  def save_level(self, level, confirmed=True):
    self.store.put("TuningLevel", level)
    if confirmed:
      self.store.put("TuningLevelConfirmed", "1")
    self.store.invalidate()
    self.tl.invalidate()
    self.writes["n"] = 0
    self.params.writes = 0

  def saved(self):
    """Every saved BogPilot value: Params-backed keys and the legacy files."""
    self.store.invalidate()
    out = dict(self.params.data)
    root = os.environ["BOGPILOT_PARAMS_DIR"]
    for name in sorted(os.listdir(root)):
      with open(os.path.join(root, name)) as f:
        out[name] = f.read().strip()
    return out


class TestMapping(MenuCase):
  def test_sections_rows_and_pills_match_the_097_menu(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    got = tuple((s.key, s.title, tuple(p.label for p in s.pills)) for s in menu_sections())
    self.assertEqual(got, EXPECTED_ROWS)

  def test_dropped_pills_are_not_offered(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    labels = {p.label for s in menu_sections() for p in s.pills}
    self.assertFalse(labels & {"MAP DATA", "THEME"})

  def test_every_page_is_real_and_reachable_exactly_once(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections, working_pages
    menu = [pg.key for s in menu_sections() for p in s.pills for pg in p.pages]
    self.assertEqual(len(menu), len(set(menu)))
    existing = {pg.key for group in working_pages().values() for pg in group}
    self.assertEqual(existing - set(menu), set(), "a working page has no pill")
    self.assertEqual(set(menu) - existing, {"navigation_widgets", "appearance"})
    for s in menu_sections():
      for p in s.pills:
        for pg in p.pages:
          self.assertTrue(callable(pg.factory) and pg.controls, pg.key)

  def test_lane_changes_under_steering_and_visuals_under_appearance(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    pills = {p.key: p for s in menu_sections() for p in s.pills}
    self.assertEqual([pg.key for pg in pills["steering"].pages], ["steering_tuning", "lane_changes"])
    from openpilot.selfdrive.ui.layouts.settings import bogpilot_visuals as bv
    appearance = pills["appearance"].pages[0].controls
    nav = pills["navigation"].pages[0].controls
    self.assertEqual(set(appearance) | set(nav), set(bv.VISUAL_KEYS))
    self.assertFalse(set(appearance) & set(nav))
    self.assertEqual(nav, ("NavigationUI", "ShowSpeedLimits"))

  def test_visuals_is_no_longer_a_sidebar_panel(self):
    from pathlib import Path
    from openpilot.selfdrive.ui.layouts.settings import settings as S
    src = Path(S.__file__).read_text()
    self.assertNotIn("BOGPILOT_VISUALS", src)
    self.assertNotIn("BogPilotVisualsLayout", src)
    self.assertEqual([p.name for p in S.PanelType], ["DEVICE", "NETWORK", "TOGGLES", "SOFTWARE", "BOGPILOT", "DEVELOPER"])

  def test_icons_exist_and_are_crisp_at_tici_scale(self):
    from pathlib import Path
    from PIL import Image
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.layouts.settings import menu_097
    import openpilot.selfdrive as sd
    root = Path(sd.__file__).parent / "assets/icons" / menu_097.ICON_DIR
    names = {"menu_tuning.png"} | {s.icon for s in menu_sections()}
    self.assertEqual(len(names), 7)
    for name in names:
      im = Image.open(root / name)
      self.assertEqual(im.mode, "RGBA", name)
      # drawn at 80 px (ListItem ICON_SIZE): the source must be at least 2x so it is only ever downscaled
      self.assertGreaterEqual(min(im.size), 160, name)
      self.assertIsNotNone(im.getchannel("A").getbbox(), name)


class TestTuningLevel(MenuCase):
  def nav(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import MenuNavigation
    return MenuNavigation(menu_sections(), lambda: None, lambda *_: None)

  def shown(self, nav, level):
    return {s.key: tuple(p.key for p in nav.pills_of(s, level)) for s in nav.visible_sections(level)}

  def test_default_keeps_todays_full_set(self):
    nav = self.nav()
    self.assertEqual(self.tl.effective_level(), 3)
    self.assertFalse(self.tl.is_confirmed())
    full = self.shown(nav, 3)
    self.assertEqual(tuple(full), tuple(r[0] for r in EXPECTED_ROWS))
    self.assertEqual(sum(len(v) for v in full.values()), 11)
    # a saved but never confirmed level is ignored: still Developer
    self.save_level(0, confirmed=False)
    self.assertEqual(self.tl.effective_level(), 3)
    for s in nav.sections:
      for p in s.pills:
        self.assertEqual(nav.pages_of(p), p.pages, p.key)   # every page visible by default

  def test_levels_only_ever_hide_more_going_down(self):
    nav = self.nav()
    previous = None
    for level in (3, 2, 1, 0):
      current = {(s, p) for s, ps in self.shown(nav, level).items() for p in ps}
      if previous is not None:
        self.assertLessEqual(current, previous, level)
      previous = current
    # Minimal still has something in each core area, Developer has all of it
    self.assertIn("alerts_sounds", self.shown(nav, 0))

  def test_hidden_rows_inside_pages_follow_registry_levels(self):
    from openpilot.common.bogpilot_store import registry_level
    tl = self.tl
    self.assertEqual(tl.row_level("BSMFlameTracks"), 1)
    self.assertEqual(tl.row_level("LaneChanges"), registry_level("LaneChanges"))
    self.assertIsNone(tl.row_level("read-only CarParams"))
    self.assertEqual(tl.row_level("group:profiles"), registry_level("LongitudinalTune"))
    for level in range(4):
      for key in ("BSMFlameTracks", "SwapSpeedGraph", "LaneChanges", "NudgelessLaneChange"):
        need = tl.row_level(key)
        self.assertEqual(tl.row_visible(key, level), need is None or level >= need, (key, level))

  def test_set_level_saves_both_params_and_nothing_else(self):
    self.assertTrue(self.tl.set_level(1))
    self.assertEqual(self.saved(), {"TuningLevel": "1", "TuningLevelConfirmed": "1"})
    self.assertEqual(self.tl.effective_level(), 1)
    self.assertTrue(self.tl.set_level(99) and self.tl.effective_level() == 3)

  def test_reading_and_filtering_never_write(self):
    self.save_level(2)
    before = (self.saved(), self.params.writes, self.writes["n"])
    nav = self.nav()
    for level in range(4):
      self.shown(nav, level)
    self.tl.effective_level()
    self.tl.row_visible("BSMFlameTracks")
    self.assertEqual((self.saved(), self.params.writes, self.writes["n"]), before)

  def test_saved_choice_is_read_back(self):
    for level in range(4):
      self.save_level(level)
      self.assertEqual(self.tl.effective_level(), level)
    self.save_level(7)
    self.assertEqual(self.tl.effective_level(), 3)


class NativeCase(MenuCase):
  @classmethod
  def setUpClass(cls):
    super().setUpClass()
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.system.ui.widgets import Widget

    class Base(Widget):
      def _render(self, rect):
        pass

    cls.rl, cls.gui_app = rl, gui_app
    if not gui_app.big_ui() and not rl.is_window_ready():
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("Menu 097 native test")
    cls.base = Base()
    gui_app.push_widget(cls.base)
    cls.shots = os.getenv("T1024_SHOTS")
    if cls.shots:
      os.makedirs(cls.shots, exist_ok=True)


class TestFlameTracksStore(MenuCase):
  """Pure: the store's legacy file path is the file the renderer and the radar producer read."""

  def test_store_round_trip_default_on_saved_off(self):
    from openpilot.common.bogpilot_toggles import read_toggle
    from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import FileToggles
    path = os.path.join(os.environ["BOGPILOT_PARAMS_DIR"], "BSMFlameTracks")

    def renderer():
      return FileToggles(path=os.environ["BOGPILOT_PARAMS_DIR"], read_param=lambda _k: None).get("BSMFlameTracks")
    self.assertTrue(self.store.get_bool("BSMFlameTracks"))     # never written: default ON
    self.assertTrue(renderer())
    self.assertFalse(os.path.exists(path))
    self.store.put_bool("BSMFlameTracks", False)
    self.assertEqual(open(path).read().strip(), "0")
    self.assertFalse(renderer())
    self.assertFalse(self.radar_reads(read_toggle))
    self.assertFalse(self.store.get_bool("BSMFlameTracks"))    # saved OFF is preserved
    self.assertEqual(self.params.data, {})                     # never a Params key
    self.store.put_bool("BSMFlameTracks", True)
    self.assertTrue(renderer())


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestFlameTracksToggle(NativeCase):
  def layout(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    return BogPilotVisualsLayout(store=self.store)

  def flame_file(self):
    return os.path.join(os.environ["BOGPILOT_PARAMS_DIR"], "BSMFlameTracks")

  def renderer_toggle(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import FileToggles
    return FileToggles(path=os.environ["BOGPILOT_PARAMS_DIR"], read_param=lambda _k: None).get("BSMFlameTracks")

  def test_row_is_named_and_helped_and_in_theme_and_appearance(self):
    from openpilot.selfdrive.ui.layouts.settings import bogpilot_visuals as bv
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
    layout = self.layout()
    row = layout._toggles["BSMFlameTracks"]
    self.assertEqual(row.title, "Bog to the Future")
    self.assertIn("BSMFlameTracks", bv.APPEARANCE_KEYS)
    self.assertNotIn("BSMFlameTracks", bv.NAVIGATION_KEYS)
    entry = HELP["BSMFlameTracks"]
    self.assertEqual(entry.title, "Bog to the Future")
    text = (entry.what + entry.when + entry.note).lower()
    for word in ("display only", "88 mph", "blind spot", "tire tracks"):
      self.assertIn(word, text)
    self.assertEqual(row.help_key, "BSMFlameTracks")
    self.assertEqual(self.tl.row_level("BSMFlameTracks"), 1)   # Standard

  def test_default_on_and_nothing_written_by_opening(self):
    layout = self.layout()
    layout.show_event()
    self.assertTrue(layout._toggles["BSMFlameTracks"].action_item.get_state())
    self.assertTrue(self.renderer_toggle())
    self.assertFalse(os.path.exists(self.flame_file()))
    self.assertEqual(self.writes["n"], 0)

  def test_toggle_writes_the_file_the_renderer_reads(self):
    from openpilot.common.bogpilot_toggles import read_toggle
    layout = self.layout()
    toggle = layout._toggles["BSMFlameTracks"].action_item
    toggle.toggle._callback(False)
    self.assertEqual(open(self.flame_file()).read().strip(), "0")
    self.assertFalse(self.renderer_toggle())
    self.assertFalse(self.radar_reads(read_toggle))            # the radar producer's reader
    self.assertNotIn("BSMFlameTracks", self.params.data)       # never a Params key
    toggle.toggle._callback(True)
    self.assertEqual(open(self.flame_file()).read().strip(), "1")
    self.assertTrue(self.renderer_toggle())
    self.assertTrue(self.radar_reads(read_toggle))

  def test_saved_off_is_preserved(self):
    with open(self.flame_file(), "w") as f:
      f.write("0")
    layout = self.layout()
    layout.show_event()
    self.assertFalse(layout._toggles["BSMFlameTracks"].action_item.get_state())
    self.assertFalse(self.renderer_toggle())
    self.assertEqual(open(self.flame_file()).read(), "0")
    self.assertEqual(self.writes["n"], 0)
    # a Tuning Level change never touches the saved choice
    self.assertTrue(self.tl.set_level(0))
    self.assertEqual(open(self.flame_file()).read(), "0")

  def test_keys_filter_keeps_only_the_asked_rows(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout, NAVIGATION_KEYS
    layout = BogPilotVisualsLayout(store=self.store, keys=NAVIGATION_KEYS)
    self.assertEqual(tuple(layout._toggles), NAVIGATION_KEYS)


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestMenuNative(NativeCase):
  def setUp(self):
    super().setUp()
    while len(self.gui_app._nav_stack) > 1:
      self.gui_app.pop_widget()
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import build_menu
    self.warned = []
    self.editable = {"v": True}
    self.menu = build_menu(menu_sections(), store=self.store, can_edit=lambda: self.editable["v"],
                           show_warning=self.warned.append)
    self.menu.show_event()
    # The settings panel hands its content area to the layout: x=500+50, y=25, 1560 x 1030 on the 2160x1080 screen.
    self.content = self.rl.Rectangle(550, 25, 1560, 1030)

  def tearDown(self):
    self.menu.hide_event()
    super().tearDown()

  def _shape_fallbacks(self):
    """The headless backend rasterizes text, lines and textures but not filled shapes, so screenshots draw rectangles, rounded
    rectangles and circles as small textures built on the CPU. Screenshot evidence only; no test depends on it."""
    rl = self.rl
    cache = {}
    keep = []

    def texture(kind, w, h, color, r=0):
      color = rl.Color(*color) if isinstance(color, tuple) else color
      key = (kind, w, h, r, color.r, color.g, color.b, color.a)
      if key not in cache:
        img = rl.gen_image_color(w, h, rl.BLANK)
        if kind == "rect":
          rl.image_draw_rectangle(img, 0, 0, w, h, color)
        elif kind == "circle":
          rl.image_draw_circle(img, w // 2, h // 2, r, color)
        else:
          rl.image_draw_rectangle(img, r, 0, w - 2 * r, h, color)
          rl.image_draw_rectangle(img, 0, r, w, h - 2 * r, color)
          for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
            rl.image_draw_circle(img, cx, cy, r, color)
        cache[key] = rl.load_texture_from_image(img)
        keep.append(img)
      return cache[key]

    def rect(x, y, w, h, color):
      if w >= 1 and h >= 1:
        rl.draw_texture(texture("rect", int(w), int(h), color), int(x), int(y), rl.WHITE)

    def rounded(rec, roundness, _segments, color):
      w, h = int(rec.width), int(rec.height)
      r = int(min(w, h) / 2 * roundness)
      rl.draw_texture(texture("round", w, h, color, r), int(rec.x), int(rec.y), rl.WHITE)

    def circle(cx, cy, radius, color):
      d = int(radius * 2) + 2
      rl.draw_texture(texture("circle", d, d, color, int(radius)), int(cx - d // 2), int(cy - d // 2), rl.WHITE)

    return {"draw_rectangle_rounded": rounded, "draw_rectangle_rec": lambda r, c: rect(r.x, r.y, r.width, r.height, c),
            "draw_rectangle": lambda x, y, w, h, c: rect(x, y, w, h, c), "draw_circle": circle}

  def draw(self, shot=None, frames=3, widget=None):
    rl = self.rl
    if shot and self.shots:
      from unittest import mock
      patches = [mock.patch.object(rl, name, fn) for name, fn in self._shape_fallbacks().items()]
      for p in patches:
        p.start()
      try:
        return self._draw(shot, frames, widget)
      finally:
        for p in patches:
          p.stop()
    return self._draw(shot, frames, widget)

  def _draw(self, shot, frames, widget=None):
    rl = self.rl
    for i in range(frames):
      rl.begin_drawing()
      try:
        rl.clear_background(rl.BLACK)
        rl.draw_rectangle_rounded(rl.Rectangle(510, 10, 1640, 1060), 0.04, 30, rl.Color(41, 41, 41, 255))
        self.menu.render(self.content)
        if widget is not None:
          widget.render(rl.Rectangle(0, 0, self.gui_app.width, self.gui_app.height))
        if shot and self.shots and i == frames - 1:
          img = rl.load_image_from_screen()
          rl.export_image(img, os.path.join(self.shots, shot))
          rl.unload_image(img)
      finally:
        rl.end_drawing()

  def home_rows(self):
    return list(self.menu.navigation.current._items)

  def test_home_has_seven_rows_that_fit_2160x1080(self):
    rl = self.rl
    self.draw()
    rows = [r for r in self.home_rows() if r.is_visible]
    self.assertEqual([r.title for r in rows], ["Tuning Level"] + [r[1] for r in EXPECTED_ROWS])
    top = self.content.y
    for row in rows:
      r = row._rect
      self.assertGreaterEqual(r.x, self.content.x)
      self.assertLessEqual(r.x + r.width, self.content.x + self.content.width + 1)
      self.assertGreaterEqual(r.y, top)
      self.assertLessEqual(r.y + r.height, self.content.y + self.content.height, row.title)   # all seven fit, no scrolling
      right = row.get_right_item_rect(r)
      self.assertLessEqual(right.x + right.width, r.x + r.width)
      self.assertEqual(right.width, row.action_item.get_width_hint(), f"{row.title}: pills clipped")
      # pills do not run into the icon + title
      title_w = rl.measure_text_ex(row._font, row.title, 50, 0).x
      self.assertGreater(right.x, r.x + 20 + 80 + 20 + title_w, row.title)
      for _key, _text, pr in row.action_item.pill_rects(right):
        self.assertGreaterEqual(pr.x, right.x)
        self.assertLessEqual(pr.x + pr.width, right.x + right.width + 1)
        self.assertGreaterEqual(pr.y, r.y)
        self.assertLessEqual(pr.y + pr.height, r.y + r.height)

  def test_every_row_has_help_and_an_icon_and_a_level_gate_free_home(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP, resolve
    for row in self.home_rows():
      self.assertTrue(row.icon and row.icon.startswith("bogpilot/menu_"), row.title)
      self.assertIsNotNone(row.help_callback, row.title)
      self.assertIsNotNone(resolve(row.help_key), row.title)
      self.assertIn(row.help_key, HELP)

  def test_tapping_row_text_opens_help_popup(self):
    self.draw()
    row = self.home_rows()[2]
    depth = len(self.gui_app._nav_stack)
    row._handle_mouse_release(self.rl.Vector2(row._rect.x + 200, row._rect.y + 60))
    self.assertEqual(len(self.gui_app._nav_stack), depth + 1)
    self.assertEqual(self.gui_app.get_active_widget().entry.title, "Driving Controls")

  def tap_pill(self, row, label):
    right = row.get_right_item_rect(row._rect)
    for _key, text, pr in row.action_item.pill_rects(right):
      if text == label:
        row.action_item._rect = right
        row.action_item._handle_mouse_release(self.rl.Vector2(pr.x + pr.width / 2, pr.y + pr.height / 2))
        return
    self.fail(f"no pill {label}")

  def test_every_pill_opens_its_page_and_back_returns(self):
    nav = self.menu.navigation
    expect = {
      "MANAGE": ("manage",), "DRIVING MODEL": ("driving_model", "driving_model"), "GAS / BRAKE": ("gas_brake", "gas_brake"),
      "STEERING": ("steering",), "NAVIGATION": ("navigation", "navigation_widgets"), "DATA": ("data", "system_data"),
      "DEVICE CONTROLS": ("device_controls", "system_device"), "UTILITIES": ("utilities", "system_utilities"),
      "APPEARANCE": ("appearance", "appearance"), "VEHICLE SETTINGS": ("vehicle_settings",),
      "WHEEL CONTROLS": ("wheel_controls", "stalk_controls"),
    }
    self.assertEqual(len(expect), 11)
    self.draw()
    for row in self.home_rows()[1:]:
      for label in [p.label for p in nav.pills_of(next(s for s in nav.sections if s.title == row.title))]:
        self.draw()
        self.assertEqual(nav.path, ())
        self.tap_pill(row, label)
        self.assertEqual(nav.path, expect[label], label)
        self.draw(frames=2)                       # the real page renders without raising
        if len(nav.path) == 1:                    # a page list: open each page in it
          for key, _title in nav.entries():
            nav.open_page(nav.path[0], key)
            self.draw(frames=2)
            self.assertEqual(len(nav.path), 2)
            nav.back()
            self.assertEqual(len(nav.path), 1)
        while nav.path:
          nav.back()
        self.assertEqual(nav.path, ())

  def test_tuning_level_control_saves_and_filters(self):
    nav = self.menu.navigation
    self.draw()
    tuning = self.home_rows()[0]
    labels = [t for _k, t, _r in tuning.action_item.pill_rects(tuning.get_right_item_rect(tuning._rect))]
    self.assertEqual(labels, ["Minimal", "Standard", "Advanced", "Developer"])
    self.assertEqual(self.menu.level(), 3)               # untouched install: Developer, today's full set
    self.tap_pill(tuning, "Minimal")
    self.assertEqual(self.saved(), {"TuningLevel": "0", "TuningLevelConfirmed": "1"})
    self.draw()
    self.assertEqual(self.menu.level(), 0)
    minimal_rows = [r.title for r in self.home_rows() if r.is_visible]
    self.tap_pill(tuning, "Developer")
    self.assertEqual(len(self.warned), 1)
    self.assertIn("WARNING", self.warned[0])
    self.draw()
    all_rows = [r.title for r in self.home_rows() if r.is_visible]
    self.assertEqual(all_rows, ["Tuning Level"] + [r[1] for r in EXPECTED_ROWS])
    self.assertLessEqual(set(minimal_rows), set(all_rows))
    # a second tap on Developer does not warn again
    self.tap_pill(tuning, "Developer")
    self.assertEqual(len(self.warned), 1)

  def test_home_is_built_once_and_survives_a_round_trip(self):
    nav = self.menu.navigation
    home = nav.current
    self.draw()
    self.assertIs(nav.current, home)
    nav.open_pill("manage")
    self.draw(frames=1)
    nav.back()
    self.assertIs(nav.current, home)
    self.assertEqual(nav.path, ())

  def test_tuning_level_is_locked_while_driving(self):
    self.editable["v"] = False
    self.draw()
    tuning = self.home_rows()[0]
    self.tap_pill(tuning, "Minimal")
    self.assertEqual(self.saved(), {})
    self.assertEqual(self.menu.level(), 3)

  def test_saved_level_is_applied_and_opening_writes_nothing(self):
    self.save_level(1)
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import build_menu
    menu = build_menu(menu_sections(), store=self.store, can_edit=lambda: True, show_warning=lambda t: None)
    menu.show_event()
    self.menu.hide_event()
    self.menu = menu
    self.draw()
    self.assertEqual(self.menu.level(), 1)
    self.assertEqual(self.saved(), {"TuningLevel": "1", "TuningLevelConfirmed": "1"})
    self.assertEqual((self.params.writes, self.writes["n"]), (0, 0))

  def test_level_gates_rows_inside_a_page(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    layout = BogPilotVisualsLayout(store=self.store)
    flame, swap = layout._toggles["BSMFlameTracks"], layout._toggles["SwapSpeedGraph"]
    self.assertTrue(flame.is_visible and swap.is_visible)       # default: Developer
    self.tl.set_level(0)
    self.assertFalse(flame.is_visible)
    self.assertFalse(swap.is_visible)
    self.tl.set_level(1)
    self.assertTrue(flame.is_visible)
    self.assertFalse(swap.is_visible)
    self.tl.set_level(2)
    self.assertTrue(swap.is_visible)

  def test_screenshots(self):
    if not self.shots:
      self.skipTest("T1024_SHOTS not set")
    nav = self.menu.navigation
    for level, name in enumerate(("minimal", "standard", "advanced", "developer")):
      self.save_level(level)
      self.draw(shot=f"menu097_home_{name}.png")
    self.save_level(3)
    self.tap_pill(self.home_rows()[5], "APPEARANCE")
    self.draw(shot="menu097_subpage_appearance_developer.png")
    self.save_level(1)
    self.draw(shot="menu097_subpage_appearance_standard.png")
    self.assertEqual(nav.path, ("appearance", "appearance"))
    while nav.path:
      nav.back()
    self.tap_pill(self.home_rows()[2], "STEERING")
    self.save_level(3)
    self.draw(shot="menu097_pagelist_steering.png")
    while nav.path:
      nav.back()
    from openpilot.selfdrive.ui.bogpilot.toggle_help import open_help
    dialog = open_help("BSMFlameTracks")
    self.draw(shot="menu097_help_bog_to_the_future.png", widget=dialog)
    self.draw(shot="menu097_help_tuning_level.png", widget=open_help("menu.tuning_level"))


if __name__ == "__main__":
  unittest.main()
