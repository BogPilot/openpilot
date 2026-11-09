"""Real native raylib render of Driving Controls > Steering Tuning (no fake ListItem/Scroller).

Drives the real widget callbacks (toggle / +/- / reset buttons) into the real ParamStore and renders every state.
Requires RAYLIB_BACKEND=headless (authorized native headless render); a store backed by a temp dir, never /data.
"""
import os
import tempfile
import unittest


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestSteeringTuningNativeRender(unittest.TestCase):
  def test_render_click_store_every_state(self):
    os.environ["BOGPILOT_PARAMS_DIR"] = tempfile.mkdtemp(prefix="steer-render-")
    if not os.path.exists("/sys/firmware/devicetree/base/model"):
      # Linux dev VM without a comma devicetree: only the device-type probe is faked, nothing else.
      import openpilot.common.hardware.comma.hardware as comma_hw
      comma_hw.get_device_type = lambda: "pc"
    import pyray as rl
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import Page, build_layout
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import ACTIVE_CONTROLS, PAGE_KEY, PAGE_TITLE, make_layout
    from openpilot.system.ui.lib.application import gui_app
    from opendbc.car.tesla_ap1.values import CAR
    from opendbc.car.tesla_ap1.interface import CarInterface

    class MemoryParams:
      def __init__(self): self.data = {}
      def all_keys(self): return []
      def get(self, key): return self.data.get(key)
      def put(self, key, value): self.data[key] = str(value)
      def remove(self, key): self.data.pop(key, None)
    store = ParamStore(MemoryParams())  # file-backed under BOGPILOT_PARAMS_DIR (all_keys empty)
    box = {"cp": None, "offroad": True}
    gui_app.init_window("Steering Tuning real native render")
    layout = make_layout(lambda: box["cp"], store, lambda: box["offroad"])
    nav = build_layout({"driving": [Page(PAGE_KEY, PAGE_TITLE, lambda: layout, ACTIVE_CONTROLS)]})
    rect = rl.Rectangle(500, 0, 1660, 1080)

    def render():
      rl.begin_drawing()
      try:
        nav.render(rect)
      finally:
        rl.end_drawing()

    def click_dual(item, side):
      button = item.action_item.left_button if side == "left" else item.action_item.right_button
      button._click_callback()

    nav.show_event()
    render()
    nav.navigation.open("driving")
    render()
    nav.navigation.open(PAGE_KEY)
    render()
    # no persisted car: Advanced rows hidden/disabled, QOL works
    adv = layout.toggles["AdvancedLateralTune"]
    self.assertFalse(adv.is_visible)
    self.assertTrue(layout.toggles["QOLLateral"].is_visible)
    layout.toggles["QOLLateral"].action_item.toggle._callback(True)
    self.assertTrue(store.get_bool("QOLLateral"))
    box["cp"] = CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS)
    layout.show_event()
    render()
    self.assertTrue(adv.is_visible)
    self.assertFalse(layout.toggles["ForceAutoTune"].is_visible)
    adv.action_item.toggle._callback(True)
    self.assertTrue(store.get_bool("AdvancedLateralTune"))
    items = layout.scroller._items
    ratio = next(i for i in items if getattr(i, "title", "") == "Steer Ratio")
    ratio_buttons = items[items.index(ratio) + 1]
    click_dual(ratio_buttons, "right")
    self.assertAlmostEqual(store.get_float("SteerRatio"), 15.01)
    render()
    reset = items[items.index(ratio) + 2]
    reset.callback()
    self.assertIsNone(store.raw("SteerRatio"))
    box["offroad"] = False
    render()
    click_dual(ratio_buttons, "right")
    self.assertIsNone(store.raw("SteerRatio"))  # onroad: widget callback cannot write
    for _ in range(2):
      nav.hide_event()
      nav.show_event()
      render()
    nav.hide_event()


if __name__ == "__main__":
  unittest.main()
