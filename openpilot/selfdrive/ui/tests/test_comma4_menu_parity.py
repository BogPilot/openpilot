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
  natively (AGNOS3X runner); here they skip with this reason."""
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

  def test_tuning_level_is_offroad_only(self):
    from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.layout import TuningLevelChoice
    root = self.build()
    tl.invalidate()
    tl.set_level(tl.STANDARD if hasattr(tl, "STANDARD") else 1)
    choice = TuningLevelChoice(root)
    self.assertEqual(choice.options(), list(tl.LEVEL_NAMES))
    self.policy.set_state(self.policy.DriveState(started=lambda: True, parked=lambda: True, engaged=lambda: False))
    self.assertFalse(choice.enabled())
    self.assertFalse(choice.choose(2))
    tl.invalidate()
    self.assertEqual(tl.effective_level(), 1)
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
      self.assertIsInstance(small.got[0], dialogs.ConfirmPage)
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
    self.assertIn("Reboot required", dialogs.confirm_text(page.dialog))
    self.pushed.clear()
    with mock.patch("openpilot.common.params.Params.put_bool") as put:
      page.dialog._confirm_button_callback()          # what the comma 4 "Reboot Now" card does
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
    self.assertNotIn("record & upload cabin camera", toggles)
    self.assertIn('"DisengageOnAccelerator"', toggles)    # on the 3X Toggles panel, so on comma 4 too
    self.assertIn('UnifiedLabel("BogPilot"', (mici / "layouts/home.py").read_text())


if __name__ == "__main__":
  unittest.main()
