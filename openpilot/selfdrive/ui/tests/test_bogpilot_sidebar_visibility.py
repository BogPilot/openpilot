"""Sidebar show / hide (0.9.7 home.cc:124-129): a tap on empty screen space toggles it and saves the Sidebar param; coming
onroad, or back onroad from settings, restores the saved choice; offroad it is always shown; a timeout that finds the
driving view already up leaves it alone."""
import unittest
from types import SimpleNamespace


class FakeSidebar:
  def __init__(self, visible=False):
    self.is_visible = visible

  def set_visible(self, visible):
    self.is_visible = bool(visible)


class FakeParams:
  def __init__(self, **saved):
    self.saved = dict(saved)
    self.writes = []

  def get_bool(self, key):
    return bool(self.saved.get(key, False))

  def put_bool(self, key, value):
    self.writes.append((key, bool(value)))
    self.saved[key] = bool(value)


class Broken:
  def get_bool(self, key):
    raise RuntimeError("no params")

  def put_bool(self, key, value):
    raise RuntimeError("no params")


def layout(mode, sidebar_visible=False, params=None):
  from openpilot.selfdrive.ui.layouts import main as M
  main = M.MainLayout.__new__(M.MainLayout)
  main._sidebar = FakeSidebar(sidebar_visible)
  main._params = params if params is not None else FakeParams()
  main._current_mode = mode
  main._layouts = {state: SimpleNamespace(hide_event=lambda: None, show_event=lambda: None) for state in M.MainState}
  return M, main


class TestSidebarVisibility(unittest.TestCase):
  def setUp(self):
    from openpilot.selfdrive.ui.layouts import main as M
    self.M = M
    self._ui_state = M.ui_state
    self.addCleanup(lambda: setattr(M, "ui_state", self._ui_state))

  def state(self, started, body=False):
    self.M.ui_state = SimpleNamespace(started=started, is_body=body, ignition=started)

  def test_tap_toggles_and_saves_each_time(self):
    M, main = layout(None, sidebar_visible=False)
    main._on_onroad_clicked()
    self.assertTrue(main._sidebar.is_visible)
    main._on_onroad_clicked()
    self.assertFalse(main._sidebar.is_visible)
    self.assertEqual(main._params.writes, [("Sidebar", True), ("Sidebar", False)])

  def test_coming_onroad_restores_the_saved_choice(self):
    for saved in (True, False):
      M, main = layout(None, params=FakeParams(Sidebar=saved))
      main._current_mode = M.MainState.HOME
      self.state(started=True)
      main._set_mode_for_state()
      self.assertEqual(main._sidebar.is_visible, saved)
      self.assertEqual(main._current_mode, M.MainState.ONROAD)

  def test_returning_from_settings_restores_the_saved_choice(self):
    M, main = layout(None, params=FakeParams(Sidebar=True))
    main._current_mode = M.MainState.SETTINGS
    self.state(started=True)
    main._set_mode_for_state()
    self.assertTrue(main._sidebar.is_visible)

  def test_a_timeout_while_already_onroad_does_not_change_the_sidebar(self):
    M, main = layout(None, sidebar_visible=False, params=FakeParams(Sidebar=True))
    main._current_mode = M.MainState.ONROAD
    self.state(started=True)
    main._set_mode_for_state()
    self.assertFalse(main._sidebar.is_visible)
    main._sidebar.set_visible(True)
    main._params.saved["Sidebar"] = False
    main._set_mode_for_state()
    self.assertTrue(main._sidebar.is_visible)

  def test_offroad_always_shows_it_and_does_not_overwrite_the_saved_choice(self):
    M, main = layout(None, params=FakeParams(Sidebar=False))
    main._current_mode = M.MainState.ONROAD
    self.state(started=False)
    main._set_mode_for_state()
    self.assertTrue(main._sidebar.is_visible)
    self.assertEqual(main._params.writes, [])
    self.assertFalse(main._params.saved["Sidebar"])

  def test_unreadable_param_falls_back_to_hidden_and_never_raises(self):
    M, main = layout(None, params=Broken())
    main._current_mode = M.MainState.HOME
    self.state(started=True)
    main._set_mode_for_state()
    self.assertFalse(main._sidebar.is_visible)
    main._on_onroad_clicked()
    self.assertTrue(main._sidebar.is_visible)


if __name__ == "__main__":
  unittest.main()
