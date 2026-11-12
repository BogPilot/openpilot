"""Contract tests for hidden-stock / leftover-widget CPU skips."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]  # bogpilot/
UI = Path(__file__).resolve().parents[3]    # selfdrive/ui


class TestHiddenStockSkips(unittest.TestCase):
  def test_exp_button_render_is_gated_on_enabled(self):
    tree = ast.parse((UI / "onroad/hud_renderer.py").read_text())
    render = None
    for node in tree.body:
      if isinstance(node, ast.ClassDef) and node.name == "HudRenderer":
        render = next((n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "_render"), None)
    self.assertIsNotNone(render)
    gated = False
    for n in ast.walk(render):
      if isinstance(n, ast.If):
        test = ast.unparse(n.test)
        if "_exp_button.enabled" in test:
          body = ast.unparse(n)
          self.assertIn("_exp_button.render", body)
          gated = True
    self.assertTrue(gated, "HudRenderer._render must skip _exp_button.render unless the button is enabled")
    # The Experimental Mode tap stays on ArcTapButton, which overrides enabled to True.
    src = (ROOT / "bogpilot_hud.py").read_text()
    self.assertIn("class ArcTapButton(ExpButton)", src)
    self.assertIn("return True", src[src.index("class ArcTapButton"):src.index("class ArcTapButton") + 800])

  def test_lead_lockon_composer_does_not_double_update(self):
    src = (ROOT / "hud_compose.py").read_text()
    self.assertNotIn("lead.update, f)", src)
    self.assertIn("lead.enabled, f)", src)
    # enabled() itself still updates so standalone tests and the composer both work once.
    lock = (ROOT / "lead_lockon.py").read_text()
    self.assertIn("def enabled(self, frame):", lock)
    enabled = lock[lock.index("def enabled(self, frame):"):lock.index("def enabled(self, frame):") + 250]
    self.assertIn("self.update(frame)", enabled)

  def test_graph_push_gated_on_visible(self):
    src = (ROOT / "bogpilot_hud.py").read_text()
    self.assertIn("if cluster_layout().graph_visible:", src)
    i = src.index("if cluster_layout().graph_visible:")
    self.assertIn("self.bp_graph.push", src[i:i + 400])

  def test_traffic_reader_prefers_shared_ui_state_sm(self):
    src = (ROOT / "hud_compose.py").read_text()
    self.assertIn('self.NAME in getattr(ui_sm, "data", {})', src)
    self.assertIn('if self._sm is not getattr(ui_state, "sm", None):', src)

  def test_bsm_maps_only_when_needed(self):
    src = (ROOT / "bogpilot_model.py").read_text()
    self.assertIn("need_lanes = any(flags)", src)
    self.assertIn("if need_lanes:", src)
    self.assertIn("_map_line_to_polygon", src)

  def test_ui_state_shares_plan_services(self):
    src = (UI / "ui_state.py").read_text()
    self.assertIn('"bogpilotPlan"', src)
    self.assertIn('"bogpilotCarState"', src)
    self.assertIn("SERVICE_LIST", src)

  def test_cem_param_store_is_not_10hz(self):
    src = (ROOT / "bogpilot_hud.py").read_text()
    self.assertIn("ParamStore(cache_ttl=2.0)", src)
    self.assertNotIn("ParamStore(cache_ttl=.1)", src)
