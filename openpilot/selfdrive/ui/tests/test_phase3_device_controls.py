"""UI -> store -> consumer proofs for Device Controls (no hardware, no shared-file edits)."""
from __future__ import annotations

import math
import unittest

from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import (
  DeviceControlsMenu, DevicePreferences, MemoryStore, DEVICE_KEYS, RANGES, UNAVAILABLE,
)
from openpilot.selfdrive.ui.bogpilot.phase3_device_controls_runtime import (
  screen_timeout, screen_brightness, screen_awake, shutdown_time, voltage_cutoff, shutdown_label,
)


class TestRuntimeConsumers(unittest.TestCase):
  def setUp(self):
    self.store = MemoryStore()

  def test_screen_timeout_parent_off_preserves_stock(self):
    self.store.put("ScreenTimeout", "15")
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

  def test_unavailable_rows_are_explanations_not_toggles(self):
    self.menu.go("Device Settings")
    kinds = {r["title"]: r["kind"] for r in self.menu.rows() if r["kind"] == "unavailable"}
    for title in ("Disable Logging", "High-Quality Recording", "Raise Temperature Limits"):
      self.assertEqual(kinds[title], "unavailable")
      self.assertIn(title, UNAVAILABLE)
    self.menu.back()
    self.menu.go("Screen Settings")
    ss = {r["title"]: r for r in self.menu.rows()}
    self.assertEqual(ss["Offroad Screensaver"]["kind"], "unavailable")

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


if __name__ == "__main__":
  unittest.main()
