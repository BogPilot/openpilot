"""Parent / child rows: the shared helper (bogpilot/nesting.py) and the pages that use it."""
import os
import shutil
import tempfile
import unittest

from openpilot.selfdrive.ui.tests.test_bogpilot_developer_rows import RowParams, native_window


class Item:
  """A stand-in row: the helper only needs is_visible, set_visible, indent and a switch."""

  def __init__(self, on=False, visible=True):
    self._is_visible = visible
    self.indent = 0
    self.action_item = type("A", (), {"get_state": lambda s: self.on})()
    self.on = on

  @property
  def is_visible(self):
    return self._is_visible() if callable(self._is_visible) else self._is_visible

  def set_visible(self, v):
    self._is_visible = v


class TestHelper(unittest.TestCase):
  def test_child_follows_the_parent_switch_and_indents(self):
    from openpilot.selfdrive.ui.bogpilot.nesting import INDENT, nest
    parent, child = Item(on=False), Item()
    nest(parent, child)
    self.assertFalse(child.is_visible)
    parent.on = True
    self.assertTrue(child.is_visible)
    self.assertEqual(child.indent, INDENT)

  def test_a_gate_the_child_already_had_still_applies(self):
    from openpilot.selfdrive.ui.bogpilot.nesting import nest
    flag = {"car": False}
    parent, child = Item(on=True), Item(visible=lambda: flag["car"])
    nest(parent, child)
    self.assertFalse(child.is_visible)
    flag["car"] = True
    self.assertTrue(child.is_visible)
    parent.on = False
    self.assertFalse(child.is_visible)

  def test_a_grandchild_is_hidden_when_its_parent_is_hidden_even_if_that_parent_is_on(self):
    from openpilot.selfdrive.ui.bogpilot.nesting import INDENT, nest
    top, mid, leaf = Item(on=False), Item(on=True), Item()
    nest(top, mid)
    nest(mid, leaf)
    self.assertFalse(leaf.is_visible)
    top.on = True
    self.assertTrue(leaf.is_visible)
    self.assertEqual(leaf.indent, 2 * INDENT)

  def test_place_orders_the_tree_and_refuses_a_row_twice(self):
    from openpilot.selfdrive.ui.bogpilot.nesting import place
    rows = {k: Item(on=True) for k in "abcd"}
    tree = (("a", (("b", ()),)), ("c", ()))
    self.assertEqual(place(rows, tree), [rows["a"], rows["b"], rows["c"]])   # d is not in the tree; the page appends it
    with self.assertRaises(ValueError):
      place(rows, (("a", ()), ("a", ())))

  def test_a_missing_parent_lets_the_children_nest_under_the_grandparent(self):
    from openpilot.selfdrive.ui.bogpilot.nesting import place
    rows = {"a": Item(on=False), "c": Item()}
    place(rows, (("a", (("b", (("c", ()),)),)),))
    self.assertFalse(rows["c"].is_visible)
    rows["a"].on = True
    self.assertTrue(rows["c"].is_visible)


class TestAppearancePage(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    native_window("nesting")

  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore
    self.tmp = tempfile.mkdtemp(prefix="nesting_")
    self._env = os.environ.get("BOGPILOT_PARAMS_DIR")
    os.environ["BOGPILOT_PARAMS_DIR"] = self.tmp
    self.addCleanup(shutil.rmtree, self.tmp, True)
    self.typed = {}
    self.store = ParamStore(params=RowParams(self.typed), cache_ttl=0)
    self.make()

  def tearDown(self):
    if self._env is None:
      os.environ.pop("BOGPILOT_PARAMS_DIR", None)
    else:
      os.environ["BOGPILOT_PARAMS_DIR"] = self._env

  def make(self, keys=None):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    self.layout = BogPilotVisualsLayout(store=self.store, keys=keys)

  def shown(self, key):
    return self.layout._toggles[key].is_visible

  def test_every_row_is_on_the_page_exactly_once(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import VISUAL_KEYS
    items = self.layout._scroller._items
    self.assertEqual(len(items), len({id(i) for i in items}))
    side = 1 if self.layout._side is not None else 0   # the Confidence Ball Side (Left / Right) row is not a toggle
    camera = 1 if self.layout._camera is not None else 0   # nor is Camera View (Auto / Standard / Wide)
    self.assertEqual(len(items), len(VISUAL_KEYS) + len(self.layout._pickers) + side + camera)
    self.assertEqual(set(self.layout._toggles), set(VISUAL_KEYS))

  def test_the_screen_recorder_button_is_not_on_appearance(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import VISUAL_KEYS
    self.assertNotIn("ScreenRecorder", VISUAL_KEYS)

  def test_children_are_offered_only_while_the_parent_is_on(self):
    for parent, children in (("QOLVisuals", ("DriverCamera", "OnroadDistanceButton")),
                             ("CustomUI", ("BlindSpotPath", "PedalsOnUI")),
                             ("BorderMetrics", ("BlindSpotMetrics",)),
                             ("NavigationUI", ("ShowSpeedLimits",))):
      for state in (True, False, True):
        self.layout._toggles[parent].action_item.set_state(state)
        for child in children:
          self.assertEqual(self.shown(child) and self.layout._toggles[child].indent > 0, self.shown(parent) and state, (parent, child, state))

  def test_camera_view_row_hides_with_quality_of_life_visuals(self):
    cam = self.layout._camera
    self.assertIsNotNone(cam)
    for state in (True, False, True):
      self.layout._toggles["QOLVisuals"].action_item.set_state(state)
      self.assertEqual(cam.is_visible and cam.indent > 0, self.shown("QOLVisuals") and state, state)

  def test_pedals_dynamic_needs_both_levels(self):
    t = self.layout._toggles
    t["CustomUI"].action_item.set_state(True)
    t["PedalsOnUI"].action_item.set_state(False)
    self.assertFalse(t["DynamicPedalsOnUI"].is_visible)
    t["PedalsOnUI"].action_item.set_state(True)
    self.assertTrue(t["DynamicPedalsOnUI"].is_visible)
    t["CustomUI"].action_item.set_state(False)     # the grandparent hides the leaf although PedalsOnUI is still on
    self.assertFalse(t["DynamicPedalsOnUI"].is_visible)
    self.assertGreater(t["DynamicPedalsOnUI"].indent, t["PedalsOnUI"].indent)

  def test_turning_a_parent_off_never_writes_its_children(self):
    self.layout._toggles["QOLVisuals"].action_item.set_state(False)
    self.layout._write("QOLVisuals", False)
    self.assertNotIn("DriverCamera", self.typed)
    self.layout._toggles["DriverCamera"].action_item.set_state(True)
    self.layout._write("DriverCamera", True)
    saved = dict(self.typed)
    self.layout._write("QOLVisuals", False)
    self.layout._write("QOLVisuals", True)
    self.assertEqual(self.typed.get("DriverCamera"), saved["DriverCamera"])   # still saved, comes back with the parent

  def test_developer_sidebar_pickers_follow_their_parent(self):
    self.layout._toggles["DeveloperSidebar"].action_item.set_state(False)
    self.assertTrue(all(not p.is_visible for p in self.layout._pickers.values()))
    self.layout._toggles["DeveloperSidebar"].action_item.set_state(True)
    self.assertEqual(len(self.layout._pickers), 7)
    self.assertTrue(all(p.is_visible for p in self.layout._pickers.values()))

  def test_peers_without_a_live_parent_are_not_nested(self):
    for key in ("BSMFlameTracks", "AdjacentLeadsUI", "LowerSpeedLimitsBox", "ShowAccelGraph", "DeveloperHUD", "FPSCounter", "ShowIP"):
      self.assertEqual(self.layout._toggles[key].indent, 0, key)

  def test_navigation_page_has_the_widgets_parent_and_the_limits_child(self):
    self.make(keys=("NavigationUI", "ShowSpeedLimits"))
    items = self.layout._scroller._items
    self.assertEqual([i for i in items], [self.layout._toggles["NavigationUI"], self.layout._toggles["ShowSpeedLimits"]])
    self.layout._toggles["NavigationUI"].action_item.set_state(False)
    self.assertFalse(self.shown("ShowSpeedLimits"))


class TestDeviceControlsPage(unittest.TestCase):
  def titles(self, layout):
    return [(i.title, i.is_visible) for i in layout._scroller._items]

  def test_screen_recorder_button_is_under_screen_settings_and_follows_its_master(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import (
      DeviceControlsMenu, MemoryStore, DEVICE_KEYS, BOOL_KEYS, DEFAULTS)
    self.assertIn("ScreenRecorder", DEVICE_KEYS)
    self.assertIn("ScreenRecorder", BOOL_KEYS)
    self.assertTrue(DEFAULTS["ScreenRecorder"])
    menu = DeviceControlsMenu(store=MemoryStore(), offroad=lambda: True, capable=lambda: True)
    menu.go("Screen Settings")
    row = next(r for r in menu.rows() if r.get("key") == "ScreenRecorder")
    self.assertEqual((row["title"], row["value"], row["requires"]), ("Screen Recorder Button", True, "ScreenManagement"))
    self.assertTrue(menu.set("ScreenRecorder", False))
    self.assertEqual(menu.store.raw("ScreenRecorder"), "0")
    self.assertFalse(next(r for r in menu.rows() if r.get("key") == "ScreenRecorder")["value"])
    self.assertIn("ScreenRecorder", menu.active_keys())

  def test_device_and_screen_children_hide_with_their_master(self):
    from openpilot.selfdrive.ui.bogpilot import phase3_device_controls as D
    native_window("device nesting")
    from openpilot.selfdrive.ui.ui_state import ui_state
    store = D.MemoryStore()
    layout = D.create_device_controls_layout(store=store, runtime_hooks=True)
    layout.go("Screen Settings")
    items = layout._scroller._items
    master = items[0]
    self.assertEqual(master.title, "Screen Settings")
    kids = [i for i in items[1:] if i.title not in ("Screen Recorder", "Status")]
    self.assertIn("Screen Recorder Button", [i.title for i in kids])
    master.action_item.set_state(True)
    self.assertTrue(all(i.is_visible for i in kids))
    master.action_item.set_state(False)
    self.assertTrue(all(not i.is_visible for i in kids))
    # Start / Stop Recording do not depend on the master, and the saved children are untouched
    self.assertTrue(all(i.is_visible for i in items if i.title == "Screen Recorder"))
    self.assertEqual(store.writes, [])
    layout.go("Device Settings")
    items = layout._scroller._items
    items[0].action_item.set_state(False)
    self.assertTrue(all(not i.is_visible for i in items[1:] if i.title in ("Device Shutdown Timer", "Low-Voltage Cutoff")))
    items[0].action_item.set_state(True)
    self.assertTrue(all(i.is_visible for i in items[1:] if i.title in ("Device Shutdown Timer", "Low-Voltage Cutoff")))


class TestOtherPages(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    native_window("nesting pages")

  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore
    self.tmp = tempfile.mkdtemp(prefix="nesting_pages_")
    self._env = os.environ.get("BOGPILOT_PARAMS_DIR")
    os.environ["BOGPILOT_PARAMS_DIR"] = self.tmp
    self.addCleanup(shutil.rmtree, self.tmp, True)
    self.typed = {}
    self.store = ParamStore(params=RowParams(self.typed), cache_ttl=0)

  def tearDown(self):
    if self._env is None:
      os.environ.pop("BOGPILOT_PARAMS_DIR", None)
    else:
      os.environ["BOGPILOT_PARAMS_DIR"] = self._env

  def test_volume_rows_are_indented_under_the_controller_and_hide_with_it(self):
    from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
    from openpilot.selfdrive.ui.bogpilot.phase2_sounds import create_volume_layout
    layout = create_volume_layout()
    self.assertTrue(layout.volumes)
    for row in layout.volumes.values():
      self.assertEqual(row.indent, INDENT)
    self.assertEqual(layout.controller.indent, 0)

  def test_lane_changes_follow_the_design_order_and_indent(self):
    from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
    from openpilot.selfdrive.ui.bogpilot import phase3_lanechange as LC
    self.assertEqual([k for k, _ in LC.TREE[0][1]], ["NudgelessLaneChange", "MinimumLaneChangeSpeed", "OneLaneChange"])
    layout = LC.LaneChangeLayout(self.store, runtime_integrated=True, offroad=lambda: True)
    titles = []
    for i in layout.scroller._items:
      name = i.title.split(" (")[0]
      if name == "Reset section to defaults":   # a section reset sits right after the value rows it resets
        name += " (width)" if titles and titles[-1][0] == "Minimum Lane Width" else " (speed)"
      titles.append((name, i.indent))
    names = [t for t, _ in titles]
    # whichever rows this tuning level offers keep the design order, parent before child
    order = ["Lane Changes", "Automatic Lane Changes", "Lane Change Delay", "Minimum Lane Width", "Reset section to defaults (width)",
             "Minimum Lane Change Speed", "Reset section to defaults (speed)", "One Lane Change Per Signal"]
    self.assertEqual(names, [n for n in order if n in names])
    for name, indent in titles:
      self.assertEqual(indent, {"Lane Changes": 0, "Automatic Lane Changes": INDENT, "Lane Change Delay": 2 * INDENT,
                                "Minimum Lane Width": 2 * INDENT,
                                "Reset section to defaults (width)": 2 * INDENT}.get(name, INDENT), name)

  def test_steering_children_are_indented_under_their_switch(self):
    from opendbc.car.tesla_ap1.interface import CarInterface
    from opendbc.car.tesla_ap1.values import CAR
    from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import make_layout
    cp = CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS)
    layout = make_layout(cp, self.store, lambda: True)
    t = layout.toggles
    self.assertEqual((t["AdvancedLateralTune"].indent, t["QOLLateral"].indent), (0, 0))
    by_title = {i.title: i for i in layout.scroller._items}
    self.assertEqual(by_title["Actuator Delay"].indent, INDENT)
    self.assertEqual(by_title["Pause Steering Below"].indent, INDENT)
    self.assertEqual(by_title["Override Sensitivity"].indent, 0)


if __name__ == "__main__":
  unittest.main()
