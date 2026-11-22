"""FrogPilot 0.9.7 onroad toggle parity (bogpilot/onroad_policy.py). Pure Python, temp file stores only, no raylib.

Covers each class (onroad-editable, reboot-prompt, parked, locked), the parked-download rule, the reboot prompt and
Reboot Now, the Disable Longitudinal staging, the Alert Volume floors (unchanged) and the live path to soundd, and
that every per-page lock site now goes through the policy.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from openpilot.selfdrive.ui.bogpilot import onroad_policy as op

UI = Path(__file__).resolve().parents[1]


class Drive:
  def __init__(self, started=False, parked=False, engaged=False):
    self.started, self.parked, self.engaged = started, parked, engaged

  def state(self):
    return op.DriveState(lambda: self.started, lambda: self.parked, lambda: self.engaged)


@pytest.fixture
def drive(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  d = Drive()
  op.set_state(d.state())
  shown = []
  op.set_prompt_ui(shown.append)
  op.new_visit()
  d.shown = shown
  yield d
  op.set_state(None)
  op.set_prompt_ui(None)
  op.register_applier("DisableOpenpilotLongitudinal", None)
  op.new_visit()


# ---- the table ------------------------------------------------------------------------------------------------------
EXPECTED = {
  "volume": op.ONROAD, "alerts": op.ONROAD, "navigation_widgets": op.ONROAD, "maps": op.ONROAD, "appearance": op.ONROAD,
  "system_data": op.ONROAD, "system_device": op.ONROAD, "system_utilities": op.ONROAD, "vehicle_info": op.ONROAD,
  "steering_tuning": op.REBOOT, "lane_changes": op.REBOOT, "driving_model": op.REBOOT,
  "car_selection": op.REBOOT, "vehicle_controls": op.REBOOT, "stalk_controls": op.REBOOT,
  "gas_brake": op.ONROAD, "tesla_tuning": op.LOCKED,
}


def test_every_menu_page_has_its_chosen_class():
  from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
  pages = {pg.key for s in menu_sections() for p in s.pills for pg in p.pages}
  assert pages == set(op.PAGE_CLASS) == set(EXPECTED)        # no page falls through to the fail-closed default
  for key, cls in EXPECTED.items():
    assert op.page_class(key) == cls, key
  assert op.page_class("no_such_page") == op.LOCKED
  assert op.row_class("tuning_level") == op.REBOOT


def test_rows_stricter_than_their_page():
  for row in ("data:delete", "data:rename", "data:restore", "data:stats_reset",
              "BogPilotDefaultsReset", "DoToggleResetStock", "ClearCaches"):
    assert op.row_class(row, "system_data") == op.LOCKED, row
  for row in ("PedalCalibrate", "TeslaRadarReadVin", "downloads"):
    assert op.row_class(row, "vehicle_controls") == op.PARKED, row
  for row in ("maps:remove", "maps:repair"):
    assert op.row_class(row, "maps") == op.PARKED, row
  assert op.row_class("maps:download", "maps") == op.ONROAD     # map downloads run while driving; models keep Park
  for row in ("ScreenBrightnessOnroad", "ScreenTimeoutOnroad", "StandbyMode", "ScreenManagement", "DebugMode",
              "LocalDebugReport", "data:backup", "data:export", "data:storage_use"):
    assert op.row_class(row, "system_device") == op.ONROAD, row


@pytest.mark.parametrize("cls,offroad,driving,parked", [
  (op.ONROAD, True, True, True),
  (op.REBOOT, True, True, True),
  (op.PARKED, True, False, True),
  (op.LOCKED, True, False, False),
])
def test_each_class_offroad_driving_parked(cls, offroad, driving, parked):
  assert op.allowed(cls, started=False) is offroad
  assert op.allowed(cls, started=True, parked=False) is driving
  assert op.allowed(cls, started=True, parked=True) is parked


def test_parked_download_rule():
  assert op.downloads_allowed(started=False, parked=False)      # !started
  assert op.downloads_allowed(started=True, parked=True)        # parked
  assert not op.downloads_allowed(started=True, parked=False)   # driving


def test_unknown_drive_state_fails_closed():
  def boom():
    raise RuntimeError
  s = op.DriveState(boom, boom, boom)
  assert s.started() and not s.parked() and s.engaged()


def test_editor_follows_the_live_state(drive):
  sounds, steer, gas, cal = op.editor("volume"), op.editor("steering_tuning"), op.editor("gas_brake"), \
    op.editor("vehicle_controls", "PedalCalibrate")
  assert all(f() for f in (sounds, steer, gas, cal))
  drive.started = True
  assert sounds() and steer() and gas() and not cal()      # Gas / Brake is onroad-editable now (0.9.7 Longitudinal)
  drive.parked = True
  assert cal() and gas()


def test_page_notes():
  assert op.note(op.ONROAD, True) == ""
  assert "reboot" in op.note(op.REBOOT, True)
  assert op.note(op.LOCKED, True) == "Locked while the car is on"
  assert op.note(op.PARKED, True, parked=True) == "" and "Park" in op.note(op.PARKED, True)
  assert all(op.note(c, False) == "" for c in op.CLASSES)


def test_menu_header_note_per_page(drive):
  from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
  from openpilot.selfdrive.ui.layouts.settings import menu_097 as m
  nav = m.MenuNavigation(menu_sections(), lambda: None, lambda *a: None, level=lambda: 3, on_move=op.new_visit)
  drive.started = True
  nav.path = ("manage",)
  assert m.page_class_of(nav) == op.ONROAD and m.page_note(nav) == ""           # Alerts and Sounds: open onroad
  nav.path = ("steering",)
  assert m.page_class_of(nav) == op.REBOOT and "reboot" in m.page_note(nav)    # Lateral
  nav.path = ("driving_model", "driving_model")
  assert "reboot" in m.page_note(nav)
  nav.path = ("gas_brake", "gas_brake")
  assert m.page_note(nav) == ""                                                # 0.9.7 Longitudinal: open onroad
  nav.path = ("vehicle_settings",)
  assert m.page_class_of(nav) is None and m.page_note(nav) == ""               # mixed list: each page says its own
  drive.started = False
  nav.path = ("gas_brake", "gas_brake")
  assert m.page_note(nav) == ""


def test_tuning_level_is_the_only_menu_wide_gate():
  src = (UI / "layouts/settings/menu_097.py").read_text()
  assert "_can_edit = can_edit or (lambda: bool(ui_state.is_offroad()))" not in src
  assert 'onroad_policy.editor("", "tuning_level")' in src
  assert "on_move=onroad_policy.new_visit" in src and "onroad_policy.install(ui_state)" in src


# ---- reboot prompt ----------------------------------------------------------------------------------------------------
def test_reboot_prompt_once_per_visit_only_for_reboot_pages_while_started(drive):
  assert not op.changed("steering_tuning")                       # offroad: no prompt
  drive.started = True
  assert not op.changed("volume") and not op.changed("appearance")   # editable pages never prompt
  assert op.changed("steering_tuning")
  assert not op.changed("steering_tuning")                       # same visit: once
  assert op.changed("vehicle_controls")
  op.new_visit()
  assert op.changed("steering_tuning")
  assert drive.shown == ["steering_tuning", "vehicle_controls", "steering_tuning"]
  assert op.REBOOT_PROMPT == "Reboot required to take effect."   # 0.9.7 wording
  assert (op.REBOOT_NOW, op.REBOOT_LATER) == ("Reboot Now", "Reboot Later")


def test_reboot_now_refused_while_engaged_and_applies_staged_first(drive):
  puts, alerts, applied = [], [], []
  op.register_applier("DisableOpenpilotLongitudinal", lambda v: applied.append(v) or True)
  drive.started, drive.engaged = True, True
  assert op.stage("DisableOpenpilotLongitudinal", True)
  assert not op.reboot_now(lambda k, v: puts.append((k, v)), alerts.append)
  assert puts == [] and alerts == [op.DISENGAGE_TO_REBOOT] and applied == []
  drive.engaged = False
  assert op.reboot_now(lambda k, v: puts.append((k, v)), alerts.append)
  assert applied == [True] and puts == [("DoReboot", True)] and not op.has_pending()


# ---- staging (Disable openpilot Longitudinal) ---------------------------------------------------------------------------
def _vehicle(tmp_path, offroad, started):
  from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import AP1, VehicleSettings
  files = tmp_path / "ic"
  files.mkdir(exist_ok=True)
  store = tmp_path / "LongParam"
  writes, changes = [], []

  def put_bool(key, value, block=False):
    writes.append((key, value))
    store.write_text("1" if value else "0")
  cp = NS(carFingerprint=AP1, dashcamOnly=False, openpilotLongitudinalControl=True, alphaLongitudinalAvailable=False)
  model = VehicleSettings(NS(put_bool=put_bool), lambda: cp, offroad, files, store, started=started,
                          on_change=changes.append)
  return model, writes, changes


def test_disable_long_is_staged_while_driving_and_applied_offroad(drive, tmp_path):
  from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import CLUSTER, LONG
  model, writes, changes = _vehicle(tmp_path, op.editor("vehicle_controls"), op.is_started)
  drive.started = True
  assert model.enabled(LONG) and model.write(LONG, True)
  assert writes == []                                    # nothing a live planner reads has changed
  assert op.pending(LONG) is True and model.read(LONG) is True    # the row shows the staged value
  assert changes == [LONG]
  assert model.write(CLUSTER, False) and changes == [LONG, CLUSTER]   # other tweaks write at once (read at car start)
  applied = []
  op.register_applier(LONG, lambda v: applied.append(v) or model_off.write(LONG, v))
  model_off, writes_off, _ = _vehicle(tmp_path, lambda: True, lambda: False)
  drive.started = False
  assert op.apply_pending() == {LONG: True}
  assert applied == [True] and writes_off == [(LONG, True)] and not op.has_pending(LONG)


def test_offroad_write_clears_a_stale_stage(drive, tmp_path):
  from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import LONG
  model, writes, _ = _vehicle(tmp_path, op.editor("vehicle_controls"), op.is_started)
  drive.started = True
  model.write(LONG, True)
  drive.started = False
  assert model.write(LONG, False) and writes == [(LONG, False)] and not op.has_pending()


def test_refused_or_failing_applier_drops_the_stage(drive):
  op.register_applier("DisableOpenpilotLongitudinal", lambda v: False)
  op.stage("DisableOpenpilotLongitudinal", True)
  assert op.apply_pending() == {"DisableOpenpilotLongitudinal": False} and not op.has_pending()
  with pytest.raises(KeyError):
    op.stage("SteerRatio", 1.0)                       # only the live-read key is ever staged


def test_install_applies_on_every_switch_to_offroad(drive):
  applied = []
  op.register_applier("DisableOpenpilotLongitudinal", lambda v: applied.append(v) or True)
  callbacks = []
  ui = NS(started=False, add_offroad_transition_callback=callbacks.append)
  op._installed = False
  try:
    op.stage("DisableOpenpilotLongitudinal", True)
    op.install(ui)
    assert applied == [True]                          # UI started with the car off: applied at once
    ui.started = True
    op.stage("DisableOpenpilotLongitudinal", False)
    callbacks[0]()
    assert applied == [True] and op.pending("DisableOpenpilotLongitudinal") is False
    ui.started = False
    callbacks[0]()
    assert applied == [True, False] and not op.has_pending()
    op.install(ui)
    assert len(callbacks) == 1                        # idempotent
  finally:
    op._installed = False


# ---- Alert Volume: editable onroad, floors unchanged, live to soundd --------------------------------------------------
def test_alert_volume_floors_unchanged():
  from openpilot.selfdrive.ui.bogpilot import alert_volumes as av
  from openpilot.selfdrive.ui.bogpilot import phase2_sounds as ps
  floors = {k: lo for k, _t, lo, _hi in ps.VOLUME_ROWS}
  assert floors == {"DisengageVolume": 0, "EngageVolume": 0, "PromptVolume": 25, "PromptDistractedVolume": 25,
                    "RefuseVolume": 0, "WarningSoftVolume": 25, "WarningImmediateVolume": 25}
  assert ps.WARNING_FLOOR == 25 and set(ps.WARNING_FLOOR_KEYS) == set(av.SAFETY_FLOOR_KEYS)
  assert av.SAFETY_FLOOR_PERCENT == 25 and av.WARNING_IMMEDIATE_MIN_PERCENT == 25
  for key in av.SAFETY_FLOOR_KEYS:
    assert av.volume_fraction(0, key=key) == 0.25
    assert av.resolve_alert_gain(alert_volume_control=True, percent=0, ambient=0.9, key=key) == 0.25
    assert ps.clamp(key, 0) == 25
  assert av.volume_fraction(0, key="EngageVolume") == 0.0
  sd = (UI / "soundd.py").read_text()
  assert 'pct = max(pct, 25)' in sd and '"WarningImmediateVolume"):' in sd     # soundd fallback floor kept


def test_alert_volume_page_has_no_offroad_gate_and_says_so():
  src = (UI / "bogpilot/phase2_sounds.py").read_text()
  assert "is_offroad" not in src
  assert 'editable = onroad_policy.editor("volume")' in src
  assert "next sound service start" not in src and "Without the soundd live-reload patch" not in src
  assert "picks them up within about a second" in src


def test_onroad_volume_change_reaches_soundd_store_and_keeps_floor(drive, tmp_path):
  from openpilot.common.bogpilot_store import read_text, write_text
  from openpilot.selfdrive.ui.bogpilot import alert_volumes as av
  drive.started = True
  assert op.editor("volume")()
  # The page writes with bogpilot_store.write_text (atomic replace); soundd's _bogpilot_read_param reads the same file.
  assert write_text("PromptVolume", "0") and read_text("PromptVolume") == "0"
  assert av.resolve_alert_gain(alert_volume_control=True, percent=int(read_text("PromptVolume")), ambient=0.5,
                               key="PromptVolume") == 0.25
  sd = (UI / "soundd.py").read_text()
  # soundd re-reads about once a second, only while no alert plays (unchanged).
  assert re.search(r"if self\.current_alert == AudibleAlert\.none and time\.monotonic\(\) >= self\._bp_next_reload:", sd)
  assert "self._bp_next_reload = time.monotonic() + 1.0" in sd


# ---- System Settings: per-row onroad --------------------------------------------------------------------------------------
def _onroad(page):
  return lambda row: op.can_edit(op.row_class(row, page))


def test_device_controls_screen_rows_and_logging_onroad(drive):
  from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import (DEVICE_MASTER, SCREEN_MASTER, DeviceControlsMenu,
                                                                     MemoryStore)
  drive.started = True
  menu = DeviceControlsMenu(MemoryStore(), offroad=lambda: False, onroad_ok=_onroad("system_device"),
                            recorder_start=lambda: "started")
  assert menu.set("ScreenBrightnessOnroad", 50) and menu.set("ScreenTimeoutOnroad", 15)
  assert menu.set(SCREEN_MASTER, True) and menu.set("StandbyMode", True) and menu.set("ScreenRecorder", False)
  assert menu.set("DeviceShutdown", 3) and menu.set("LowVoltageShutdown", 12.0)
  assert menu.set("NoLogging", True) and menu.set(DEVICE_MASTER, False)   # 0.9.7: both live (manager re-reads each loop)
  assert menu.run_action("start_recording")
  legacy = DeviceControlsMenu(MemoryStore(), offroad=lambda: False)                 # no policy: offroad only
  assert not legacy.set("ScreenBrightnessOnroad", 50) and not legacy.run_action("start_recording")


def test_utilities_debug_onroad_resets_locked(drive, tmp_path):
  from openpilot.selfdrive.ui.bogpilot import phase3_system_utilities as u
  from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import MemoryStore
  drive.started = True
  store = MemoryStore({"DebugMode": "0"})
  act = u.UtilitiesActions(lambda: False, lambda: True, store=store, file_root=tmp_path / "f",
                           backup_root=tmp_path / "b", cache_roots=(str(tmp_path / "c"),),
                           report_root=tmp_path / "r", onroad_ok=_onroad("system_utilities"))
  assert "enabled" in act.set_debug_mode(True) and store.values["DebugMode"] == "1"
  assert "saved locally" in act.save_debug_report()
  for destructive in (act.clear_caches, act.reset_bogpilot_defaults, act.queue_stock_reset):
    with pytest.raises(PermissionError):
      destructive()
  with pytest.raises(PermissionError):
    act.guard()


def test_data_backup_export_storage_onroad_destructive_locked(drive, tmp_path):
  from openpilot.selfdrive.ui.bogpilot import phase3_system_settings_backend as b
  drive.started = True
  ok = _onroad("system_data")
  prefs = b.SystemPreferences(NS(), lambda: False, lambda: True, onroad_ok=ok)
  prefs.guard("data:backup")
  prefs.guard("data:export")
  for row in (None, "data:delete", "data:restore", "data:stats_reset"):
    with pytest.raises(PermissionError):
      prefs.guard(row)
  roots = {"driving": (str(tmp_path / "d"),), "errors": (str(tmp_path / "e"),), "recordings": (str(tmp_path / "r"),)}
  data = b.LocalData(lambda: False, lambda: True, roots=roots, onroad_ok=ok)
  assert set(data.storage_use()) == set(roots)
  with pytest.raises(PermissionError):
    data.delete("errors")


# ---- reboot-class models: editable while driving, report the change ---------------------------------------------------------
def test_stalk_menu_editable_while_driving_reports_change(drive, tmp_path):
  from opendbc.car.tesla_ap1.phase3_stalk_controls import Store
  from openpilot.selfdrive.ui.bogpilot.phase3_stalk_controls import StalkMenu
  car = NS(carFingerprint="TESLA_AP1_MODELS", dashcamOnly=False, passive=False, openpilotLongitudinalControl=True)
  drive.started = True
  menu = StalkMenu(lambda: car, op.editor("stalk_controls"), Store(tmp_path / "s.json"),
                   on_change=op.on_change("stalk_controls"))
  assert menu.write("tip_round", False) and menu.store.read().tip_round is False
  assert drive.shown == ["stalk_controls"]


def test_steering_editor_editable_while_driving_reports_change(drive):
  from opendbc.car.tesla_ap1.interface import CarInterface
  from opendbc.car.tesla_ap1.values import CAR
  from openpilot.common.bogpilot_store import ParamStore
  from openpilot.selfdrive.ui.bogpilot import phase3_steering_tuning as st

  class Mem:
    def __init__(self): self.data = {}
    def all_keys(self): return []
    def get(self, k): return self.data.get(k)
    def put(self, k, v): self.data[k] = str(v)
    def remove(self, k): self.data.pop(k, None)
  cp = CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS)
  drive.started = True
  e = st.TuningEditor(cp, ParamStore(Mem()), op.editor("steering_tuning"), on_change=op.on_change("steering_tuning"))
  assert e.write("AdvancedLateralTune", True) and e.write("SteerRatio", round(cp.steerRatio + 1, 2))
  assert drive.shown == ["steering_tuning"]


def test_model_selector_gate_and_status(drive, tmp_path, monkeypatch):
  from openpilot.selfdrive.ui.bogpilot.bogpilot_model_selector import ModelSelectorController

  class Mem:
    def __init__(self): self.kv = {}
    def raw(self, k): return self.kv.get(k)
    def put(self, k, v): self.kv[k] = str(v)
    def remove(self, k): self.kv.pop(k, None)
  monkeypatch.setenv("BOGPILOT_MODELS_DIR", str(tmp_path))
  drive.started = True
  ctrl = ModelSelectorController(op.editor("driving_model"), Mem(), str(tmp_path), started=op.is_started)
  snap = ctrl.refresh()
  assert snap.offroad and "Takes effect after a reboot" in snap.status
  locked = ModelSelectorController(lambda: False, Mem(), str(tmp_path)).refresh()
  assert "Changes apply offroad only" in locked.status


def test_car_selection_writes_while_driving_through_the_gate():
  from openpilot.selfdrive.ui.bogpilot.phase2_car_selection import AUTO, apply_choice
  calls = []
  params = NS(remove=lambda k: calls.append(("rm", k)), put=lambda *a, **k: calls.append(a),
              put_bool=lambda *a, **k: calls.append(a), get=lambda k: None, get_bool=lambda k: False)
  assert not apply_choice(params, AUTO, offroad=False) and calls == []
  src = (UI / "bogpilot/phase2_car_selection.py").read_text()
  assert 'editable = onroad_policy.editor("car_selection")' in src and 'onroad_policy.changed("car_selection")' in src


# ---- every lock site from the audit goes through the policy ---------------------------------------------------------------
LOCK_SITES = {
  "bogpilot/phase2_car_selection.py": 'onroad_policy.editor("car_selection")',
  "bogpilot/phase2_vehicle.py": 'onroad_policy.editor("vehicle_controls")',
  "bogpilot/phase3_stalk_controls.py": 'onroad_policy.editor("stalk_controls")',
  "bogpilot/phase3_steering_tuning.py": 'onroad_policy.editor("steering_tuning")',
  "layouts/settings/bogpilot.py": 'onroad_policy.editor("lane_changes")',
  "bogpilot/bogpilot_model_selector.py": 'onroad_policy.editor("driving_model")',
  "bogpilot/phase3_device_controls.py": 'onroad_policy.row_class(key, "system_device")',
  "bogpilot/phase3_system_utilities_ui.py": 'onroad_policy.row_class(row, "system_utilities")',
  "layouts/settings/phase3_system_settings_data_ui.py": 'onroad_policy.row_class(row, "system_data")',
  "bogpilot/phase2_sounds.py": 'onroad_policy.editor("volume")',
  "bogpilot/phase3_gas_brake.py": 'onroad_policy.editor("gas_brake")',
  "layouts/settings/software.py": "onroad_policy.downloads_allowed(",
  "mici/layouts/settings/software.py": "onroad_policy.downloads_allowed(",
}


@pytest.mark.parametrize("path,needle", sorted(LOCK_SITES.items()))
def test_lock_site_uses_policy(path, needle):
  src = (UI / path).read_text()
  assert needle in src
  # No page passes the raw offroad check as its edit gate any more (stock stays only as the offroad base / Install).
  for bad in ("ui_state.CP, ui_state.is_offroad", "offroad=ui_state.is_offroad)", "ModelSelectorController(ui_state.is_offroad)",
              "enabled=ui_state.is_offroad", "ParamStore(), ui_state.is_offroad)"):
    assert bad not in src, (path, bad)


def test_stock_offroad_only_actions_untouched():
  dev = (UI / "layouts/settings/device.py").read_text()
  assert "set_visible(ui_state.is_offroad())" in dev                     # Power Off
  assert "CabinCameraDialog()), enabled=ui_state.is_offroad" in dev      # driver camera
  assert dev.count('"Disengage to Reboot"') >= 1
  sw = (UI / "layouts/settings/software.py").read_text()
  assert "self._install_btn.set_visible(ui_state.is_offroad() and update_available)" in sw
  devl = (UI / "layouts/settings/developer.py").read_text()
  assert "enabled=ui_state.is_offroad" in devl


def test_gated_actions_docstring_is_true():
  src = (UI / "bogpilot/gated_actions.py").read_text()
  assert "Every BogPilot editor still refuses\nthe write itself while onroad" not in src
  assert "onroad_policy.py" in src


def test_staged_store_is_json(drive, tmp_path):
  op.stage("DisableOpenpilotLongitudinal", True)
  assert json.loads((tmp_path / op.PENDING_KEY).read_text()) == {"DisableOpenpilotLongitudinal": True}
  op.clear_pending("DisableOpenpilotLongitudinal")
  assert not (tmp_path / op.PENDING_KEY).exists()


# ---- 0.9.7 full parity: Gas / Brake, Tuning Level, Disable Logging, Device Settings master -----------------------------
START_READ_ROWS = ("CustomPersonalities", "HumanFollowing", "LeadDetectionThreshold",
                   "AggressivePersonalityProfile", "StandardFollow", "RelaxedJerkAcceleration", "AggressiveJerkDeceleration",
                   "StandardJerkDanger", "RelaxedJerkSpeedDecrease", "AggressiveJerkSpeed")
LIVE_GAS_ROWS = ("SpeedLimitController", "Offset1", "Offset7", "SLCConfirmation", "AccelerationProfile", "DecelerationProfile",
                 "HumanAcceleration", "MaxDesiredAcceleration", "StopAccel", "StoppingDecelRate", "LongitudinalActuatorDelay",
                 "ForceStops", "IncreasedStoppedDistance", "WeatherPresets", "QOLLongitudinal", "HumanLaneChanges",
                 "AP1TapFromZeroMs")


def test_gas_brake_page_is_onroad_and_its_start_read_rows_prompt_for_reboot():
  assert op.page_class("gas_brake") == op.ONROAD
  for row in START_READ_ROWS:
    assert op.row_class(row, "gas_brake") == op.REBOOT, row
  for row in LIVE_GAS_ROWS:
    assert op.row_class(row, "gas_brake") == op.ONROAD, row      # SLC and its offsets, profiles, stopping: read live
  assert op.row_class("tuning_level") == op.REBOOT
  for row in ("DeviceManagement", "NoLogging"):
    assert op.row_class(row, "system_device") == op.ONROAD, row   # manager re-reads both every loop


def test_gas_brake_editor_is_open_onroad_and_long_lock_is_untouched(drive):
  from openpilot.selfdrive.ui.bogpilot import menu_locks
  drive.started = True
  assert op.editor("gas_brake")() and op.editor("gas_brake", "SpeedLimitController")()
  # the openpilot-longitudinal requirement is a separate lock and still applies
  no_long = NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=False, dashcamOnly=False, passive=False)
  assert menu_locks.long_lock(no_long) is not None
  assert menu_locks.long_lock(NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True)) is None
  assert menu_locks.long_lock(None) is menu_locks.NO_CAR


def test_row_changed_prompts_once_per_visit_only_for_reboot_rows_while_started(drive):
  assert not op.row_changed("CustomPersonalities", "gas_brake")             # car off: no prompt
  drive.started = True
  for row in LIVE_GAS_ROWS:
    assert not op.row_changed(row, "gas_brake"), row                        # live rows never prompt
  assert op.row_changed("CustomPersonalities", "gas_brake")
  assert not op.row_changed("LeadDetectionThreshold", "gas_brake")          # same visit: once
  op.new_visit()
  assert op.row_changed("HumanFollowing", "gas_brake")
  assert op.row_changed("tuning_level")                                     # menu control, its own key
  assert drive.shown == ["gas_brake", "gas_brake", "tuning_level"]


def test_gas_brake_store_proxy_prompts_after_start_read_writes_only(drive):
  from openpilot.selfdrive.ui.bogpilot.phase3_gas_brake import _NotifyingStore

  class Store:
    def __init__(self):
      self.w = []

    def put(self, k, v, **kw):
      self.w.append((k, v))

    def put_bool(self, k, v, **kw):
      self.w.append((k, v))

    def remove(self, k):
      self.w.append((k, None))

    def get_bool(self, k, default=None):
      return True

  raw = Store()
  st = _NotifyingStore(raw)
  drive.started = True
  st.put_bool("SpeedLimitController", True)
  st.put("Offset3", 5)
  assert drive.shown == [] and st.get_bool("x") is True                     # live rows: written, no prompt, reads pass through
  st.put_bool("CustomPersonalities", True)
  st.put("AggressiveFollow", 1.4)                                           # same visit: still one prompt
  assert drive.shown == ["gas_brake"]
  assert raw.w == [("SpeedLimitController", True), ("Offset3", 5), ("CustomPersonalities", True), ("AggressiveFollow", 1.4)]
  drive.started = False
  op.new_visit()
  st.put_bool("HumanFollowing", True)
  assert drive.shown == ["gas_brake"]                                       # car off: no prompt


def test_tuning_level_change_while_driving_writes_and_prompts_once(drive, tmp_path):
  from openpilot.selfdrive.ui.layouts.settings import menu_097 as m
  from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
  drive.started = True
  class Mem:
    def __init__(self):
      self.d = {}

    def get_bool(self, k, default=None):
      return bool(self.d.get(k, default))

    def get_int(self, k, default=None):
      return int(self.d.get(k, default or 0))

    def put_bool(self, k, v, **kw):
      self.d[k] = bool(v)

    def put(self, k, v, **kw):
      self.d[k] = v

    def get(self, k, default=None):
      return self.d.get(k, default)

    def raw(self, k):
      return None if k not in self.d else str(self.d[k])

    def remove(self, k):
      self.d.pop(k, None)

    def invalidate(self, key=None):
      pass

    def tuning_level(self):
      return int(self.d.get("TuningLevel", 0)) if self.d.get("TuningLevelConfirmed") else 3

  store, warned = Mem(), []
  can_edit = op.editor("", "tuning_level")
  assert can_edit()
  assert m.choose_tuning_level(1, can_edit=can_edit, show_warning=warned.append, store=store)
  assert drive.shown == ["tuning_level"]
  assert m.choose_tuning_level(2, can_edit=can_edit, show_warning=warned.append, store=store)
  assert drive.shown == ["tuning_level"]                                     # once per visit
  assert tl.effective_level(store) == 2


def test_nologging_and_device_master_writes_go_through_while_driving(drive):
  from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import DEVICE_MASTER, DeviceControlsMenu, MemoryStore
  drive.started = True
  menu = DeviceControlsMenu(MemoryStore(), offroad=lambda: False, onroad_ok=_onroad("system_device"))
  assert menu.set(DEVICE_MASTER, True) and menu.set("NoLogging", True)
  assert menu.set("NoLogging", False) and menu.set(DEVICE_MASTER, False)
  assert not drive.shown                                                     # live: no reboot prompt


def test_stock_offroad_only_actions_and_destructive_rows_still_locked(drive):
  drive.started = True
  for row in ("data:delete", "data:restore", "BogPilotDefaultsReset", "ClearCaches"):
    assert not op.can_edit(op.row_class(row, "system_data")), row
  assert not op.can_edit(op.row_class("PedalCalibrate", "vehicle_controls"))
  assert not op.ONROAD_CAVEATS.keys() - {"data:delete"}


def test_alert_volume_floors_untouched_by_full_parity():
  src = (UI / "bogpilot/onroad_policy.py").read_text()
  assert "volume" in src and 'AlertVolumeControl' not in src.split("ROW_CLASS", 1)[1]
