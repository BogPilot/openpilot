"""Headless contract tests; no graphics context, cereal or generated params needed."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import numpy as np
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
  spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module   # dataclasses on Python < 3.10 resolve the module
  spec.loader.exec_module(module)
  return module


class TestDefaults(unittest.TestCase):
  def test_default_on_and_explicit_off(self):
    module = load("file_toggles")
    with tempfile.TemporaryDirectory() as folder:
      now = [0.0]
      values = module.FileToggles(folder, lambda: now[0], lambda _: None)
      for key, default in module.DEFAULTS.items():
        self.assertEqual(values.get(key), default)
        (Path(folder) / key).write_text("1" if not default else "0")
      # Keep filesystem work rate limited, then pick up the user's explicit choices.
      self.assertTrue(values.get("RedesignUI"))
      now[0] = 3
      for key, default in module.DEFAULTS.items():
        self.assertEqual(values.get(key), not default)
      self.assertFalse(module.DEFAULTS["HideAccelGraph"])

  def test_registered_setting_wins_over_fallback(self):
    module = load("file_toggles")
    with tempfile.TemporaryDirectory() as folder:
      (Path(folder) / "BlindSpotPath").write_text("1")
      values = module.FileToggles(folder, read_param=lambda key: False if key == "BlindSpotPath" else None)
      self.assertFalse(values.get("BlindSpotPath"))
      self.assertTrue(values.get("RedesignUI"))

  def test_no_writes(self):
    module = load("file_toggles")
    with tempfile.TemporaryDirectory() as folder:
      values = module.FileToggles(folder, read_param=lambda _: None)
      values.get("RedesignUI")
      self.assertEqual(list(Path(folder).iterdir()), [])


class _FreshTimes(dict):
  """recv_time defaults to 'just received' (time.monotonic()); tests set explicit stale ages."""
  def __missing__(self, key):
    import time
    return time.monotonic()


class TestRadarContract(unittest.TestCase):
  def setUp(self):
    self.module = load("bsm_state")
    self.sm = FakeSM()

  def test_stock_missing_topic_is_safe(self):
    self.assertEqual(self.module.adjacent_leads(self.sm, 10), [(False, 0.0)] * 2)

  def test_valid_and_fresh_only(self):
    self.sm.add()
    self.assertEqual(self.module.adjacent_leads(self.sm, 10), [(True, 40.0), (False, 20.0)])
    self.sm.valid["frogpilotRadarState"] = False
    self.assertEqual(self.module.adjacent_leads(self.sm, 10), [(False, 0.0)] * 2)

  def test_previous_drive_and_dead_topic_rejected(self):
    self.sm.add()
    self.sm.recv_frame["frogpilotRadarState"] = 10
    self.assertEqual(self.module.adjacent_leads(self.sm, 10), [(False, 0.0)] * 2)
    self.sm.recv_frame["frogpilotRadarState"] = 11
    self.sm.alive["radarState"] = False
    self.assertEqual(self.module.adjacent_leads(self.sm, 10), [(False, 0.0)] * 2)

  def test_stale_topic_rejected(self):
    import time
    self.sm.add()
    self.sm.recv_time["frogpilotRadarState"] = time.monotonic() - 0.6
    self.assertEqual(self.module.adjacent_leads(self.sm, 10), [(False, 0.0)] * 2)
    self.sm.recv_time["frogpilotRadarState"] = time.monotonic() - 0.3
    self.assertEqual(self.module.adjacent_leads(self.sm, 10), [(True, 40.0), (False, 20.0)])

  def test_nonfinite_speed_never_triggers(self):
    self.sm.add()
    self.sm["frogpilotRadarState"].leadLeft.vLead = float("inf")
    self.assertEqual(self.module.adjacent_leads(self.sm, 10)[0], (False, 0.0))


class FakeSM(dict):
  def __init__(self):
    super().__init__()
    self.valid, self.alive, self.recv_frame = {}, {}, {}
    self.recv_time = _FreshTimes()

  def add(self):
    for name in ("radarState", "frogpilotRadarState"):
      self.valid[name], self.alive[name], self.recv_frame[name] = True, True, 11
    self["frogpilotRadarState"] = SimpleNamespace(leadLeft=SimpleNamespace(status=True, vLead=40),
                                                 leadRight=SimpleNamespace(status=False, vLead=20))


class TestIntegrationSurface(unittest.TestCase):
  def test_both_hardware_paths_hooked(self):
    ui = ROOT.parents[1]
    for path, suffix in (("onroad", ""), ("mici/onroad", "Mici")):
      tree = ast.parse((ui / path / "augmented_road_view.py").read_text())
      factories = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
      self.assertIn(f"BogPilot{suffix}HudRenderer", factories)
      self.assertIn(f"BogPilot{suffix}ModelRenderer", factories)

  def test_excluded_features_not_imported(self):
    for path in ROOT.glob("*.py"):
      tree = ast.parse(path.read_text())
      for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
          self.assertNotIn("upload_rate", node.module or "")
          self.assertNotIn("stream", node.module or "")


def hud_stubs():
  """Names bogpilot_hud.py imports for the t913u features (arc, pedals, LIMIT tile, record button), headless."""
  class _Widget:
    is_pressed = False
    def __init__(self, *a, **k):
      pass
  return {"SL": load("speed_limit_display"), "ARC": load("steering_arc"), "PED": load("pedals"), "math": __import__("math"),
          "UI_CONFIG": SimpleNamespace(button_size=192, wheel_icon_size=144), "ExpButton": _Widget, "Widget": _Widget,
          "cloudlog": SimpleNamespace(exception=lambda *a: None), "REC_CX": 95, "REC_CY": 696, "REC_HIT": 174,
          "rl": SimpleNamespace(Color=lambda *c: c)}


def adapter_namespace(name, env):
  tree = ast.parse((ROOT / f"{name}.py").read_text())
  tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
  exec(compile(tree, str(ROOT / f"{name}.py"), "exec"), env)
  return env


class TestHudAdapter(unittest.TestCase):
  def setUp(self):
    self.calls = []
    self.enabled = True
    self.swap = True
    self.state = SimpleNamespace(is_metric=False, status="engaged")
    calls = self.calls

    class Base:
      set_speed, speed, is_cruise_set = 100, 35, True
      _can_draw_top_icons = True
      def _draw_set_speed(self, rect):
        calls.append("stock-set")
      def _draw_current_speed(self, rect):
        calls.append("stock-current")
      def _render(self, rect):
        calls.append("stock-hud")
        self._draw_set_speed(rect)

    self.env = adapter_namespace("bogpilot_hud", {
      "HudRenderer": Base, "MiciHudRenderer": Base,
      "COLORS": SimpleNamespace(ENGAGED="green", DISENGAGED="grey"),
      "UIStatus": SimpleNamespace(ENGAGED="engaged"), "ui_state": self.state,
      "R": SimpleNamespace(SpeedRowInputs=lambda **kw: kw),
      "toggles": SimpleNamespace(get=lambda key: self.swap if key == "SwapSpeedGraph" else
                                 (False if key == "HideAccelGraph" else self.enabled)),
      "L": load("cluster_layout"), "time": __import__("time"),
      "AccelGraph": lambda hz=20: SimpleNamespace(paint=lambda r: calls.append("graph"), clear=lambda: None),
      "messaging": None, "SERVICE_LIST": {}, **hud_stubs(),
    })
    self.env["draw_cluster"] = lambda hud, rect, mici=False: calls.append(("cluster", mici))

  def test_redesign_preserves_stock_off_path(self):
    hud = self.env["BogPilotHudRenderer"]()
    hud._draw_set_speed(None)
    hud._draw_current_speed(None)
    self.assertEqual(self.calls, [("cluster", False)])
    self.calls.clear()
    self.enabled = False
    hud._draw_set_speed(None)
    hud._draw_current_speed(None)
    self.assertEqual(self.calls, ["stock-set", "stock-current"])

  def test_c4_keeps_stock_warnings_and_alert_occlusion(self):
    hud = self.env["BogPilotMiciHudRenderer"]()
    hud._render(None)
    self.assertEqual(self.calls, ["stock-hud", ("cluster", True)])
    self.calls.clear()
    hud._can_draw_top_icons = False
    hud._render(None)
    self.assertEqual(self.calls, ["stock-hud"])
    self.enabled = False
    self.calls.clear()
    hud._render(None)
    self.assertEqual(self.calls, ["stock-hud", "stock-set"])

  def test_units_and_swap_contract(self):
    hud = self.env["BogPilotHudRenderer"]()
    f = self.env["speed_row_inputs"]
    self.assertEqual(f(hud)["set_speed"], "100")
    self.assertEqual(f(hud, mici=True)["set_speed"], "62")
    self.assertTrue(f(hud)["swap"])
    self.state.is_metric = True
    self.assertEqual(f(hud, mici=True)["set_speed"], "100")
    self.assertEqual(f(hud)["unit"], "km/h")
    hud.is_cruise_set = False
    self.assertEqual(f(hud)["set_speed"], "–")


class TestModelAdapter(unittest.TestCase):
  def setUp(self):
    self.draws, self.calls = [], []
    self.sm = FakeSM()
    self.sm.add()
    for name in ("carState", "modelV2", "extrinsicsCalibration"):
      self.sm.valid[name], self.sm.alive[name], self.sm.recv_frame[name] = True, True, 11
    self.sm["carState"] = SimpleNamespace(leftBlindspot=True, rightBlindspot=False)
    calls = self.calls

    class Base:
      def __init__(self):
        self._rect = SimpleNamespace(x=70, y=30)
        x = np.array([0, 10, 20], dtype=np.float32)
        self._lane_lines = [SimpleNamespace(raw_points=np.column_stack((x, np.full(3, y), x * 0)))
                            for y in (-5.4, -1.8, 1.8, 5.4)]
      def _draw_lane_lines(self):
        calls.append("stock-lanes")
      def _get_path_length_idx(self, x, distance):
        return len(x) - 1
      def _map_line_to_polygon(self, *args):
        return np.array([[0, 0], [0, 10], [10, 10], [10, 0]], dtype=np.float32)

    class Flames:
      def __init__(self):
        self.trigger = SimpleNamespace(update=lambda *args: calls.append("reset"))
        self.inputs = []
      def update_and_paint(self, inputs, lanes):
        self.inputs = inputs

    logic = load("bsm_state")
    self.env = adapter_namespace("bogpilot_model", {
      "ModelRenderer": Base, "MiciModelRenderer": Base, "FlameTracks": Flames,
      "FlameSideInput": lambda *args: args, "np": np,
      "rl": SimpleNamespace(Color=lambda *args: args),
      "toggles": SimpleNamespace(get=lambda _: True),
      "ui_state": SimpleNamespace(sm=self.sm, started_frame=10),
      "adjacent_leads": logic.adjacent_leads, "blindspots": logic.blindspots, "time": __import__("time"),
      "BsmPolicy": lambda: SimpleNamespace(enabled=lambda b: b),
      "draw_polygon": lambda *args: self.draws.append(args),
    })

  def test_both_models_keep_stock_lanes_and_red_side(self):
    for name in ("BogPilotModelRenderer", "BogPilotMiciModelRenderer"):
      model = self.env[name]()
      model._draw_lane_lines()
      self.assertEqual(self.calls[-1], "stock-lanes")
      self.assertEqual(self.draws[-1][-1], (255, 0, 0, 110))
      self.assertEqual(model._flames.inputs, [(True, True, 40), (False, False, 20)])

  def test_mici_projection_is_offset_once(self):
    model = self.env["BogPilotMiciModelRenderer"]()
    model._draw_lane_lines()
    np.testing.assert_array_equal(self.draws[-1][1][0], [70, 30])
    model = self.env["BogPilotModelRenderer"]()
    model._draw_lane_lines()
    np.testing.assert_array_equal(self.draws[-1][1][0], [0, 0])

  def test_stale_model_and_missing_adjacent_radar_fail_closed(self):
    model = self.env["BogPilotModelRenderer"]()
    self.sm.valid["modelV2"] = False
    model._draw_lane_lines()
    self.assertEqual(self.draws, [])
    self.assertIn("reset", self.calls)
    self.sm.valid["modelV2"] = True
    self.sm.valid["frogpilotRadarState"] = False
    model._draw_lane_lines()
    self.assertEqual(model._flames.inputs, [(True, False, 0), (False, False, 0)])


if __name__ == "__main__":
  unittest.main()
