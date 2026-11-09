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

  def test_fresh_defaults_equal_stock_power_behaviour(self):
    # t994 INT: fresh-install Device Controls = STOCK (30 h shutdown, 30 s offroad / 10 s onroad screen timeout, stock
    # voltage cutoff). The compiled libparams defaults (9 -> 6 h, onroad 30) are moved to stock once at manager
    # startup; masters stay ON so the user-adjustable ranges work, and user-changed values are preserved.
    import tempfile
    from pathlib import Path
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS as P
    from openpilot.system.manager import bogpilot_startup as bs
    from openpilot.selfdrive.ui.bogpilot.phase3_device_controls_runtime import shutdown_time, screen_timeout, voltage_cutoff
    from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import DEFAULTS, RANGES
    self.assertEqual((P["DeviceManagement"][2], P["ScreenManagement"][2]), ("1", "1"))
    self.assertEqual((DEFAULTS["DeviceShutdown"], DEFAULTS["ScreenTimeout"], DEFAULTS["ScreenTimeoutOnroad"]), (33, 30, 10))
    self.assertEqual(RANGES["DeviceShutdown"][1], 33)  # user range still reaches the 30 h stock ceiling

    class Params(FakeStore):
      def put(self, k, v): self.d[k] = v

    with tempfile.TemporaryDirectory() as tmp:
      # fresh install: compiled defaults present
      p = Params(DeviceManagement=True, ScreenManagement=True, DeviceShutdown=P["DeviceShutdown"][2],
                 ScreenTimeout=P["ScreenTimeout"][2], ScreenTimeoutOnroad=P["ScreenTimeoutOnroad"][2],
                 LowVoltageShutdown=P["LowVoltageShutdown"][2])
      res = bs.after_defaults(p, file_root=Path(tmp))
      self.assertIn("device-stock:2", res.events)
      self.assertEqual((p.d["DeviceShutdown"], p.d["ScreenTimeoutOnroad"]), ("33", "10"))
      self.assertEqual(shutdown_time(p, 30 * 3600.0), 30 * 3600.0)
      self.assertEqual(screen_timeout(p, False, 30), 30)
      self.assertEqual(screen_timeout(p, True, 10), 10)
      self.assertEqual(voltage_cutoff(p, 11.8), 11.8)
      # idempotent; later user choice (stricter than stock) takes effect and is never rewritten
      p.d["DeviceShutdown"] = "9"
      bs.after_defaults(p, file_root=Path(tmp))
      self.assertEqual(p.d["DeviceShutdown"], "9")
      self.assertEqual(shutdown_time(p, 30 * 3600.0), 6 * 3600.0)
    with tempfile.TemporaryDirectory() as tmp:
      # saved non-default choices survive the one-shot
      p = Params(DeviceShutdown="12", ScreenTimeoutOnroad="45")
      bs.after_defaults(p, file_root=Path(tmp))
      self.assertEqual((p.d["DeviceShutdown"], p.d["ScreenTimeoutOnroad"]), ("12", "45"))
    # defaults reset / shipping table also lands on stock
    from openpilot.system.bogpilot.toggle_reset import shipping_defaults, reset_defaults
    from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import shipping_defaults as util_shipping
    sd = shipping_defaults()
    self.assertEqual((sd["DeviceShutdown"], sd["ScreenTimeoutOnroad"], sd["ScreenTimeout"]), ("33", "10", "30"))
    ud = util_shipping()
    self.assertEqual((ud["DeviceShutdown"], ud["ScreenTimeoutOnroad"]), ("33", "10"))
    rd = reset_defaults()
    self.assertEqual((rd["DeviceShutdown"], rd["ScreenTimeoutOnroad"]), ("33", "10"))

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
