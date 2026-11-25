"""Alerts & Sounds page rows for the two 0.9.7 driver-alert toggles (headless native render)."""
from types import SimpleNamespace
import os
import tempfile
import unittest


from openpilot.selfdrive.ui.bogpilot.phase2_driver_alerts import DRIVER_ALERT_KEYS


class FakeStore:
  def __init__(self, values=None):
    self.values = values or {}

  def get_bool(self, key, default=False):
    return self.values.get(key, default)


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestAlertsPanel(unittest.TestCase):
  """The two new rows sit in the existing Alerts & Sounds page, honour saved choices and hide without a consumer."""

  @classmethod
  def setUpClass(cls):
    os.environ.setdefault("BOGPILOT_PARAMS_DIR", tempfile.mkdtemp(prefix="driver-alerts-panel-"))
    from openpilot.selfdrive.ui.tests.test_bogpilot_toggle_help import _fake_device_type
    _fake_device_type()
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    if not gui_app.big_ui() and not rl.is_window_ready():
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("Driver alerts panel test")

  def layout(self, values, cp):
    from openpilot.selfdrive.ui.bogpilot.phase2_alerts import create_alerts_layout
    import openpilot.selfdrive.ui.ui_state as ui_state_module
    store = FakeStore(values)
    store.put_bool = lambda k, v: store.values.__setitem__(k, bool(v))
    store.invalidate = lambda k=None: None
    self.addCleanup(setattr, ui_state_module.ui_state, "CP", getattr(ui_state_module.ui_state, "CP", None))
    ui_state_module.ui_state.CP = cp
    return create_alerts_layout(store), store

  def test_rows_default_off_visibility_and_write_back(self):
    ap1 = SimpleNamespace(carFingerprint="TESLA_AP1_MODELS")
    layout, store = self.layout({"SpeedLimitController": True}, ap1)   # real ParamStore defaults it ON
    self.assertEqual(set(layout.items), {"GreenLightAlert", "LeadDepartingAlert", "CruiseEngageDisengageChimes", *DRIVER_ALERT_KEYS})
    for key in DRIVER_ALERT_KEYS:
      self.assertTrue(layout.items[key].action_item.get_state())                        # fresh install ON
    self.assertTrue(layout.items["GreenLightAlert"].action_item.get_state())          # unchanged fresh-ON rows
    self.assertTrue(layout.items["LoudBlindspotAlert"].is_visible)                      # AP1 reports blind spot cars
    self.assertTrue(layout.items["SpeedLimitChangedAlert"].is_visible)                  # SLC default ON
    layout.write("LoudBlindspotAlert", False)
    self.assertFalse(store.values["LoudBlindspotAlert"])
    layout.show_event()
    self.assertFalse(layout.items["LoudBlindspotAlert"].action_item.get_state())        # saved OFF kept

  def test_loud_blindspot_row_shows_on_the_ap1_model_x(self):
    layout, _ = self.layout({"SpeedLimitController": True}, SimpleNamespace(carFingerprint="TESLA_AP1_MODELX"))
    self.assertTrue(layout.items["LoudBlindspotAlert"].is_visible)                      # X reads the same 0x399 BSM
    layout, _ = self.layout({"SpeedLimitController": True}, SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS"))
    self.assertFalse(layout.items["LoudBlindspotAlert"].is_visible)                     # Pre-AP: no BSM source

  def test_rows_hide_without_a_consumer_and_saved_state_shows(self):
    layout, _ = self.layout({"SpeedLimitController": False, "SpeedLimitChangedAlert": True, "LoudBlindspotAlert": True},
                            SimpleNamespace(carFingerprint="TESLA_AP1_PREAP"))
    self.assertFalse(layout.items["LoudBlindspotAlert"].is_visible)
    self.assertFalse(layout.items["SpeedLimitChangedAlert"].is_visible)
    self.assertTrue(layout.items["SpeedLimitChangedAlert"].action_item.get_state())     # hidden, choice kept
    layout, _ = self.layout({}, None)
    self.assertFalse(layout.items["LoudBlindspotAlert"].is_visible)


if __name__ == "__main__":
  unittest.main()
