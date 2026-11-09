from pathlib import Path
from opendbc.car import structs as car
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle_info import vehicle_info
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import supported
from openpilot.selfdrive.ui.layouts.settings.bogpilot import working_pages


def test_real_schema_vehicle_info_is_explicitly_unverified():
  cp = car.CarParams.new_message()
  assert vehicle_info(cp)["Vehicle Info"] in ("not detected", "Unavailable - non-vehicle / mock CarParams")  # t994 vehicle lane labels
  cp.carFingerprint = "TESLA_AP1_MODELS"
  cp.brand = "tesla_ap1"
  cp.dashcamOnly = False
  assert supported(cp)
  assert "UNVERIFIED" in vehicle_info(cp)["Vehicle Info"]  # t994 vehicle lane provenance label


def test_actual_factories_and_honest_restart_semantics():
  pages = working_pages()
  assert {page.key for page in pages["alerts_sounds"]} == {"volume", "alerts"}
  assert {page.key for page in pages["vehicle"]} == {"car_selection", "vehicle_controls", "stalk_controls", "vehicle_info"}
  assert {page.key for page in pages["system"]} == {"system_data", "system_device", "system_utilities"}
  assert all(callable(page.factory) and page.controls for group in pages.values() for page in group)
  assert "next sound service start" in (Path(__file__).parents[1] / "bogpilot/phase2_sounds.py").read_text()


def test_reverse_retains_real_stock_safety_alert_renderer_last():
  source = (Path(__file__).parents[1] / "layouts/main.py").read_text()
  camera = source.index("self._reverse_view.render(self._rect)")
  overlay = source.index("self._layouts[MainState.ONROAD].alert_renderer.render(self._rect)")
  assert camera < overlay < source.index("return", overlay)


def test_corrupt_volume_input_cannot_crash_sound_or_menu():
  from openpilot.selfdrive.ui.soundd import _bogpilot_int
  for text in ("inf", "-inf", "NaN", "not numeric", None):
    assert _bogpilot_int(text, 101) == 101


def test_native_leaf_factories_show_render_and_hide_without_writing_preferences():
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.common.params import Params
  from openpilot.selfdrive.ui.bogpilot.phase2_sounds import PARENT_KEY, VOLUME_KEYS
  from openpilot.common.bogpilot_store import ParamStore
  if not rl.is_window_ready():
    gui_app.init_window("BogPilot native leaf integration")
  store = ParamStore()
  keys = (PARENT_KEY, *VOLUME_KEYS, "GreenLightAlert", "LeadDepartingAlert", "DriverCamera", "AdjacentLeadsUI")
  before = {k: store.raw(k) for k in keys}
  assert Params().get_bool("IsOnroad") is False
  for group in working_pages().values():
    for page in group:
      widget = page.factory()
      widget.show_event()
      widget.render(rl.Rectangle(500, 0, 1660, 1080))
      widget.hide_event()
  after = {k: ParamStore().raw(k) for k in keys}
  assert before == after


def test_native_volume_click_store_actual_soundd_consumer(tmp_path, monkeypatch):
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.selfdrive.ui import soundd
  from openpilot.selfdrive.ui.bogpilot import phase2_sounds as volume
  from openpilot.selfdrive.ui.ui_state import ui_state
  if not rl.is_window_ready():
    gui_app.init_window("BogPilot volume click integration")
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  assert ui_state.is_offroad()
  widget = volume.create_volume_layout()
  widget.controller.action_item.toggle._callback(True)
  assert (tmp_path / "AlertVolumeControl").read_text() == "1"
  volume.set_volume("PromptVolume", 50)
  widget.volumes["PromptVolume"].action_item.callback(3)  # buttons: [Mute, -, label, +] (t994 soundsUI)
  assert volume.read_volume("PromptVolume") == 51
  assert volume.effective_gain("PromptVolume", .8) == .51
