"""A section's "Reset section to defaults" restores the shipped BogPilot defaults for the WHOLE section, its own on/off
switch included (what "Reset BogPilot Settings to Defaults" writes: toggle_reset.shipping_defaults), then the car type's
reset profile on top (SLC_RESET_PROFILES: the whole AP1 profile on AP1 Model S, SLC values only on AP1 Model X and
Pre-AP). The section switch takes the profile value when the profile sets one. Keys outside the section are never touched.

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
  # car-type values replace the shipped ones, including the switch when the profile sets it (written last)
  table = sd.whole_section({}, toggles=("ShowSLCOffset",), parent="SpeedLimitController",
                           overrides={"ShowSLCOffset": False, "SpeedLimitController": False})
  assert list(table)[-1] == "SpeedLimitController"
  assert table == {"ShowSLCOffset": False, "SpeedLimitController": False}
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
  ALL_CARS, MAIN, OFFSETS, SAVED, TODAY, VISUALS, editor, expected_reset, reset,
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




# -------------------------------------------------------- AP1 profile values on section reset (S only; X stays SLC)
from types import SimpleNamespace

from openpilot.common.bogpilot_ap1_profile import AP1_CAR_MODEL, is_ap1, is_ap1x_slc_platform, is_preap_slc_platform
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore


class _MemParams:
  """In-memory Params stand-in so these tests do not import openpilot.common.params (native)."""

  def __init__(self, **vals):
    self.d = dict(vals)
    self.puts = []

  def all_keys(self):
    return list(BOGPILOT_PARAMS)

  def get(self, k, *a, **kw):
    return self.d.get(k)

  def put(self, k, v, *a, **kw):
    self.puts.append((k, v))
    self.d[k] = v

  def put_bool(self, k, v, *a, **kw):
    self.put(k, bool(v))

  def remove(self, k):
    self.d.pop(k, None)


@pytest.fixture
def profile_store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  s = ParamStore(params=_MemParams())
  s.put("TuningLevelConfirmed", "1")
  s.put("TuningLevel", "3")
  return s


def _set_car(store, car):
  if car is not None:
    store.put("CarModel", car)
    store.invalidate()
  return store


def _group_table(controller):
  """The same reset table the group panel builds (step_defaults.whole_section + car-type overrides)."""
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SUB_PARENTS
  c = controller
  if not bool(c.can_edit()) or not c.long_available():
    return {}
  rows = c.rows()
  shown = {r.key for r in rows}
  reset_keys = tuple(r.key for r in rows if c.unsaved_value(r.key) is not None)
  keys = (c.parent,) + tuple(r.key for r in rows)
  return sd.whole_section(c.section_defaults(reset_keys),
                          toggles=tuple(r.key for r in rows if r.kind == "toggle"),
                          choices=tuple(r.key for r in rows if r.kind == "choice"),
                          parent=c.parent, sub_parents=SUB_PARENTS,
                          can_edit=lambda k: k == c.parent or k in shown,
                          overrides=sd.car_type_overrides(c.store, keys))


def test_is_ap1_still_matches_only_the_model_s():
  # The detector is unchanged: only TESLA_AP1_MODELS, never the X or Pre-AP.
  for car, expect_s, expect_x, expect_pre in (
    (AP1_CAR_MODEL, True, False, False),
    ("TESLA_AP1_MODELX", False, True, False),
    ("TESLA_PREAP_MODELS", False, False, True),
    ("TESLA_MODEL_3", False, False, False),
    (None, False, False, False),
  ):
    _, store = editor(car)
    assert is_ap1(store) is expect_s
    assert is_ap1x_slc_platform(store) is expect_x
    assert is_preap_slc_platform(store) is expect_pre


def test_ap1_s_cem_reset_writes_the_profile_values(profile_store):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
  _set_car(profile_store, AP1_CAR_MODEL)
  assert is_ap1(profile_store)
  c = SettingsController("conditional", profile_store, cp=stop_cp())
  assert c.change("ConditionalExperimental", True) and c.change("CECurves", False)
  assert c.change("CESignalSpeed", 40)
  table = _group_table(c)
  assert list(table)[-1] == "ConditionalExperimental" and table["ConditionalExperimental"] is False
  assert table["CECurves"] is True
  assert table["CESignalSpeed"] == 55   # not in the profile: shipped / catalog default
  sd.reset_section(table, c.reset_write)
  profile_store.invalidate()
  assert not profile_store.get_bool("ConditionalExperimental") and profile_store.get_bool("CECurves")
  assert profile_store.get_float("CESignalSpeed") == 55
  # the switch at the non-profile value (on): the table still writes it back off
  assert c.change("ConditionalExperimental", True)
  profile_store.invalidate()
  assert _group_table(c)["ConditionalExperimental"] is False
  sd.reset_section(_group_table(c), c.reset_write)
  profile_store.invalidate()
  assert not profile_store.get_bool("ConditionalExperimental")


def test_ap1_s_cem_reset_writes_hidden_nav_child_when_shown(profile_store):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import Capabilities, SettingsController
  _set_car(profile_store, AP1_CAR_MODEL)
  caps = Capabilities(navigation=True)
  c = SettingsController("conditional", profile_store, capabilities=caps, cp=stop_cp())
  assert c.change("ConditionalExperimental", True)
  assert c.change("CENavigationIntersections", False)
  table = _group_table(c)
  assert table["CENavigationIntersections"] is True
  sd.reset_section(table, c.reset_write)
  profile_store.invalidate()
  assert profile_store.get_bool("CENavigationIntersections")
  assert not profile_store.get_bool("ConditionalExperimental")


def test_ap1_s_deceleration_reset_writes_the_profile_value(profile_store):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
  _set_car(profile_store, AP1_CAR_MODEL)
  c = SettingsController("profiles", profile_store, cp=stop_cp())
  assert c.change("DecelerationProfile", 1) and c.change("AccelerationProfile", 0)
  table = _group_table(c)
  assert table["DecelerationProfile"] == 2 and table["AccelerationProfile"] == 2
  sd.reset_section(table, c.reset_write)
  profile_store.invalidate()
  assert int(float(profile_store.get("DecelerationProfile"))) == 2
  assert int(float(profile_store.get("AccelerationProfile"))) == 2


def test_ap1_s_relaxed_follow_reset_writes_the_profile_value(profile_store):
  from openpilot.selfdrive.ui.bogpilot import phase3_following as following
  _set_car(profile_store, AP1_CAR_MODEL)
  cp = SimpleNamespace(openpilotLongitudinalControl=True, radarUnavailable=False)
  e = following.FollowingEditor(cp, profile_store, lambda: True)
  assert e.write("CustomPersonalities", True)
  assert e.write("RelaxedFollow", 1.25)
  keys = following.profile_value_keys("Relaxed")
  assert e.default("RelaxedFollow") == 2.0
  table = sd.whole_section(e.section_defaults(keys), parent="RelaxedPersonalityProfile", can_edit=e.can_edit,
                           overrides=sd.car_type_overrides(profile_store, list(keys) + ["RelaxedPersonalityProfile"]))
  assert table["RelaxedFollow"] == 2.0

  def write(k, v):
    if not e.write(k, v):
      raise PermissionError(k)

  written = sd.reset_section(table, write)
  assert "RelaxedFollow" in written
  assert e.value("RelaxedFollow") == 2.0


@pytest.mark.parametrize("car, expect_ce", [
  ("TESLA_AP1_MODELX", True),
  ("TESLA_PREAP_MODELS", True),
  ("TESLA_MODEL_3", True),
  (None, True),
])
def test_non_ap1_s_cem_reset_keeps_the_shipped_switch(profile_store, car, expect_ce):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
  _set_car(profile_store, car)
  assert not is_ap1(profile_store)
  c = SettingsController("conditional", profile_store, cp=stop_cp())
  assert c.change("ConditionalExperimental", False)
  table = _group_table(c)
  assert table == {"ConditionalExperimental": expect_ce}
  sd.reset_section(table, c.reset_write)
  profile_store.invalidate()
  assert profile_store.get_bool("ConditionalExperimental") is expect_ce


def test_ap1_x_slc_values_are_unchanged_and_ce_stays_shipped(profile_store):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
  _set_car(profile_store, "TESLA_AP1_MODELX")
  assert is_ap1x_slc_platform(profile_store) and not is_ap1(profile_store)
  # SLC values on the X still come from the AP1 profile's SLC keys
  ed, _ = editor("TESLA_AP1_MODELX", **SAVED)
  reset(ed, MAIN + VISUALS + OFFSETS)
  assert {k: ed.store.vals[k] for k in MAIN} == {"SLCOverride": "2", "SLCPriority1": "Dashboard",
                                                 "SLCPriority2": "Map Data", "SLCPriority3": "Navigation",
                                                 "SLCLookaheadLower": "5"}
  assert ed.store.vals["ShowSLCOffset"] == "0"
  # CE section reset still ships on
  c = SettingsController("conditional", profile_store, cp=stop_cp())
  assert c.change("ConditionalExperimental", False)
  table = _group_table(c)
  assert table == {"ConditionalExperimental": True}
  sd.reset_section(table, c.reset_write)
  profile_store.invalidate()
  assert profile_store.get_bool("ConditionalExperimental")
