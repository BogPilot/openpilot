"""Deterministic tests: real consumer calculations, no rendering/builds/road tests."""
from dataclasses import replace
from types import SimpleNamespace as NS
import importlib.util
import os
import numpy as np
import pytest
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.controls.lib.phase3_long_accel import (
  Profiles, Conditions, Scene, ConditionalMode, LongAccelPort, advanced_values, configure,
  PROFILE_ACK, ADVANCED_ACK, CEM_ACK,
)


class Store:
  def __init__(self, **values):
    self.values = values
    self.hidden = set()
    self.writes = []
  def default(self, key):
    return BOGPILOT_PARAMS.get(key, (None, None, '0'))[2] or '0'
  def get(self, key, default=None):
    return self.values.get(key, self.default(key) if default is None else default)
  def get_bool(self, key, default=None):
    return str(self.get(key, default)).lower() in ('1', 'true')
  def get_float(self, key):
    return float(self.get(key))
  def get_int(self, key):
    return int(self.get_float(key))
  def tuning_level(self):
    return 3
  def honoured(self, key, level=None):
    return key not in self.hidden
  def toggle_bool(self, key, level=None):
    return self.get_bool(key) if self.honoured(key) else str(self.default(key)) == '1'
  def toggle_float(self, key, level=None):
    return self.get_float(key) if self.honoured(key) else float(self.default(key))
  def toggle_int(self, key, level=None):
    return int(self.toggle_float(key))
  def put(self, key, value, block=False):
    self.values[key] = value
    self.writes.append((key, value))
  def put_bool(self, key, value, block=False):
    self.put(key, value)
  def invalidate(self):
    pass


def test_dormant_tuning_never_activates_without_explicit_action():
  s = Store(LongitudinalTune=1, AccelerationProfile=3, DecelerationProfile=2,
            AdvancedLongitudinalTune=1, LongitudinalActuatorDelay=1, MaxDesiredAcceleration=.1,
            ConditionalExperimental=1, CESpeed=99)
  cp = NS(longitudinalActuatorDelay=.25)
  assert Profiles.read(s) is None and Conditions.read(s) is None
  assert advanced_values(s, cp) == (.25, None)
  assert s.writes == []
  configure(s, 'AccelerationProfile', 1)
  assert Profiles.read(s).acceleration == 1
  assert Conditions.read(s) is None
  assert advanced_values(s, cp) == (.25, None)
  assert set(k for k, _ in s.writes) == {'AccelerationProfile', PROFILE_ACK}


@pytest.mark.parametrize('profile,speed,expected', [
  (0, 0, 2), (0, 10, 1.6), (0, 25, .8), (0, 40, .6),
  (1, 0, 2), (1, 5, 1.5), (1, 10, 1), (1, 15, .8), (1, 20, .6), (1, 25, .4), (1, 40, .2),
  (2, 0, 3), (2, 5, 2.5), (2, 10, 2), (2, 15, 1.5), (2, 20, 1), (2, 25, .8), (2, 40, .6),
  (3, 0, 4), (3, 5, 4), (3, 20, 2), (2, 7.5, 2.25), (1, 100, .2),
])
def test_exact_historical_acceleration_tables(profile, speed, expected):
  assert Profiles(profile).limits(speed, 30, -3.5)[1] == pytest.approx(expected)


@pytest.mark.parametrize('profile,floor', [(0, -3.5), (1, -1.75), (2, -.875)])
def test_deceleration_and_lead_braking_precedence(profile, floor):
  p = Profiles(deceleration=profile)
  assert p.limits(20, 15, -3.5)[0] == floor
  assert p.limits(20, 15, -3.5, True, force_coast=True, eco=True, map_deceleration=True)[0] == -3.5


def test_gear_human_weather_precedence_matches_old_consumer():
  p = Profiles(3, 2, True)
  assert p.limits(10, 10, -3.5)[1] == 0
  assert Profiles(2).limits(5, 30, -3.5, eco=True, map_acceleration=True)[1] == 1.5
  assert Profiles(2).limits(5, 30, -3.5, sport=True, map_acceleration=True)[1] == 2.5
  assert Profiles(1).limits(5, 30, -3.5, sport=True, map_acceleration=True)[1] == 4
  assert Profiles(2).limits(5, 30, -3.5, weather_reduction=.2)[1] == 2
  assert p.limits(20, 25, -3.5, force_coast=True)[0] == -1.75


@pytest.mark.parametrize('delay,cap,expected', [(-1, -1, (0, .1)), (2, 9, (1, 4)), (.6, 1.3, (.6, 1.3)), (float('nan'), float('nan'), (.25, 4))])
def test_advanced_range_and_nonfinite(delay, cap, expected):
  s = Store(**{ADVANCED_ACK: 1, 'AdvancedLongitudinalTune': 1,
               'LongitudinalActuatorDelay': delay, 'MaxDesiredAcceleration': cap})
  assert advanced_values(s, NS(longitudinalActuatorDelay=.25)) == expected
  s.hidden.update(('LongitudinalActuatorDelay', 'MaxDesiredAcceleration'))
  assert advanced_values(s, NS(longitudinalActuatorDelay=.25)) == (.25, None)


def test_metric_conversion_and_hidden_speed_fallback_is_mph():
  s = Store(**{CEM_ACK: 1, 'ConditionalExperimental': 1, 'IsMetric': 1, 'CESpeed': 36})
  assert Conditions.read(s).below == 10
  s.hidden.add('CESpeed')
  assert Conditions.read(s).below == float(s.default('CESpeed')) * .44704


def replay(scene, conditions, ticks=80):
  m = ConditionalMode()
  statuses = []
  for _ in range(ticks):
    m.update(scene, conditions)
    statuses.append(m.status)
  return m, statuses


@pytest.mark.parametrize('scene,conditions,status', [
  (Scene(10, model_length=300), Conditions(below=15), 4),
  (Scene(10, following_lead=True, model_length=300), Conditions(below_lead=15), 3),
  (Scene(10, blinker=True, model_length=300), Conditions(signal=15, signal_lane_detection=True, lane_width=3), 5),
  (Scene(10, intersection=True, model_length=300), Conditions(navigation=True), 6),
  (Scene(10, turn=True, model_length=300), Conditions(navigation=True), 7),
  (Scene(10, curve=True, model_length=300), Conditions(curves=True), 8),
  (Scene(10, tracking_lead=True, lead_speed=0, model_length=300), Conditions(lead=True, stopped_lead=True), 9),
  (Scene(20, tracking_lead=True, lead_speed=10, model_length=300), Conditions(lead=True, slower_lead=True), 10),
  (Scene(10, model_length=20), Conditions(model_stop_time=3), 11),
  (Scene(10, model_length=20, forcing_stop=True), Conditions(model_stop_time=3), 12),
  (Scene(10, model_length=300, slc_experimental=True), Conditions(), 13),
])
def test_cem_statuses_filters_and_precedence(scene, conditions, status):
  m, statuses = replay(scene, conditions)
  assert m.experimental and statuses[-1] == status
  if status in (8, 9, 10, 11, 12):
    assert statuses[0] == 0


def test_signal_exclusion_historical_quirk_and_standstill_latch():
  # Faithful: Not For Detected Lanes unchecked makes lane_available True,
  # therefore the old signal condition never triggers (do not silently fix it).
  s = Scene(10, blinker=True, model_length=300)
  assert not replay(s, Conditions(signal=20))[0].experimental
  assert not replay(replace(s, desired_lane_width=4), Conditions(signal=20, signal_lane_detection=True, lane_width=3))[0].experimental
  m, _ = replay(Scene(10, model_length=20), Conditions(model_stop_time=3))
  assert m.update(Scene(0, standstill=True, model_stopped=True), Conditions())
  assert not m.update(Scene(0, standstill=True), Conditions())
  assert m.update(s, Conditions(), override=2)
  assert not m.update(s, Conditions(below=20), override=1)


def test_cem_no_lead_stop_detection_and_traffic_mode_suppression():
  scene = Scene(10, model_length=20, tracking_lead=True, lead_speed=10)
  assert not replay(scene, Conditions(model_stop_time=3))[0].experimental
  assert not replay(replace(scene, tracking_lead=False, traffic_mode=True), Conditions(model_stop_time=3))[0].experimental


# The following use the real native AGNOS capnp messages, MPC and planner, not a mocked planner.
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import planner, SM, msgs
from openpilot.selfdrive.controls.lib.longitudinal_planner import get_cruise_accel
from openpilot.selfdrive.controls.lib.longcontrol import LongControl


def test_real_cruise_consumer_profile_changes_output_and_preserves_braking():
  cp = planner().CP
  def out(p):
    return get_cruise_accel(False, 30, 10, 0, 0, cp, 10, 1, True, p.limits(10, 30, -3.5))
  assert out(Profiles(1)) == 1
  assert out(Profiles(2)) == 1.7  # existing total-acceleration envelope wins
  low = get_cruise_accel(False, 0, 10, 0, 0, cp, 10, 1, True, Profiles(1, 2).limits(10, 0, -3.5))
  assert low == -.875


def test_native_planner_cem_adds_real_e2e_candidate():
  p = planner(toggle=False)
  p.long_accel.store = Store(**{CEM_ACK: 1, 'ConditionalExperimental': 1, 'CESpeed': 40,
                               'CEModelStopTime': 0, 'CESignalSpeed': 0})
  p.update(SM(msgs(10, 20, e2e_accel=-2)))
  assert p.long_accel.cem.status == 4 and p.output_a_target <= -2
  p.long_accel.store.values[CEM_ACK] = 0
  p.update(SM(msgs(10, 20, e2e_accel=-2)))
  assert not p.long_accel.cem.experimental and p.output_a_target > -2


@pytest.mark.parametrize('bad', ['gas', 'brake', 'disengaged', 'stale', 'no_long'])
def test_native_bridge_disengagement_and_stale_guards(bad):
  p = planner(toggle=False)
  p.long_accel.store = Store(**{CEM_ACK: 1, 'ConditionalExperimental': 1, 'CESpeed': 40})
  sm = SM(msgs(10, 20, enabled=bad != 'disengaged'))
  if bad == 'gas': sm['carState'].gasPressed = True
  if bad == 'brake': sm['carState'].brakePressed = True
  if bad == 'stale': sm.valid['modelV2'] = False
  if bad == 'no_long': p.CP.openpilotLongitudinalControl = False
  p.update(sm)
  assert not p.long_accel.cem.experimental


def test_native_actuator_cap_no_disengagement_bypass():
  cp = planner().CP
  control = LongControl(cp)
  control.long_accel_store = Store(**{ADVANCED_ACK: 1, 'AdvancedLongitudinalTune': 1, 'MaxDesiredAcceleration': .3})
  cs = SM(msgs(10, 20))['carState']
  assert control.update(True, cs, 2, False, [-3.5, 2]) == pytest.approx(.3)
  assert control.update(False, cs, 2, False, [-3.5, 2]) == 0


def test_no_ack_matches_actual_preport_planner_replay():
  path = os.environ.get('BASELINE_LONG_PLANNER')
  if not path:
    pytest.skip('Set BASELINE_LONG_PLANNER to committed c6582fc3e planner source')
  spec = importlib.util.spec_from_file_location('phase3_baseline_planner', path)
  baseline = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(baseline)
  p = planner(toggle=False)
  p.long_accel.store = Store()
  old = baseline.LongitudinalPlanner(p.CP)
  old.curve_speed = p.curve_speed
  for i in range(200):
    message = SM(msgs(10 + i / 100, 20, e2e_accel=-.4, experimental=i > 100))
    p.update(message)
    old.update(message)
    assert p.output_a_target == old.output_a_target
    assert p.output_should_stop == old.output_should_stop


def test_native_delay_used_by_actual_projection(monkeypatch):
  import openpilot.selfdrive.controls.lib.longitudinal_planner as native
  real = native.get_accel_from_plan
  seen = []
  def project(*args, **kwargs):
    seen.append(kwargs["action_t"])
    return real(*args, **kwargs)
  monkeypatch.setattr(native, "get_accel_from_plan", project)
  p = planner(toggle=False)
  p.long_accel.store = Store(**{ADVANCED_ACK: 1, 'AdvancedLongitudinalTune': 1, 'LongitudinalActuatorDelay': .8})
  p.update(SM(msgs(10, 20)))
  assert seen == [pytest.approx(.85)]


def test_native_profiles_change_real_output_not_metadata():
  outputs = []
  for profile in (1, 2):
    p = planner(toggle=False)
    p.long_accel.store = Store(**{PROFILE_ACK: 1, 'LongitudinalTune': 1, 'AccelerationProfile': profile,
                                 'DecelerationProfile': 0, 'HumanAcceleration': 0})
    for _ in range(100):
      p.update(SM(msgs(10, 30)))
    outputs.append(p.output_a_target)
  assert outputs[0] == pytest.approx(1)
  assert outputs[1] == pytest.approx(1.7)


def test_cem_model_observations_for_force_stop_contract():
  p = planner(toggle=False)
  p.long_accel.store = Store(**{CEM_ACK: 1, 'ConditionalExperimental': 1, 'CEModelStopTime': 3})
  for _ in range(80):
    p.update(SM(msgs(10, 20, model_v=1)))
  assert p.long_accel.model_valid and p.long_accel.model_horizon > 0
  assert p.long_accel.model_stopped and p.long_accel.cem.red_light
  sm = SM(msgs(10, 20, model_v=1), valid={'modelV2': False})
  p.update(sm)
  assert not p.long_accel.model_valid and not p.long_accel.cem.red_light


def test_old_v9_predicted_lead_never_assumed_for_current_model():
  from openpilot.selfdrive.controls.lib.phase3_long_accel import predicted_lead_flags
  lead = NS(dRel=15, vLead=15)
  model = NS(prob=.9, x=[15, 20, 25], v=[15, 10, 0])
  assert predicted_lead_flags(lead, model, 15, 1.45, "v9", .5) == (True, True)
  assert predicted_lead_flags(lead, model, 15, 1.45, "", .5) == (False, False)
  assert predicted_lead_flags(lead, model, 15, 1.45, "v10", .5) == (False, False)
  assert predicted_lead_flags(lead, model, 15, 1.45, "v9", .95) == (False, False)


def test_native_cem_lane_width_requires_real_geometry_and_units():
  from openpilot.selfdrive.controls.lib.phase3_long_accel import lane_width
  lane = NS(x=[0, 10], y=[4, 4])
  current = NS(x=[0, 10], y=[0, 0])
  assert lane_width(lane, current, NS(x=[0, 10], y=[3, 3])) == 0
  assert lane_width(lane, current, NS(x=[0, 10], y=[5, 5])) == 4
  assert lane_width(NS(x=[], y=[]), current, lane) is None
  store = Store(**{CEM_ACK: 1, 'ConditionalExperimental': 1, 'LaneChanges': 1,
                    'LaneDetectionWidth': 10, 'IsMetric': 0})
  assert Conditions.read(store).lane_width == pytest.approx(3.048)
  store.values['IsMetric'] = 1
  assert Conditions.read(store).lane_width == 10
