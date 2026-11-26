"""BogPilot menu flow, as in 0.9.7: Back is the top-left item, and the BogPilot menu always opens at its top level.

Also the lock notes: why a page is locked or empty and which setting (if any) unlocks it.

Pure tests (no window): navigation reset, the lock-reason tables, which steering rows show. Native tests (RAYLIB_BACKEND=headless):
the real settings sidebar and the real pages. Nothing here writes a preference except where a test taps a control on purpose.
"""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from openpilot.selfdrive.ui.tests.test_bogpilot_menu_097 import MenuCase, NativeCase

HEADLESS = unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")


def cp(fingerprint="TESLA_AP1_MODELS", long_on=True, dashcam=False):
  return SimpleNamespace(carFingerprint=fingerprint, openpilotLongitudinalControl=long_on, dashcamOnly=dashcam,
                         alphaLongitudinalAvailable=False, passive=False)


class FakePage:
  """A page with inner pages, like Data / Device Controls."""
  def __init__(self, depth=0):
    self.depth, self.events = depth, []

  def navigation_back(self):
    if self.depth:
      self.depth -= 1
      return True
    return False

  def show_event(self):
    self.events.append("show")

  def hide_event(self):
    self.events.append("hide")


class TestNavigationReset(MenuCase):
  def nav(self):
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import MenuNavigation, Pill, Section
    from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import Page
    self.pages = {k: FakePage() for k in ("a", "b", "c")}
    mk = lambda k: Page(k, k.upper(), lambda k=k: self.pages[k], ("LaneChanges",))
    sections = (Section("s", "S", "x.png", (Pill("one", "ONE", "One", (mk("a"),)), Pill("two", "TWO", "Two", (mk("b"), mk("c"))))),)
    return MenuNavigation(sections, lambda: FakePage(), lambda entries, op: FakePage(), level=lambda: 3)

  def test_reset_from_a_page_goes_to_the_top(self):
    nav = self.nav()
    nav.open_pill("one")
    self.assertEqual(nav.path, ("one", "a"))
    nav.reset()
    self.assertEqual(nav.path, ())
    self.assertTrue(nav.at_top)

  def test_reset_from_a_page_list_and_a_page_under_it(self):
    nav = self.nav()
    nav.open_pill("two")
    self.assertEqual(nav.path, ("two",))
    nav.reset()
    self.assertEqual(nav.path, ())
    nav.open_pill("two")
    nav.open_page("two", "c")
    nav.reset()
    self.assertEqual(nav.path, ())

  def test_reset_walks_inner_pages_back_so_the_page_reopens_on_its_first_view(self):
    nav = self.nav()
    nav.open_pill("one")
    self.pages["a"].depth = 3
    nav.reset()
    self.assertEqual(self.pages["a"].depth, 0)
    nav.open_pill("one")
    self.assertEqual(self.pages["a"].depth, 0)

  def test_reset_at_the_top_does_nothing(self):
    nav = self.nav()
    nav.show_event()
    home = nav.current
    nav.reset()
    self.assertIs(nav.current, home)
    self.assertEqual(nav.path, ())

  def test_reset_while_visible_hides_the_page_and_shows_home(self):
    nav = self.nav()
    nav.show_event()
    nav.open_pill("one")
    page = self.pages["a"]
    page.events.clear()
    nav.reset()
    self.assertEqual(page.events, ["hide"])
    self.assertIsNotNone(nav.current)

  def test_back_still_goes_one_level_at_a_time(self):
    nav = self.nav()
    nav.open_pill("two")
    nav.open_page("two", "b")
    self.assertTrue(nav.back())
    self.assertEqual(nav.path, ("two",))
    self.assertTrue(nav.back())
    self.assertEqual(nav.path, ())
    self.assertFalse(nav.back())


class TestLongLock(unittest.TestCase):
  def lock(self, *a, **k):
    from openpilot.selfdrive.ui.bogpilot import menu_locks
    return menu_locks.long_lock(*a, **k)

  def test_available_when_the_car_reports_longitudinal_control(self):
    self.assertIsNone(self.lock(cp()))
    self.assertIsNone(self.lock(cp("TESLA_PREAP_MODELS")))
    self.assertIsNone(self.lock(cp(), disable_toggle_on=True))   # the saved choice only takes effect at the next start

  def test_reasons(self):
    cases = (
      (None, False, "no_car"),
      (cp(""), False, "no_car"),
      (cp("MOCK", long_on=False), False, "no_car"),
      (cp(long_on=False, dashcam=True), False, "dashcam"),
      (cp("TESLA_AP1_MODELX", long_on=False), False, "restart"),
      (cp("TESLA_AP1_MODELX", long_on=False), True, "toggle_off"),
      (cp(long_on=False), True, "toggle_off"),
      (cp("TESLA_PREAP_MODELS", long_on=False), True, "toggle_off"),
      (cp(long_on=False), False, "restart"),
      (cp("TOYOTA_COROLLA", long_on=False), False, "not_supported"),
    )
    for car, disabled, code in cases:
      lock = self.lock(car, disabled)
      self.assertIsNotNone(lock)
      self.assertEqual(lock.code, code, (car, disabled))

  def test_toggle_reason_names_the_toggle_and_where_it_is(self):
    lock = self.lock(cp(long_on=False), True)
    self.assertEqual(lock.unlock_toggle, "DisableOpenpilotLongitudinal")
    self.assertIn("Disable openpilot Longitudinal Control", lock.detail)
    self.assertIn("Vehicle Settings, then VEHICLE SETTINGS, then Vehicle Controls", lock.detail)
    pre = self.lock(cp("TESLA_PREAP_MODELS", long_on=False), True)
    self.assertIn("Disable Pedal Longitudinal", pre.detail)
    # a reason that has no setting behind it must not point at one
    for car, disabled in ((None, False), (cp(long_on=False, dashcam=True), False)):
      lock = self.lock(car, disabled)
      self.assertEqual(lock.unlock_toggle, "")
      self.assertNotIn("Vehicle Controls", lock.detail)
    # Model X: Disable openpilot Longitudinal Control is its single longitudinal row. Off but long still off: restart pending
    x_lock = self.lock(cp("TESLA_AP1_MODELX", long_on=False), False)
    self.assertEqual(x_lock.unlock_toggle, "")
    self.assertEqual(x_lock.code, "restart")
    # Model X with Disable on: the lock points at that toggle, as on the Model S
    x_disabled = self.lock(cp("TESLA_AP1_MODELX", long_on=False), True)
    self.assertEqual(x_disabled.unlock_toggle, "DisableOpenpilotLongitudinal")
    self.assertIn("Disable openpilot Longitudinal Control", x_disabled.detail)

  def test_text_is_ascii_and_has_no_angle_brackets(self):
    from openpilot.selfdrive.ui.bogpilot import menu_locks as m
    locks = [m.NO_CAR, m.DASHCAM, m.STEERING_ONLY, m.RESTART, m.NOT_SUPPORTED, m.UNSUPPORTED_VEHICLE, m.NO_CAR_VEHICLE, m.MODEL_X,
             m.MODEL_X_WHEEL, m.WHEEL_AP1_ONLY, m._toggle_lock("TESLA_AP1_MODELS"), m._toggle_lock("TESLA_PREAP_MODELS")]
    for lock in locks:
      for text in (lock.short, lock.detail):
        self.assertTrue(text.isascii(), text)
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
    self.assertTrue(m.TITLE.isascii())

  def test_page_note(self):
    from openpilot.selfdrive.ui.bogpilot import menu_locks as m
    for kind in ("vehicle_controls", "stalk_controls"):
      self.assertEqual(m.page_note(None, kind).code, "no_car")
      self.assertEqual(m.page_note(cp("TESLA_AP1_MODELX", long_on=False), kind).code, "steering_only")
      self.assertEqual(m.page_note(cp(long_on=False, dashcam=True), kind).code, "dashcam")
      self.assertIsNone(m.page_note(cp(), kind))
    # Model X with openpilot longitudinal: Wheel Controls like the S
    self.assertIsNone(m.page_note(cp("TESLA_AP1_MODELX"), "stalk_controls"))
    # Pre-AP has vehicle controls but no wheel controls
    self.assertIsNone(m.page_note(cp("TESLA_PREAP_MODELS"), "vehicle_controls"))
    self.assertEqual(m.page_note(cp("TESLA_PREAP_MODELS"), "stalk_controls").code, "unsupported_vehicle")
    # supported car, longitudinal off: the page is short, and says why
    short = m.page_note(cp(long_on=False), "stalk_controls", disable_toggle_on=True)
    self.assertEqual(short.code, "toggle_off")
    self.assertIn("Some rows", short.detail)
    self.assertEqual(m.page_note(cp(long_on=False), "stalk_controls").code, "restart")

  def test_effective_toggle_never_raises(self):
    from openpilot.selfdrive.ui.bogpilot import menu_locks as m
    with mock.patch("openpilot.selfdrive.ui.bogpilot.vehicle_settings.disable_long_effective", side_effect=OSError):
      self.assertFalse(m.effective_disable_toggle())


class TestSteeringChildrenFollowTheirParent(MenuCase):
  def editor(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import TuningEditor
    from opendbc.car.tesla_ap1.interface import CarInterface
    from opendbc.car.tesla_ap1.values import CAR
    return TuningEditor(CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS), self.store, lambda: True)

  def test_advanced_rows_show_only_with_advanced_lateral_tuning_on(self):
    e = self.editor()
    advanced = ("SteerDelay", "SteerRatio")
    self.assertTrue(e.visible("AdvancedLateralTune"))
    for key in advanced:
      self.assertFalse(e.visible(key), key)
    self.store.put_bool("AdvancedLateralTune", True)
    self.store.invalidate()
    for key in advanced:
      self.assertTrue(e.visible(key), key)

  def test_pause_rows_show_only_with_quality_of_life_on(self):
    e = self.editor()
    self.store.put_bool("QOLLateral", False)
    self.store.invalidate()
    self.assertTrue(e.visible("QOLLateral"))
    self.assertFalse(e.visible("PauseLateralSpeed"))
    self.assertFalse(e.visible("PauseLateralOnSignal"))
    self.store.put_bool("QOLLateral", True)
    self.store.invalidate()
    self.assertTrue(e.visible("PauseLateralSpeed"))
    self.assertTrue(e.visible("PauseLateralOnSignal"))

  def test_a_hidden_child_cannot_be_written(self):
    e = self.editor()
    self.store.put_bool("QOLLateral", False)
    self.store.put_bool("AdvancedLateralTune", False)
    self.store.invalidate()
    self.assertFalse(e.write("SteerDelay", 0.3))
    self.assertFalse(e.write("PauseLateralSpeed", 5))
    self.assertIsNone(self.store.raw("SteerDelay"))
    self.assertIsNone(self.store.raw("PauseLateralSpeed"))


@HEADLESS
class TestSettingsSidebarFlow(NativeCase):
  """The real SettingsLayout with the real BogPilot panel; only the Wi-Fi manager is replaced (no dbus on the build VM)."""

  def setUp(self):
    super().setUp()
    while self.gui_app._nav_stack[-1] is not self.base and len(self.gui_app._nav_stack) > 1:
      self.gui_app.pop_widget()
    from openpilot.system.ui.widgets import Widget
    from openpilot.selfdrive.ui.layouts.settings import settings as S

    class Dummy(Widget):
      def __init__(self, *a, **k):
        super().__init__()

      def set_active(self, *_):
        pass

      def _render(self, rect):
        pass

    self.S = S
    patches = [mock.patch.object(S, "WifiManager", Dummy), mock.patch.object(S, "NetworkUI", Dummy)]
    for p in patches:
      p.start()
      self.addCleanup(p.stop)
    self.settings = S.SettingsLayout()
    self.closed = []
    self.settings.set_callbacks(lambda: self.closed.append(True))
    self.settings.show_event()
    self.addCleanup(self.settings.hide_event)
    self.rect = self.rl.Rectangle(0, 0, 2160, 1080)
    self.nav = self.bogpilot.content.navigation
    self.draw()

  @property
  def bogpilot(self):
    return self.settings._panels[self.S.PanelType.BOGPILOT].instance

  def draw(self, frames=2):
    rl = self.rl
    for _ in range(frames):
      rl.begin_drawing()
      try:
        rl.clear_background(rl.BLACK)
        self.settings.render(self.rect)
      finally:
        rl.end_drawing()

  def tap(self, rect):
    self.settings._handle_mouse_release(self.rl.Vector2(rect.x + rect.width / 2, rect.y + rect.height / 2))

  def tap_tab(self, panel):
    self.draw()
    self.tap(self.settings._panels[panel].button_rect)

  def open_bogpilot(self):
    self.tap_tab(self.S.PanelType.BOGPILOT)
    self.draw()
    self.assertEqual(self.nav.path, ())

  def open_pill(self, key):
    self.nav.open_pill(key)
    self.draw()

  # ---- the BogPilot menu always opens at the top level
  def test_returning_from_another_tab_lands_on_the_top_level(self):
    P = self.S.PanelType
    self.open_bogpilot()
    self.open_pill("gas_brake")
    self.assertEqual(self.nav.path, ("gas_brake", "gas_brake"))
    self.tap_tab(P.DEVICE)
    self.assertEqual(self.nav.path, ())          # already reset while leaving
    self.tap_tab(P.BOGPILOT)
    self.draw()
    self.assertEqual(self.nav.path, ())
    self.assertEqual(self.settings._current_panel, P.BOGPILOT)

  def test_tapping_the_bogpilot_tab_again_goes_to_the_top_level(self):
    self.open_bogpilot()
    self.open_pill("steering")
    self.assertEqual(self.nav.path, ("steering",))
    self.tap_tab(self.S.PanelType.BOGPILOT)
    self.draw()
    self.assertEqual(self.nav.path, ())
    self.open_pill("data")
    self.assertEqual(self.nav.path, ("data", "system_data"))
    self.tap_tab(self.S.PanelType.BOGPILOT)
    self.assertEqual(self.nav.path, ())

  def test_closing_and_reopening_settings_lands_on_the_top_level(self):
    self.open_bogpilot()
    self.open_pill("manage")
    self.settings.hide_event()
    self.assertEqual(self.nav.path, ())
    self.settings.show_event()
    self.draw()
    self.assertEqual(self.nav.path, ())

  def test_a_page_with_inner_pages_reopens_on_its_first_view(self):
    self.open_bogpilot()
    self.open_pill("device_controls")
    page = self.nav.current
    page.go("Device Settings")
    self.assertTrue(page.navigation_title != "Device Controls" and page.navigation_back.__self__ is page)
    self.tap_tab(self.S.PanelType.TOGGLES)
    self.tap_tab(self.S.PanelType.BOGPILOT)
    self.open_pill("device_controls")
    self.assertEqual(self.nav.current.navigation_title, "Device Controls")

  def test_nothing_is_written_by_navigating(self):
    before = (self.saved(), self.params.writes, self.writes["n"])
    self.open_bogpilot()
    self.open_pill("gas_brake")
    self.tap_tab(self.S.PanelType.DEVICE)
    self.tap_tab(self.S.PanelType.BOGPILOT)
    self.assertEqual((self.saved(), self.params.writes, self.writes["n"]), before)

  # ---- Back is the top-left item
  def test_top_level_top_left_item_is_back_and_closes_settings(self):
    self.open_bogpilot()
    self.draw()
    self.assertFalse(self.settings._bogpilot_can_go_back())
    self.tap(self.settings._back_btn_rect)        # 0.9.7: Back at the top level closes settings
    self.assertEqual(self.closed, [True])

  def test_the_top_left_item_is_the_same_back_pill_on_every_panel(self):
    rects = set()
    for panel in self.S.PanelType:
      self.tap_tab(panel)
      self.draw()
      r = self.settings._back_btn_rect
      rects.add((r.x, r.y, r.width, r.height))
      self.assertEqual((self.settings._close_btn_rect.x, self.settings._close_btn_rect.y), (r.x, r.y))
    self.assertEqual(len(rects), 1)
    self.closed.clear()
    self.tap(self.settings._back_btn_rect)
    self.assertEqual(self.closed, [True])

  def test_inside_a_menu_the_top_left_item_is_back_and_goes_up_one_level(self):
    self.open_bogpilot()
    self.open_pill("steering")                    # a page list under a pill
    self.nav.open_page("steering", "lane_changes")
    self.draw()
    self.assertEqual(self.nav.path, ("steering", "lane_changes"))
    back = self.settings._back_btn_rect
    self.assertTrue(self.settings._bogpilot_can_go_back())
    # top left: in the sidebar's left half and above the first tab
    self.assertLess(back.x + back.width, self.S.SIDEBAR_WIDTH)
    self.assertLess(back.y + back.height, self.settings._panels[self.S.PanelType.DEVICE].button_rect.y)
    self.tap(back)
    self.assertEqual(self.nav.path, ("steering",))
    self.draw()
    self.tap(self.settings._back_btn_rect)
    self.assertEqual(self.nav.path, ())
    self.assertEqual(self.closed, [])             # Back never closes settings from inside a menu
    self.draw()
    self.assertFalse(self.settings._bogpilot_can_go_back())
    self.tap(self.settings._back_btn_rect)        # at the top level the same pill closes settings
    self.assertEqual(self.closed, [True])

  def test_the_gas_brake_lock_button_opens_the_disable_setting(self):
    from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake
    from openpilot.selfdrive.ui.ui_state import ui_state
    phase3_gas_brake._pill_state = None
    self.addCleanup(setattr, phase3_gas_brake, "_pill_state", None)
    from openpilot.selfdrive.ui.bogpilot import menu_locks
    with mock.patch.object(ui_state, "CP", cp(long_on=False)), \
         mock.patch("openpilot.selfdrive.ui.bogpilot.menu_locks.effective_disable_toggle", lambda: True):
      self.open_bogpilot()
      with self.assertRaises(KeyError):
        self.open_pill("gas_brake")                     # the pill is hidden now (strict 0.9.7), so the page is not reachable
      # ... but a page that is already open when the car state changes still explains itself and offers the way to the setting
      with mock.patch.object(menu_locks, "PILL_STAYS", ("no_car", "toggle_off", "restart")):
        phase3_gas_brake._pill_state = None
        self.open_pill("gas_brake")
      page = self.nav.current
      page.lock.refresh()
      self.draw()
      self.assertTrue(page._jump_row.is_visible)
      page._jump()
      self.draw()
      self.assertEqual(self.nav.path, ("vehicle_settings", "vehicle_controls"))
      rows = {r.title: r for r in self.nav.current.scroller._items if r.is_visible}
      self.assertIn("Disable openpilot Longitudinal Control", rows)
      self.tap(self.settings._back_btn_rect)             # Back leaves the page, one level up
      self.assertEqual(self.nav.path, ("vehicle_settings",))

  def test_the_home_page_says_when_settings_are_locked_while_driving(self):
    from openpilot.selfdrive.ui.ui_state import ui_state
    self.open_bogpilot()
    first = self.nav.current._items[0]                     # the Tuning Level row
    with mock.patch.object(ui_state, "is_offroad", lambda: True):
      self.assertEqual(first.subtitle(), "")
      self.draw()
    with mock.patch.object(ui_state, "is_offroad", lambda: False):
      self.assertEqual(first.subtitle(), "Locked while the car is on")
      self.draw()
      self.assertEqual(self.nav.path, ())
      others = [i.subtitle for i in self.nav.current._items[1:]]
      self.assertEqual(others, [None] * len(others))        # one note, on the first row

  def test_back_on_a_single_page_pill_goes_straight_to_the_top(self):
    self.open_bogpilot()
    self.open_pill("gas_brake")
    self.draw()
    self.tap(self.settings._back_btn_rect)
    self.assertEqual(self.nav.path, ())

  def test_back_steps_out_of_inner_pages_first(self):
    self.open_bogpilot()
    self.open_pill("device_controls")
    self.nav.current.go("Device Settings")
    self.draw()
    self.tap(self.settings._back_btn_rect)
    self.assertEqual(self.nav.path, ("device_controls", "system_device"))
    self.assertEqual(self.nav.current.navigation_title, "Device Controls")
    self.draw()
    self.tap(self.settings._back_btn_rect)
    self.assertEqual(self.nav.path, ())

  def test_back_on_another_panel_closes_settings(self):
    self.tap_tab(self.S.PanelType.DEVICE)
    self.draw()
    self.assertFalse(self.settings._bogpilot_can_go_back())
    self.tap(self.settings._back_btn_rect)
    self.assertEqual(self.closed, [True])

  def test_the_page_header_has_no_back_button_any_more(self):
    from openpilot.system.ui.widgets.list_view import TextAction
    self.open_bogpilot()
    self.open_pill("manage")
    header = self.bogpilot.content._header
    self.assertIsInstance(header.action_item, TextAction)
    self.assertNotEqual(header.action_item.text, "BACK")

  def test_header_shows_the_open_pages_onroad_class(self):
    # 0.9.7 onroad parity (onroad_policy): Alerts and Sounds stay open onroad, Steering asks for a reboot.
    from openpilot.selfdrive.ui.ui_state import ui_state
    self.open_bogpilot()
    self.open_pill("manage")
    header = self.bogpilot.content._header
    with mock.patch.object(ui_state, "is_offroad", lambda: True):
      self.assertEqual(header.action_item.text, "")
    with mock.patch.object(ui_state, "is_offroad", lambda: False):
      self.assertEqual(header.action_item.text, "")
    self.tap(self.settings._back_btn_rect)
    self.open_pill("steering")
    with mock.patch.object(ui_state, "is_offroad", lambda: False):
      self.assertIn("reboot", header.action_item.text)

  def test_screenshots(self):
    shots = os.getenv("MENU_SHOTS")
    if not shots:
      self.skipTest("MENU_SHOTS not set")
    from openpilot.selfdrive.ui.tests.test_bogpilot_menu_097 import TestMenuNative
    helper = TestMenuNative("test_home_has_seven_rows_that_fit_2160x1080")
    helper.rl = self.rl
    helper.shots = shots
    patches = [mock.patch.object(self.rl, n, f) for n, f in helper._shape_fallbacks().items()]
    for p in patches:
      p.start()
    try:
      self.open_bogpilot()
      self.draw(3)
      self._shot(shots, "flow_top_level.png")
      from openpilot.selfdrive.ui.ui_state import ui_state
      with mock.patch.object(ui_state, "is_offroad", lambda: False):
        self.draw(3)
        self._shot(shots, "flow_top_level_onroad_note.png")
      self.open_pill("gas_brake")
      self.draw(3)
      self._shot(shots, "flow_gas_brake_back_top_left.png")
    finally:
      for p in patches:
        p.stop()

  def _shot(self, shots, name):
    img = self.rl.load_image_from_screen()
    self.rl.export_image(img, os.path.join(shots, name))
    self.rl.unload_image(img)


@HEADLESS
class TestLockNotesNative(NativeCase):
  def setUp(self):
    super().setUp()
    while self.gui_app._nav_stack[-1] is not self.base and len(self.gui_app._nav_stack) > 1:
      self.gui_app.pop_widget()
    self.car = {"cp": None}
    self.offroad = {"v": True}

  def gas_brake(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_gas_brake import create_gas_brake_layout
    layout = create_gas_brake_layout(self.store, lambda: self.car["cp"], lambda: self.offroad["v"])
    layout.show_event()
    self.addCleanup(layout.hide_event)
    return layout

  def draw(self, widget, frames=2):
    rl = self.rl
    for _ in range(frames):
      rl.begin_drawing()
      try:
        rl.clear_background(rl.BLACK)
        widget.render(rl.Rectangle(550, 25, 1560, 1030))
      finally:
        rl.end_drawing()

  def rows(self, layout):
    return [i for i in layout.root._items if i.is_visible]

  def test_gas_brake_without_a_car_says_why_and_stays_locked(self):
    self._before = self.saved()
    layout = self.gas_brake()
    self.draw(layout)
    rows = self.rows(layout)
    lock, groups = rows[0], rows[1:]
    self.assertEqual(lock.title, "Locked: needs longitudinal control")
    self.assertEqual(lock.action_item.text, "No car detected")
    self.assertTrue(lock.description_visible)
    self.assertEqual(len(groups), 7)   # 5 groups (no Conditional Experimental Mode) + the 2 AP1 tap-speed rows (greyed, like SLC)
    for row in groups:
      self.assertFalse(row.action_item.enabled, row.title)   # not un-greyed: the explanation is added, the gate stays
    # opening the page and rendering it wrote nothing
    self.assertEqual((self.saved(), self.params.writes, self.writes["n"]), (self._before, 0, 0))

  def test_gas_brake_with_the_disable_toggle_on_names_the_toggle(self):
    self.car["cp"] = cp(long_on=False)
    with mock.patch("openpilot.selfdrive.ui.bogpilot.menu_locks.effective_disable_toggle", lambda: True):
      layout = self.gas_brake()
      self.draw(layout)
      lock = self.rows(layout)[0]
      self.assertEqual(lock.action_item.text, "Turned off")
      self.assertIn("Disable openpilot Longitudinal Control", lock.description)
      self.assertIn("Vehicle Controls", lock.description)
      for row in self.rows(layout)[1:]:
        self.assertFalse(row.action_item.enabled)

  def test_the_disable_lock_has_a_button_that_jumps_to_the_setting(self):
    from openpilot.selfdrive.ui.bogpilot import menu_locks
    self.car["cp"] = cp(long_on=False)
    calls = []
    nav = SimpleNamespace(can_open=lambda *a: True, open_page=lambda *a: calls.append(a))
    with mock.patch("openpilot.selfdrive.ui.bogpilot.menu_locks.effective_disable_toggle", lambda: True):
      layout = self.gas_brake()
      layout.set_navigator(nav)
      layout.lock.refresh()
      self.draw(layout)
      rows = self.rows(layout)
      self.assertEqual(rows[1].title, "Open: Disable openpilot Longitudinal Control")
      self.assertEqual([r.action_item.enabled for r in rows[2:]], [False] * 7)   # the group rows stay locked
      rows[1].callback()
    self.assertEqual(calls, [menu_locks.JUMP_TARGET])

  def test_no_jump_button_when_no_setting_can_unlock_it(self):
    nav = SimpleNamespace(can_open=lambda *a: True, open_page=lambda *a: None)
    cases = ((None, False), (cp("TESLA_AP1_MODELX", long_on=False), False), (cp(long_on=False, dashcam=True), False),
             (cp(long_on=False), False), (cp(), True))
    for car, disabled in cases:
      self.car["cp"] = car
      with mock.patch("openpilot.selfdrive.ui.bogpilot.menu_locks.effective_disable_toggle", lambda d=disabled: d):
        layout = self.gas_brake()
        layout.set_navigator(nav)
        layout.lock.refresh()
        self.draw(layout)
        self.assertFalse(layout._jump_row.is_visible, car)

  def test_no_jump_button_when_the_target_page_is_not_available(self):
    self.car["cp"] = cp(long_on=False)
    nav = SimpleNamespace(can_open=lambda *a: False, open_page=lambda *a: self.fail("must not open"))
    with mock.patch("openpilot.selfdrive.ui.bogpilot.menu_locks.effective_disable_toggle", lambda: True):
      layout = self.gas_brake()
      layout.set_navigator(nav)
      layout.lock.refresh()
      self.draw(layout)
      self.assertFalse(layout._jump_row.is_visible)
      layout._jump()          # nothing happens

  def test_gas_brake_on_model_x_with_disable_off_says_restart_and_offers_no_toggle(self):
    self.car["cp"] = cp("TESLA_AP1_MODELX", long_on=False)
    with mock.patch("openpilot.selfdrive.ui.bogpilot.menu_locks.effective_disable_toggle", lambda: False):
      layout = self.gas_brake()
      self.draw(layout)
      lock = self.rows(layout)[0]
      self.assertEqual(lock.action_item.text, "Restart the car")
      self.assertNotIn("Vehicle Controls", lock.description)

  def test_gas_brake_unlocked_has_no_lock_row_and_enabled_groups(self):
    self.car["cp"] = cp()
    layout = self.gas_brake()
    self.draw(layout)
    rows = self.rows(layout)
    self.assertEqual(len(rows), 7)
    self.assertNotIn("Locked", " ".join(r.title for r in rows))
    for row in rows:
      self.assertTrue(row.action_item.enabled, row.title)

  def test_the_note_follows_the_car_while_the_page_is_open(self):
    layout = self.gas_brake()
    self.draw(layout)
    self.assertEqual(self.rows(layout)[0].action_item.text, "No car detected")
    self.car["cp"] = cp()
    layout.lock.refresh()
    self.draw(layout)
    self.assertEqual(len(self.rows(layout)), 7)

  def test_gas_brake_back_closes_an_open_group_and_reports_its_title(self):
    self.car["cp"] = cp()
    layout = self.gas_brake()
    self.assertEqual(layout.navigation_title, "")
    self.assertFalse(layout.navigation_back())
    layout.open_panel("advanced")
    self.draw(layout)
    self.assertEqual(layout.navigation_title, "Advanced Longitudinal Tuning")
    self.assertTrue(layout.navigation_back())
    self.assertIsNone(layout.panel)
    self.assertFalse(layout.navigation_back())

  def test_gas_brake_quality_of_life_inner_pages_step_back_before_the_group_closes(self):
    self.car["cp"] = cp()
    layout = self.gas_brake()
    layout.open_panel("qol")
    panel = layout.panel
    rows = panel.model.rows(panel.page)
    page_row = next((r for r in rows if r.kind == "page"), None)
    if page_row is None:
      self.skipTest("no inner page in Quality of Life in this build")
    panel._open(page_row.key)
    self.assertTrue(layout.navigation_back())
    self.assertIs(layout.panel, panel)
    self.assertTrue(layout.navigation_back())
    self.assertIsNone(layout.panel)

  def note_page(self, factory, ui_cp):
    from openpilot.selfdrive.ui.ui_state import ui_state
    patches = [mock.patch.object(ui_state, "CP", ui_cp, create=True), mock.patch.object(ui_state, "is_offroad", lambda: True)]
    for p in patches:
      p.start()
      self.addCleanup(p.stop)
    layout = factory()
    layout.show_event()
    self.addCleanup(layout.hide_event)
    self.draw(layout)
    return layout

  def test_vehicle_controls_and_wheel_controls_say_why_they_are_empty(self):
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import create_vehicle_settings_layout
    from openpilot.selfdrive.ui.bogpilot.phase3_stalk_controls import create_stalk_controls_layout
    for factory in (create_vehicle_settings_layout, create_stalk_controls_layout):
      layout = self.note_page(factory, None)
      visible = [i for i in layout.scroller._items if i.is_visible]
      self.assertEqual(len(visible), 1, factory.__name__)
      self.assertEqual(visible[0].action_item.text, "No car detected")
      self.assertTrue(visible[0].description_visible)
    for factory in (create_vehicle_settings_layout, create_stalk_controls_layout):
      layout = self.note_page(factory, cp("TESLA_AP1_MODELX", long_on=False))
      visible = [i for i in layout.scroller._items if i.is_visible]
      self.assertEqual([i.action_item.text for i in visible], ["Model X: steering only"], factory.__name__)

  def test_a_fully_available_page_shows_no_note(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_stalk_controls import create_stalk_controls_layout
    layout = self.note_page(create_stalk_controls_layout, cp())
    self.assertFalse(layout.note_row.is_visible)
    self.assertTrue(any(i.is_visible for i in layout.scroller._items if i is not layout.note_row))


class TestGasBrakePill(unittest.TestCase):
  """The GAS / BRAKE pill, strictly as in 0.9.7: gone whenever the car params say no openpilot longitudinal control (including
  when Disable longitudinal is on or a restart is pending), shown before any car is known."""

  def visible(self, car, disabled=False):
    from openpilot.selfdrive.ui.bogpilot import menu_locks
    return menu_locks.gas_brake_pill_visible(car, disabled)

  def test_shown_when_longitudinal_control_is_available(self):
    self.assertTrue(self.visible(cp()))
    self.assertTrue(self.visible(cp("TESLA_PREAP_MODELS")))

  def test_shown_before_any_car_is_detected(self):
    # 0.9.7 started with hasOpenpilotLongitudinal = true and only hid the pill once a persisted CarParams said the car has none.
    self.assertTrue(self.visible(None))
    self.assertTrue(self.visible(cp("")))
    self.assertTrue(self.visible(cp("MOCK", long_on=False)))

  def test_hidden_for_a_car_that_cannot_do_it(self):
    self.assertFalse(self.visible(cp(long_on=False, dashcam=True)))
    self.assertFalse(self.visible(cp("TESLA_AP1_MODELX", long_on=False)))
    self.assertFalse(self.visible(cp("TOYOTA_COROLLA", long_on=False)))

  def test_hidden_when_disable_longitudinal_is_on_or_a_restart_is_pending(self):
    # 0.9.7: setVisibleButton(1, hasLongitudinalControl(CP)), which is false with the Disable setting on and for a CarParams
    # written without longitudinal control. The way back is the Disable toggle in Vehicle Controls.
    self.assertFalse(self.visible(cp(long_on=False), True))
    self.assertFalse(self.visible(cp("TESLA_PREAP_MODELS", long_on=False), True))
    self.assertFalse(self.visible(cp(long_on=False), False))
    self.assertFalse(self.visible(cp(), True))        # switched on just now, car not restarted: hidden at once, as in 0.9.7

  def test_only_the_no_car_case_keeps_the_pill_for_a_lock(self):
    from openpilot.selfdrive.ui.bogpilot import menu_locks
    self.assertEqual(menu_locks.PILL_STAYS, ("no_car",))

  def test_navigation_drops_a_hidden_pill_and_refuses_to_open_it(self):
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import MenuNavigation, Pill, Section
    from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import Page
    shown = {"v": True}
    page = lambda k: Page(k, k.upper(), lambda k=k: FakePage(), ("LaneChanges",))
    sections = (Section("s", "S", "x.png", (Pill("a", "A", "A", (page("a"),)),
                                              Pill("b", "B", "B", (page("b"),), visible=lambda: shown["v"]))),)
    nav = MenuNavigation(sections, lambda: FakePage(), lambda entries, op: FakePage(), level=lambda: 3)
    self.assertEqual([p.key for p in nav.pills_of(sections[0])], ["a", "b"])
    shown["v"] = False
    self.assertEqual([p.key for p in nav.pills_of(sections[0])], ["a"])
    with self.assertRaises(KeyError):
      nav.open_pill("b")
    shown["v"] = True
    nav.open_pill("b")
    self.assertEqual(nav.path, ("b", "b"))

  def test_a_failing_predicate_shows_the_pill(self):
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import MenuNavigation, Pill, Section
    from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import Page

    def boom():
      raise OSError("settings file")
    sections = (Section("s", "S", "x.png", (Pill("a", "A", "A", (Page("a", "A", lambda: FakePage(), ("LaneChanges",)),), visible=boom),)),)
    nav = MenuNavigation(sections, lambda: FakePage(), lambda entries, op: FakePage(), level=lambda: 3)
    self.assertEqual([p.key for p in nav.pills_of(sections[0])], ["a"])


@HEADLESS
class TestGasBrakePillNative(NativeCase):
  def setUp(self):
    super().setUp()
    from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake
    from openpilot.selfdrive.ui.ui_state import ui_state
    self.gb, self.ui_state = phase3_gas_brake, ui_state

  def labels(self, car, disabled=False):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    self.gb._pill_state = None     # drop the half-second cache
    with mock.patch.object(self.ui_state, "CP", car), \
         mock.patch("openpilot.selfdrive.ui.bogpilot.menu_locks.effective_disable_toggle", lambda: disabled):
      from openpilot.selfdrive.ui.layouts.settings.menu_097 import MenuNavigation
      nav = MenuNavigation(menu_sections(), lambda: None, lambda *a: None, level=lambda: 3)
      driving = next(s for s in nav.sections if s.key == "driving")
      return [p.label for p in nav.pills_of(driving)]

  def tearDown(self):
    self.gb._pill_state = None
    super().tearDown()

  def test_the_real_menu_has_the_pill_with_no_car_and_with_a_capable_car(self):
    self.assertIn("GAS / BRAKE", self.labels(None))
    self.assertIn("GAS / BRAKE", self.labels(cp()))

  def test_the_real_menu_drops_the_pill_for_model_x_and_dashcam(self):
    for car in (cp("TESLA_AP1_MODELX", long_on=False), cp(long_on=False, dashcam=True)):
      labels = self.labels(car)
      self.assertNotIn("GAS / BRAKE", labels)
      self.assertEqual(labels, ["DRIVING MODEL", "STEERING"])

  def test_the_real_menu_drops_the_pill_when_disable_longitudinal_is_on_or_a_restart_is_pending(self):
    self.assertNotIn("GAS / BRAKE", self.labels(cp(long_on=False), disabled=True))
    self.assertNotIn("GAS / BRAKE", self.labels(cp(long_on=False), disabled=False))
    self.assertNotIn("GAS / BRAKE", self.labels(cp(), disabled=True))
    self.assertIn("GAS / BRAKE", self.labels(cp(), disabled=False))

  def test_the_disable_toggle_stays_reachable_in_vehicle_controls(self):
    # with the pill gone, Vehicle Controls is how longitudinal control is turned back on
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import LONG, VehicleSettings
    for car in (cp(long_on=False), cp("TESLA_PREAP_MODELS", long_on=False)):
      car.alphaLongitudinalAvailable = False
      self.assertTrue(VehicleSettings(mock.Mock(), lambda c=car: c, lambda: True).visible(LONG))


if __name__ == "__main__":
  unittest.main()
