"""t994 gasAccelStop lane: production-store (async Params) race, stock-equivalent defaults, composed page.

All stores here are REAL compiled-Params ParamStore objects with PRODUCTION defaults (non-blocking put) unless a
test says otherwise: the lane-4 tests used a store whose setup writes were forced to block=True, which hides
the asynchronous-Params readback race this file is about. Stock baselines are the untouched feae source files
(BASELINE_* env, copied before the lane overlay). Synthetic native replays only - no route log, no road test.
"""
import os
from types import SimpleNamespace as NS
from pathlib import Path
import subprocess

import pytest
import pyray as rl
from opendbc.car.structs import car
from openpilot.common.bogpilot_store import ParamStore
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.longcontrol import LongControl, LongCtrlState
from openpilot.selfdrive.controls.lib.phase3_long_accel import (
  ADVANCED_ACK, CEM_ACK, PROFILE_ACK, ADVANCED_KEYS, advanced_values, configure,
)
from openpilot.selfdrive.controls.lib.phase3_long_stopping import (
  DISTANCE_ACK, FORCE_ACK, WEATHER_ACK, STOPPING_ACK, read_runtime_stopping,
)
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import planner, SM, msgs
from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake as GB
from openpilot.selfdrive.ui.bogpilot.phase3_stopping_settings import StoppingCapabilities, StoppingSettingsModel
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
from openpilot.system.ui.lib.application import gui_app

ALL_ACKS = (ADVANCED_ACK, PROFILE_ACK, CEM_ACK, DISTANCE_ACK, FORCE_ACK, WEATHER_ACK,
            "Phase3StopAccelEnabled", "Phase3StoppingRateEnabled")


@pytest.fixture(scope="module", autouse=True)
def window():
  # Real native Widgets/callbacks; font resource only is stubbed (no rendered-frame claim).
  original = gui_app.font
  gui_app.font = lambda *a, **kw: rl.Font()
  yield
  gui_app.font = original


@pytest.fixture
def prefs(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "prefs"))
  return tmp_path


def production_store(prefs, name="native"):
  return ParamStore(params=Params(str(prefs / name)))


@pytest.fixture
def store(prefs):
  s = production_store(prefs)
  s.put_bool("TuningLevelConfirmed", True, block=True)
  s.put("TuningLevel", 3, block=True)
  return s


def make_cp(long=True):
  cp = car.CarParams.new_message()
  cp.openpilotLongitudinalControl = long
  cp.stopAccel = -2
  cp.longitudinalActuatorDelay = .15
  cp.brand = "tesla"
  cp.carFingerprint = "TESLA_AP1_MODELS"
  cp.longitudinalTuning.kiBP = [0.0]
  cp.longitudinalTuning.kiV = [0.2]
  return cp


def stock_class(env, git_path, name):
  path = os.environ.get(env)
  source = Path(path).read_text() if path else subprocess.check_output(
    ["git", "show", f"feae029245e281e37667457a74387671458d716f:{git_path}"], text=True)
  namespace = {"__name__": name}
  exec(compile(source, name + ".py", "exec"), namespace)
  return namespace


def toggle(panel, key):
  panel.items[key].action_item.toggle._handle_mouse_release(None)


# ---------------------------------------------------------------------------------------------------
# 1. Mandatory: blocking Params store fix for the asynchronous compiled-Params readback race
# ---------------------------------------------------------------------------------------------------
class Recording(Params):
  def __init__(self, *a):
    super().__init__(*a)
    self.calls = []
  def put(self, key, dat, block=False):
    self.calls.append(("put", key, block))
    return super().put(key, dat, block=block)
  def put_bool(self, key, val, block=False):
    self.calls.append(("put_bool", key, block))
    return super().put_bool(key, val, block=block)


def test_store_block_keyword_reaches_compiled_params_for_every_type_and_defaults_to_async(prefs):
  rec = Recording(str(prefs / "rec"))
  s = ParamStore(params=rec)
  s.put_bool("ForceStops", True, block=True)          # BOOL
  s.put("IncreasedStoppedDistance", 3, block=True)    # INT
  s.put("StopAccel", -1.5, block=True)                # FLOAT
  s.put("BogPilotManualWeather", "rain", block=True)  # file-only key: block is ignored, never an error
  s.put_bool("ConditionalExperimental", False)        # default behaviour unchanged: asynchronous
  s.put("CESpeed", 10)
  assert ("put_bool", "ForceStops", True) in rec.calls
  assert ("put", "IncreasedStoppedDistance", True) in rec.calls
  assert ("put", "StopAccel", True) in rec.calls
  assert ("put_bool", "ConditionalExperimental", False) in rec.calls
  assert ("put", "CESpeed", False) in rec.calls
  assert (prefs / "prefs" / "BogPilotManualWeather").read_text() == "rain"


def test_blocking_write_is_visible_to_an_independent_reader_immediately_500_times(store, prefs):
  for i in range(500):
    value = round(-0.5 - (i % 350) * 0.01, 2)
    store.put("StopAccel", value, block=True)
    other = ParamStore(params=Params(store._params.d))
    assert other.get_float("StopAccel") == pytest.approx(value), i


@pytest.mark.parametrize("via", ["accel_controller", "stopping_model", "configure"])
def test_ui_callbacks_commit_preference_before_adoption_marker_and_survive_fresh_reader(store, via):
  cp = make_cp()
  order = []
  real_put, real_put_bool = store.put, store.put_bool
  store.put = lambda key, value, **kw: (order.append(("put", key, kw.get("block", False))), real_put(key, value, **kw))[1]
  store.put_bool = lambda key, value, **kw: (order.append(("put_bool", key, kw.get("block", False))), real_put_bool(key, value, **kw))[1]
  if via == "accel_controller":
    c = SettingsController("advanced", store, cp=cp)
    assert c.change("AdvancedLongitudinalTune", True)
    assert c.change("MaxDesiredAcceleration", 1.5)
    expect = [("MaxDesiredAcceleration", 1.5)]
    ack = ADVANCED_ACK
  elif via == "stopping_model":
    m = StoppingSettingsModel(store, cp, StoppingCapabilities(stopped_distance=True, force_stop_inputs=True), lambda: True)
    assert m.change("qol", "ForceStops", True)
    assert m.change("qol", "IncreasedStoppedDistance", value=2)
    expect = [("ForceStops", True), ("IncreasedStoppedDistance", 2)]
    ack = FORCE_ACK
  else:
    configure(store, "AccelerationProfile", 2)
    expect, ack = [("AccelerationProfile", 2)], PROFILE_ACK
  # Every preference + marker write was blocking, and the preference write came first.
  assert order and all(block for _, _, block in order), order
  names = [name for _, name, _ in order]
  # The first adoption-marker write happens only after the first preference write it adopts.
  first_pref = {"accel_controller": "AdvancedLongitudinalTune", "stopping_model": "ForceStops", "configure": "AccelerationProfile"}[via]
  assert names.index(ack) > names.index(first_pref)
  reader = ParamStore(params=Params(store._params.d))
  for key, value in expect:
    got = reader.get_bool(key) if isinstance(value, bool) else reader.get_float(key)
    assert got == (value if isinstance(value, bool) else pytest.approx(value))
  assert reader.get_bool(ack, False)


def test_adoption_marker_is_not_written_when_readback_fails(store):
  cp = make_cp()
  m = StoppingSettingsModel(store, cp, StoppingCapabilities(stopped_distance=True, force_stop_inputs=True), lambda: True)
  real = store.put_bool
  # A store whose write silently does not land (the async-race failure mode).
  store.put_bool = lambda key, value, **kw: None if key == "ForceStops" else real(key, value, **kw)
  assert m.change("qol", "ForceStops", True) is False
  assert store.raw(FORCE_ACK) is None and not store.get_bool("ForceStops")
  store.put_bool = real


def test_configure_refuses_a_store_without_the_blocking_integration(store):
  class NonBlocking(ParamStore):
    def put(self, key, value): return super().put(key, value)
    def put_bool(self, key, value): return super().put_bool(key, value)
  legacy = NonBlocking(params=Params(store._params.d))
  with pytest.raises(RuntimeError):
    configure(legacy, "AccelerationProfile", 2)
  assert legacy.raw(PROFILE_ACK) is None


# ---------------------------------------------------------------------------------------------------
# 2. Stock-equivalent defaults (real compiled Params, production store, nothing written)
# ---------------------------------------------------------------------------------------------------
def run_longcontrol_equivalence(cp, store, frames=5000, limits=(-3., 2.)):
  original = stock_class("BASELINE_LONGCONTROL", "openpilot/selfdrive/controls/lib/longcontrol.py", "stock_longcontrol")["LongControl"](cp)
  actual = LongControl(cp, stopping_store=store)
  cs = car.CarState.new_message()
  seen = set()
  for tick in range(frames):
    cs.vEgo = (tick % 100) / 10
    cs.aEgo = ((tick % 11) - 5) / 10
    cs.brakePressed = tick % 23 < 3
    cs.gasPressed = tick % 19 < 2
    cs.cruiseState.standstill = tick % 29 < 5
    active, stop = tick % 1000 >= 50, tick % 150 < 75
    target = ((tick % 17) - 8) / 5
    expected = original.update(active, cs, target, stop, limits)
    got = actual.update(active, cs, target, stop, limits)
    assert got == expected, tick
    assert actual.long_control_state == original.long_control_state, tick
    assert actual.pid.i == original.pid.i, tick
    seen.add(actual.long_control_state)
  assert seen == {LongCtrlState.off, LongCtrlState.stopping, LongCtrlState.pid}


def test_fresh_install_longcontrol_5000_frames_equal_stock_real_params(prefs):
  run_longcontrol_equivalence(make_cp(), production_store(prefs, "fresh"))


def test_dormant_saved_0_9_7_values_without_adoption_5000_frames_equal_stock_real_params(prefs):
  s = production_store(prefs, "dormant")
  for key, value in (("StopAccel", -4), ("StoppingDecelRate", .001), ("MaxDesiredAcceleration", .1),
                     ("LongitudinalActuatorDelay", 1.0), ("ForceStops", True), ("IncreasedStoppedDistance", 10)):
    s.put(key, value, block=True)
  s.put_bool("AdvancedLongitudinalTune", True, block=True)
  run_longcontrol_equivalence(make_cp(), s)


def test_adopting_only_the_advanced_parent_keeps_stock_5000_frames_and_cp_delay(prefs):
  """Enabling the parent with no child written must not change the controller or zero the actuator delay."""
  cp = make_cp()
  s = production_store(prefs, "parent_only")
  s.put_bool("TuningLevelConfirmed", True, block=True)
  s.put("TuningLevel", 3, block=True)
  assert SettingsController("advanced", s, cp=cp).change("AdvancedLongitudinalTune", True)
  assert s.get_bool(ADVANCED_ACK, False)
  assert advanced_values(s, cp) == (pytest.approx(.15), 4.0)
  assert read_runtime_stopping(s, cp).stop_accel == -2 and read_runtime_stopping(s, cp).stopping_decel_rate == 1.0
  run_longcontrol_equivalence(cp, s)


def planner_equivalence(prefs, name, prepare=None, frames=200):
  p = planner(toggle=False)
  p.long_accel.store = production_store(prefs, name)
  if prepare:
    prepare(p.long_accel.store, p.CP)
  module = stock_class("BASELINE_LONG_PLANNER", "openpilot/selfdrive/controls/lib/longitudinal_planner.py", "stock_planner")
  old = module["LongitudinalPlanner"](p.CP)
  old.curve_speed = p.curve_speed
  for tick in range(frames):
    sm = SM(msgs(10 + tick / 100, 20, model_v=1 if tick % 50 > 25 else 10 + tick / 100))
    p.update(sm)
    old.update(sm)
    assert p.output_a_target == old.output_a_target, tick
    assert p.output_should_stop == old.output_should_stop, tick
    assert not p.force_stop_result.forcing_stop
    assert not p.long_accel.cem.experimental


def test_fresh_install_planner_200_frames_equal_stock_real_params(prefs):
  planner_equivalence(prefs, "planner_fresh")


def test_dormant_saved_planner_values_without_adoption_200_frames_equal_stock(prefs):
  def prepare(s, cp):
    for key, value in (("AccelerationProfile", 3), ("DecelerationProfile", 2), ("LongitudinalActuatorDelay", .9),
                       ("CESpeed", 99)):
      s.put(key, value, block=True)
    for key in ("ForceStops", "ConditionalExperimental", "HumanAcceleration", "LongitudinalTune"):
      s.put_bool(key, True, block=True)
  planner_equivalence(prefs, "planner_dormant", prepare)


def test_parent_only_advanced_adoption_planner_200_frames_equal_stock(prefs):
  def prepare(s, cp):
    s.put_bool("TuningLevelConfirmed", True, block=True)
    s.put("TuningLevel", 3, block=True)
    assert SettingsController("advanced", s, cp=cp).change("AdvancedLongitudinalTune", True)
  planner_equivalence(prefs, "planner_parent_only", prepare)


def test_opening_the_page_and_every_subpanel_never_writes_a_preference_or_marker(store, prefs):
  cp = make_cp()
  watched = [*GB.CONTROLS, *ALL_ACKS, "AdvancedLongitudinalTune", "LongitudinalTune", "QOLLongitudinal",
             "CEStatus", "BogPilotManualWeather", *ADVANCED_KEYS]
  before = {k: store.raw(k) for k in watched}
  files = sorted(p.name for p in (prefs / "prefs").glob("*")) if (prefs / "prefs").exists() else []
  page = GB.create_gas_brake_layout(store, cp_source=lambda: cp, can_edit=lambda: True)
  page.show_event()
  for key, _, _ in GB.root_entries(store):
    page.open_panel(key)
    page.show_event()
  page.close_panel()
  page.hide_event()
  store._params.put_bool("IsMetric", True, block=True)   # stock compiled BOOL key: write via Params
  store.invalidate()
  page.show_event()
  assert {k: store.raw(k) for k in watched if k != "IsMetric"} == before
  assert sorted(p.name for p in (prefs / "prefs").glob("*")) == files


# ---------------------------------------------------------------------------------------------------
# 3. Composed Gas / Brake page: UI -> store -> consumer, live guards, no inert rows
# ---------------------------------------------------------------------------------------------------
def test_root_entries_cover_the_four_consumer_backed_groups_in_order(store):
  assert [(k, t) for k, t, _ in GB.root_entries(store)] == [
    ("advanced", "Advanced Longitudinal Tuning"), ("conditional", "Conditional Experimental Mode"),
    ("profiles", "Longitudinal Tuning"), ("qol", "Quality of Life")]


def test_advanced_panel_has_delay_max_accel_stop_accel_and_rate_and_hides_nothing_dormant(store):
  cp = make_cp()
  page = GB.create_gas_brake_layout(store, cp_source=lambda: cp, can_edit=lambda: True)
  page.show_event()
  page.open_panel("advanced")
  assert tuple(page.panel.items) == ("AdvancedLongitudinalTune",)           # nothing but the parent until adopted
  toggle(page.panel, "AdvancedLongitudinalTune")
  assert tuple(page.panel.items) == ("AdvancedLongitudinalTune", "LongitudinalActuatorDelay", "MaxDesiredAcceleration",
                                     "StopAccel", "StoppingDecelRate")  # t1003u: Stop rows registered
  c = page.panel.controller
  assert c.display_value("LongitudinalActuatorDelay") == pytest.approx(.15)
  assert store.raw("StopAccel") is None and store.raw("LongitudinalActuatorDelay") is None   # shown, never seeded


def test_stop_rows_registered_and_saved_legacy_values_stay_dormant_until_the_row_is_changed(store):
  """t1003u: rows are on the page; a saved 0.9.7 value never reaches LongControl until THAT row is changed."""
  assert "StopAccel" in GB.CONTROLS and "StoppingDecelRate" in GB.CONTROLS
  cp = make_cp()
  page = GB.create_gas_brake_layout(store, cp_source=lambda: cp, can_edit=lambda: True)
  page.show_event()
  page.open_panel("advanced")
  toggle(page.panel, "AdvancedLongitudinalTune")
  assert "StopAccel" in page.panel.items and "StoppingDecelRate" in page.panel.items
  store.put("StopAccel", -0.5); store.put("StoppingDecelRate", 0.1)
  control = LongControl(cp, stopping_store=ParamStore(params=Params(store._params.d)))
  cs = car.CarState.new_message()
  out = control.update(True, cs, 0, True, (-3., 2.))
  assert control.long_control_state == LongCtrlState.stopping
  assert out == pytest.approx(-1.0 * DT_CTRL)  # stock 1 m/s^3 ramp: saved values dormant


def test_int_t994_stop_bounds_clamped_in_runtime_reads(store):
  """INT review BLOCKER: legacy/saved StopAccel 0 or StoppingRate .001 must not reach the controller."""
  from openpilot.selfdrive.controls.lib import phase3_long_stopping as LS
  assert LS.STOP_ACCEL_CEILING == -0.5 and LS.STOPPING_RATE_FLOOR == 0.1
  assert LS.offset_lead({"present": True, "dRel": 1.0}, 10.0)["dRel"] == 0.5
  assert LS.offset_lead({"present": True, "dRel": 0.2}, 10.0)["dRel"] == 0.2
  assert LS.offset_lead({"present": True, "dRel": 30.0}, 3.0)["dRel"] == 27.0
  assert LS.offset_lead({"present": False, "dRel": 30.0}, 3.0)["dRel"] == 30.0
