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
    # reset_section_item binds _confirm_dialog at construction; auto-yes so a later section-reset tap writes.
    from unittest.mock import patch
    from openpilot.selfdrive.ui.bogpilot import gated_actions
    confirm_patch = patch.object(gated_actions, "_confirm_dialog", lambda text, yes: yes())
    confirm_patch.start()
    self.addCleanup(confirm_patch.stop)
    layout = make_layout(lambda: box["cp"], store, lambda: box["offroad"])
    nav = build_layout({"driving": [Page(PAGE_KEY, PAGE_TITLE, lambda: layout, ACTIVE_CONTROLS)]})
    rect = rl.Rectangle(500, 0, 1660, 1080)

    def render():
      rl.begin_drawing()
      try:
        nav.render(rect)
      finally:
        rl.end_drawing()

    def click_step(item, side):
      # The value row is [-] [value] [+]: tap the real button through the gated action's own hit test.
      from openpilot.system.ui.widgets.list_view import BUTTON_HEIGHT, RIGHT_ITEM_PADDING
      a = item.action_item
      i = 0 if side == "left" else len(a.buttons) - 1
      x = a._rect.x + i * (a.button_width + RIGHT_ITEM_PADDING) + a.button_width / 2
      y = a._rect.y + (a._rect.height - BUTTON_HEIGHT) / 2 + BUTTON_HEIGHT / 2
      a._handle_mouse_release(rl.Vector2(x, y))

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
    self.assertFalse(ratio.action_item.highlighted)
    self.assertTrue(ratio.action_item.hint_text.endswith("15.00"))
    click_step(ratio, "right")
    self.assertAlmostEqual(store.get_float("SteerRatio"), 15.01)
    self.assertTrue(ratio.action_item.highlighted)
    render()
    layout.advanced_reset.callback()
    self.assertIsNone(store.raw("SteerRatio"))
    self.assertFalse(store.get_bool("AdvancedLateralTune"))  # the whole section: its switch back to the shipped default
    box["offroad"] = False
    render()
    click_step(ratio, "right")
    self.assertIsNone(store.raw("SteerRatio"))  # onroad: widget callback cannot write
    for _ in range(2):
      nav.hide_event()
      nav.show_event()
      render()
    nav.hide_event()


if __name__ == "__main__":
  unittest.main()
