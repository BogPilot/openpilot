"""Legacy SLC profile (Pre-AP Model S, AP1 Model X): what the one-time apply writes, what the SLC section resets
return, and that a device whose marker is set is never rewritten. Values are read from the profile module."""
import pytest

from openpilot.common.bogpilot_ap1_profile import (
  AP1_CAR_MODEL, AP1_PARAM_PROFILE, AP1_SLC_KEYS, AP1_SPEED_OFFSETS_MPH, LEGACY_SLC_PROFILE, MPH_TO_KPH,
  _profile_for_units, ap1_slc_profile_for_units,
  OLD_LEGACY_SLC_MARKER_NAMES, apply_legacy_slc_defaults_once, clear_ap1_defaults_marker, is_ap1, is_legacy_slc_platform,
  legacy_slc_marker_path, legacy_slc_profile_for_units,
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
  if car in (PREAP, AP1X):
    out["SLCOverride"] = "2"
    out.update({k: f"{v:.6f}" for k, v in zip(OFFSETS, offsets(metric))})
  if car == AP1X:
    out["ShowSLCOffset"] = "1"                             # the X gets the AP1 S profile's SLC keys, this one too (on)
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
  if car == PREAP:
    assert "ShowSLCOffset" not in written


@pytest.mark.parametrize("metric", [False, True])
def test_ap1x_gets_the_ap1_s_slc_keys_only(tmp_path, metric):
  p = fresh(AP1X, metric)
  s_profile = _profile_for_units(fresh(AP1_CAR_MODEL, metric))
  slc = ap1_slc_profile_for_units(p)
  assert slc == {k: v for k, v in s_profile.items() if k in AP1_SLC_KEYS}
  assert {k: v for k, v in legacy_slc_profile_for_units(p).items() if k in s_profile} == slc   # same as the S
  non_slc = set(s_profile) - set(AP1_SLC_KEYS)
  assert non_slc                                           # themes, personalities, ... exist in the S profile
  before = {k: p.get(k) for k in non_slc}
  written = apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert not set(written) & non_slc and {k: p.get(k) for k in non_slc} == before
  assert not is_ap1(p)


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
  p = fresh(car, metric)                                   # an upgraded device: old stock values saved, marker present
  p.vals.update(OLD)
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
def test_ap1x_section_reset_returns_the_ap1_slc_values(metric):
  ed, store = editor(AP1X, metric, **SAVED)
  # the legacy SLC profile, plus Conditional Experimental Mode off (every legacy Tesla)
  assert ss.slc_reset_profile(store) == {**legacy_slc_profile_for_units(store), "ConditionalExperimental": "0"}
  reset(ed, OFFSETS)
  assert [int(store.vals[k]) for k in OFFSETS] == offsets(metric)
  reset(ed, MAIN)
  assert {k: store.vals[k] for k in MAIN} == {"SLCOverride": "2", "SLCPriority1": "Dashboard", "SLCPriority2": "Map Data",
                                              "SLCPriority3": "Navigation", "SLCLookaheadLower": "5"}
  assert store.vals["ShowSLCOffset"] == "1"
  assert ed.profile_reset_rows(("ShowSLCOffset",)) == ("ShowSLCOffset",)
  store.vals["ShowSLCOffset"] = "0"                       # a saved off is only changed by the reset
  reset(ed, ("ShowSLCOffset",))
  assert store.vals["ShowSLCOffset"] == "1"
  assert store.vals["SLCFallback"] == "0" and "SLCLookaheadHigher" not in store.vals


@pytest.mark.parametrize("metric", [False, True])
def test_preap_section_reset_returns_the_legacy_profile(metric):
  ed, store = editor(PREAP, metric, **SAVED)
  # the legacy SLC profile, plus Conditional Experimental Mode off (every legacy Tesla)
  assert ss.slc_reset_profile(store) == {**legacy_slc_profile_for_units(store), "ConditionalExperimental": "0"}
  reset(ed, OFFSETS)
  assert [int(store.vals[k]) for k in OFFSETS] == offsets(metric)
  reset(ed, MAIN)
  assert {k: store.vals[k] for k in MAIN} == {"SLCOverride": "2", "SLCPriority1": "Dashboard", "SLCPriority2": "Map Data",
                                              "SLCPriority3": "Navigation", "SLCLookaheadLower": "5"}
  # no AP1-only key on Pre-AP: no profile row in Visual Settings (the panel shows no reset row there); its table is
  # the shipped default for the toggle (on), and Fallback (another section) keeps its saved value
  assert ed.profile_reset_rows(("ShowSLCOffset",)) == () and reset(ed, ("ShowSLCOffset",)) == {"ShowSLCOffset": True}
  assert (store.vals["ShowSLCOffset"], store.vals["SLCFallback"]) == ("1", "0")
  assert "SLCLookaheadHigher" not in store.vals


def _earlier_build_device(tmp_path, car, metric):
  """A device that ran an earlier build: the earlier marker is present (it was offered the sources / look-ahead only),
  everything else is still at the table defaults."""
  for name in OLD_LEGACY_SLC_MARKER_NAMES:
    (tmp_path / name).write_text("1\n")
  return fresh(car, metric)


@pytest.mark.parametrize("car", LEGACY_CARS)
@pytest.mark.parametrize("metric", [False, True])
def test_earlier_build_device_gets_the_added_speed_settings_once(tmp_path, car, metric):
  p = _earlier_build_device(tmp_path, car, metric)
  before = dict(p.vals)
  written = apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  added = {k: v for k, v in expected(car, metric).items() if k not in LEGACY_SLC_PROFILE}
  assert set(written) == set(added)
  for k, v in added.items():
    assert float(p.get(k)) == float(v) if k in OFFSETS else p.get(k) == v
  for k in LEGACY_SLC_PROFILE:                             # offered once already by the earlier build: kept as they are
    assert p.get(k) == before[k]
  assert legacy_slc_marker_path(tmp_path).exists()
  # Second run is a no-op.
  p.put("Offset1", "9")
  assert apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False) == []
  assert p.get("Offset1") == "9"


def test_earlier_build_device_keeps_saved_speed_values(tmp_path):
  p = _earlier_build_device(tmp_path, PREAP, False)
  p.put("Offset1", "3")
  p.put("SLCOverride", "0")
  apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert (p.get("Offset1"), p.get("SLCOverride")) == ("3", "0")
  assert float(p.get("Offset2")) == 5.0 and float(p.get("Offset5")) == 7.0


@pytest.mark.parametrize("car", LEGACY_CARS)
def test_toggle_reset_clears_the_earlier_build_marker_too(tmp_path, car):
  p = _earlier_build_device(tmp_path, car, False)
  apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  clear_ap1_defaults_marker(tmp_path)
  assert not legacy_slc_marker_path(tmp_path).exists()
  assert not any((tmp_path / name).exists() for name in OLD_LEGACY_SLC_MARKER_NAMES)
  p2 = fresh(car, False)
  apply_legacy_slc_defaults_once(p2, bogpilot_dir=tmp_path, refresh=False)
  for k, v in expected(car, False).items():               # full profile again, sources included
    assert float(p2.get(k)) == float(v) if k in OFFSETS else p2.get(k) == v

