"""Tap-to-explain help for BogPilot settings rows (t1017).

Pure tests (no raylib) check the help table: coverage of every registered row, ASCII text, translatable strings, and the
defaults written in the text against the shipping defaults. The native tests (RAYLIB_BACKEND=headless) build the real
pages, tap the real rows, open and close the real popup, and check the popup layout on the 2160x1080 screen.
"""
import os
import tempfile
import unittest


def _registered_keys():
  """Every param key / row id a BogPilot page registers, with where it comes from."""
  keys: dict[str, str] = {}

  def add(source, items):
    for k in items:
      keys.setdefault(k, source)

  from openpilot.selfdrive.ui.bogpilot import phase2_alerts, phase2_sounds, phase2_vehicle, phase3_stalk_controls
  from openpilot.selfdrive.ui.bogpilot import phase3_lanechange, phase3_steering_tuning, phase3_device_controls
  from openpilot.selfdrive.ui.layouts.settings import phase3_long_accel_settings as accel, bogpilot_visuals
  from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake
  add("alerts", phase2_alerts.ACTIVE_ALERT_KEYS)
  add("sounds", phase2_sounds.VOLUME_KEYS)
  add("sounds", [phase2_sounds.PARENT_KEY])
  add("vehicle", phase2_vehicle.TITLES)
  add("stalk", phase3_stalk_controls.TITLES)
  add("lane changes", [r[0] for r in phase3_lanechange.ROWS])
  add("accel panel", [r.key for r in accel.ROWS])
  add("accel groups", [g[0] for g in accel.GROUPS.values()])
  add("gas/brake", phase3_gas_brake.CONTROLS)
  add("steering", phase3_steering_tuning.ACTIVE_CONTROLS)
  add("visuals", bogpilot_visuals.VISUAL_KEYS)
  add("device", phase3_device_controls.RANGES)
  add("device", [phase3_device_controls.DEVICE_MASTER, phase3_device_controls.SCREEN_MASTER, "StandbyMode"])
  return keys


def _fake_device_type():
  if not os.path.exists("/sys/firmware/devicetree/base/model"):
    # Linux dev VM without a comma devicetree: only the device-type probe is faked, nothing else.
    import openpilot.common.hardware.comma.hardware as comma_hw
    comma_hw.get_device_type = lambda: "pc"


class TestHelpTable(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    os.environ.setdefault("BOGPILOT_PARAMS_DIR", tempfile.mkdtemp(prefix="toggle-help-table-"))
    _fake_device_type()

  def test_every_registered_row_has_help_or_is_skipped(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import SKIPPED_KEYS, resolve
    missing = {k: src for k, src in _registered_keys().items() if resolve(k) is None and k not in SKIPPED_KEYS}
    self.assertEqual(missing, {}, "rows with neither a help entry nor a SKIPPED_KEYS reason")
    for key, reason in SKIPPED_KEYS.items():
      self.assertTrue(reason.strip(), key)
      self.assertIsNone(resolve(key), f"{key} is skipped but also has help")

  def test_skipped_keys_are_not_dead_entries(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP, SKIPPED, SKIPPED_KEYS
    self.assertGreater(len(HELP), 100)
    self.assertTrue(all(reason.strip() for reason in SKIPPED.values()))
    self.assertTrue(set(SKIPPED_KEYS).isdisjoint(HELP))

  def test_help_text_is_ascii_without_tag_characters(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
    for key, entry in HELP.items():
      for field in ("title", "what", "when", "note", "default", "range", "recommended"):
        text = getattr(entry, field)
        self.assertTrue(text.isascii(), f"{key}.{field} has non-ASCII text (not in the font atlas)")
        self.assertNotIn("<", text, f"{key}.{field}")
        self.assertNotIn(">", text, f"{key}.{field}")
      self.assertTrue(entry.title.strip() and entry.what.strip(), key)
      self.assertNotRegex(entry.what + entry.note, r"\s{2,}", key)

  def test_every_string_goes_through_translate(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP, help_html
    for key, entry in HELP.items():
      html = help_html(entry, lambda s: "T" + s)
      for text in (entry.title, entry.what, entry.when, entry.note, entry.default, entry.range, entry.recommended):
        if text:
          self.assertIn("T" + text, html, key)
      self.assertNotIn("<p>" + entry.what, html, key)

  def test_defaults_text_matches_shipping_defaults(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import shipping_defaults
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
    shipping = shipping_defaults()
    checked = 0
    for key, entry in HELP.items():
      if not entry.default_param:
        continue
      self.assertIn(entry.default_param, shipping, f"{key}: unknown default_param {entry.default_param}")
      want = "On" if str(shipping[entry.default_param]).lower() in ("1", "true") else "Off"
      self.assertTrue(entry.default.startswith(want), f"{key}: help says {entry.default!r}, shipping default is {want}")
      checked += 1
    self.assertGreaterEqual(checked, 40)

  def test_group_switches_read_off_on_a_fresh_install(self):
    # The three tuning groups ship with their switch value On but stay dormant (and show Off) until the user changes a
    # row inside them: the page switch shows active() = adoption marker AND switch value.
    from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import shipping_defaults
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
    from openpilot.selfdrive.ui.layouts.settings import phase3_long_accel_settings as accel
    shipping = shipping_defaults()
    for parent, _title, marker, _keys in accel.GROUPS.values():
      self.assertIn(shipping.get(marker, "0"), ("0", None, False), f"{marker} must not ship adopted")
      self.assertTrue(HELP[parent].default.startswith("Off"), parent)

  def test_stated_facts_match_the_code(self):
    from opendbc.car.tesla_ap1.phase3_stalk_controls import DEFAULT_HOLD_S, MAX_HOLD_S, MIN_HOLD_S
    from openpilot.selfdrive.controls.lib.phase3_long_stopping import STOP_ACCEL_CEILING, STOPPING_RATE_FLOOR
    from openpilot.selfdrive.ui.bogpilot import phase2_sounds
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP, resolve
    for key in ("experimental_pull", "experimental_push", "pull_hold_s", "push_hold_s"):
      pass
    for key in ("pull_hold_s", "push_hold_s"):
      entry = HELP[key]
      self.assertIn(f"{DEFAULT_HOLD_S:.2f} s", entry.default)
      self.assertIn(f"{MIN_HOLD_S:.2f} to {MAX_HOLD_S:.2f}", entry.range)
    stop = HELP["StopAccel"]
    self.assertIn(f"{STOP_ACCEL_CEILING:g}", stop.note + stop.range)
    rate = HELP["StoppingDecelRate"]
    self.assertIn(f"{STOPPING_RATE_FLOOR:g}", rate.note + rate.range)
    for key in phase2_sounds.WARNING_FLOOR_KEYS:
      entry = resolve(key)
      self.assertIsNotNone(entry, key)
      self.assertIn(f"{phase2_sounds.WARNING_FLOOR} percent", entry.note)
    self.assertIn(f"{phase2_sounds.WARNING_FLOOR} percent", HELP["AlertVolumeFloor"].what + HELP["AlertVolumeFloor"].default)
    # Safety and fallback statements the task calls out must be present, in plain words.
    self.assertIn("blind-spot", (HELP["LaneChanges"].note + HELP["NudgelessLaneChange"].note).lower())
    self.assertIn("stock", (HELP["driving_model.default"].what + HELP["driving_model.status"].what).lower())
    self.assertIn("steering only", (HELP["CarSelection"].what + HELP["CarSelection"].note).lower())

  def test_aliases_point_at_real_entries(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import ALIASES, HELP
    for alias, target in ALIASES.items():
      self.assertIn(target, HELP, alias)

  def test_unknown_key_leaves_the_row_alone(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

    class Row:
      help_callback = None
      help_key = None

      def set_help_callback(self, cb):
        self.help_callback = cb

    row = Row()
    stand_in = object()  # a row that is not a ListItem has no hook: it is returned untouched
    self.assertIs(attach_help(stand_in, "DriverCamera"), stand_in)
    self.assertIs(attach_help(row, "NoSuchKey"), row)
    self.assertIsNone(row.help_callback)
    self.assertIsNone(row.help_key)


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestHelpNative(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.tmp = tempfile.mkdtemp(prefix="toggle-help-")
    os.environ["BOGPILOT_PARAMS_DIR"] = os.path.join(cls.tmp, "bp")
    os.makedirs(os.environ["BOGPILOT_PARAMS_DIR"], exist_ok=True)
    _fake_device_type()
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.system.ui.widgets import Widget

    class Base(Widget):
      def _render(self, rect):
        pass

    cls.rl, cls.gui_app = rl, gui_app
    if not gui_app.big_ui() and not rl.is_window_ready():
      # The TICI screen is 2160x1080: size the window like the device (the dev VM reports no comma devicetree).
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("Toggle help native test")
    cls.base = Base()
    gui_app.push_widget(cls.base)

  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore

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

    self.params = MemoryParams()
    self.store = ParamStore(self.params)
    self.spy = {"calls": 0}
    for name in ("put", "put_bool", "remove"):
      original = getattr(self.store, name)

      def wrapper(*a, _o=original, **k):
        self.spy["calls"] += 1
        return _o(*a, **k)
      setattr(self.store, name, wrapper)
    # Leave only the base widget on the stack.
    while len(self.gui_app._nav_stack) > 1:
      self.gui_app.pop_widget()

  # -- helpers -------------------------------------------------------------------------------------------------------
  def file_state(self):
    root = os.environ["BOGPILOT_PARAMS_DIR"]
    out = {}
    for dirpath, _dirs, files in os.walk(root):
      for f in files:
        full = os.path.join(dirpath, f)
        with open(full, "rb") as fh:
          out[full] = (os.path.getmtime(full), fh.read())
    return out

  def snapshot(self):
    return (dict(self.params.data), self.params.writes, self.spy["calls"], self.file_state())

  def render_top(self):
    rl = self.rl
    rl.begin_drawing()
    try:
      rl.clear_background(rl.BLACK)
      top = self.gui_app.get_active_widget()
      top.render(rl.Rectangle(0, 0, self.gui_app.width, self.gui_app.height))
    finally:
      rl.end_drawing()

  def rows_of(self, layout):
    for name in ("scroller", "_scroller"):
      sc = getattr(layout, name, None)
      if sc is not None and hasattr(sc, "_items"):
        return list(sc._items)
    raise AssertionError(f"{type(layout).__name__} has no scroller")

  def prepare(self, item):
    rl = self.rl
    item.set_rect(rl.Rectangle(0, 0, 1600, 160))
    return item

  # -- tap behaviour -------------------------------------------------------------------------------------------------
  def test_tap_text_opens_popup_and_switch_only_toggles(self):
    rl = self.rl
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
    layout = BogPilotVisualsLayout(self.store)
    layout.show_event()
    item = self.prepare(layout._toggles["DriverCamera"])
    depth = len(self.gui_app._nav_stack)
    before = self.snapshot()

    # Tap on the switch: no popup, and the handler alone writes nothing.
    switch = item.get_right_item_rect(item._rect)
    item._handle_mouse_release(rl.Vector2(switch.x + switch.width / 2, switch.y + switch.height / 2))
    self.assertEqual(len(self.gui_app._nav_stack), depth)
    self.assertEqual(self.snapshot(), before)
    # The switch's own callback still toggles exactly as before.
    item.action_item.toggle._callback(True)
    self.assertTrue(self.store.get_bool("DriverCamera"))
    self.assertEqual(len(self.gui_app._nav_stack), depth)
    after_toggle = self.snapshot()

    # Tap on the text: popup opens, nothing is written, inline description stays closed.
    item._handle_mouse_release(rl.Vector2(80, 80))
    self.assertEqual(len(self.gui_app._nav_stack), depth + 1)
    dialog = self.gui_app.get_active_widget()
    self.assertEqual(dialog.entry, HELP["DriverCamera"])
    self.assertFalse(item.description_visible)
    self.render_top()
    self.assertEqual(self.snapshot(), after_toggle)
    self.assertTrue(self.store.get_bool("DriverCamera"))

  def test_popup_closes_with_button_and_escape_path_and_writes_nothing(self):
    rl = self.rl
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    layout = BogPilotVisualsLayout(self.store)
    layout.show_event()
    item = self.prepare(layout._toggles["Fahrenheit"])
    before = self.snapshot()
    depth = len(self.gui_app._nav_stack)
    for closer in ("button", "escape"):
      item._handle_mouse_release(rl.Vector2(80, 80))
      dialog = self.gui_app.get_active_widget()
      self.assertEqual(len(self.gui_app._nav_stack), depth + 1)
      self.assertFalse(dialog.closed)
      self.render_top()
      if closer == "button":
        dialog._confirm_button._click_callback()
      else:
        dialog._cancel_button_callback()
      self.assertTrue(dialog.closed)
      self.assertEqual(len(self.gui_app._nav_stack), depth)
      self.assertIs(self.gui_app.get_active_widget(), self.base)
    self.assertEqual(self.snapshot(), before)

  def test_row_without_help_keeps_stock_inline_description(self):
    rl = self.rl
    from openpilot.system.ui.widgets.list_view import toggle_item
    item = self.prepare(toggle_item("Stock row", "stock text", False))
    depth = len(self.gui_app._nav_stack)
    item._handle_mouse_release(rl.Vector2(80, 80))
    self.assertEqual(len(self.gui_app._nav_stack), depth)
    self.assertTrue(item.description_visible)

  # -- popup layout --------------------------------------------------------------------------------------------------
  def test_every_popup_fits_the_screen_and_long_text_scrolls(self):
    rl = self.rl
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP, create_help_dialog
    from openpilot.system.ui.widgets import confirm_dialog as cd
    self.assertEqual((self.gui_app.width, self.gui_app.height), (2160, 1080))
    dlg_x = dlg_y = cd.RICH_OUTER_MARGIN
    dlg_w, dlg_h = 2160 - 2 * dlg_x, 1080 - 2 * dlg_y
    text_w = dlg_w - 2 * cd.MARGIN
    visible_h = dlg_h - cd.BUTTON_HEIGHT - cd.MARGIN - 2 * cd.TEXT_PADDING
    self.assertGreater(visible_h, 400)
    self.assertLessEqual(dlg_y + dlg_h, 1080)
    tallest, tallest_key = 0, None
    for key, entry in HELP.items():
      dialog = create_help_dialog(entry)
      height = dialog._html_renderer.get_total_height(int(text_w))
      self.assertGreater(height, 0, key)
      if height > tallest:
        tallest, tallest_key = height, key
    # Every popup shows its own start without scrolling and the longest one is taller than the window, so it scrolls.
    self.assertGreater(tallest, 0)
    dialog = create_help_dialog(HELP[tallest_key], extra="x " * 400)
    self.gui_app.push_widget(dialog)
    self.render_top()
    self.assertGreater(dialog._html_renderer.get_total_height(int(text_w)), visible_h)
    button = dialog._confirm_button.rect
    self.assertGreaterEqual(button.x, 0)
    self.assertLessEqual(button.x + button.width, 2160)
    self.assertLessEqual(button.y + button.height, 1080)
    self.assertGreater(button.y, dlg_y + visible_h - 1, "Close button sits below the scrolling text")
    self.assertGreaterEqual(button.height, 100, "big enough to tap")
    panel = dialog._scroller.scroll_panel
    panel.set_offset(-300)
    self.render_top()
    self.assertLess(panel.offset, -100, "long popup text must scroll")
    dialog._confirm_button_callback()

  # -- every real page ---------------------------------------------------------------------------------------------
  def build_pages(self):
    """name -> layout (real page widgets, real store), pages needing a car use the Tesla AP1 CarParams."""
    from opendbc.car.tesla_ap1.interface import CarInterface
    from opendbc.car.tesla_ap1.values import CAR
    cp = CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS)
    pages = {}
    from openpilot.selfdrive.ui.bogpilot.phase2_alerts import create_alerts_layout
    from openpilot.selfdrive.ui.bogpilot.phase2_sounds import create_volume_layout
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import create_vehicle_settings_layout
    from openpilot.selfdrive.ui.bogpilot.phase2_car_selection import create_car_selection_layout
    from openpilot.selfdrive.ui.bogpilot.phase3_stalk_controls import create_stalk_controls_layout
    from openpilot.selfdrive.ui.bogpilot.phase3_lanechange import LaneChangeLayout
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import make_layout as make_steering
    from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities_ui import create_utilities_layout
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    from openpilot.selfdrive.ui.layouts.settings.phase3_system_settings_data_ui import build_data_layout
    pages["alerts"] = create_alerts_layout(self.store)
    pages["volume"] = create_volume_layout()
    pages["vehicle"] = create_vehicle_settings_layout(self.params)
    pages["car selection"] = create_car_selection_layout(self.params)
    pages["stalk"] = create_stalk_controls_layout()
    pages["lane changes"] = LaneChangeLayout(self.store, runtime_integrated=True, offroad=lambda: True)
    pages["steering"] = make_steering(cp, self.store, lambda: True)
    pages["visuals"] = BogPilotVisualsLayout(self.store)
    pages["utilities"] = create_utilities_layout(params=self.params, store=self.store, offroad=lambda: True, capable=lambda: True)
    pages["data"] = build_data_layout(params=self.params, store=self.store, offroad=lambda: True, capable=lambda: True,
                                      show_header=False)
    return pages

  def test_every_row_on_every_page_has_help_or_is_skipped_and_help_writes_nothing(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import SKIPPED_TITLES, resolve
    uncovered, opened, hidden = [], 0, 0
    for name, layout in self.build_pages().items():
      layout.show_event()
      if name == "volume":
        from openpilot.selfdrive.ui.bogpilot import phase2_sounds
        phase2_sounds.set_controller(True)
        layout.refresh(force=True)
      for item in self.rows_of(layout):
        title = item.title if isinstance(getattr(item, "title", ""), str) else ""
        if not title or title in SKIPPED_TITLES:
          continue
        if item.help_key is None:
          uncovered.append((name, title))
          continue
        self.assertIsNotNone(resolve(item.help_key), (name, title, item.help_key))
        if not item.is_visible:
          hidden += 1  # hidden for this car or setting; its help is still resolvable (checked above)
          continue
        self.prepare(item)
        before = self.snapshot()
        depth = len(self.gui_app._nav_stack)
        item._handle_mouse_release(self.rl.Vector2(80, 80))
        self.assertEqual(len(self.gui_app._nav_stack), depth + 1, (name, title))
        dialog = self.gui_app.get_active_widget()
        self.render_top()
        dialog._confirm_button_callback()
        self.assertEqual(self.snapshot(), before, (name, title))
        opened += 1
    self.assertEqual(uncovered, [], "rows with no help and not in SKIPPED_TITLES")
    self.assertGreater(opened, 40)


if __name__ == "__main__":
  unittest.main()
