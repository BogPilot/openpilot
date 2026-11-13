"""Legacy SLC profile (Pre-AP Model S, AP1 Model X): what the one-time apply writes, what the SLC section resets
return, and that a device whose marker is set is never rewritten. Values are read from the profile module."""
import pytest

from openpilot.common.bogpilot_ap1_profile import (
  AP1_CAR_MODEL, AP1_PARAM_PROFILE, AP1_SPEED_OFFSETS_MPH, LEGACY_SLC_PROFILE, MPH_TO_KPH,
  apply_legacy_slc_defaults_once, clear_ap1_defaults_marker, is_ap1, is_legacy_slc_platform, legacy_slc_marker_path,
  legacy_slc_profile_for_units,
)
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import CP_AP1, FakeStore
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss
from openpilot.system.bogpilot.toggle_reset import shipping_defaults

PREAP, AP1X = "TESLA_PREAP_MODELS", "TESLA_AP1_MODELX"
ALL_CARS = (AP1_CAR_MODEL, AP1X, PREAP, "TESLA_MODEL_3", None)
LEGACY_CARS = (AP1X, PREAP)
OFFSETS = tuple(f"Offset{i}" for i in range(1, 8))
MAIN = ("SLCOverride", "SLCPriority1", "SLCPriority2", "SLCPriority3", "SLCLookaheadLower")
SHARED = {"SLCPriority1": "Dashboard", "SLCPriority2": "Map Data", "SLCPriority3": "Navigation",
          "SLCLookaheadLower": "5", "SLCLookaheadHigher": "0"}
OLD = {**{k: "5" for k in OFFSETS[:4]}, **{k: "10" for k in OFFSETS[4:]}}       # the general table's offsets


def offsets(metric):
  return [round(m * MPH_TO_KPH) if metric else m for m in AP1_SPEED_OFFSETS_MPH.values()]


def expected(car, metric):
  """The legacy SLC values each car type receives (stored text)."""
  out = dict(SHARED)
  if car == PREAP:
    out["SLCOverride"] = "2"
    out.update({k: f"{v:.6f}" for k, v in zip(OFFSETS, offsets(metric))})
  return out


class FakeParams:
  def __init__(self, **vals):
    self.vals = dict(vals)

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value):
    self.vals[key] = value

  def invalidate(self):
    pass


def fresh(car, metric):
  p = FakeParams(IsMetric="1" if metric else "0")
  if car is not None:
    p.vals["CarModel"] = car
  for k, (_f, _t, d, lvl, _s) in BOGPILOT_PARAMS.items():
    if d is not None and lvl is not None and p.get(k) is None:
      p.put(k, d)
  return p


def test_shared_profile_and_sources_are_unchanged():
  assert LEGACY_SLC_PROFILE == SHARED
  assert offsets(False) == [4, 5, 5, 5, 7, 8, 10] and offsets(True) == [6, 8, 8, 8, 11, 13, 16]
  assert AP1_PARAM_PROFILE["SLCOverride"] == "2"
  assert BOGPILOT_PARAMS["SLCFallback"][2] == "2"         # Previous Limit, the same as AP1; never written here


@pytest.mark.parametrize("car", ALL_CARS)
@pytest.mark.parametrize("metric", [False, True])
def test_profile_by_car_type(car, metric):
  p = fresh(car, metric)
  assert legacy_slc_profile_for_units(p) == (expected(car, metric) if car in LEGACY_CARS else {})


@pytest.mark.parametrize("car", ALL_CARS)
def test_is_ap1_is_unchanged(car):
  p = fresh(car, False)
  assert is_ap1(p) == (car == AP1_CAR_MODEL)
  assert is_legacy_slc_platform(p) == (car in LEGACY_CARS)


@pytest.mark.parametrize("car", ALL_CARS)
@pytest.mark.parametrize("metric", [False, True])
def test_fresh_install_apply(tmp_path, car, metric):
  p = fresh(car, metric)
  before = dict(p.vals)
  written = apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  if car not in LEGACY_CARS:
    assert written == [] and p.vals == before
    return
  want = expected(car, metric)
  assert set(written) <= set(want)
  for k, v in want.items():
    assert float(p.get(k)) == float(v) if k in OFFSETS else p.get(k) == v
  # nothing outside the expected SLC keys is written: no ShowSLCOffset, no other AP1 profile key
  assert {k: v for k, v in p.vals.items() if k not in want} == {k: v for k, v in before.items() if k not in want}
  if car == AP1X:
    assert [p.get(k) for k in OFFSETS] == [OLD[k] for k in OFFSETS] and p.get("SLCOverride") == before["SLCOverride"]


def test_metric_ui_converted_default_counts_as_default(tmp_path):
  p = fresh(PREAP, True)
  for k in OFFSETS:
    p.put(k, str(int(float(OLD[k]) * MPH_TO_KPH)))         # the settings UI's km/h conversion of the table default
  apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert [float(p.get(k)) for k in OFFSETS] == [float(v) for v in offsets(True)]


@pytest.mark.parametrize("car", LEGACY_CARS)
@pytest.mark.parametrize("metric", [False, True])
def test_marker_set_never_rewrites(tmp_path, car, metric):
  legacy_slc_marker_path(tmp_path).write_text("1\n")
  p = fresh(car, metric)                                   # an upgraded device: old table values, marker present
  before = dict(p.vals)
  assert apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False) == []
  assert p.vals == before and [p.get(k) for k in OFFSETS] == [OLD[k] for k in OFFSETS]


def test_saved_values_are_kept(tmp_path):
  p = fresh(PREAP, False)
  p.put("Offset1", "3")
  p.put("SLCOverride", "0")
  apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert (p.get("Offset1"), p.get("SLCOverride")) == ("3", "0")
  assert float(p.get("Offset2")) == 5.0 and float(p.get("Offset5")) == 7.0


@pytest.mark.parametrize("car", LEGACY_CARS)
@pytest.mark.parametrize("metric", [False, True])
def test_toggle_reset_clears_the_marker_and_the_profile_reapplies(tmp_path, car, metric):
  p = fresh(car, metric)
  apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  for k in OFFSETS + MAIN:
    p.put(k, "1")                                          # user edits after the first apply
  values = shipping_defaults()                             # Reset BogPilot Settings (DoToggleReset)
  for k in OFFSETS + MAIN + ("SLCLookaheadHigher", "ShowSLCOffset"):
    p.put(k, values.get(k, BOGPILOT_PARAMS[k][2]))
  clear_ap1_defaults_marker(tmp_path)
  assert not legacy_slc_marker_path(tmp_path).exists()
  apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert legacy_slc_marker_path(tmp_path).exists()
  for k, v in expected(car, metric).items():
    assert float(p.get(k)) == float(v) if k in OFFSETS else p.get(k) == v


SAVED = dict(SLCOverride="0", SLCPriority1="Map Data", SLCPriority2="Navigation", SLCPriority3="None",
             SLCLookaheadLower="9", ShowSLCOffset="1", SLCFallback="0", **{k: str(20 + i) for i, k in enumerate(OFFSETS)})


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


@pytest.mark.parametrize("metric", [False, True])
def test_preap_section_reset_returns_the_legacy_profile(metric):
  ed, store = editor(PREAP, metric, **SAVED)
  assert ss.slc_reset_profile(store) == legacy_slc_profile_for_units(store)
  reset(ed, OFFSETS)
  assert [int(store.vals[k]) for k in OFFSETS] == offsets(metric)
  reset(ed, MAIN)
  assert {k: store.vals[k] for k in MAIN} == {"SLCOverride": "2", "SLCPriority1": "Dashboard", "SLCPriority2": "Map Data",
                                              "SLCPriority3": "Navigation", "SLCLookaheadLower": "5"}
  # no AP1-only key on Pre-AP: Visual Settings has nothing to reset, Show Speed Limit Offset keeps its value
  assert ed.profile_reset_rows(("ShowSLCOffset",)) == () and reset(ed, ("ShowSLCOffset",)) == {}
  assert (store.vals["ShowSLCOffset"], store.vals["SLCFallback"]) == ("1", "0")
  assert "SLCLookaheadHigher" not in store.vals
