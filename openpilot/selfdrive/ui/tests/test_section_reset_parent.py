"""A section's "Reset section to defaults" restores the shipped BogPilot defaults for the WHOLE section, its own on/off
switch included (what "Reset BogPilot Settings to Defaults" writes: toggle_reset.shipping_defaults), with the car type's
SLC values on top (SLC_RESET_PROFILES). Keys outside the section are never touched.

Pure part (no window): the shared table builder, the parent list, Sounds, Gas / Brake Quality of Life and the Speed
Limit Controller on every car type. The panel-level checks for the other sections sit next to each panel's reset tests
(steering, lane changes, following, longitudinal groups)."""
import pytest

from openpilot.selfdrive.ui.bogpilot import step_defaults as sd
from openpilot.system.bogpilot.toggle_reset import shipping_defaults

# Every section reset that has its own parent switch, with the switch's shipped default (stored text).
PARENTS = {
  "SpeedLimitController": "1",          # Speed Limit Controller, main page
  "QOLLongitudinal": "1",               # Gas / Brake > Quality of Life
  "AlertVolumeControl": "0",            # Sounds > Alert Volume Controller
  "LaneChanges": "1",                   # Lane Changes (minimum speed, one lane change per signal)
  "NudgelessLaneChange": "0",           # Automatic Lane Changes (delay, lane width)
  "AdvancedLateralTune": "0",           # Steering > Advanced Lateral Tuning
  "QOLLateral": "1",                    # Steering > Quality of Life
  "AdvancedLongitudinalTune": "0",      # Gas / Brake > Advanced Longitudinal Tuning
  "ConditionalExperimental": "1",       # Conditional Experimental Mode
  "AggressivePersonalityProfile": "1",  # Driving Personalities, one section per profile
  "StandardPersonalityProfile": "1",
  "RelaxedPersonalityProfile": "1",
}


def test_parent_switches_and_their_shipped_defaults():
  shipped = shipping_defaults()
  assert {k: shipped[k] for k in PARENTS} == PARENTS
  for k, v in PARENTS.items():
    assert sd.shipped_toggle(k) is (v == "1")


def test_whole_section_order_overrides_and_lock():
  # rows first, sub-parents that turn on before them and off after them, the section's own switch last
  table = sd.whole_section({"SLCOverride": 1}, toggles=("CENavigation", "CELead", "ShowSLCOffset"),
                           choices=("SLCFallback",), parent="SpeedLimitController", sub_parents=("CENavigation", "CELead"))
  assert list(table) == ["CENavigation", "SLCOverride", "SLCFallback", "ShowSLCOffset", "CELead", "SpeedLimitController"]
  assert table == {"CENavigation": True, "SLCOverride": 1, "SLCFallback": 2, "ShowSLCOffset": True, "CELead": False,
                   "SpeedLimitController": True}
  # car-type values replace the shipped ones; never the switch
  table = sd.whole_section({}, toggles=("ShowSLCOffset",), parent="SpeedLimitController",
                           overrides={"ShowSLCOffset": False, "SpeedLimitController": False})
  assert table == {"ShowSLCOffset": False, "SpeedLimitController": True}
  # locked keys are left out, the switch too
  assert sd.whole_section({"a": 1}, toggles=("ShowSLCOffset",), parent="QOLLateral", can_edit=lambda k: k == "a") == {"a": 1}
  # a key without a shipped default is left alone
  assert sd.whole_section({}, toggles=("NoSuchKey",), parent="NoSuchParent") == {}


# ------------------------------------------------------------------------------------------------------------- Sounds
@pytest.fixture
def sound_store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  from openpilot.selfdrive.ui import soundd
  monkeypatch.setattr(soundd, "_bogpilot_params_dir", lambda: tmp_path)
  import openpilot.common.params as p
  monkeypatch.setattr(p, "Params", lambda: type("P", (), {"get": lambda s, k: None})())
  return tmp_path


def test_sounds_reset_turns_the_controller_back_to_its_default(sound_store):
  from openpilot.selfdrive.ui.bogpilot import phase2_sounds as ps
  ps.set_controller(True)                                  # parent at the non-default value
  ps.set_volume("EngageVolume", 60)
  (sound_store / "OtherSetting").write_text("7")
  written = sd.reset_section(ps.section_defaults, ps.write_volume_default)
  assert written[-1] == ps.PARENT_KEY and not ps.read_controller()
  assert (sound_store / ps.PARENT_KEY).read_text() == PARENTS[ps.PARENT_KEY]
  assert ps.read_volume("EngageVolume") == 101 and (sound_store / "OtherSetting").read_text() == "7"


# -------------------------------------------------------------------------------------- Gas / Brake > Quality of Life
@pytest.fixture
def stop_store(tmp_path, monkeypatch):
  from openpilot.common.bogpilot_store import ParamStore
  from openpilot.common.params import Params
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "prefs"))
  s = ParamStore(params=Params(str(tmp_path / "native")))
  s.put_bool("TuningLevelConfirmed", True, block=True)
  s.put("TuningLevel", 3, block=True)
  return s


def stop_cp():
  from opendbc.car.structs import car
  cp = car.CarParams.new_message()
  cp.openpilotLongitudinalControl = True
  cp.brand = "tesla"
  cp.carFingerprint = "TESLA_AP1_MODELS"
  return cp


def test_stopping_qol_reset_restores_the_whole_page(stop_store):
  from openpilot.selfdrive.ui.bogpilot.phase3_stopping_settings import StoppingCapabilities, StoppingSettingsModel
  m = StoppingSettingsModel(stop_store, stop_cp(), StoppingCapabilities(stopped_distance=True, force_stop_inputs=True),
                            lambda: True)
  assert m.change("qol", "ForceStops", True) and m.change("qol", "IncreasedStoppedDistance", value=2)
  stop_store.put("LaneChangeTime", "2.5", block=True)       # outside the section
  table = m.section_defaults("qol")
  assert list(table)[-1] == "QOLLongitudinal" and table["QOLLongitudinal"] is True
  assert table["ForceStops"] is False and table["IncreasedStoppedDistance"] == 0
  sd.reset_section(table, lambda k, v: m.reset_write("qol", k, v))
  stop_store.invalidate()
  assert not stop_store.get_bool("ForceStops") and stop_store.get_float("IncreasedStoppedDistance") == 0
  assert stop_store.get_bool("QOLLongitudinal") and stop_store.get("LaneChangeTime") == "2.5"
  # parent at the non-default value (off): the page's table still brings the switch back on
  assert m.change("qol", "QOLLongitudinal", False)
  table = m.section_defaults("qol")
  assert table == {"QOLLongitudinal": True}
  sd.reset_section(table, lambda k, v: m.reset_write("qol", k, v))
  stop_store.invalidate()
  assert stop_store.get_bool("QOLLongitudinal")


# ------------------------------------------------------------------------------------------ Speed Limit Controller
from openpilot.selfdrive.ui.tests.test_slc_ap1_section_reset import (  # noqa: E402
  ALL_CARS, MAIN, OFFSETS, SAVED, TODAY, editor, expected_reset, reset,
)
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss  # noqa: E402

SLC_MAIN = (ss.PARENT_KEY, "SLCFallback") + MAIN       # every row of the main page


@pytest.mark.parametrize("car", ALL_CARS)
@pytest.mark.parametrize("metric", [False, True])
def test_slc_main_reset_is_the_parent_default_plus_the_car_values(car, metric):
  ed, store = editor(car, metric, **SAVED)
  profile = ss.slc_reset_profile(store)
  assert (profile is not None) == (car in TODAY)          # AP1 S, AP1 X, Pre-AP: car values; Model 3 / unset: plain
  table = reset(ed, SLC_MAIN)
  assert list(table)[-1] == ss.PARENT_KEY and table[ss.PARENT_KEY] is True
  assert {k: store.vals[k] for k in SLC_MAIN} == expected_reset(store, SLC_MAIN, profile)
  if profile is None:
    assert {k: store.vals[k] for k in ("SLCOverride", "SLCFallback")} == {"SLCOverride": "1", "SLCFallback": "2"}
  else:
    assert store.vals["SLCOverride"] == "2" and store.vals["SLCFallback"] == "2"
  # keys outside the section are untouched
  assert [store.vals[k] for k in OFFSETS] == [SAVED[k] for k in OFFSETS]
  assert (store.vals["ShowSLCOffset"], store.vals["SLCConfirmation"], store.vals["SetSpeedLimit"]) == ("1", "1", "1")


@pytest.mark.parametrize("car", ALL_CARS)
def test_slc_reset_with_the_parent_off_turns_it_back_on(car):
  ed, store = editor(car, **SAVED)
  assert ed.write(ss.PARENT_KEY, False) and store.vals[ss.PARENT_KEY] == "0"
  table = reset(ed, SLC_MAIN)
  assert table == {ss.PARENT_KEY: True}                     # the hidden rows are locked; only the switch is listed
  assert store.vals[ss.PARENT_KEY] == "1"
  assert store.vals["SLCOverride"] == SAVED["SLCOverride"]


# ------------------------------------------------------------------------- Gas / Brake longitudinal groups (one each)
@pytest.fixture
def long_page(stop_store, monkeypatch):
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.selfdrive.ui.bogpilot import gated_actions
  monkeypatch.setattr(gui_app, "font", lambda *a, **kw: rl.Font())   # real widgets, font only stubbed
  monkeypatch.setattr(gated_actions, "_confirm_dialog", lambda text, yes: yes())
  from openpilot.selfdrive.ui.layouts.settings import phase3_long_accel_settings as la

  def make(group):
    w = la.make_settings(group, stop_store, cp=stop_cp())
    w.show_event()
    return w
  return make


def test_advanced_longitudinal_reset_turns_its_switch_back_off(long_page, stop_store):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
  c = SettingsController("advanced", stop_store, cp=stop_cp())
  assert c.change("AdvancedLongitudinalTune", True) and c.change("MaxDesiredAcceleration", 1.5)
  stop_store.put("LaneChangeTime", "2.5", block=True)       # outside the group
  page = long_page("advanced")
  table = page.reset.section_defaults()
  assert list(table)[-1] == "AdvancedLongitudinalTune" and table["AdvancedLongitudinalTune"] is False
  assert table["MaxDesiredAcceleration"] == 4.0
  page.reset.callback()                                     # yes straight away
  stop_store.invalidate()
  assert not stop_store.get_bool("AdvancedLongitudinalTune")
  assert stop_store.get_float("MaxDesiredAcceleration") == 4.0 and stop_store.get("LaneChangeTime") == "2.5"


def test_conditional_experimental_reset_restores_the_group_and_its_switch(long_page, stop_store):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
  c = SettingsController("conditional", stop_store, cp=stop_cp())
  assert c.change("ConditionalExperimental", True) and c.change("CESignalSpeed", 40)
  assert c.change("CELead", True) and c.change("CESlowerLead", True)
  page = long_page("conditional")
  table = page.reset.section_defaults()
  assert list(table)[-1] == "ConditionalExperimental" and table["ConditionalExperimental"] is True
  assert table["CESignalSpeed"] == 55
  shipped = shipping_defaults()
  assert all(table[k] is (shipped[k] == "1") for k in table if isinstance(table[k], bool))
  # a sub-switch that turns off is written after its own rows (With Lead's children first, then With Lead)
  order = list(table)
  assert table["CELead"] is False and order.index("CESlowerLead") < order.index("CELead")
  page.reset.callback()
  stop_store.invalidate()
  assert stop_store.get_bool("ConditionalExperimental") and not stop_store.get_bool("CELead")
  assert not stop_store.get_bool("CESlowerLead") and stop_store.get_float("CESignalSpeed") == 55
  # the switch at its non-default value (off): its rows are hidden, the table writes the switch back on
  assert c.change("ConditionalExperimental", False)
  stop_store.invalidate()
  assert page.reset.section_defaults() == {"ConditionalExperimental": True}
  sd.reset_section(page.reset.section_defaults(), page.reset.section_write)
  stop_store.invalidate()
  assert stop_store.get_bool("ConditionalExperimental")
