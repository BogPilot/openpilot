"""SLC section resets follow the car type's SLC reset profile (SLC_RESET_PROFILES): AP1 Model S maps to the
one-time AP1 profile, Pre-AP and AP1 Model X to the legacy SLC profile; every other car keeps the general table. The profile itself, the general table and saved
values are unchanged. The car-type cases are parametrized over ALL_CARS, so a new table entry is covered as is."""
import pytest

from openpilot.common.bogpilot_ap1_profile import (
  AP1_CAR_MODEL, AP1_PARAM_PROFILE, AP1_SPEED_OFFSETS_MPH, MPH_TO_KPH, _profile_for_units, apply_ap1_defaults_once,
  clear_ap1_defaults_marker, is_ap1, marker_path, theme_marker_path,
)
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import CP_AP1, FakeStore
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss
from openpilot.system.bogpilot.toggle_reset import shipping_defaults

OFFSETS = tuple(f"Offset{i}" for i in range(1, 8))
MAIN = ("SLCOverride", "SLCPriority1", "SLCPriority2", "SLCPriority3", "SLCLookaheadLower")
VISUALS = ("ShowSLCOffset",)
ALL_CARS = (AP1_CAR_MODEL, "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS", "TESLA_MODEL_3", None)
TODAY = {AP1_CAR_MODEL, "TESLA_PREAP_MODELS", "TESLA_AP1_MODELX"}   # car types with an SLC reset profile
OTHER_CARS = tuple(c for c in ALL_CARS if c not in TODAY)
SAVED = dict(SLCOverride="0", SLCPriority1="Map Data", SLCPriority2="Navigation", SLCPriority3="None", SLCLookaheadLower="9",
             ShowSLCOffset="1", SLCFallback="0", SLCConfirmation="1", SetSpeedLimit="1",
             **{k: str(20 + i) for i, k in enumerate(OFFSETS)})


def editor(car, metric=False, **vals):
  base = dict(SpeedLimitController="1", Phase3SpeedLimitEnabled="1", IsMetric="1" if metric else "0", **vals)
  if car is not None:
    base["CarModel"] = car
  store = FakeStore(**base)
  return ss.SlcEditor(CP_AP1, store, lambda: True), store


def reset(ed, keys):
  table = ed.section_defaults(keys)
  for k, v in table.items():
    ed.reset_write(k, v)
  return table


def expected_offsets(metric):
  return [round(m * MPH_TO_KPH) if metric else m for m in AP1_SPEED_OFFSETS_MPH.values()]


def test_profile_values_used_by_the_reset():
  # the reset reads the profile; these are the values it holds (unchanged by this feature)
  assert AP1_SPEED_OFFSETS_MPH == {"Offset1": 4, "Offset2": 5, "Offset3": 5, "Offset4": 5, "Offset5": 7, "Offset6": 8,
                                   "Offset7": 10}
  slc = {k: AP1_PARAM_PROFILE[k] for k in AP1_PARAM_PROFILE if k.startswith("SLC") or k == "ShowSLCOffset"}
  assert slc == {"SLCOverride": "2", "SLCPriority1": "Dashboard", "SLCPriority3": "Navigation",
                 "SLCLookaheadHigher": "0", "SLCLookaheadLower": "5", "ShowSLCOffset": "0"}
  assert expected_offsets(False) == [4, 5, 5, 5, 7, 8, 10]
  assert expected_offsets(True) == [6, 8, 8, 8, 11, 13, 16]


@pytest.mark.parametrize("metric", [False, True])
def test_ap1_s_reset_writes_the_ap1_profile_values(metric):
  ed, store = editor(AP1_CAR_MODEL, metric, **SAVED)
  assert is_ap1(store)
  reset(ed, OFFSETS)
  assert [int(store.vals[k]) for k in OFFSETS] == expected_offsets(metric)
  assert [ed.default_text(k) for k in OFFSETS] == [f"+{v} " + ("km/h" if metric else "mph") for v in expected_offsets(metric)]
  # the offsets page reset leaves the main section and the sub pages alone
  assert {k: store.vals[k] for k in MAIN + VISUALS} == {k: SAVED[k] for k in MAIN + VISUALS}
  reset(ed, MAIN)
  assert {k: store.vals[k] for k in MAIN} == {"SLCOverride": "2", "SLCPriority1": "Dashboard", "SLCPriority2": "Map Data",
                                              "SLCPriority3": "Navigation", "SLCLookaheadLower": "5"}
  assert store.vals["ShowSLCOffset"] == "1"
  reset(ed, VISUALS)
  assert store.vals["ShowSLCOffset"] == "0"
  # rows outside the reset sections are never touched by any reset
  assert (store.vals["SLCFallback"], store.vals["SLCConfirmation"], store.vals["SetSpeedLimit"]) == ("0", "1", "1")
  assert "SLCLookaheadHigher" not in store.vals      # profile key without a row: not written by the panel


@pytest.mark.parametrize("metric", [False, True])
def test_ap1_s_defaults_follow_the_profiles_own_table(metric):
  ed, store = editor(AP1_CAR_MODEL, metric)
  profile = _profile_for_units(store)
  for k in OFFSETS:
    assert ed.default(k) == int(float(profile[k]))
  assert ed.reset_profile_values() == {k: v for k, v in profile.items() if k in ss.BY_KEY}
  assert ed.profile_reset_rows(MAIN + VISUALS + OFFSETS) == ("SLCOverride", "ShowSLCOffset")


def test_todays_mapping():
  assert [e[0] for e in ss.SLC_RESET_PROFILES] == ["TESLA_AP1_MODELS", "TESLA_PREAP_MODELS", "TESLA_AP1_MODELX"]
  assert {c for c in ALL_CARS if ss.slc_reset_profile(editor(c)[1]) is not None} == TODAY
  ed, store = editor(AP1_CAR_MODEL)
  assert ss.slc_reset_profile(store) == _profile_for_units(store)      # read from the profile, nothing copied


def expected_reset(store, keys, profile):
  """What a reset of keys must store: the profile's value when the car type has one for the key, else the shipped
  default (value rows: the registry default the panel shows; toggle / choice rows: shipping_defaults())."""
  out = {}
  shipped = shipping_defaults()
  for k in keys:
    fallback = shipped[k] if ss.BY_KEY[k][1] in ("choice", "toggle") else BOGPILOT_PARAMS[k][2]
    text = (profile or {}).get(k, fallback)
    kind = ss.BY_KEY[k][1]
    if kind in ("offset", "seconds", "choice"):
      out[k] = str(int(float(text)))
    elif kind == "toggle":
      out[k] = "1" if text == "1" else "0"
    else:
      out[k] = text
  return out


@pytest.mark.parametrize("car", ALL_CARS)
@pytest.mark.parametrize("metric", [False, True])
def test_every_car_type_resets_to_its_profile_or_the_general_table(car, metric):
  ed, store = editor(car, metric, **SAVED)
  profile = ss.slc_reset_profile(store)
  assert (profile is not None) == (car in TODAY)
  for keys in (OFFSETS, MAIN, VISUALS):
    reset(ed, keys)
  # the whole section resets: every row (choice / toggle rows too) to the profile's value, else the shipped default
  resettable = OFFSETS + MAIN + VISUALS
  assert {k: store.vals[k] for k in resettable} == expected_reset(store, resettable, profile)
  # rows outside the reset sections keep the saved value
  assert (store.vals["SLCFallback"], store.vals["SLCConfirmation"], store.vals["SetSpeedLimit"]) == ("0", "1", "1")


@pytest.mark.parametrize("car", OTHER_CARS)
@pytest.mark.parametrize("metric", [False, True])
def test_other_cars_reset_to_the_general_table(car, metric):
  ed, store = editor(car, metric, **SAVED)
  assert not is_ap1(store)
  assert ed.reset_profile_values() == {} and ed.profile_reset_rows(MAIN + VISUALS) == ()
  reset(ed, OFFSETS)
  assert [int(store.vals[k]) for k in OFFSETS] == [int(BOGPILOT_PARAMS[k][2]) for k in OFFSETS]
  reset(ed, MAIN)
  assert {k: store.vals[k] for k in MAIN} == {"SLCOverride": shipping_defaults()["SLCOverride"],
                                              "SLCPriority1": "Navigation", "SLCPriority2": "Map Data",
                                              "SLCPriority3": "Dashboard", "SLCLookaheadLower": "5"}
  # a toggle-only section resets its toggle to the shipped default (the panel shows no reset row there on these cars)
  assert reset(ed, VISUALS) == {"ShowSLCOffset": shipping_defaults()["ShowSLCOffset"] == "1"}
  assert store.vals["ShowSLCOffset"] == shipping_defaults()["ShowSLCOffset"]


def test_general_table_is_unchanged():
  assert [BOGPILOT_PARAMS[k][2] for k in OFFSETS] == ["5"] * 4 + ["10"] * 3
  assert {k: BOGPILOT_PARAMS[k][2] for k in MAIN + VISUALS} == {
    "SLCOverride": "1", "SLCPriority1": "Navigation", "SLCPriority2": "Map Data", "SLCPriority3": "Dashboard",
    "SLCLookaheadLower": "5", "ShowSLCOffset": BOGPILOT_PARAMS["ShowSLCOffset"][2]}


def test_reset_is_refused_onroad_and_reading_never_writes():
  ed, store = editor(AP1_CAR_MODEL, **SAVED)
  ed.offroad = lambda: False
  assert ed.section_defaults(OFFSETS + MAIN + VISUALS) == {}
  ed2, store2 = editor(AP1_CAR_MODEL)
  [ed2.default_text(k) for k in OFFSETS + MAIN]
  ed2.section_defaults(OFFSETS + MAIN + VISUALS)
  assert store2.puts == []


class FakeParams:
  def __init__(self, **vals):
    self.vals = dict(vals)

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value):
    self.vals[key] = value

  def invalidate(self):
    pass


def fresh(**vals):
  p = FakeParams(**vals)
  for k, (_f, _t, d, lvl, _s) in BOGPILOT_PARAMS.items():
    if d is not None and lvl is not None and p.get(k) is None:
      p.put(k, d)
  return p


@pytest.mark.parametrize("metric", ["0", "1"])
def test_settings_reset_clears_the_marker_and_the_profile_reapplies(tmp_path, metric):
  """Reset BogPilot Settings to Defaults writes shipping_defaults() and clears the AP1 marker (DoToggleReset path);
  the next start applies the AP1 profile again, offsets included."""
  p = fresh(CarModel=AP1_CAR_MODEL, IsMetric=metric)
  apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert marker_path(tmp_path).exists()
  for k in OFFSETS + ("SLCOverride",):
    p.put(k, "33")                                   # user edits after the first apply
  values = shipping_defaults()
  for k in OFFSETS + ("SLCOverride", "SLCPriority1", "SLCPriority3", "SLCLookaheadLower", "ShowSLCOffset"):
    p.put(k, values[k])
  clear_ap1_defaults_marker(tmp_path)
  assert not marker_path(tmp_path).exists()
  written = apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert set(OFFSETS) <= set(written) and marker_path(tmp_path).exists()
  assert [float(p.get(k)) for k in OFFSETS] == [float(v) for v in expected_offsets(metric == "1")]
  assert (p.get("SLCOverride"), p.get("SLCPriority1"), p.get("SLCPriority3"), p.get("ShowSLCOffset")) == \
         ("2", "Dashboard", "Navigation", "0")


def test_settings_reset_runs_both_steps():
  from pathlib import Path
  src = (Path(ss.__file__).resolve().parents[2] / "bogpilot/phase3_system_utilities.py").read_text()
  body = src[src.index("def reset_bogpilot_defaults"):]
  body = body[:body.index("\n  def ", 1)]
  assert "values = shipping_defaults()" in body and "clear_ap1_defaults_marker(directory)" in body


@pytest.mark.parametrize("car", tuple(c for c in ALL_CARS if c is not None))
@pytest.mark.parametrize("metric", ["0", "1"])
def test_upgrade_with_the_marker_set_never_rewrites(tmp_path, car, metric):
  marker_path(tmp_path).write_text("1\n")
  theme_marker_path(tmp_path).write_text("1\n")
  p = FakeParams(CarModel=car, IsMetric=metric, **SAVED)
  before = dict(p.vals)
  assert apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False) == []
  assert p.vals == before
