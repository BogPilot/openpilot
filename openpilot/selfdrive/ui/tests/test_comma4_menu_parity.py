"""comma 4 (mici) BogPilot menu parity with the comma 3X.

Fails if any comma 3X BogPilot setting (every row of every page of menu_sections(), every MANAGE / OPEN sub-page, at
the Developer Tuning Level, for no car / AP1 / Pre-AP) has no comma 4 card, if a page cannot be reached from the
comma 4 menu, if a comma 4 label would draw '?' (a character outside the font atlas, e.g. U+2212), or if the comma 4
loses a 3X lock (Tuning Level offroad only, locked rows, reboot prompt once per page visit, Reboot Now refused while
engaged). No window is opened: fonts / textures are stubbed and taps go through row_model.Row.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pyray as rl

from openpilot.system.ui.lib.application import EXTRA_FONT_CHARS, gui_app

UI = Path(__file__).resolve().parents[1]
ATLAS = set(map(chr, range(32, 127))) | set(EXTRA_FONT_CHARS) | {"\n"}

# 3X rows that truly cannot apply on comma 4 hardware: (page key, row title) -> why. Empty: everything applies.
EXCLUSIONS: dict[tuple[str, str], str] = {}


def _fake_device_type():
  if not os.path.exists("/sys/firmware/devicetree/base/model"):
    import openpilot.common.hardware.comma.hardware as comma_hw
    comma_hw.get_device_type = lambda: "pc"


def _native_missing() -> str | None:
  """The menus import ui_state (msgq) and Params (libparams); a Mac pyray-stub env has neither built. Those tests run
  natively (AGNOS runner); here they skip with this reason."""
  try:
    from openpilot.common.params import Params
    Params()
    from openpilot.selfdrive.ui.ui_state import ui_state  # noqa: F401
  except (ImportError, OSError) as e:
    return f"needs built msgq / params ({type(e).__name__})"
  return None


class NoWindow(unittest.TestCase):
  NATIVE = False

  @classmethod
  def setUpClass(cls):
    cls.tmp = tempfile.mkdtemp(prefix="c4parity-")
    os.environ["BOGPILOT_PARAMS_DIR"] = os.path.join(cls.tmp, "bp")
    os.environ.setdefault("PARAMS_ROOT", os.path.join(cls.tmp, "params"))
    os.makedirs(os.environ["BOGPILOT_PARAMS_DIR"], exist_ok=True)
    os.makedirs(os.environ["PARAMS_ROOT"], exist_ok=True)
    _fake_device_type()

  def setUp(self):
    if self.NATIVE and (why := _native_missing()):
      self.skipTest(why)
    for name, value in (("font", lambda *a, **k: rl.Font()), ("texture", lambda *a, **k: rl.Texture())):
      p = mock.patch.object(gui_app, name, value)
      p.start()
      self.addCleanup(p.stop)
    self.pushed = []
    p = mock.patch.object(gui_app, "push_widget", lambda w: self.pushed.append(w))
    p.start()
    self.addCleanup(p.stop)
    p = mock.patch.object(gui_app, "pop_widget", lambda *a, **k: None)
    p.start()
    self.addCleanup(p.stop)
    from openpilot.selfdrive.ui.bogpilot import onroad_policy
    onroad_policy.set_state(onroad_policy.DriveState(started=lambda: False, parked=lambda: True, engaged=lambda: False))
    onroad_policy.set_prompt_ui(None)
    onroad_policy.new_visit()
    self.addCleanup(onroad_policy.set_state, None)
    self.policy = onroad_policy


def _cp(car):
  if car is None:
    return None
  from opendbc.car.tesla_ap1.interface import CarInterface
  from opendbc.car.tesla_ap1.values import CAR
  return CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS if car == "ap1" else CAR.TESLA_PREAP_MODELS)


def walk_page(page, depth=3):
  """(path, Row) for every row of a 3X page and of every MANAGE / OPEN sub-page reachable from it (fresh page per
  sub-page, as tools/bogpilot/settings_row_dump.py does)."""
  from openpilot.selfdrive.ui.bogpilot import row_model as rm
  out = []

  def entries(rows):
    found = []
    for r in rows:
      if r.kind == rm.MANAGE_TOGGLE:
        found.append((r.title(), "manage"))
      elif r.kind == rm.BUTTON and r.button_text().strip().upper() in ("MANAGE", "OPEN"):
        found.append((r.title(), "press"))
    return found

  def explore(clicks):
    widget = page.factory()
    widget.show_event()
    before: set = set()
    for title, how in clicks:
      rows = [rm.Row(i) for i in rm.static_rows(widget)]
      before = {id(r.item) for r in rows}
      match = [r for r in rows if r.title() == title]
      if not match:
        return
      row = match[0]
      if how == "manage":
        cb = getattr(row.action.manage, "_click_callback", None)
        cb and cb()
      else:
        row.item.callback and row.item.callback()
    rows = [rm.Row(i) for i in rm.static_rows(widget) if id(i) not in before]
    path = [page.key] + [t for t, _ in clicks]
    for r in rows:
      out.append((tuple(path), r))
    if len(clicks) < depth:
      for e in entries(rows):
        if e not in clicks:
          explore(clicks + [e])

  explore([])
  return out


class TestEveryRowHasACard(NoWindow):
  NATIVE = True

  def test_every_3x_row_on_every_page_has_a_comma4_card(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import cards_for
    from openpilot.selfdrive.ui.ui_state import ui_state
    tl.invalidate()
    self.assertTrue(tl.set_level(tl.DEVELOPER))
    total, missing, bad_glyphs, build_errors = 0, [], [], []
    for car in (None, "ap1", "preap"):
      ui_state.CP = _cp(car)
      for section in menu_sections():
        for pill in section.pills:
          for page in pill.pages:
            try:
              rows = walk_page(page)
            except Exception as e:  # noqa: BLE001
              build_errors.append((car, page.key, f"{type(e).__name__}: {e}"))
              continue
            for path, row in rows:
              total += 1
              key = (page.key, row.title())
              if key in EXCLUSIONS:
                continue
              cards = cards_for(row, lambda *_: None, lambda *_: None) if row.kind != rm.UNSUPPORTED else []
              if row.kind == rm.UNSUPPORTED or not cards:
                missing.append((car, path, row.title(), type(row.action).__name__))
              for title, value in rm.card_labels(row):
                odd = sorted(set(title + value) - ATLAS)
                if odd:
                  bad_glyphs.append((car, path, title, value, odd))
    ui_state.CP = None
    self.assertEqual(build_errors, [], "3X pages that could not be built here (the comma 4 shows the same pages)")
    self.assertGreater(total, 300)
    self.assertEqual(missing, [])
    self.assertEqual(bad_glyphs, [])

  def test_exclusions_are_justified(self):
    for key, why in EXCLUSIONS.items():
      self.assertTrue(why.strip(), key)


class TestComma4RadarEpasType(NoWindow):
  """Pre-AP Radar EPAS Type: a comma 4 card (lowercase title, label value) that steps like the 3X row, no wrap."""
  NATIVE = True

  def test_card_title_value_and_steps(self):
    from opendbc.car.tesla_ap1.preap import params as pp
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import cards_for, mici_title
    from openpilot.selfdrive.ui.ui_state import ui_state
    tl.invalidate()
    self.assertTrue(tl.set_level(tl.DEVELOPER))
    pdir = Path(self.tmp) / "preap"
    pdir.mkdir(exist_ok=True)
    old = pp._params_dir
    pp._params_dir = pdir
    self.addCleanup(setattr, pp, "_params_dir", old)
    self.addCleanup(setattr, ui_state, "CP", None)
    pp.set_bool("TeslaRadarEnabled", True)
    ui_state.CP = _cp("preap")
    found = [row for section in menu_sections() for pill in section.pills for page in pill.pages if page.key == "vehicle_controls"
             for _, row in walk_page(page) if row.title() == "Pre-AP: Radar EPAS Type"]
    self.assertEqual(len(found), 1)
    row = found[0]
    self.assertEqual(row.kind, rm.STEPPER)
    cards = cards_for(row, lambda *_: None, lambda *_: None)
    self.assertEqual(len(cards), 1)
    self.assertEqual(rm.card_labels(row), [(row.title(), "Bosch L538")])
    self.assertEqual(mici_title(row.title()), "Pre-AP: radar EPAS type")
    self.assertEqual(cards[0].text, "Pre-AP: radar EPAS type")
    self.assertEqual(row.value(), "Bosch L538")
    self.assertTrue(row.plus())
    self.assertEqual(row.value(), "Bosch L405")
    for _ in range(5):
      row.plus()
    self.assertEqual(row.value(), "Mando VGR66 Gen3")
    self.assertEqual((pdir / "TeslaRadarEpasType").read_text(), "4")
    for _ in range(6):
      row.minus()
    self.assertEqual(row.value(), "Bosch L538")
    self.assertTrue(row.enabled())
    self.policy.set_state(self.policy.DriveState(started=lambda: True, parked=lambda: False, engaged=lambda: False))
    self.assertTrue(row.enabled())      # reboot-prompt class: editable while driving, applied at the next start


class TestNavigation(NoWindow):
  NATIVE = True

  def build(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import dialogs, layout
    with mock.patch.object(dialogs, "install", lambda *a, **k: False):
      return layout.BogPilotLayoutMici()

  def test_every_section_pill_and_page_is_reachable(self):
    from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.layout import PageHost, PageList, SectionPage
    tl.invalidate()
    self.assertTrue(tl.set_level(tl.DEVELOPER))
    root = self.build()
    root.show_event()
    reached = set()
    for section in root.sections:
      pills = root.navigation.pills_of(section)
      self.pushed.clear()
      root.open_section(section)
      if len(pills) > 1:
        self.assertIsInstance(self.pushed[0], SectionPage)
      for pill in pills:
        pages = root.navigation.pages_of(pill)
        for page in pages:
          self.pushed.clear()
          if len(pages) == 1:
            root.open_pill(pill.key)
          else:
            if root.navigation.path != (pill.key,):
              root.open_pill(pill.key)
              self.assertIsInstance(root._views[-1], PageList)
            root.open_page(pill.key, page.key)
          view = root._views[-1]
          self.assertIsInstance(view, PageHost)
          self.assertEqual(view.path, (pill.key, page.key))
          self.assertIs(view.widget, root.navigation.current)
          reached.add(page.key)
          root._view_closed(view)                                 # swipe down
          self.assertEqual(root.navigation.path, (pill.key,) if len(pages) > 1 else ())
        if root._views:
          root._view_closed(root._views[-1])
        self.assertEqual(root.navigation.path, ())
        self.assertEqual(root._views, [])
    want = {p.key for s in root.sections for pl in s.pills for p in root.navigation.pages_of(pl)}
    self.assertEqual(reached, want)
    root.hide_event()

  def test_each_move_is_a_new_page_visit_for_the_reboot_prompt(self):
    root = self.build()
    shown = []
    self.policy.set_prompt_ui(shown.append)
    self.policy.set_state(self.policy.DriveState(started=lambda: True, parked=lambda: False, engaged=lambda: False))
    self.assertTrue(self.policy.changed("steering_tuning"))
    self.assertFalse(self.policy.changed("steering_tuning"))      # once per page visit
    root.open_pill("steering")
    self.assertTrue(self.policy.changed("steering_tuning"))       # a move on the comma 4 starts a new visit
    self.assertEqual(shown, ["steering_tuning", "steering_tuning"])

  def test_tuning_level_onroad_as_097_with_one_reboot_prompt(self):
    # FrogPilot 0.9.7 allowed the Tuning Level onroad; it is a REBOOT-class control (onroad_policy ROW_CLASS), so the
    # comma 4 option list writes while the car is on and shows the reboot prompt once per page visit, like the 3X.
    from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.layout import TuningLevelChoice
    root = self.build()
    tl.invalidate()
    tl.set_level(tl.STANDARD if hasattr(tl, "STANDARD") else 1)
    choice = TuningLevelChoice(root)
    self.assertEqual(choice.options(), list(tl.LEVEL_NAMES))
    self.assertEqual(self.policy.row_class("tuning_level", ""), self.policy.REBOOT)
    prompts = []
    self.policy.set_prompt_ui(prompts.append)
    self.policy.new_visit()
    self.policy.set_state(self.policy.DriveState(started=lambda: True, parked=lambda: False, engaged=lambda: False))
    self.assertTrue(choice.enabled())
    self.assertTrue(choice.choose(2))
    tl.invalidate()
    self.assertEqual(tl.effective_level(), 2)
    self.assertTrue(choice.choose(1))
    tl.invalidate()
    self.assertEqual(tl.effective_level(), 1)
    self.assertEqual(len(prompts), 1)                              # once per page visit
    self.policy.set_prompt_ui(None)
    self.policy.set_state(self.policy.DriveState(started=lambda: False))
    self.assertTrue(choice.choose(2))
    tl.invalidate()
    self.assertEqual(tl.effective_level(), 2)
    self.assertTrue(choice.choose(3))                              # Developer: the 0.9.7 warning, as a comma 4 dialog
    self.assertTrue(any(type(w).__name__ == "ConfirmDialog" for w in self.pushed))


class TestRowActions(NoWindow):
  def test_toggle_locked_and_unlocked(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.system.ui.widgets.list_view import toggle_item
    lock = {"on": True}
    calls = []
    row = rm.Row(toggle_item("t", "d", False, callback=calls.append, enabled=lambda: lock["on"]))
    self.assertEqual(row.kind, rm.TOGGLE)
    lock["on"] = False
    self.assertFalse(row.toggle())
    self.assertEqual(calls, [])
    lock["on"] = True
    self.assertTrue(row.toggle())
    self.assertEqual(calls, [True])
    self.assertTrue(row.state())

  def test_value_row_minus_plus_leading_and_lock(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_value_step_item
    lock = {"on": True}
    calls = []
    item = gated_value_step_item("Engage", "d", lambda: "60%", on_minus=lambda: calls.append("-"), on_plus=lambda: calls.append("+"),
                                 leading=["Mute"], on_leading=lambda i: calls.append(("lead", i)), enabled=lambda: lock["on"],
                                 default_text="80%", is_default=lambda: False)
    row = rm.Row(item)
    self.assertEqual(row.kind, rm.STEPPER)
    self.assertEqual((row.value(), row.leading(), row.trailing()), ("60%", ["Mute"], []))
    self.assertTrue(row.highlighted())
    self.assertIn("80%", row.hint())
    self.assertTrue(row.minus() and row.plus() and row.press_leading(0))
    self.assertEqual(calls, ["-", "+", ("lead", 0)])
    lock["on"] = False
    self.assertFalse(row.minus() or row.plus() or row.press_leading(0))
    self.assertEqual(len(calls), 3)

  def test_choice_button_dual_and_manage(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_dual_button_item, gated_multiple_button_item
    from openpilot.selfdrive.ui.bogpilot.phase3_following import _manage_toggle_item
    from openpilot.system.ui.widgets.list_view import button_item
    stored = {"v": 0}
    choice = rm.Row(gated_multiple_button_item("Mode", "d", ["A", "B", "C"], 0, callback=lambda i: stored.update(v=i),
                                               selected_source=lambda: stored["v"]))
    self.assertEqual((choice.kind, choice.options(), choice.selected()), (rm.CHOICE, ["A", "B", "C"], 0))
    self.assertTrue(choice.choose(2))
    self.assertEqual((stored["v"], choice.selected(), choice.value_text()), (2, 2, "C"))
    pressed = []
    btn = rm.Row(button_item("Reset", "RESET", callback=lambda: pressed.append(1)))
    self.assertEqual((btn.kind, rm.card_labels(btn)), (rm.BUTTON, [("Reset", "RESET")]))
    self.assertTrue(btn.press())
    self.assertEqual(pressed, [1])
    sides = []
    dual = rm.Row(gated_dual_button_item("Left", "Right", lambda: sides.append("L"), lambda: sides.append("R")))
    self.assertEqual(dual.kind, rm.DUAL)
    self.assertTrue(dual.press_dual(0) and dual.press_dual(1))
    self.assertEqual(sides, ["L", "R"])
    managed, on = [], {"v": False}
    m = rm.Row(_manage_toggle_item("Personalities", "d", False, lambda s: on.update(v=s), lambda: True,
                                   lambda: managed.append(1), lambda: on["v"]))
    self.assertEqual(m.kind, rm.MANAGE_TOGGLE)
    self.assertFalse(m.manage())                  # MANAGE only while the switch is on (0.9.7 manage control)
    self.assertTrue(m.toggle())
    self.assertTrue(m.manage())
    self.assertEqual(managed, [1])


class TestDialogs(NoWindow):
  def test_bridge_only_on_the_small_ui(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import dialogs

    class App:
      def __init__(self, big):
        self.big, self.got = big, []
        self.push_widget = self.got.append

      def big_ui(self):
        return self.big

    with mock.patch.object(dialogs, "_installed", False):
      big = App(True)
      self.assertFalse(dialogs.install(big))
      self.assertEqual(big.push_widget, big.got.append)
    with mock.patch.object(dialogs, "_installed", False):
      small = App(False)
      self.assertTrue(dialogs.install(small))
      from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
      small.push_widget(alert_dialog("hello"))
      self.assertIsInstance(small.got[0], dialogs.AlertPage)          # one OK button: not a confirmation
      marker = object()
      small.push_widget(marker)
      self.assertIs(small.got[1], marker)

  def test_reboot_prompt_and_reboot_now_refused_while_engaged(self):
    if why := _native_missing():
      self.skipTest(why)
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import dialogs
    self.policy.set_state(self.policy.DriveState(started=lambda: True, parked=lambda: False, engaged=lambda: True))
    self.assertTrue(self.policy.changed("vehicle_controls"))
    page = dialogs.to_mici(self.pushed[-1])
    self.assertIsInstance(page, dialogs.ConfirmPage)
    self.assertIn("Reboot required", page.question)
    self.assertEqual(page.slider_title, "slide to reboot now")
    self.pushed.clear()
    with mock.patch("openpilot.common.params.Params.put_bool") as put:
      page._confirmed()                               # the comma 4 slide-to-confirm finished
      put.assert_not_called()
    self.assertEqual(len(self.pushed), 1)
    self.assertIn("Disengage", dialogs.confirm_text(self.pushed[0]))

  def test_option_list_answers_through_the_3x_dialog(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import dialogs
    from openpilot.system.ui.widgets import DialogResult
    from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
    got = []
    dlg = MultiOptionDialog("Pick", ["One", "Two"], "One", callback=got.append)
    page = dialogs.to_mici(dlg)
    self.assertIsInstance(page, dialogs.OptionsPage)
    page._pick("Two")
    self.assertEqual((dlg.selection, got), ("Two", [DialogResult.CONFIRM]))


class TestSlideToConfirm(NoWindow):
  def _dialog(self, confirm="Reset", got=None, text="Reset all saved values?"):
    from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
    return ConfirmDialog(text, confirm, "Cancel", callback=(got if got is not None else []).append)

  def test_slider_confirms_through_the_3x_dialog_and_swipe_is_cancel(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import dialogs
    from openpilot.system.ui.widgets import DialogResult
    from openpilot.system.ui.widgets.slider import RedBigSlider
    got = []
    page = dialogs.to_mici(self._dialog(got=got))
    self.assertIsInstance(page, dialogs.ConfirmPage)
    self.assertIsInstance(page.slider, RedBigSlider)                # destructive wording: the stock red slider
    self.assertEqual(page.slider_title, "slide to reset")
    self.assertTrue(page.slider.enabled)
    page._confirmed()
    self.assertEqual(got, [DialogResult.CONFIRM])
    got2 = []
    page2 = dialogs.to_mici(self._dialog("Continue", got2, text="Open the pedal calibration?"))
    self.assertFalse(page2.red)
    page2._swiped()
    self.assertEqual(got2, [DialogResult.CANCEL])

  def test_a_locked_row_cannot_be_slid(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import dialogs
    from openpilot.system.ui.widgets.list_view import button_item
    lock, got, pages = {"on": True}, [], []
    row = rm.Row(button_item("Reset", "RESET", callback=lambda: pages.append(dialogs.to_mici(self._dialog(got=got))),
                             enabled=lambda: lock["on"]))
    self.assertTrue(row.press())
    page = pages[0]
    self.assertTrue(page.unlocked() and page.slider.enabled)
    lock["on"] = False                                              # e.g. the car started while the page was open
    self.assertFalse(page.unlocked())
    self.assertFalse(page.slider.enabled)                           # disabled widgets get no touches: not slidable
    page._confirmed()                                               # even a slide that was already under way
    self.assertEqual(got, [])
    lock["on"] = True
    page._confirmed()
    self.assertEqual(len(got), 1)
    self.assertIsNone(rm.opening_gate())                            # outside a row action


class TestHoldToRepeat(unittest.TestCase):
  def _button(self, value, lo=0, hi=5):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import StepButton
    from openpilot.system.ui.lib.application import MousePos
    self.t = 0.0
    self.v = value
    calls = []

    def plus():
      calls.append(1)
      self.v = min(hi, self.v + 1)            # the 3X handler clamps to its range
      return True
    b = StepButton("plus", plus, lambda: True, value=lambda: str(self.v), clock=lambda: self.t)
    return b, calls, MousePos(0, 0)

  def test_stalk_timing(self):
    from opendbc.car.tesla_ap1 import stalk_repeat
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import widgets
    self.assertEqual((widgets.REPEAT_DELAY_S, widgets.REPEAT_PERIOD_S), (stalk_repeat.INITIAL_S, stalk_repeat.PERIOD_S))
    self.assertEqual((widgets.REPEAT_DELAY_S, widgets.REPEAT_PERIOD_S), (0.35, 0.2))

  def test_one_step_on_press_then_repeat_after_the_delay(self):
    b, calls, pos = self._button(0, hi=50)
    b._handle_mouse_press(pos)
    self.assertEqual(self.v, 1)                       # one step on the press
    for self.t, want in ((0.2, 1), (0.34, 1), (0.35, 2), (0.54, 2), (0.55, 3), (0.75, 4), (0.95, 5)):
      b.hold(True)
      self.assertEqual(self.v, want, self.t)
    b._handle_mouse_release(pos)                      # release: no extra step, repeat stops
    self.t = 2.0
    b.hold(True)
    self.assertEqual(self.v, 5)
    self.assertFalse(b.repeating)

  def test_no_repeat_past_the_limit(self):
    b, calls, pos = self._button(3, hi=5)
    b._handle_mouse_press(pos)
    self.t = 0.35
    b.hold(True)
    self.assertEqual(self.v, 5)
    self.t = 0.55
    b.hold(True)                                      # the 3X clamps: value unchanged -> repeat ends
    self.assertFalse(b.repeating)
    n = len(calls)
    self.t = 5.0
    b.hold(True)
    self.assertEqual((self.v, len(calls)), (5, n))
    b2, calls2, _ = self._button(5, hi=5)             # already at the limit: a press, no repeat
    b2._handle_mouse_press(pos)
    self.assertFalse(b2.repeating)

  def test_finger_leaving_or_lock_stops_the_repeat(self):
    b, calls, pos = self._button(0, hi=50)
    b._handle_mouse_press(pos)
    self.t = 0.35
    b.hold(False)                                     # finger slid off the button
    self.assertFalse(b.repeating)
    self.assertEqual(self.v, 1)

  def test_pills_act_once_on_release(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import StepButton
    from openpilot.system.ui.lib.application import MousePos
    hits = []
    b = StepButton("pill", lambda: hits.append(1), lambda: True, lambda: "Mute")
    b._handle_mouse_press(MousePos(0, 0))
    self.assertEqual(hits, [])
    b._handle_mouse_release(MousePos(0, 0))
    self.assertEqual(hits, [1])


class TestLowercaseTitles(unittest.TestCase):
  def test_titles(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import mici_title
    for src, want in (("Lane Change Timer", "lane change timer"), ("Pre-AP Pedal Calibration", "Pre-AP pedal calibration"),
                      ("AP1 Tap From Zero (mph)", "AP1 tap from zero (mph)"), ("BogPilot Backups", "BogPilot backups"),
                      ("Speed in km/h", "speed in km/h"), ("Show VIN", "show VIN"), ("AGNOS Version", "AGNOS version"),
                      ("Stop-and-Go Mode", "stop-and-go mode"), ("AP1/Pre-AP Info", "AP1/Pre-AP info"),
                      ("Record mic audio locally", "record mic audio locally")):
      self.assertEqual(mici_title(src), want)

  def test_cards_use_lowercase_titles_and_keep_values(self):
    with mock.patch.object(gui_app, "texture", lambda *a, **k: rl.Texture()), mock.patch.object(gui_app, "font", lambda *a, **k: rl.Font()):
      from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import InfoCard, LiveCard
      card = LiveCard(lambda: "Lane Change Timer", lambda: "MANAGE")
      self.assertEqual((card.text, card.value), ("lane change timer", "MANAGE"))
      self.assertEqual(InfoCard(lambda: "Pre-AP Status", lambda: "On").text, "Pre-AP status")


class TestComma4Software(NoWindow):
  NATIVE = True

  def test_check_update_greyed_onroad_like_the_3x(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.software import CheckUpdateButton
    btn = CheckUpdateButton()
    st = {"started": True, "parked": False}
    self.policy.set_state(self.policy.DriveState(started=lambda: st["started"], parked=lambda: st["parked"], engaged=lambda: False))
    btn._update_state()
    self.assertFalse(btn.enabled)                     # driving
    st["parked"] = True
    btn._update_state()
    self.assertFalse(btn.enabled)                     # in Park: greyed too (updated runs offroad only), as on the 3X
    st.update(started=False, parked=False)
    btn._update_state()
    self.assertTrue(btn.enabled)                      # car off

  def test_uses_the_shared_policy(self):
    src = (UI / "mici/layouts/settings/software.py").read_text()
    self.assertIn("onroad_policy.downloads_allowed(", src)
    self.assertNotIn("if ui_state.started:\n      self.set_enabled(False)", src)


class TestComma4ModelFallbackAlert(NoWindow):
  NATIVE = True

  def test_fallback_alert_shows_and_clears_like_the_3x(self):
    from openpilot.common.bogpilot_models import alert, selection
    from openpilot.common.tests import bogpilot_model_fixtures as fx
    from openpilot.selfdrive.ui.mici.layouts import offroad_alerts as oa
    self.assertEqual(oa.BOGPILOT_MODEL_ALERT_KEY, "BogPilot_ModelFallback")
    store = fx.MemStore()
    with tempfile.TemporaryDirectory() as t:
      fx.install_model(Path(t), "m", name="Fancy")
      self.assertTrue(selection.select("m", lambda: True, store, Path(t)).ok)
      sel = selection.read_selection(store)[0]
      selection.record_fallback(store, sel, "Fancy", "hash mismatch (file changed or corrupt)", "validate")
      real = alert.current_alert
      want = real(store)
      with mock.patch.object(alert, "current_alert", lambda store_=None: real(store)), \
           mock.patch.object(oa.threading, "Thread", mock.MagicMock()):
        w = oa.MiciOffroadAlerts()
        before = w._refresh(w.read_params())
        mine = next(a for a in w.sorted_alerts if a.key == oa.BOGPILOT_MODEL_ALERT_KEY)
        self.assertTrue(mine.visible)
        self.assertEqual(mine.text, want["text"])     # the 3X text, unchanged
        self.assertEqual(mine.severity, 1)
        item = next(i for i in w.alert_items if i.alert_data is mine)
        self.assertIs(item.icon, item._icon_red)      # stock comma 4 look for a severity-1 offroad alert
        self.assertGreaterEqual(before, 1)
        self.assertTrue(selection.select("default", lambda: True, store, Path(t)).ok)
        after = w._refresh(w.read_params())
        self.assertFalse(mine.visible)
        self.assertEqual(after, before - 1)


class TestComma4Screens(unittest.TestCase):
  def test_minus_and_plus_are_drawn_never_glyphs(self):
    src = (UI / "mici/layouts/settings/bogpilot/widgets.py").read_text()
    for path in (UI / "mici/layouts/settings/bogpilot").glob("*.py"):
      self.assertNotIn("\u2212", path.read_text(), path.name)
    self.assertIn('StepButton("minus"', src)
    self.assertIn('StepButton("plus"', src)

  def test_settings_root_opens_bogpilot_with_the_bogpilot_logo(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.layout import LOGO
    src = (UI / "mici/layouts/settings/settings.py").read_text()
    self.assertIn("BogPilotLayoutMici()", src)
    self.assertIn("gui_app.texture(LOGO", src)
    self.assertIn("bogpilot", LOGO)
    self.assertNotIn("frog", LOGO.lower())
    self.assertTrue((UI.parent / "assets" / LOGO).is_file())

  def test_stock_items_bogpilot_hides_on_the_3x_are_gone_on_comma4(self):
    mici = UI / "mici"
    settings = (mici / "layouts/settings/settings.py").read_text()
    for gone in ("firehose", "FirehoseLayout", "prime", "pairing"):
      self.assertNotIn(gone, settings.lower() if gone.islower() else settings)
    self.assertFalse((mici / "layouts/settings/firehose.py").exists())
    self.assertFalse((mici / "layouts/settings/device/prime.py").exists())
    toggles = (mici / "layouts/settings/toggles.py").read_text()
    self.assertIn('"record cabin camera locally"', toggles)
    self.assertIn('"record mic audio locally"', toggles)
    self.assertNotIn("upload mic", toggles)
    tici = (UI / "layouts/settings/toggles.py").read_text()
    self.assertIn('tr("Record mic audio locally")', tici)
    self.assertNotIn("Record and Upload Microphone Audio", tici)
    self.assertNotIn("record & upload cabin camera", toggles)
    self.assertIn('"DisengageOnAccelerator"', toggles)    # on the 3X Toggles panel, so on comma 4 too
    self.assertIn('UnifiedLabel("BogPilot"', (mici / "layouts/home.py").read_text())


if __name__ == "__main__":
  unittest.main()
