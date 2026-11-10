"""t994 visualsTheme: catalog + UI -> store -> consumer proofs (headless)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


def _stub_raylib_ui():
  """op-test-py312 has no pyray; stub enough for BogPilotVisualsLayout import."""
  import sys
  import types
  # INT t994: never pollute sys.modules when the real raylib UI stack imports (native env).
  try:
    import pyray  # noqa: F401
    import openpilot.system.ui.widgets.list_view  # noqa: F401
    import openpilot.system.ui.widgets.scroller_tici  # noqa: F401
    return
  except Exception:
    pass
  if "pyray" not in sys.modules:
    rl = types.ModuleType("pyray")
    class _C:  # noqa: N801
      pass
    rl.Color = _C
    rl.Rectangle = _C
    rl.Vector2 = _C
    rl.WHITE = _C()
    rl.BLACK = _C()
    sys.modules["pyray"] = rl
  # lightweight stand-ins for Widget / toggle_item / Scroller / multilang
  for name, attrs in {
    "openpilot.system.ui.widgets": {"Widget": type("Widget", (), {"__init__": lambda self, *a, **k: None, "show_event": lambda self: None})},
  }.items():
    if name not in sys.modules:
      m = types.ModuleType(name)
      for k, v in attrs.items():
        setattr(m, k, v)
      sys.modules[name] = m
  if "openpilot.system.ui.widgets.list_view" not in sys.modules:
    m = types.ModuleType("openpilot.system.ui.widgets.list_view")
    class FakeToggle:
      def __init__(self):
        self._state = False
        self.toggle = self
        self._callback = None
      def set_state(self, s): self._state = bool(s)
      def get_state(self): return self._state
    class FakeItem:
      def __init__(self, state=False):
        self.action_item = FakeToggle()
        self.action_item.set_state(state)
    def toggle_item(title, desc, state, callback=None):
      it = FakeItem(state)
      it.action_item._callback = callback
      it.action_item.toggle = it.action_item
      return it
    m.toggle_item = toggle_item
    sys.modules[name := "openpilot.system.ui.widgets.list_view"] = m
  if "openpilot.system.ui.widgets.scroller_tici" not in sys.modules:
    m = types.ModuleType("openpilot.system.ui.widgets.scroller_tici")
    class Scroller:
      def __init__(self, items, **k): self.items = items
      def show_event(self): pass
      def render(self, rect): pass
    m.Scroller = Scroller
    sys.modules["openpilot.system.ui.widgets.scroller_tici"] = m
  if "openpilot.system.ui.lib.multilang" not in sys.modules:
    m = types.ModuleType("openpilot.system.ui.lib.multilang")
    m.tr = lambda s: s
    m.tr_noop = lambda s: s
    sys.modules["openpilot.system.ui.lib.multilang"] = m
  # package parents
  for pkg in ("openpilot.system", "openpilot.system.ui", "openpilot.system.ui.widgets",
              "openpilot.system.ui.lib"):
    if pkg not in sys.modules:
      sys.modules[pkg] = types.ModuleType(pkg)

_stub_raylib_ui()



TYPED_KEYS = [
  "AdjacentLeadsUI", "BlindSpotPath", "BlindSpotMetrics", "OnroadDistanceButton", "PedalsOnUI",
  "ScreenRecorder", "DriverCamera", "QOLVisuals", "CustomUI", "BorderMetrics", "DynamicPedalsOnUI",
  "Fahrenheit", "NumericalTemp", "ShowCPU", "ShowMemoryUsage", "NavigationUI", "ShowSpeedLimits",
  "StaticPedalsOnUI", "TuningLevel", "TuningLevelConfirmed",
]


class FakeParams:
  def __init__(self, typed=None):
    self.typed = typed if typed is not None else {}

  def get(self, k):
    return self.typed.get(k)

  def put(self, k, v):
    self.typed[k] = v

  def put_bool(self, k, v):
    self.typed[k] = "1" if v else "0"

  def get_bool(self, k):
    v = self.typed.get(k)
    if v is None:
      return None
    if isinstance(v, bool):
      return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")

  def all_keys(self):
    return [k.encode() if isinstance(k, str) else k for k in TYPED_KEYS]

  def check_key(self, k):
    if k not in TYPED_KEYS:
      raise KeyError(k)


class TestCatalog(unittest.TestCase):
  def test_21_audit_keys_partitioned(self):
    from openpilot.selfdrive.ui.bogpilot.phase2_visuals_theme import (
      AUDIT_KEYS, NEW_VISUAL_KEYS, OMITTED_KEYS, decision_table,
    )
    self.assertEqual(len(AUDIT_KEYS), 21)
    self.assertEqual(len(NEW_VISUAL_KEYS) + len(OMITTED_KEYS), 21)
    self.assertEqual(set(AUDIT_KEYS), set(NEW_VISUAL_KEYS) | set(OMITTED_KEYS))
    self.assertEqual(len(NEW_VISUAL_KEYS), 11)
    self.assertEqual(len(OMITTED_KEYS), 10)
    table = decision_table()
    self.assertEqual(sum(1 for r in table if r["decision"] == "IMPLEMENT"), 11)
    self.assertEqual(sum(1 for r in table if r["decision"] == "OMIT"), 10)

  def test_visuals_menu_includes_new_and_existing(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import VISUAL_KEYS, EXISTING_VISUAL_KEYS
    from openpilot.selfdrive.ui.bogpilot.phase2_visuals_theme import NEW_VISUAL_KEYS
    self.assertEqual(EXISTING_VISUAL_KEYS, (
      "AdjacentLeadsUI", "BlindSpotPath", "BlindSpotMetrics", "OnroadDistanceButton",
      "PedalsOnUI", "ScreenRecorder", "DriverCamera",
    ))
    for k in EXISTING_VISUAL_KEYS:
      self.assertIn(k, VISUAL_KEYS)
    for k in NEW_VISUAL_KEYS:
      self.assertIn(k, VISUAL_KEYS)
    # t1025: plus "Bog to the Future" (BSMFlameTracks), the one row with no entry in the theme audit
    self.assertEqual(len(VISUAL_KEYS), len(EXISTING_VISUAL_KEYS) + len(NEW_VISUAL_KEYS) + 1)
    self.assertIn("BSMFlameTracks", VISUAL_KEYS)


class TestSidebarPolicy(unittest.TestCase):
  def test_defaults_and_gates(self):
    from openpilot.selfdrive.ui.bogpilot.phase2_visuals_theme import (
      sidebar_metric_policy, select_sidebar_metrics,
    )
    store = FakeParams({})
    # empty typed -> defaults via get_bool None path in sidebar_metric_policy uses defaults
    # FakeParams.get_bool returns None for missing — sidebar_metric_policy treats Exception/default
    p = sidebar_metric_policy(SimpleNamespace(get_bool=lambda k, d=False: d))
    self.assertTrue(p.show_cpu)
    self.assertTrue(p.show_memory)
    self.assertTrue(p.numerical_temp)
    self.assertFalse(p.fahrenheit)

    p2 = sidebar_metric_policy(SimpleNamespace(get_bool=lambda k, d=False: {
      "ShowCPU": False, "ShowMemoryUsage": False, "NumericalTemp": False, "Fahrenheit": True,
    }.get(k, d)))
    self.assertFalse(p2.show_cpu)
    self.assertFalse(p2.show_memory)
    self.assertFalse(p2.numerical_temp)
    self.assertTrue(p2.fahrenheit)

    off_t, on_t, cpu, ram, panda = "OFFTEMP", "ONTEMP", "CPU", "RAM", "PANDA"
    offroad = select_sidebar_metrics(
      started=False, policy=p2, offroad_temp=off_t, onroad_temp_status=on_t, cpu=cpu, ram=ram, panda=panda)
    self.assertEqual(offroad, [on_t])  # numerical off -> status label; cpu/ram gated off

    onroad = select_sidebar_metrics(
      started=True, policy=p2, offroad_temp=off_t, onroad_temp_status=on_t, cpu=cpu, ram=ram, panda=panda)
    self.assertEqual(onroad, [on_t, panda])

  def test_metric_visibility_from_params(self):
    from openpilot.selfdrive.ui.bogpilot.sidebar_metrics import metric_visibility_from_params
    params = FakeParams({})
    self.assertEqual(metric_visibility_from_params(params), (True, True, True, False))
    params.typed.update({"ShowCPU": "0", "ShowMemoryUsage": "0", "NumericalTemp": "0", "Fahrenheit": "1"})
    self.assertEqual(metric_visibility_from_params(params), (False, False, False, True))


class TestUIStoreConsumer(unittest.TestCase):
  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore
    self.tmp = tempfile.mkdtemp(prefix="vis_theme_")
    self.typed = {}
    self._env = os.environ.get("BOGPILOT_PARAMS_DIR")
    os.environ["BOGPILOT_PARAMS_DIR"] = self.tmp
    params = FakeParams(self.typed)
    self.store = ParamStore(params=params, cache_ttl=0)

  def tearDown(self):
    if self._env is None:
      os.environ.pop("BOGPILOT_PARAMS_DIR", None)
    else:
      os.environ["BOGPILOT_PARAMS_DIR"] = self._env

  def make(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    return BogPilotVisualsLayout(store=self.store)

  def test_click_writes_typed_and_file_keys(self):
    from openpilot.selfdrive.ui.bogpilot.phase2_visuals_theme import NEW_VISUAL_KEYS, FILE_ONLY_VISUAL_KEYS
    lay = self.make()
    for k in NEW_VISUAL_KEYS:
      lay._write(k, False)
      if k in FILE_ONLY_VISUAL_KEYS:
        self.assertNotIn(k, self.typed)
        self.assertTrue((Path(self.tmp) / k).exists(), k)
        self.assertEqual((Path(self.tmp) / k).read_text().strip(), "0")
      else:
        self.assertEqual(self.typed.get(k), "0", k)
      lay._write(k, True)
      if k in FILE_ONLY_VISUAL_KEYS:
        self.assertEqual((Path(self.tmp) / k).read_text().strip(), "1")
      else:
        self.assertEqual(self.typed.get(k), "1", k)

  def test_qol_custom_border_dynamic_consumers(self):
    from openpilot.selfdrive.ui.bogpilot.phase2_visuals_theme import consumer_snapshot
    lay = self.make()
    # seed children ON so parents are the gate
    for k in ("DriverCamera", "OnroadDistanceButton", "PedalsOnUI", "BlindSpotMetrics", "ShowSpeedLimits"):
      self.typed[k] = "1"
    lay._write("QOLVisuals", True)
    lay._write("CustomUI", True)
    lay._write("BorderMetrics", True)
    lay._write("DynamicPedalsOnUI", True)
    lay._write("NavigationUI", True)
    lay._write("ShowSpeedLimits", True)
    snap = consumer_snapshot(self.store, longitudinal=True, has_bsm=True)
    self.assertTrue(snap["QOLVisuals_reverse"])
    self.assertTrue(snap["QOLVisuals_personality"])
    self.assertTrue(snap["CustomUI_pedals"])
    self.assertTrue(snap["DynamicPedalsOnUI"])
    self.assertTrue(snap["BorderMetrics"])
    self.assertTrue(snap["ShowSpeedLimits"])

    lay._write("QOLVisuals", False)
    lay._write("CustomUI", False)
    lay._write("BorderMetrics", False)
    lay._write("DynamicPedalsOnUI", False)
    lay._write("NavigationUI", False)
    snap = consumer_snapshot(self.store, longitudinal=True, has_bsm=True)
    self.assertFalse(snap["QOLVisuals_reverse"])
    self.assertFalse(snap["QOLVisuals_personality"])
    self.assertFalse(snap["CustomUI_pedals"])
    self.assertFalse(snap["DynamicPedalsOnUI"])
    self.assertFalse(snap["BorderMetrics"])
    self.assertFalse(snap["ShowSpeedLimits"])

  def test_swap_speed_graph_file_consumer(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.cluster_layout import layout_from_toggles
    from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import FileToggles
    lay = self.make()
    lay._write("SwapSpeedGraph", False)
    # read_param=None stub avoids importing Params/zmq in op-test-py312
    ft = FileToggles(path=self.tmp, clock=lambda: 0.0, read_param=lambda k: None)
    self.assertFalse(ft.get("SwapSpeedGraph"))
    self.assertFalse(layout_from_toggles(ft.get).swap)
    lay._write("SwapSpeedGraph", True)
    ft2 = FileToggles(path=self.tmp, clock=lambda: 0.0, read_param=lambda k: None)
    self.assertTrue(ft2.get("SwapSpeedGraph"))
    self.assertTrue(layout_from_toggles(ft2.get).swap)

  def test_sidebar_prefs_consumers(self):
    from openpilot.selfdrive.ui.bogpilot.sidebar_metrics import device_readings, metric_visibility_from_params
    lay = self.make()
    lay._write("Fahrenheit", True)
    lay._write("ShowCPU", False)
    lay._write("ShowMemoryUsage", False)
    lay._write("NumericalTemp", False)
    # Params-like object for sidebar helper reads typed dict via FakeParams underneath store
    vis = metric_visibility_from_params(self.store._params)
    self.assertEqual(vis, (False, False, False, True))
    device = SimpleNamespace(
      maxTempC=54, cpuUsagePercent=[25], memoryUsagePercent=41,
      thermalStatus=SimpleNamespace(raw=0),
    )
    temp, cpu, ram = device_readings(device, fresh=True, fahrenheit=vis[3])
    self.assertEqual(temp.value, "129°F")
    self.assertEqual(cpu.value, "25%")
    self.assertEqual(ram.value, "41%")

  def test_preserved_on_choice_not_overwritten_by_defaults(self):
    """Fresh layout must not rewrite an already-stored OFF for a shipping-default-ON key."""
    self.typed["QOLVisuals"] = "0"
    self.typed["ShowCPU"] = "0"
    lay = self.make()
    self.assertFalse(lay._read("QOLVisuals"))
    self.assertFalse(lay._read("ShowCPU"))
    self.assertEqual(self.typed["QOLVisuals"], "0")
    self.assertEqual(self.typed["ShowCPU"], "0")


class TestBsmBorderStillGated(unittest.TestCase):
  def test_border_metrics_parent_required(self):
    """Mirror hud_compose._bsm_border_enabled formula without importing pyray."""
    def enabled(store):
      level = store.tuning_level()
      return bool((store.toggle_bool("BorderMetrics", level) and store.toggle_bool("BlindSpotMetrics", level))
                  or store.get_bool("DebugMode", False))

    class Store:
      def __init__(self, d):
        self.d = d
      def tuning_level(self):
        return 3
      def toggle_bool(self, k, level=None):
        return bool(self.d.get(k, False))
      def get_bool(self, k, default=False):
        return bool(self.d.get(k, default))

    self.assertTrue(enabled(Store({"BorderMetrics": True, "BlindSpotMetrics": True})))
    self.assertFalse(enabled(Store({"BorderMetrics": False, "BlindSpotMetrics": True})))
    self.assertFalse(enabled(Store({"BorderMetrics": True, "BlindSpotMetrics": False})))
    self.assertTrue(enabled(Store({"BorderMetrics": False, "BlindSpotMetrics": False, "DebugMode": True})))


if __name__ == "__main__":
  unittest.main()
