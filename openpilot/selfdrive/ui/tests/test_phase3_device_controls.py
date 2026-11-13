"""UI -> store -> consumer proofs for Device Controls (no hardware, no shared-file edits)."""
from __future__ import annotations

import math
import unittest

from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import (
  DeviceControlsMenu, DevicePreferences, MemoryStore, DEVICE_KEYS, RANGES,
)
from openpilot.selfdrive.ui.bogpilot.phase3_device_controls_runtime import (
  screen_timeout, screen_brightness, screen_awake, shutdown_time, voltage_cutoff, shutdown_label,
)


class TestRuntimeConsumers(unittest.TestCase):
  def setUp(self):
    self.store = MemoryStore()

  def test_screen_timeout_parent_off_preserves_stock(self):
    self.store.put("ScreenTimeout", "15")
    self.assertEqual(screen_timeout(self.store, False, 30), 15)   # unset master reads On like the 0.9.7 table
    self.store.put_bool("ScreenManagement", False)                  # explicit Off keeps the stock timeout
    self.assertEqual(screen_timeout(self.store, False, 30), 30)
    self.store.put_bool("ScreenManagement", True)
    self.assertEqual(screen_timeout(self.store, False, 30), 15)
    self.store.put("ScreenTimeoutOnroad", "20")
    self.assertEqual(screen_timeout(self.store, True, 10), 20)

  def test_screen_timeout_malformed_fails_closed(self):
    self.store.put_bool("ScreenManagement", True)
    self.store.put("ScreenTimeout", "nope")
    self.assertEqual(screen_timeout(self.store, False, 30), 30)
    self.store.put("ScreenTimeout", "999")
    self.assertEqual(screen_timeout(self.store, False, 30), 60)  # clamped

  def test_brightness_auto_and_attention_floor(self):
    self.store.put_bool("ScreenManagement", True)
    self.store.put("ScreenBrightnessOnroad", "101")
    self.assertEqual(screen_brightness(self.store, True, 55.0), 55.0)
    self.store.put("ScreenBrightnessOnroad", "10")
    self.assertEqual(screen_brightness(self.store, True, 55.0), 10.0)
    self.assertEqual(screen_brightness(self.store, True, 55.0, attention=True), 30.0)

  def test_standby_sleeps_only_with_master_and_timeout(self):
    self.store.put_bool("ScreenManagement", True)
    self.store.put_bool("StandbyMode", True)
    self.assertFalse(screen_awake(self.store, True, True, False))
    self.assertTrue(screen_awake(self.store, True, True, False, attention=True))
    self.assertTrue(screen_awake(self.store, True, False, False))
    self.store.put_bool("ScreenManagement", False)
    self.assertTrue(screen_awake(self.store, True, True, False))

  def test_shutdown_never_extends_stock(self):
    self.store.put_bool("DeviceManagement", True)
    self.store.put("DeviceShutdown", "33")  # historical 30h label
    self.assertEqual(shutdown_time(self.store, 30 * 3600), 30 * 3600)
    self.store.put("DeviceShutdown", "0")  # 5 min
    self.assertEqual(shutdown_time(self.store, 30 * 3600), 300)
    self.store.put("DeviceShutdown", "9")  # 6 h
    self.assertEqual(shutdown_time(self.store, 30 * 3600), 6 * 3600)
    self.store.put_bool("DeviceManagement", False)
    self.assertEqual(shutdown_time(self.store, 30 * 3600), 30 * 3600)

  def test_voltage_never_below_stock_floor(self):
    self.store.put_bool("DeviceManagement", True)
    self.store.put("LowVoltageShutdown", "11.5")  # below stock — clamped to stock
    self.assertEqual(voltage_cutoff(self.store, 11.8), 11.8)
    self.store.put("LowVoltageShutdown", "12.5")
    self.assertEqual(voltage_cutoff(self.store, 11.8), 12.5)
    self.store.put_bool("DeviceManagement", False)
    self.assertEqual(voltage_cutoff(self.store, 11.8), 11.8)

  def test_shutdown_labels(self):
    self.assertEqual(shutdown_label(0), "5 mins")
    self.assertEqual(shutdown_label(2), "30 mins")
    self.assertEqual(shutdown_label(4), "1 hour")
    self.assertEqual(shutdown_label(9), "6 hours")


class TestUIStoreConsumer(unittest.TestCase):
  def setUp(self):
    self.starts = []
    self.stops = []
    self.menu = DeviceControlsMenu(
      store=MemoryStore(),
      offroad=lambda: True,
      capable=lambda: True,
      recorder_start=lambda: self.starts.append("start") or "started",
      recorder_stop=lambda: self.stops.append("stop") or "stopped",
    )

  def test_root_pages(self):
    titles = [r["title"] for r in self.menu.rows()]
    self.assertEqual(titles, ["Device Settings", "Screen Settings"])

  def test_device_settings_ui_to_shutdown_consumer(self):
    self.assertTrue(self.menu.go("Device Settings"))
    self.assertTrue(self.menu.set("DeviceManagement", True))
    self.assertEqual(self.menu.store.raw("DeviceManagement"), "1")
    self.assertTrue(self.menu.set("DeviceShutdown", 0))
    self.assertEqual(self.menu.store.raw("DeviceShutdown"), "0")
    self.assertEqual(self.menu.consume_shutdown(), 300)
    # Parent off restores stock even if value remains
    self.assertTrue(self.menu.set("DeviceManagement", False))
    self.assertEqual(self.menu.consume_shutdown(), 30 * 3600)

  def test_device_settings_ui_to_voltage_consumer(self):
    self.menu.go("Device Settings")
    self.menu.set("DeviceManagement", True)
    self.menu.set("LowVoltageShutdown", 12.3)
    self.assertEqual(self.menu.store.raw("LowVoltageShutdown"), "12.3")
    self.assertAlmostEqual(self.menu.consume_voltage(), 12.3)

  def test_screen_settings_ui_to_timeout_brightness_standby(self):
    self.menu.go("Screen Settings")
    self.menu.set("ScreenManagement", True)
    self.menu.set("ScreenTimeout", 15)
    self.menu.set("ScreenTimeoutOnroad", 25)
    self.menu.set("ScreenBrightness", 70)
    self.menu.set("ScreenBrightnessOnroad", 40)
    self.menu.set("StandbyMode", True)
    self.assertEqual(self.menu.consume_timeout(False), 15)
    self.assertEqual(self.menu.consume_timeout(True), 25)
    self.assertEqual(self.menu.consume_brightness(False), 70.0)
    self.assertEqual(self.menu.consume_brightness(True, attention=True), 40.0)  # 40 >= 30
    self.assertFalse(self.menu.consume_awake(ignition=True, timed_out=True))

  def test_offroad_and_capability_guards(self):
    self.menu.offroad = lambda: False
    self.menu.go("Device Settings")
    self.assertFalse(self.menu.set("DeviceManagement", True))
    self.assertIsNone(self.menu.store.raw("DeviceManagement"))
    self.menu.offroad = lambda: True
    self.menu.capable = lambda: False
    self.assertFalse(self.menu.set("DeviceManagement", True))

  def test_range_rejection(self):
    self.menu.go("Screen Settings")
    self.menu.set("ScreenManagement", True)
    self.assertFalse(self.menu.set("ScreenTimeout", 7))  # step 5
    self.assertFalse(self.menu.set("ScreenTimeout", 100))
    prefs = DevicePreferences(MemoryStore(), lambda: True, lambda: True)
    with self.assertRaises(ValueError):
      prefs.set("NotAKey", True)

  def test_placeholder_rows_are_hidden(self):
    hidden = ("High-Quality Recording", "Raise Temperature Limits", "Offroad Screensaver")
    for page in ("Device Settings", "Screen Settings"):
      self.menu.go(page)
      rows = self.menu.rows()
      self.assertFalse([r for r in rows if r["kind"] == "unavailable"])
      self.assertFalse([r for r in rows if r["title"] in hidden])
      self.menu.back()

  def test_recorder_actions_invoke_injected_consumer(self):
    self.menu.go("Screen Settings")
    self.assertTrue(self.menu.run_action("start_recording"))
    self.assertTrue(self.menu.run_action("stop_recording"))
    self.assertEqual(self.starts, ["start"])
    self.assertEqual(self.stops, ["stop"])

  def test_no_inert_active_toggle_without_consumer_path(self):
    """Every editable Device Controls key has a consume_* path or recorder action."""
    self.menu.go("Device Settings")
    for key in self.menu.active_keys():
      self.assertIn(key, DEVICE_KEYS)
    self.menu.back()
    self.menu.go("Screen Settings")
    for key in self.menu.active_keys():
      self.assertIn(key, DEVICE_KEYS)
    # Prove each numeric/bool maps to a consumer when masters ON
    self.menu.set("ScreenManagement", True)
    self.menu.set("DeviceManagement", True)
    for key, value in (
      ("DeviceShutdown", 1), ("LowVoltageShutdown", 12.0),
      ("ScreenBrightness", 60), ("ScreenBrightnessOnroad", 55),
      ("ScreenTimeout", 10), ("ScreenTimeoutOnroad", 15), ("StandbyMode", True),
    ):
      self.assertTrue(self.menu.set(key, value))
    self.assertEqual(self.menu.consume_shutdown(), 900)
    self.assertAlmostEqual(self.menu.consume_voltage(), 12.0)
    self.assertEqual(self.menu.consume_brightness(False), 60.0)
    self.assertEqual(self.menu.consume_timeout(True), 15)
    self.assertFalse(self.menu.consume_awake(True, True, False))

  def test_range_tables_match_historical_steps(self):
    self.assertEqual(RANGES["DeviceShutdown"], (0, 33, 1))
    self.assertEqual(RANGES["ScreenTimeout"], (5, 60, 5))
    self.assertEqual(RANGES["LowVoltageShutdown"], (11.8, 12.5, 0.1))


class TestSimulatedHookedDevicePower(unittest.TestCase):
  """Simulate the PROPOSED ui_state/power_monitoring call sites without editing shared files."""

  def test_device_interactive_timeout_callsite(self):
    store = MemoryStore({"ScreenManagement": "1", "ScreenTimeout": "15"})
    ignition = False
    stock = 10 if ignition else 30
    self.assertEqual(screen_timeout(store, ignition, stock), 15)

  def test_power_monitor_callsite_clamps(self):
    store = MemoryStore({"DeviceManagement": "1", "DeviceShutdown": "0", "LowVoltageShutdown": "12.4"})
    MAX_TIME_OFFROAD_S = 30 * 3600
    VBATT_PAUSE_CHARGING = 11.8
    self.assertEqual(shutdown_time(store, MAX_TIME_OFFROAD_S), 300)
    self.assertAlmostEqual(voltage_cutoff(store, VBATT_PAUSE_CHARGING), 12.4)


class TestDisableLoggingRow(unittest.TestCase):
  """Disable Logging (NoLogging) in its 0.9.7 spot: Device Settings, after the shutdown timer, level 2, DeviceManagement child."""

  def _menu(self, level=None, dm=None, **vals):
    if level is not None:
      vals.update(TuningLevelConfirmed="1", TuningLevel=str(level))
    if dm is not None:
      vals["DeviceManagement"] = "1" if dm else "0"
    menu = DeviceControlsMenu(store=MemoryStore(vals), offroad=lambda: True, capable=lambda: True)
    menu.go("Device Settings")
    return menu

  def _keys(self, menu):
    return [r.get("key") for r in menu.visible_rows()]

  def test_visible_at_level_2_and_above_with_device_management_on(self):
    for level in (2, 3):
      menu = self._menu(level, dm=True)
      self.assertEqual(self._keys(menu), ["DeviceManagement", "DeviceShutdown", "NoLogging", "LowVoltageShutdown"], level)
      row = next(r for r in menu.rows() if r.get("key") == "NoLogging")
      self.assertEqual((row["title"], row["kind"], row["requires"]), ("Disable Logging", "toggle", "DeviceManagement"))
    self.assertIn("NoLogging", self._keys(self._menu(None, dm=True)))   # level not confirmed = Developer (3)

  def test_hidden_below_level_2(self):
    for level in (0, 1):
      self.assertNotIn("NoLogging", [r.get("key") for r in self._menu(level, dm=True).rows()], level)

  def test_hidden_with_device_management_off(self):
    for level in (2, 3):
      self.assertNotIn("NoLogging", self._keys(self._menu(level, dm=False)), level)

  def test_default_off_and_write_readback(self):
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    self.assertEqual(BOGPILOT_PARAMS["NoLogging"][2], "0")
    self.assertEqual(BOGPILOT_PARAMS["NoLogging"][3], 2)
    menu = self._menu(2, dm=True)
    self.assertFalse(next(r for r in menu.rows() if r.get("key") == "NoLogging")["value"])
    self.assertTrue(menu.set("NoLogging", True))
    self.assertEqual(menu.store.raw("NoLogging"), "1")
    self.assertFalse(menu.set("NoLogging", "1"))   # bool only
    self.assertIn("NoLogging", DEVICE_KEYS)

  def test_layout_wires_the_row_under_the_master(self):
    from pathlib import Path
    from openpilot.selfdrive.ui.bogpilot import phase3_device_controls as D
    src = Path(D.__file__).read_text()
    self.assertIn("callback=lambda v: switch.toggled(v)", src)
    self.assertIn('"NoLogging")', src)                                   # attach_help key -> tuning-level gate
    self.assertIn('children = [self.number("DeviceShutdown", "Device Shutdown Timer"), no_logging,', src)
    self.assertIn("nest(master, *children)", src)
    self.assertNotIn("Disable Logging, High-Quality Recording", src)

  def test_help_entry_and_level_gate(self):
    from openpilot.selfdrive.ui.bogpilot import toggle_help, tuning_level
    self.assertIsNotNone(toggle_help.resolve("NoLogging"))
    self.assertNotIn("Disable Logging", toggle_help.SKIPPED_TITLES)
    self.assertEqual(tuning_level.row_level("NoLogging"), 2)
    self.assertTrue(tuning_level.row_visible("NoLogging", 2))
    self.assertFalse(tuning_level.row_visible("NoLogging", 1))


class TestDisableLoggingConfirm(unittest.TestCase):
  """0.9.7 device_settings.cc:168 setConfirmation(true, false): ON asks every time, OFF does not, Cancel keeps OFF."""
  WARNING_097 = ("<b>WARNING: This will prevent your drives from being recorded and all data will be unobtainable!</b>"
                 "<br><br><b>Prevent the device from saving driving data.</b>")

  def setUp(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import NoLoggingSwitch
    self.store = MemoryStore({"DeviceManagement": "1"})
    self.menu = DeviceControlsMenu(store=self.store, offroad=lambda: True, capable=lambda: True)
    self.menu.go("Device Settings")
    self.asked, self.resets = [], []
    self.switch = NoLoggingSwitch(lambda html, done: self.asked.append((html, done)),
                                  lambda v: self.menu.set("NoLogging", v), lambda: self.resets.append(False))

  def test_on_asks_with_the_097_text(self):
    self.switch.toggled(True)
    self.assertEqual(len(self.asked), 1)
    self.assertIsNone(self.store.raw("NoLogging"))           # nothing saved before the answer
    html = self.asked[0][0]
    self.assertIn("Disable Logging", html)
    self.assertIn(self.WARNING_097, html)

  def test_cancel_keeps_off(self):
    self.switch.toggled(True)
    self.asked[0][1](False)
    self.assertIsNone(self.store.raw("NoLogging"))
    self.assertFalse(self.store.get_bool("NoLogging", False))
    self.assertEqual(self.resets, [False])

  def test_confirm_saves_on(self):
    self.switch.toggled(True)
    self.asked[0][1](True)
    self.assertEqual(self.store.raw("NoLogging"), "1")
    self.assertEqual(self.resets, [])

  def test_confirm_refused_write_resets_switch(self):
    self.menu.offroad = lambda: False
    self.switch.toggled(True)
    self.asked[0][1](True)
    self.assertIsNone(self.store.raw("NoLogging"))
    self.assertEqual(self.resets, [False])

  def test_off_needs_no_dialog(self):
    self.store.put("NoLogging", "1")
    self.switch.toggled(False)
    self.assertEqual(self.asked, [])
    self.assertEqual(self.store.raw("NoLogging"), "0")

  def test_every_on_asks_again(self):
    for _ in range(2):
      self.switch.toggled(True)
      self.asked[-1][1](True)
      self.switch.toggled(False)
    self.assertEqual(len(self.asked), 2)
    self.assertIsNone(self.store.raw("NoLoggingConfirmed"))  # store_confirm false: nothing remembered

  def test_layout_uses_the_stock_confirm_dialog(self):
    from pathlib import Path
    from openpilot.selfdrive.ui.bogpilot import phase3_device_controls as D
    src = Path(D.__file__).read_text()
    self.assertIn('ConfirmDialog(no_logging_confirm_html(tr), tr("Enable"), rich=True,', src)
    self.assertIn("callback=lambda r: done(r == DialogResult.CONFIRM)", src)
    self.assertIn("device_settings.cc:168", src)
    self.assertIn("no_logging.action_item.set_state(False)", src)


if __name__ == "__main__":
  unittest.main()
