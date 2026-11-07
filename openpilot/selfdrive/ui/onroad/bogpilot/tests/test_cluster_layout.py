"""Stream 8 headless contract: stack order, HideAccelGraph keeps the lower capsule, CSC MAX slot fail-closed."""
import ast
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
  spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module   # dataclasses on Python < 3.10 resolve the module
  spec.loader.exec_module(module)
  return module


L = load("cluster_layout")


class TestLayout(unittest.TestCase):
  def test_defaults(self):
    self.assertTrue(L.DEFAULTS["SwapSpeedGraph"])
    self.assertFalse(L.DEFAULTS["HideAccelGraph"])
    d = L.ClusterLayout()
    self.assertTrue(d.swap and d.graph_visible and d.capsule_lower)

  def test_swap_on_graph_above_capsule_same_footprint(self):
    d = L.ClusterLayout(swap=True)
    x, y, w, h = d.graph_rect()
    self.assertEqual(y, L.SPEED_ROW_TOP)
    self.assertLess(y + h, d.capsule_top)
    self.assertEqual(d.capsule_top + L.SPEED_ROW_HEIGHT, L.STACK_BOTTOM)

  def test_swap_off_legacy(self):
    d = L.ClusterLayout(swap=False)
    self.assertEqual(d.capsule_top, L.SPEED_ROW_TOP)
    self.assertEqual(d.graph_rect()[1], L.GRAPH_TOP)
    self.assertFalse(d.redesign_swap)

  def test_hide_accel_keeps_lower_capsule(self):
    for swap in (True, False):
      d = L.ClusterLayout(swap=swap, hide_accel=True)
      self.assertFalse(d.graph_visible)
      self.assertIsNone(d.graph_rect())
      self.assertEqual(d.capsule_top, L.SWAP_SPEED_ROW_TOP)
      self.assertTrue(d.redesign_swap)
      self.assertEqual(d.keepouts(), [d.capsule_band()])

  def test_map_suppresses_graph_only(self):
    d = L.ClusterLayout(graph_suppressed=True)
    self.assertFalse(d.graph_visible)
    self.assertEqual(d.capsule_top, L.SWAP_SPEED_ROW_TOP)

  def test_metadata_minimal(self):
    for key in ("SwapSpeedGraph", "HideAccelGraph"):
      self.assertEqual(L.TOGGLE_METADATA[key]["tuning_level"], 0)
      self.assertEqual(L.TOGGLE_METADATA[key]["default"], L.DEFAULTS[key])


def plan(**kw):
  base = dict(cscTraining=False, cscControllingSpeed=True, cscSpeed=20.0, roadCurvature=-0.01,
              slcOverriddenSpeed=0.0, slcSpeedLimit=0.0, slcSpeedLimitOffset=0.0, speedLimitChanged=False)
  base.update(kw)
  return SimpleNamespace(**base)


class FakeSM:
  def __init__(self, msg=None, alive=True, valid=True, t=10.0):
    self.data = {} if msg is None else {"frogpilotPlan": msg}
    self.alive = {"frogpilotPlan": alive}
    self.valid = {"frogpilotPlan": valid}
    self.recv_time = {"frogpilotPlan": t}

  def __getitem__(self, k):
    return self.data[k]


class TestCsc(unittest.TestCase):
  ctx = L.CscContext(cruise_set=True, set_speed_display=65, display_conv=2.23694)

  def test_active_from_n(self):
    s = L.csc_status_from_plan(plan())
    slot = L.csc_slot(s, self.ctx)
    self.assertTrue(slot.active and slot.left)
    self.assertEqual((slot.speed, slot.from_speed), ("45", 65))
    f = L.csc_fields(slot)
    self.assertEqual(f["csc_label"], "from 65")
    self.assertTrue(f["csc_active"])

  def test_equal_hides_from(self):
    slot = L.csc_slot(L.csc_status_from_plan(plan(cscSpeed=40.0)), self.ctx)
    self.assertEqual((slot.speed, slot.from_speed), ("65", None))
    self.assertEqual(L.csc_fields(slot)["csc_label"], "")

  def test_override_and_slc(self):
    slot = L.csc_slot(L.csc_status_from_plan(plan(cscSpeed=15.0, slcOverriddenSpeed=24.5872)), self.ctx)
    self.assertEqual((slot.speed, slot.from_speed), ("34", 55))
    s = L.csc_status_from_plan(plan(cscSpeed=15.0, slcSpeedLimit=22.352, slcSpeedLimitOffset=2.2352))
    self.assertEqual(L.csc_slot(s, self.ctx).from_speed, 65)       # SLC ignored unless enabled
    ctx = L.CscContext(cruise_set=True, set_speed_display=65, slc_limits=True)
    self.assertEqual(L.csc_slot(s, ctx).from_speed, 55)

  def test_training(self):
    slot = L.csc_slot(L.csc_status_from_plan(plan(cscTraining=True)), self.ctx)
    self.assertTrue(slot.training and not slot.active and 0 <= slot.pulse <= 1)
    self.assertEqual(L.csc_fields(slot)["csc_label"], "training")

  def test_fail_closed(self):
    good = L.csc_status_from_plan(plan())
    self.assertFalse(L.csc_slot(L.INVALID_CSC, self.ctx).active)
    self.assertFalse(L.csc_status_from_plan(plan(cscSpeed=math.nan)).valid)
    self.assertFalse(L.csc_status_from_plan(SimpleNamespace(cscTraining=True)).valid)   # missing fields
    for ctx in (L.CscContext(cruise_set=False, set_speed_display=65), L.CscContext(redesign=False, cruise_set=True),
                L.CscContext(cruise_set=True, show_status=False), L.CscContext(cruise_set=True, map_open=True),
                L.CscContext(cruise_set=True, static_left_signal=True)):
      self.assertFalse(L.csc_slot(good, ctx).active)
    self.assertFalse(L.csc_slot(L.csc_status_from_plan(plan(speedLimitChanged=True)), self.ctx).active)
    self.assertFalse(L.csc_slot(L.csc_status_from_plan(plan(cscControllingSpeed=False)), self.ctx).active)

  def test_reader_freshness(self):
    self.assertFalse(L.read_csc_status(FakeSM(), 10.0, 0.0).valid)               # stock: no service
    self.assertTrue(L.read_csc_status(FakeSM(plan()), 10.2, 0.0).valid)
    self.assertFalse(L.read_csc_status(FakeSM(plan()), 11.0, 0.0).valid)         # stale > 0.5 s
    self.assertFalse(L.read_csc_status(FakeSM(plan()), 10.2, 10.1).valid)        # previous drive
    self.assertFalse(L.read_csc_status(FakeSM(plan(), valid=False), 10.2, 0.0).valid)
    self.assertFalse(L.read_csc_status(FakeSM(plan(), alive=False), 10.2, 0.0).valid)


def hud_env(calls, toggles):
  tree = ast.parse((ROOT / "bogpilot_hud.py").read_text())
  tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]

  class Base:
    set_speed, speed, is_cruise_set = 65, 62, True
    _can_draw_top_icons = True
    def _update_state(self):
      pass

  class Graph:
    def __init__(self, hz=20):
      self.samples = []
    def push(self, c, a):
      self.samples.append((c, a))
    def clear(self):
      self.samples.clear()
    def paint(self, r):
      calls.append(("graph", r))

  env = {
    "HudRenderer": Base, "MiciHudRenderer": Base, "L": L, "time": __import__("time"),
    "COLORS": SimpleNamespace(ENGAGED="green", DISENGAGED="grey"), "UIStatus": SimpleNamespace(ENGAGED="engaged"),
    "ui_state": SimpleNamespace(is_metric=False, status="engaged", started_frame=5, sm=None),
    "R": SimpleNamespace(SpeedRowInputs=lambda **kw: kw, paint_speed_row=lambda inp, ox, oy: calls.append(("row", inp)),
                         accel_graph_rect=lambda swap: ("graph_rect", swap)),
    "rl": SimpleNamespace(rl_push_matrix=lambda: None, rl_pop_matrix=lambda: None,
                          rl_translatef=lambda *a: None, rl_scalef=lambda *a: None),
    "toggles": SimpleNamespace(get=lambda k: toggles[k]), "AccelGraph": Graph,
    "messaging": None, "SERVICE_LIST": {},
  }
  from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import hud_stubs
  stubs = hud_stubs()
  env["rl"].Color = stubs.pop("rl").Color
  env.update(stubs)
  exec(compile(tree, "bogpilot_hud.py", "exec"), env)
  return env


class TestHudComposition(unittest.TestCase):
  def run_draw(self, swap, hide):
    calls = []
    env = hud_env(calls, {"RedesignUI": True, "SwapSpeedGraph": swap, "HideAccelGraph": hide})
    hud = env["BogPilotHudRenderer"]()
    env["draw_cluster"](hud, SimpleNamespace(x=0, y=0, width=2160, height=1080))
    return calls

  def test_default_paints_row_and_graph_on_top(self):
    calls = self.run_draw(True, False)
    self.assertTrue(calls[0][1]["swap"])
    self.assertEqual(calls[1], ("graph", ("graph_rect", True)))
    self.assertFalse(calls[0][1]["csc_active"])   # stock: no planner -> no CSC

  def test_hide_accel_keeps_lower_capsule(self):
    for swap in (True, False):
      calls = self.run_draw(swap, True)
      self.assertEqual(len(calls), 1)
      self.assertEqual(calls[0][0], "row")
      self.assertTrue(calls[0][1]["swap"])        # lower slot

  def test_graph_samples_rate_limited_and_fail_closed(self):
    calls = []
    env = hud_env(calls, {"RedesignUI": True, "SwapSpeedGraph": True, "HideAccelGraph": False})
    class SM(dict):
      pass
    sm = SM(carControl=SimpleNamespace(actuators=SimpleNamespace(accel=0.5)), carState=SimpleNamespace(aEgo=0.4))
    sm.recv_frame = {"carState": 6}
    sm.alive = {"carState": True, "carControl": True}
    sm.valid = {"carState": True, "carControl": True}
    env["ui_state"].sm = sm
    hud = env["BogPilotHudRenderer"]()
    hud._update_state()
    hud._update_state()                              # same 50 ms window: one sample
    self.assertEqual(hud.bp_graph.samples, [(0.5, 0.4)])
    sm.valid["carState"] = False
    hud._update_state()
    self.assertEqual(hud.bp_graph.samples, [])
    self.assertFalse(hud.bp_csc.valid)


class TestBoundaries(unittest.TestCase):
  def test_no_forbidden_imports(self):
    forbidden = ("csc" + "_straight", "csc" + "-straight", "planner", "upload_rate", "stream")
    for name in ("cluster_layout", "bogpilot_hud", "accel_graph"):
      src = (ROOT / f"{name}.py").read_text()
      self.assertNotIn("csc" + "_straight", src)
      self.assertNotIn("csc" + "-straight", src)
      for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
          mods = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
          for m in mods:
            for f in forbidden:
              self.assertNotIn(f, m)

  def test_cluster_layout_is_pure(self):
    tree = ast.parse((ROOT / "cluster_layout.py").read_text())
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    self.assertTrue(mods <= {"__future__", "dataclasses", "math"})


if __name__ == "__main__":
  unittest.main()
