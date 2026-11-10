"""t994 INT: Device Controls hooks in hardwared (power_monitoring) and ui_state, with REAL registry defaults."""
import os
import tempfile
import unittest


class FakeStore:
  def __init__(self, **kw):
    self.d = dict(kw)

  def get_bool(self, k, default=False):
    return bool(self.d.get(k, default))

  def get(self, k, default=None):
    return self.d.get(k, default)

  def raw(self, k):
    v = self.d.get(k)
    return None if v is None else str(v)


class TestPowerHooks(unittest.TestCase):
  def test_power_monitoring_imports_and_hooks_resolve(self):
    from openpilot.system.hardware import power_monitoring as pm
    self.assertTrue(callable(pm.bp_shutdown_time) and callable(pm.bp_voltage_cutoff))
    # master OFF -> stock values exactly
    store = FakeStore(DeviceManagement=False)
    self.assertEqual(pm.bp_shutdown_time(store, pm.MAX_TIME_OFFROAD_S), pm.MAX_TIME_OFFROAD_S)
    self.assertEqual(pm.bp_voltage_cutoff(store, pm.VBATT_PAUSE_CHARGING), pm.VBATT_PAUSE_CHARGING)

  def test_hooks_can_only_make_protection_stricter(self):
    from openpilot.system.hardware import power_monitoring as pm
    store = FakeStore(DeviceManagement=True, DeviceShutdown=33, LowVoltageShutdown=11.0)
    self.assertLessEqual(pm.bp_shutdown_time(store, pm.MAX_TIME_OFFROAD_S), pm.MAX_TIME_OFFROAD_S)
    self.assertGreaterEqual(pm.bp_voltage_cutoff(store, pm.VBATT_PAUSE_CHARGING), pm.VBATT_PAUSE_CHARGING)

  def test_fresh_defaults_are_the_097_shipped_table_and_unset_reads_the_same(self):
    # t1035 (Bardo): Device/Screen defaults are the shipped 0.9.7 table values (shutdown 6 h, onroad timeout 30 s, ...),
    # no longer moved to stock at startup, and an unset key reads exactly like the table (no "table 1, page Off").
    # Saved user values are never rewritten; the hard safety bounds (low-voltage floor, 30 h ceiling) are unchanged.
    import tempfile
    from pathlib import Path
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS as P
    from openpilot.system.manager import bogpilot_startup as bs
    from openpilot.selfdrive.ui.bogpilot import phase3_device_controls as dc
    from openpilot.selfdrive.ui.bogpilot.phase3_device_controls_runtime import (
      shutdown_time, screen_timeout, screen_brightness, device_enabled, screen_enabled, voltage_cutoff)
    from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import DEFAULTS, RANGES, MemoryStore
    table = {"DeviceManagement": "1", "DeviceShutdown": "9", "LowVoltageShutdown": "11.8", "ScreenManagement": "1",
             "ScreenBrightness": "101", "ScreenBrightnessOnroad": "101", "ScreenTimeout": "30",
             "ScreenTimeoutOnroad": "30", "StandbyMode": "0"}
    for key, value in table.items():
      self.assertEqual(P[key][2], value, key)
    # the page's own defaults equal the table
    self.assertEqual((DEFAULTS["DeviceManagement"], DEFAULTS["ScreenManagement"], DEFAULTS["StandbyMode"]), (True, True, False))
    for key in ("DeviceShutdown", "ScreenBrightness", "ScreenBrightnessOnroad", "ScreenTimeout", "ScreenTimeoutOnroad"):
      self.assertEqual(str(DEFAULTS[key]), table[key], key)
    self.assertEqual(float(DEFAULTS["LowVoltageShutdown"]), 11.8)
    # an UNSET store reads like the table everywhere
    unset = MemoryStore()
    self.assertTrue(device_enabled(unset) and screen_enabled(unset))
    self.assertEqual(shutdown_time(unset, 30 * 3600.0), 6 * 3600.0)
    self.assertEqual((screen_timeout(unset, False, 30), screen_timeout(unset, True, 10)), (30, 30))
    self.assertEqual(screen_brightness(unset, True, 55.0), 55.0)   # 101 = Auto = the stock brightness
    self.assertEqual(voltage_cutoff(unset, 11.8), 11.8)
    # explicit master Off is still honoured (stock behaviour)
    off = MemoryStore({"DeviceManagement": "0", "ScreenManagement": "0", "DeviceShutdown": "9", "ScreenTimeoutOnroad": "30"})
    self.assertFalse(device_enabled(off) or screen_enabled(off))
    self.assertEqual(shutdown_time(off, 30 * 3600.0), 30 * 3600.0)
    self.assertEqual(screen_timeout(off, True, 10), 10)
    # hard safety bounds are unchanged
    self.assertEqual(RANGES["DeviceShutdown"], (0, 33, 1))
    self.assertEqual(RANGES["LowVoltageShutdown"], (11.8, 12.5, 0.1))
    self.assertEqual(voltage_cutoff(MemoryStore({"LowVoltageShutdown": "9.0"}), 11.8), 11.8)       # never below the floor
    self.assertEqual(shutdown_time(MemoryStore({"DeviceShutdown": "99"}), 30 * 3600.0), 30 * 3600.0)  # never past stock

    class Params(FakeStore):
      def put(self, k, v): self.d[k] = v

    with tempfile.TemporaryDirectory() as tmp:
      # startup no longer touches the device defaults; saved values stay exactly as saved
      saved = dict(DeviceShutdown="33", ScreenTimeoutOnroad="10", ScreenTimeout="15", LowVoltageShutdown="12.2")
      p = Params(**saved)
      res = bs.after_defaults(p, file_root=Path(tmp))
      self.assertFalse([e for e in res.events if e.startswith("device-stock")])
      self.assertEqual({k: p.d[k] for k in saved}, saved)
      self.assertFalse((Path(tmp) / "DeviceStockDefaults1").exists())
    # the Utilities reset / shipping table also lands on the table values
    from openpilot.system.bogpilot.toggle_reset import shipping_defaults
    from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import shipping_defaults as util_shipping
    for d in (shipping_defaults(), util_shipping()):
      self.assertEqual({k: d[k] for k in table}, table)

  def test_power_monitoring_fallback_when_helper_import_fails(self):
    import importlib
    import sys
    from unittest import mock
    name = "openpilot.system.hardware.power_monitoring"
    original = importlib.import_module(name)  # keep the real module object registered for other tests
    sys.modules.pop(name, None)
    try:
      with mock.patch.dict(sys.modules, {"openpilot.selfdrive.ui.bogpilot.phase3_device_controls_runtime": None}):
        pm = importlib.import_module(name)
        self.assertEqual(pm.bp_shutdown_time(None, 123.0), 123.0)
        self.assertEqual(pm.bp_voltage_cutoff(None, 11.8), 11.8)
    finally:
      sys.modules[name] = original


class TestUiStateAttentionGate(unittest.TestCase):
  def test_attention_noop_when_screen_master_off(self):
    src = open(os.path.join(os.path.dirname(__file__), "..", "ui_state.py")).read()
    i = src.index("def _bp_attention")
    j = src.index("def _update_wakefulness")
    body = src[i:j]
    self.assertIn("bp_screen_enabled(bp_device_store())", body)
    self.assertLess(body.index("bp_screen_enabled"), body.index("alertType"))


if __name__ == "__main__":
  unittest.main()
