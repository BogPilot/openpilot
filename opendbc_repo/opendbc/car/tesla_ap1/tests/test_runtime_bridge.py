"""Synthetic tests for AP1 bridges, using each target's stock car schema."""
from types import SimpleNamespace as NS
import numpy as np
import pytest
from openpilot.selfdrive.controls.lib.ap1_planning import Ap1Planning, comfort_distance_delta, lead_present
from openpilot.selfdrive.car import ap1_runtime as runtime

AP1 = "TESLA_AP1_MODELS"


class Params:
  def __init__(self, **values):
    self.values = values
  def get(self, key):
    # Unknown key is expected on an un-rebuilt tici params store.
    return self.values.get(key, b"0")


def car():
  return NS(bogpilot=NS(ap1StalkFollowS=1.45, ap1MotorTorqueNm=-30.0, ap1MotorRpm=3000.0, ap1AmbientTempC=20.0),
            vEgo=10.0, canValid=True, gasPressed=False, brakePressed=False, steeringAngleDeg=0.0,
            standstill=False, gearShifter="drive", cruiseState=NS(available=True, enabled=False))


def sm():
  return {"carState": car(), "radarState": NS(leadOne=NS(present=True, dRel=40.0, vLead=0.0)),
          "selfdriveState": NS(experimentalMode=False),
          "modelV2": NS(position=NS(x=[]), velocity=NS(x=[]))}


def planner(fp=AP1, long=True):
  return Ap1Planning(NS(carFingerprint=fp, openpilotLongitudinalControl=long), 0.05)


def test_default_regen_helpers_on_ap1_only(monkeypatch):
  import opendbc.car.tesla_ap1.regen_brake as rb
  import opendbc.car.tesla_ap1.regen_aware as ra
  # Avoid any machine-local toggle files; use explicit unset semantics.
  monkeypatch.setattr(rb, "_read_regen_comfort_file", lambda: "")
  monkeypatch.setattr("openpilot.selfdrive.controls.lib.ap1_planning.regen_aware_enabled", lambda fp: fp == AP1)
  p = planner()
  assert p.comfort_brake == 1.0
  assert p.regen_enabled
  for fp in ("TESLA_MODEL_3", "TESLA_MODEL_Y", "PREAP"):
    p = planner(fp)
    assert not p.regen_enabled and p.comfort_brake == 2.5
  assert not planner(long=False).active


def test_comfort_cost_preserves_steady_gap_and_adds_gap_to_stopped_lead():
  v = np.array([0.0, 5.0, 10.0, 20.0])
  delta = comfort_distance_delta(v, 1.0)
  assert np.all(delta >= 0.0) and delta[0] == 0
  # x_obstacle adjustment: stationary lead closer, steady lead cancels.
  assert np.all(comfort_distance_delta(v, 1.0) - delta == 0)
  assert np.all(comfort_distance_delta(np.zeros_like(v), 1.0) - delta <= 0)
  assert np.all(comfort_distance_delta(v, 2.5) == 0)


def test_follow_detents_are_ap1_only_and_require_enabled():
  cs = car()
  assert planner().t_follow(cs, True) == 1.45
  assert planner().t_follow(cs, False) is None
  assert planner("TESLA_MODEL_3").t_follow(cs, True) is None
  cs.bogpilot.ap1StalkFollowS = float("nan")
  assert planner().t_follow(cs, True) is None
  cs.bogpilot.ap1StalkFollowS = 1.0
  cs.vEgo = 0
  assert planner().t_follow(cs, True) == 0.5


def test_regen_stop_is_add_only_and_resets_on_driver_override():
  p, state = planner(), sm()
  for _ in range(40):
    assert p.shape_stop(state, -0.1, True) <= -0.1
  assert p.shape_stop(state, -3.0, True) == -3.0
  state['carState'].gasPressed = True
  assert p.shape_stop(state, 0.2, True) == 0.2
  assert not p.stop.active and p.stop.a_added == 0.0
  state['carState'].gasPressed = False
  assert p.shape_stop(state, 0.2, False) == 0.2


def test_regen_stop_ignores_model_without_experimental_mode():
  p, state = planner(), sm()
  state['radarState'].leadOne.present = False
  state['modelV2'] = NS(position=NS(x=[0, 10, 20]), velocity=NS(x=[10, 5, 0]))
  assert p.shape_stop(state, 0.2, True) == 0.2
  state['selfdriveState'].experimentalMode = True
  assert p.shape_stop(state, 0.2, True) < 0.2


def test_both_radar_schema_spellings():
  assert lead_present(NS(status=True)) and lead_present(NS(present=True))
  assert not lead_present(NS(status=False))


def test_aol_default_off_and_unavailable_safety_bit_is_fail_closed(monkeypatch):
  monkeypatch.setattr(runtime, "aol_bit", lambda: 8)
  cp = NS(carFingerprint=AP1, alternativeExperience=0)
  runtime.apply_ap1_alternative_experience(cp, Params())
  assert cp.alternativeExperience == 0
  runtime.apply_ap1_alternative_experience(cp, Params(AlwaysOnLateral=b"1"))
  assert cp.alternativeExperience == 8
  monkeypatch.setattr(runtime, "aol_bit", lambda: 0)
  cp.alternativeExperience = 0
  runtime.apply_ap1_alternative_experience(cp, Params(AlwaysOnLateral=b"1"))
  assert cp.alternativeExperience == 0


def test_aol_never_changes_stock_tesla(monkeypatch):
  monkeypatch.setattr(runtime, "aol_bit", lambda: 8)
  cp = NS(carFingerprint="TESLA_MODEL_3", alternativeExperience=0)
  runtime.apply_ap1_alternative_experience(cp, Params(AlwaysOnLateral=b"1"))
  assert cp.alternativeExperience == 0


def test_aol_requires_calibration_good_can_and_no_disable_events(monkeypatch):
  monkeypatch.setattr(runtime, "aol_bit", lambda: 8)
  p = runtime.Ap1Lateral(NS(carFingerprint=AP1, alternativeExperience=8), Params(AlwaysOnLateralMain=b"1"))
  cs = car()
  assert not p.update(cs, False, False, False)
  assert not p.update(cs, False, True, True)
  cs.canValid = False
  assert not p.update(cs, False, True, False)
  cs.canValid = True
  assert p.update(cs, False, True, False)
  cs.vEgo = 0
  assert not p.update(cs, False, True, False)


def test_ap1_volume_defaults_use_audible_profile_and_preserve_choices():
  class Store:
    def __init__(self):
      self.values = {"PromptVolume": "60"}
    def raw(self, key):
      return self.values.get(key)
    def put(self, key, value):
      self.values[key] = value
  store = Store()
  profile = {"AlertVolumeControl": "0", "EngageVolume": "101", "DisengageVolume": "101", "PromptVolume": "101"}
  changed = runtime.apply_ap1_volume_defaults(NS(carFingerprint=AP1), None, store, profile)
  assert set(changed) == {"AlertVolumeControl", "EngageVolume", "DisengageVolume"}
  assert store.values["PromptVolume"] == "60"
  assert store.values["AlertVolumeControl"] == "0"
  assert store.values["EngageVolume"] == store.values["DisengageVolume"] == "101"
  assert runtime.apply_ap1_volume_defaults(NS(carFingerprint=AP1), None, store, profile) == []
  assert runtime.apply_ap1_volume_defaults(NS(carFingerprint="TESLA_MODEL_3"), None) == []
