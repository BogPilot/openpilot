"""w9 HUD composition contract: order, gating, stock fallback, lifecycle and geometry (synthetic, headless).

Everything here is mocked/synthetic: no pyray context, no cereal, no device. The real pyray render lives in the
separate VM script (render_hud_compose.py) and is reported separately."""
import ast
from dataclasses import dataclass, field
import importlib
import time
import unittest
from types import SimpleNamespace

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import ROOT, adapter_namespace, load

L = load("cluster_layout")
FULL, MID, SMALL = 3, 2, 1


class Rect:
  def __init__(self, x, y, width, height):
    self.x, self.y, self.width, self.height = x, y, width, height

  def t(self):
    return (round(self.x, 3), round(self.y, 3), round(self.width, 3), round(self.height, 3))


def overlaps(a, b):
  return a.x < b.x + b.width and b.x < a.x + a.width and a.y < b.y + b.height and b.y < a.y + a.height


def personality_rect(rhd, widget_w):   # redesign.personality_rect with style.py constants
  x = widget_w - 20 - 150 if rhd else 20
  return Rect(x, 900 - 75, 150, 150)


class Log:
  def __init__(self):
    self.errors = []

  def exception(self, msg):
    self.errors.append(msg)


class SM(dict):
  def __init__(self, frame=10):
    super().__init__()
    self.valid, self.alive, self.recv_frame, self.recv_time = {}, {}, {}, {}
    for name in ("selfdriveState", "driverMonitoringState", "carState", "radarState", "modelV2"):
      self.valid[name] = self.alive[name] = True
      self.recv_frame[name] = frame
    self["selfdriveState"] = SimpleNamespace(enabled=True, alertSize=0)
    self["driverMonitoringState"] = SimpleNamespace(isRHD=False)


def env(state, toggle_vals, log):
  class AlertRenderer:
    def _render(self, rect):
      self.calls.append("stock_alert_paint")
  ns = adapter_namespace("hud_compose", {
    "rl": SimpleNamespace(Rectangle=Rect), "log": SimpleNamespace(SelfdriveState=SimpleNamespace(AlertSize=SimpleNamespace(full=FULL))),
    "messaging": None, "SERVICE_LIST": {}, "cloudlog": log, "AlertRenderer": AlertRenderer,
    "R": SimpleNamespace(personality_rect=personality_rect, lkas_fault_border_color=lambda ms: ("lkas", ms)),
    "cluster_layout": lambda: L.layout_from_toggles(lambda k: toggle_vals.get(k, L.ClusterLayout().swap if k == "SwapSpeedGraph" else False)),
    "toggles": SimpleNamespace(get=lambda k: toggle_vals[k]), "PILL_LABEL_SPACE": 40, "CLUSTER_GAP": 6, "ui_state": state,
    "dataclass": dataclass, "field": field, "importlib": importlib, "time": time, "__name__": "hud_compose_synthetic",
  })
  return ns


class Calls(list):
  pass


class FakeModel:
  def __init__(self, calls, pending=True):
    self.calls, self.pending = calls, pending
    self.bp_defer_primary_lead = False
    self.bp_pending_primary = None
    self.defer_seen = None

  def render(self, rect):
    self.defer_seen = self.bp_defer_primary_lead
    self.calls.append("model")
    if self.pending and self.bp_defer_primary_lead:
      self.bp_pending_primary = "lead0"

  def bp_flush_primary_lead(self):
    self.calls.append("stock_lead0")
    self.bp_pending_primary = None


class Widget:
  def __init__(self, calls, name):
    self.calls, self.name = calls, name

  def render(self, rect):
    self.calls.append(self.name)


class FakeAlert(Widget):
  def __init__(self, calls, alert=None, raises=False):
    super().__init__(calls, "alert")
    self.alert, self.raises = alert, raises

  def get_alert(self, sm):
    return self.alert

  def _get_alert_rect(self, rect, size):
    return Rect(rect.x, rect.y, rect.width, rect.height) if size == FULL else Rect(rect.x, rect.y + rect.height - 271, rect.width, 271)

  def render(self, rect):
    if self.raises:
      raise RuntimeError("boom")
    super().render(rect)


class Layer:
  supports_compact = False

  def __init__(self, calls, name, replaces=(), enabled=True, draw=True, raises=None):
    self.calls, self.name, self.replaces = calls, name, frozenset(replaces)
    self.on, self.ret, self.raises = enabled, draw, raises
    self.resets, self.frames = 0, []
    self.bounds = Rect(206, 855, 150, 150) if name == "driver_monitor" else None

  def reset(self):
    self.resets += 1

  def update(self, frame):
    self.frames.append(frame)

  def enabled(self, frame):
    if self.raises == "enabled":
      raise RuntimeError("x")
    return self.on

  def draw(self, frame):
    if self.raises == "draw":
      raise RuntimeError("x")
    self.calls.append(self.name)
    return Rect(900, 500, 120, 100) if (self.name == "lead_lockon" and self.ret) else (None if self.ret else False)


class Base(unittest.TestCase):
  W, H = 2100, 1020   # C3X content rect (2160x1080 minus the 30 px border)

  def setUp(self):
    self.log = Log()
    self.calls = Calls()
    self.toggles = {"RedesignUI": True, "SwapSpeedGraph": True, "HideAccelGraph": False}
    self.state = SimpleNamespace(started_frame=10, sm=SM(), is_metric=False, has_longitudinal_control=True)
    self.ns = env(self.state, self.toggles, self.log)
    self.policy = SimpleNamespace(get=lambda: {"hide_lead_marker": False, "onroad_distance_button": True})
    self.traffic = SimpleNamespace(read=lambda now, start: False)
    self.rect = Rect(30, 30, self.W, self.H)

  def composer(self, layers=None, alert=None, model=None, rect=None):
    self.model = model or FakeModel(self.calls)
    self.alert = alert or FakeAlert(self.calls)
    self.alert.calls = self.calls
    self.dm = Widget(self.calls, "stock_dm")
    return self.ns["HudComposer"](self.model, Widget(self.calls, "hud"), self.alert, self.dm, layers=layers or {},
                                  policy=self.policy, traffic=self.traffic, clock=lambda: 100.0, state=self.state,
                                  toggle_get=lambda k: self.toggles[k])


class TestOrder(Base):
  def test_redesign_off_is_exact_stock(self):
    self.toggles["RedesignUI"] = False
    lead = Layer(self.calls, "lead_lockon", {"lead_chevron"})
    c = self.composer({"lead_lockon": lead})
    c.render(self.rect)
    self.assertEqual(list(self.calls), ["model", "hud", "alert", "stock_dm"])
    self.assertFalse(self.model.defer_seen)
    self.assertEqual(lead.frames, [])

  def test_redesign_no_peers_keeps_stock_elements_alert_last(self):
    c = self.composer()
    c.render(self.rect)
    self.assertEqual(list(self.calls), ["model", "hud", "stock_dm", "alert"])
    self.assertFalse(self.model.defer_seen)

  def test_full_stack_order(self):
    layers = {"lead_lockon": Layer(self.calls, "lead_lockon", {"lead_chevron"}),
              "lead_labels": Layer(self.calls, "lead_labels"),
              "driver_monitor": Layer(self.calls, "driver_monitor", {"driver_state"}, draw=True)}
    c = self.composer(layers)
    c.render(self.rect)
    # t920u: a driver_monitor relocation layer, even if supplied, is never used; the stock DM always paints
    self.assertEqual(list(self.calls), ["model", "lead_lockon", "hud", "lead_labels", "stock_dm", "alert"])
    self.assertFalse(c.frame.dm_relocated)
    self.assertTrue(self.model.defer_seen)
    self.assertNotIn("stock_lead0", self.calls)
    self.assertEqual(c.frame.lead_label_box.t(), (900, 500, 120, 100))
    self.assertEqual(self.calls[-1], "alert")

  def test_alert_last_in_every_mode(self):
    for redesign in (False, True):
      self.calls.clear()
      self.toggles["RedesignUI"] = redesign
      self.composer({"driver_monitor": Layer(self.calls, "driver_monitor", {"driver_state"})}).render(self.rect)
      self.assertEqual(self.calls[-1] if redesign else self.calls[-2], "alert")
      if not redesign:
        self.assertEqual(self.calls[-1], "stock_dm")   # stock order untouched when the redesign is off


class TestStockFallback(Base):
  def test_lock_not_painted_restores_stock_primary_chevron(self):
    for kw in ({"enabled": False}, {"draw": False}, {"raises": "draw"}, {"raises": "enabled"}):
      self.calls.clear()
      c = self.composer({"lead_lockon": Layer(self.calls, "lead_lockon", {"lead_chevron"}, **kw)})
      c.render(self.rect)
      self.assertIn("stock_lead0", self.calls, kw)
      self.assertLess(self.calls.index("stock_lead0"), self.calls.index("hud"))
      self.assertIsNone(c.frame.lead_label_box)

  def test_no_pending_stock_lead_no_flush(self):
    c = self.composer({"lead_lockon": Layer(self.calls, "lead_lockon", {"lead_chevron"}, enabled=False)},
                      model=FakeModel(self.calls, pending=False))
    c.render(self.rect)
    self.assertNotIn("stock_lead0", self.calls)

  def test_dm_failure_paints_stock_same_frame(self):
    for kw in ({"enabled": False}, {"draw": False}, {"raises": "draw"}, {"raises": "enabled"}):
      self.calls.clear()
      self.composer({"driver_monitor": Layer(self.calls, "driver_monitor", {"driver_state"}, **kw)}).render(self.rect)
      self.assertIn("stock_dm", self.calls, kw)
      self.assertEqual(self.calls[-1], "alert")

  def test_alert_failure_uses_stock_painter(self):
    c = self.composer(alert=FakeAlert(self.calls, raises=True))
    c.render(self.rect)
    self.assertEqual(self.calls[-1], "stock_alert_paint")
    self.assertIn("alert", c.disabled)
    self.assertTrue(self.log.errors)

  def test_failed_layer_off_until_next_drive_then_reset(self):
    lead = Layer(self.calls, "lead_lockon", {"lead_chevron"}, raises="draw")
    c = self.composer({"lead_lockon": lead})
    c.render(self.rect)
    self.assertIn("lead_lockon", c.disabled)
    lead.raises = None
    self.calls.clear()
    c.render(self.rect)
    self.assertNotIn("lead_lockon", self.calls)       # still off this drive
    self.state.started_frame = 99                      # new drive
    self.calls.clear()
    c.render(self.rect)
    self.assertIn("lead_lockon", self.calls)
    self.assertEqual(lead.resets, 2)                   # first frame + new drive
    self.assertEqual(c.drive_start, 100.0)


class TestGatingGeometry(Base):
  def test_c3x_reservations(self):
    c = self.composer()
    c.render(self.rect)
    f = c.frame
    self.assertAlmostEqual(f.scale, min(1, 2100 / 2160, 1020 / 1080))
    self.assertTrue(f.wide)
    self.assertEqual(f.stock_dm_rect.t(), (60, 828, 192, 192))       # stock corner DM, 0.11.2 geometry
    self.assertIn((30 + 2100 - 30 - 192, 60, 192, 192), [k.t() for k in f.keepouts])   # stock exp button
    s = f.scale
    # t920u: stock-corner DM always; the pill sits beside it on the driver side, CLUSTER_GAP away, never under it
    self.assertEqual(f.personality_rect.t(), Rect(60 + 192 + 6 * s, 30 + 825 * s, 150 * s, 150 * s).t())
    self.assertFalse(overlaps(f.stock_dm_rect, f.personality_rect))
    band = Rect(f.personality_rect.x, f.personality_rect.y - 40, f.personality_rect.width, f.personality_rect.height + 40)
    self.assertFalse(any(overlaps(k, band) for k in f.label_keepouts))
    self.assertIn(f.stock_dm_rect, f.label_keepouts)
    self.assertIn(f.stock_dm_rect, f.keepouts)
    # capsule/graph from ClusterLayout.keepouts mapped with the cluster's own scale
    for k in L.layout_from_toggles(lambda k: self.toggles.get(k, False)).keepouts():
      self.assertIn(Rect(30 + k[0] * s, 30 + k[1] * s, k[2] * s, k[3] * s).t(), [r.t() for r in f.keepouts])

  def test_stock_dm_never_relocated(self):
    dm = Layer(self.calls, "driver_monitor", {"driver_state"})
    c = self.composer({"driver_monitor": dm})
    c.render(self.rect)
    f = c.frame
    self.assertFalse(f.dm_relocated)
    self.assertEqual(dm.frames, [])                    # relocation layer not consulted at all
    self.assertIn("stock_dm", self.calls)
    self.assertNotIn("driver_monitor", self.calls)
    self.assertIn(f.stock_dm_rect, f.label_keepouts)
    self.assertNotIn("driver_monitor", [n for n, _ in self.ns["PEER_LAYERS"]])

  def test_rhd_mirrors(self):
    self.state.sm["driverMonitoringState"].isRHD = True
    c = self.composer()
    c.render(self.rect)
    f = c.frame
    self.assertEqual(f.stock_dm_rect.t(), (30 + 2100 - 126 - 96, 828, 192, 192))
    self.assertGreater(f.personality_rect.x, 30 + 2100 / 2)
    self.assertFalse(overlaps(f.stock_dm_rect, f.personality_rect))
    self.assertAlmostEqual(f.personality_rect.x + f.personality_rect.width, f.stock_dm_rect.x - 6 * f.scale)

  def test_stale_dm_state_not_used_for_rhd(self):
    self.state.sm["driverMonitoringState"].isRHD = True
    self.state.sm.recv_frame["driverMonitoringState"] = 5   # previous drive
    c = self.composer()
    c.render(self.rect)
    self.assertFalse(c.frame.rhd)

  def test_pill_gates(self):
    # (onroad_distance_button, traffic_mode) -> pill reserved?
    for odb, traffic, shown in ((True, False, True), (True, True, True), (False, False, False), (True, None, False)):
      self.policy = SimpleNamespace(get=lambda odb=odb: {"hide_lead_marker": False, "onroad_distance_button": odb})
      self.traffic = SimpleNamespace(read=lambda now, start, t=traffic: t)
      c = self.composer()
      c.render(self.rect)
      self.assertEqual(c.frame.personality_rect is not None, shown, (odb, traffic))
      self.assertEqual(c.frame.traffic_mode, traffic)
    self.state.has_longitudinal_control = False
    self.policy = SimpleNamespace(get=lambda: {"hide_lead_marker": True, "onroad_distance_button": True})
    c = self.composer()
    c.render(self.rect)
    self.assertIsNone(c.frame.personality_rect)
    self.assertFalse(c.frame.hide_lead_marker)

  def test_full_alert_reserves_everything_and_hides_pill(self):
    c = self.composer(alert=FakeAlert(self.calls, alert=SimpleNamespace(size=FULL)))
    c.render(self.rect)
    f = c.frame
    self.assertTrue(f.full_alert)
    self.assertIsNone(f.personality_rect)
    self.assertIn(self.rect.t(), [k.t() for k in f.keepouts])

  def test_banner_plan_rect_used_when_present(self):
    alert = FakeAlert(self.calls, alert=SimpleNamespace(size=MID))
    alert.current_plan = lambda rect: SimpleNamespace(mode="banner", rect=(248, 534, 1732, 245))
    c = self.composer(alert=alert)
    c.render(self.rect)
    self.assertIn((248, 534, 1732, 245), [k.t() for k in c.frame.keepouts])
    alert.current_plan = lambda rect: SimpleNamespace(mode="native", rect=(30, 30, 2100, 1020))
    c.render(self.rect)
    self.assertIn((30, 30 + 1020 - 271, 2100, 271), [k.t() for k in c.frame.keepouts])

  def test_compact_c4_has_no_redesign_layers(self):
    layers = {n: Layer(self.calls, n, r) for n, r in (("lead_lockon", {"lead_chevron"}), ("lead_labels", ()),
                                                       ("driver_monitor", {"driver_state"}))}
    c = self.composer(layers, rect=None)
    c.render(Rect(0, 0, 536, 240))
    self.assertFalse(c.frame.wide)
    self.assertIsNone(c.frame.personality_rect)        # no C3X pill reservation on the compact layout
    self.assertEqual(list(self.calls), ["model", "hud", "stock_dm", "alert"])
    self.assertAlmostEqual(c.frame.scale, min(536 / 2160, 240 / 1080))
    layers["lead_labels"].supports_compact = True     # explicit opt-in only
    self.calls.clear()
    c.render(Rect(0, 0, 536, 240))
    self.assertIn("lead_labels", self.calls)

  def test_frame_fields_native_only(self):
    c = self.composer()
    c.render(self.rect)
    f = c.frame
    self.assertIs(f.sm, self.state.sm)
    self.assertIs(f.model_renderer, self.model)
    self.assertTrue(f.engaged and f.longitudinal and f.lead_info)
    self.state.sm.recv_frame["selfdriveState"] = 3
    c.render(self.rect)
    self.assertFalse(c.frame.engaged)


class TestPolicy(unittest.TestCase):
  class Store:
    def __init__(self, level=3, **vals):
      self.level, self.vals = level, vals

    def tuning_level(self):
      return self.level

    def get_bool(self, k, default=None):
      return self.vals.get(k, default)

    def toggle_bool(self, k, level=None):
      if isinstance(self.vals.get(k), Exception):
        raise self.vals[k]
      return self.vals.get(k, False)

  def ns(self):
    return env(SimpleNamespace(), {}, Log())

  def test_367e1fe_formulas(self):
    P = self.ns()["PolicyToggles"]
    cases = [({"AdvancedCustomUI": True, "HideLeadMarker": True}, True, False),
             ({"AdvancedCustomUI": False, "HideLeadMarker": True}, False, False),
             ({"AdvancedCustomUI": True, "HideLeadMarker": True, "DebugMode": True}, False, True),
             ({"QOLVisuals": True, "OnroadDistanceButton": True}, False, True),
             ({"QOLVisuals": False, "OnroadDistanceButton": True}, False, False)]
    for vals, hide, odb in cases:
      v = P(self.Store(**vals), clock=lambda: 0.0).get()
      self.assertEqual((v["hide_lead_marker"], v["onroad_distance_button"]), (hide, odb), vals)

  def test_failure_closed(self):
    v = self.ns()["PolicyToggles"](self.Store(QOLVisuals=KeyError("x")), clock=lambda: 0.0).get()
    self.assertEqual(v, {"hide_lead_marker": True, "onroad_distance_button": False, "adjacent_leads": False})


class TestTrafficAndLoader(unittest.TestCase):
  def test_traffic_reader(self):
    ns = env(SimpleNamespace(), {}, Log())

    class TSM(dict):
      def __init__(self, t, ok=True):
        super().__init__(frogpilotCarState=SimpleNamespace(trafficModeEnabled=True))
        self.recv_time, self.valid, self.alive = {"frogpilotCarState": t}, {"frogpilotCarState": ok}, {"frogpilotCarState": ok}

      def update(self, timeout):
        pass
    R = ns["TrafficModeReader"]
    self.assertTrue(R(TSM(9.8)).read(10.0, 5.0))
    self.assertIsNone(R(TSM(9.0)).read(10.0, 5.0))        # stale
    self.assertIsNone(R(TSM(4.0)).read(4.1, 5.0))         # previous drive
    self.assertIsNone(R(TSM(9.9, ok=False)).read(10.0, 5.0))
    self.assertIsNone(ns["TrafficModeReader"]().read(10.0, 5.0))   # topic absent from SERVICE_LIST

  def test_missing_peers_are_not_errors(self):
    log = Log()
    ns = env(SimpleNamespace(), {}, log)

    def loader(name):
      if name.endswith("lead_lockon"):
        return SimpleNamespace(make_layer=lambda mici=False: None if mici else "LAYER")
      err = ModuleNotFoundError(name)
      err.name = name
      raise err
    layers, missing = ns["load_peer_layers"](loader)
    self.assertEqual(layers, {"lead_lockon": "LAYER"})
    self.assertEqual(missing, {"lead_labels": "module not present"})   # t920u: driver_monitor no longer a peer
    self.assertEqual(log.errors, [])
    self.assertEqual(ns["load_peer_layers"](loader, mici=True)[0], {})

  def test_alert_renderer_fallback(self):
    ns = env(SimpleNamespace(), {"RedesignUI": True}, Log())

    def missing(name):
      e = ModuleNotFoundError(name)
      e.name = name
      raise e
    self.assertIsInstance(ns["make_alert_renderer"](missing), ns["AlertRenderer"])

    class W4:
      def __init__(self, redesign_fn):
        self.redesign_fn = redesign_fn
    r = ns["make_alert_renderer"](lambda name: SimpleNamespace(BogPilotAlertRenderer=W4))
    self.assertTrue(r.redesign_fn())


class TestModelDeferral(unittest.TestCase):
  def test_primary_deferred_secondary_kept(self):
    drawn = []

    class Base:
      def __init__(self):
        self._lead_vehicles = [SimpleNamespace(glow=[1], chevron=[1], n=0), SimpleNamespace(glow=[2], chevron=[2], n=1)]

      def _draw_lead_indicator(self):
        drawn.extend(v.n for v in self._lead_vehicles if v.glow and v.chevron)
    ns = adapter_namespace("bogpilot_model", {"ModelRenderer": Base, "MiciModelRenderer": Base, "toggles": None,
                                              "FlameTracks": lambda: None, "FlameSideInput": None, "adjacent_leads": None,
                                              "blindspots": None, "BsmPolicy": lambda: None, "time": None,
                                              "ui_state": None, "draw_polygon": None, "np": None, "rl": None})
    m = ns["BogPilotModelRenderer"]()
    m._draw_lead_indicator()
    self.assertEqual(drawn, [0, 1])                    # default: stock, both markers
    drawn.clear()
    m.bp_defer_primary_lead = True
    m._draw_lead_indicator()
    self.assertEqual(drawn, [1])                       # leadTwo keeps its stock marker
    self.assertEqual(m.bp_pending_primary.n, 0)
    self.assertEqual(len(m._lead_vehicles), 2)
    m.bp_flush_primary_lead()
    self.assertEqual(drawn, [1, 0])
    self.assertIsNone(m.bp_pending_primary)
    m.bp_flush_primary_lead()
    self.assertEqual(drawn, [1, 0])                    # flush is one-shot


class TestCallSites(unittest.TestCase):
  def test_c3x_view_uses_composer_only(self):
    src = (ROOT.parents[1] / "onroad" / "augmented_road_view.py").read_text()
    tree = ast.parse(src)
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    self.assertIn("self._hud_compose.render", calls)
    for direct in ("self.alert_renderer.render", "self.driver_state_renderer.render", "self.model_renderer.render",
                   "self._hud_renderer.render"):
      self.assertNotIn(direct, calls)
    self.assertIn("make_alert_renderer", calls)

  def test_mici_untouched(self):
    src = (ROOT.parents[1] / "mici" / "onroad" / "augmented_road_view.py").read_text()
    self.assertNotIn("hud_compose", src)


if __name__ == "__main__":
  unittest.main()
