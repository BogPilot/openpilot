"""Tesla AP1 (BogStar) planner-side wiring of the BogPilot milestone 3 / 4 work.

- StarPilotVCruise AP1 set-speed layer: stalk UP/DN engage = sticky vEgo, RWD pull engage = SLC+offset,
  engaged tip holds through posted-limit changes until a pull, full tip = next 5, the < 15 mph posted-limit
  guard, and the StarPilot persistent set-speed SLC override being off for AP1 only.
- LongitudinalPlanner: AP1 throttle cap fraction (Ap1ThrottleCap) instead of the 0/1 gate, and the AP1
  regen comfort brake handed to the lead MPC.
- long_mpc comfort-brake helpers.
- TeslaAp1CardHooks stalk levels and the cluster set lift.

Unit tests only. Not a drive test.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import log
from openpilot.common.constants import CV
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.starpilot.controls.lib.starpilot_vcruise import StarPilotVCruise
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import (
  COMFORT_BRAKE, comfort_distance_delta, desired_follow_distance, get_safe_obstacle_distance,
  get_stopped_equivalence_factor,
)
import opendbc.car.tesla.ap1_regen_brake as regen

AP1 = "TESLA_MODEL_S_HW1"
MPH = CV.MPH_TO_MS


# --- StarPilotVCruise AP1 set-speed layer ------------------------------------

class _Params:
  def get(self, *a, **k): return None
  def get_float(self, *a, **k): return 0.0
  def get_bool(self, *a, **k): return False
  def put_nonblocking(self, *a, **k): pass
  put = put_nonblocking


class Drive:
  """Feeds StarPilotVCruise.update at 20 Hz with a posted limit, the DI_cruiseSet based v_cruise and stalk levels."""

  def __init__(self, car_model=AP1, limit_mph=45.0, offset_mph=5.0):
    planner = SimpleNamespace(
      params=_Params(), params_memory=_Params(), starpilot_cem=SimpleNamespace(stop_light_detected=False),
      model_length=200.0, driving_in_curve=False, tracking_lead=False,
      lead_one=SimpleNamespace(status=False, dRel=200.0, vLead=0.0),
      starpilot_following=SimpleNamespace(following_lead=False), road_curvature=0.0, raw_model_stopped=False)
    self.vc = StarPilotVCruise(planner)
    self.limit_mph, self.offset_mph = limit_mph, offset_mph
    self.vc.slc.update_limits = self._limits
    self.vc.slc.get_offset = lambda target: self.offset_mph * MPH if target > 0 else 0.0
    self.toggles = SimpleNamespace(
      speed_limit_controller=True, show_speed_limits=True, car_model=car_model, force_stops=False,
      force_standstill=False, curve_speed_controller=False, is_metric=False, set_speed_limit=False,
      redneck_cruise=False, nav_longitudinal_allowed=False, speed_limit_confirmation_lower=False,
      speed_limit_confirmation_higher=False, force_stop_distance_offset=0)
    self.enabled = False
    self.v_ego_mph = 37.0
    self.di_set_mph = 0.0
    self.t = 0.0

  def _limits(self, *a, **k):
    slc = self.vc.slc
    slc.target = self.limit_mph * MPH
    slc.source = "Dashboard" if slc.target > 0 else "None"

  def step(self, up=False, dn=False, rwd=False, spd=0, gas=False, n=1):
    v = 0.0
    for _ in range(n):
      self.t += 0.05
      sm = {
        "carState": SimpleNamespace(cruiseState=SimpleNamespace(enabled=self.enabled), vEgo=self.v_ego_mph * MPH,
                                    vEgoCluster=self.v_ego_mph * MPH, gasPressed=gas, brakePressed=False,
                                    standstill=False, vCruiseCluster=self.di_set_mph * CV.MPH_TO_KPH,
                                    leftBlinker=False, rightBlinker=False, steeringAngleDeg=0.0),
        "carControl": SimpleNamespace(longActive=self.enabled),
        "carParams": SimpleNamespace(carFingerprint=self.toggles.car_model, minSteerSpeed=0.0),
        "selfdriveState": SimpleNamespace(enabled=self.enabled),
        "starpilotCarState": SimpleNamespace(accelPressed=up, decelPressed=dn, resumePressed=rwd, spdCtrlLvr=spd,
                                             dashboardSpeedLimit=0.0, dashboardStopSign=0,
                                             alwaysOnLateralEnabled=False),
        "modelV2": SimpleNamespace(action=SimpleNamespace(shouldStop=False)),
        "starpilotRadarState": SimpleNamespace(),
      }
      v_cruise = self.di_set_mph * MPH if self.enabled else 255.0 * CV.KPH_TO_MS
      v = self.vc.update(self.enabled, self.t, True, v_cruise, self.v_ego_mph * MPH, sm, self.toggles)
    return v / MPH

  def engage(self, how):
    """Tesla clears the stalk before cruise enables; the planner sees the stalk then the enable."""
    self.step(up=how == "up", dn=how == "dn", rwd=how == "rwd", n=2)
    self.step(n=2)
    self.enabled = True
    # DI_cruiseSet on engage: about vEgo (UP/DN) or the stock set; the AP1 layer must not follow it.
    self.di_set_mph = self.v_ego_mph
    return self.step(n=4)


def test_stalk_up_engage_is_sticky_vego_through_limit_changes():
  d = Drive(limit_mph=45.0)
  assert d.engage("up") == pytest.approx(37.0, abs=0.05)
  d.limit_mph = 55.0
  assert d.step(n=20) == pytest.approx(37.0, abs=0.05)
  d.limit_mph = 25.0
  assert d.step(n=60) == pytest.approx(37.0, abs=0.05)


def test_pull_engage_goes_to_slc_plus_offset_and_tracks_limits():
  d = Drive(limit_mph=45.0)
  assert d.engage("rwd") == pytest.approx(50.0, abs=0.05)
  d.limit_mph = 55.0
  assert d.step(n=4) == pytest.approx(60.0, abs=0.05)


def test_engaged_tip_holds_through_zone_change_until_pull():
  d = Drive(limit_mph=45.0)
  d.engage("rwd")
  assert d.step(up=True, spd=16) == pytest.approx(51.0, abs=0.05)
  assert d.step(n=4) == pytest.approx(51.0, abs=0.05)
  d.limit_mph = 35.0
  assert d.step(n=60) == pytest.approx(51.0, abs=0.05)
  d.limit_mph = 65.0
  assert d.step(n=20) == pytest.approx(51.0, abs=0.05)
  # Engaged pull: back to SLC+offset (the ~2 s hold toggles Experimental mode in card, not here).
  d.step(rwd=True)
  assert d.step(n=4) == pytest.approx(70.0, abs=0.05)


def test_full_tip_goes_to_next_and_previous_five():
  d = Drive(limit_mph=45.0)
  d.engage("up")  # sticky 37
  assert d.step(up=True, spd=4) == pytest.approx(40.0, abs=0.05)
  d.step(n=2)
  assert d.step(dn=True, spd=8) == pytest.approx(35.0, abs=0.05)


def test_low_posted_limit_is_ignored_and_big_drop_needs_persistence():
  d = Drive(limit_mph=45.0)
  d.engage("rwd")
  d.limit_mph = 5.0  # the route 2a blip
  assert d.step(n=40) == pytest.approx(50.0, abs=0.05)
  d.limit_mph = 25.0  # 45 -> 25: sudden drop, must persist 2 s
  assert d.step(n=20) == pytest.approx(50.0, abs=0.05)
  assert d.step(n=30) == pytest.approx(30.0, abs=0.05)


def test_persistent_set_speed_override_off_for_ap1_only():
  ap1 = Drive()
  ap1.step()
  assert ap1.vc.slc.set_speed_override_enabled is False
  other = Drive(car_model="HONDA_CIVIC")
  other.step()
  assert other.vc.slc.set_speed_override_enabled is True
  assert other.vc.ap1_raise_holdoff.tip_ms == 0.0


def test_non_ap1_car_does_not_use_ap1_layer():
  d = Drive(car_model="HONDA_CIVIC", limit_mph=45.0)
  d.engage("up")
  # Stock StarPilot: min(v_cruise, SLC+offset); no sticky / tip authority.
  assert d.step(n=4) == pytest.approx(min(37.0, 50.0), abs=0.05)
  assert not d.vc.ap1_raise_holdoff.sticky_vego


def test_disengage_clears_tip():
  d = Drive(limit_mph=45.0)
  d.engage("rwd")
  d.step(up=True, spd=16)
  d.step(n=2)
  d.enabled = False
  d.step(n=2)
  assert d.vc.ap1_raise_holdoff.tip_ms == 0.0
  assert d.vc.slc.overridden_speed == 0


# --- long_mpc comfort brake ---------------------------------------------------

def test_comfort_distance_delta():
  assert comfort_distance_delta(20.0, COMFORT_BRAKE) == 0.0
  assert comfort_distance_delta(0.0, 1.0) == 0.0
  v = np.array([0.0, 10.0, 20.0])
  expected = 0.5 * (1 / 1.0 - 1 / COMFORT_BRAKE) * v ** 2
  assert np.allclose(comfort_distance_delta(v, 1.0), expected)


def test_desired_follow_distance_comfort_brake():
  assert desired_follow_distance(20.0, 15.0, 1.45) == pytest.approx(desired_follow_distance(20.0, 15.0, 1.45, COMFORT_BRAKE))
  stock = desired_follow_distance(20.0, 15.0, 1.45)
  regen_gap = desired_follow_distance(20.0, 15.0, 1.45, comfort_brake=1.0)
  assert regen_gap - stock == pytest.approx(0.5 * (1 / 1.0 - 1 / COMFORT_BRAKE) * (20.0 ** 2 - 15.0 ** 2))
  assert get_safe_obstacle_distance(0.0, 1.45, 1.0) == get_safe_obstacle_distance(0.0, 1.45)
  assert get_stopped_equivalence_factor(10.0, 1.0) == pytest.approx(50.0)


# --- LongitudinalPlanner AP1 throttle cap and comfort brake -------------------

def _planner(fingerprint, v_ego):
  from opendbc.car.honda.interface import CarInterface as HondaInterface
  from opendbc.car.tesla.interface import CarInterface as TeslaInterface
  from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
  ci = TeslaInterface if fingerprint.startswith("TESLA") else HondaInterface
  return LongitudinalPlanner(ci.get_non_essential_params(fingerprint), init_v=v_ego)


# Same shapes as test_longitudinal_planner.make_lead / make_sm / make_toggles (kept local so this file
# does not import modeld).
def make_lead(*, status, d_rel=200.0, v_lead=0.0, a_lead=0.0, radar=False, model_prob=0.0):
  lead = log.RadarState.LeadData.new_message()
  lead.status = status
  lead.dRel = d_rel
  lead.vLead = v_lead
  lead.vLeadK = v_lead
  lead.aLeadK = a_lead
  lead.modelProb = model_prob
  lead.radar = radar
  return lead


def make_model(v_ego, desired_accel, gas_press_prob=1.0):
  model = log.ModelDataV2.new_message()
  model.init('leadsV3', 3)
  t_idxs = ModelConstants.T_IDXS
  for name, vals in (("position", [float(v_ego * t) for t in t_idxs]), ("velocity", [float(v_ego)] * len(t_idxs)),
                     ("acceleration", [0.0] * len(t_idxs))):
    xyz = getattr(model, name)
    xyz.x = vals
    xyz.y = [0.0] * len(t_idxs)
    xyz.z = [0.0] * len(t_idxs)
    xyz.t = [float(t) for t in t_idxs]
  model.meta.disengagePredictions.gasPressProbs = [float(gas_press_prob)] * 6
  model.meta.disengagePredictions.brakePressProbs = [0.0] * 6
  model.action.desiredAcceleration = desired_accel
  return model


def make_sm(v_ego, desired_accel, min_accel, *, tracking_lead=False, lead_one=None, gas_press_prob=1.0,
            disable_throttle=False):
  return {
    "carControl": SimpleNamespace(orientationNED=[0.0, 0.0, 0.0]),
    "carState": SimpleNamespace(vEgo=v_ego, vEgoCluster=v_ego, aEgo=0.0, vCruise=100.0, standstill=False,
                                steeringAngleDeg=0.0),
    "controlsState": SimpleNamespace(longControlState=LongCtrlState.pid, forceDecel=False),
    "liveParameters": SimpleNamespace(angleOffsetDeg=0.0),
    "modelV2": make_model(v_ego, desired_accel, gas_press_prob=gas_press_prob),
    "radarState": SimpleNamespace(leadOne=lead_one if lead_one is not None else make_lead(status=False),
                                  leadTwo=make_lead(status=False)),
    "selfdriveState": SimpleNamespace(enabled=True, experimentalMode=False, personality=0),
    "starpilotCarState": SimpleNamespace(accelPressed=False),
    "starpilotPlan": SimpleNamespace(
      vCruise=v_ego + 5.0, minAcceleration=min_accel, maxAcceleration=2.0, disableThrottle=disable_throttle,
      trackingLead=tracking_lead, accelerationJerk=5.0, dangerJerk=5.0, speedJerk=5.0, dangerFactor=1.0,
      tFollow=1.45, forcingStop=False, redLight=False, forcingStopLength=2, approachStopLength=0.0),
  }


def make_toggles():
  return SimpleNamespace(taco_tune=False, classic_model=False, tinygrad_model=True, model_version="v11",
                         vEgoStopping=0.5, radar_takeoffs=False, conditional_limit=0.0, conditional_limit_lead=0.0)


@pytest.fixture
def regen_file(tmp_path, monkeypatch):
  p = tmp_path / "RegenComfortBrake"
  monkeypatch.setattr(regen, "_regen_comfort_path", p)
  return p


def test_planner_ap1_gate_and_comfort_brake_selection(regen_file):
  ap1 = _planner(AP1, 18.0)
  assert ap1.ap1_throttle_gate is not None
  assert ap1.ap1_comfort_brake == pytest.approx(regen.AP1_REGEN_COMFORT_BRAKE)
  regen_file.write_text("0")
  assert regen.ap1_comfort_brake(AP1) == pytest.approx(COMFORT_BRAKE)
  other = _planner("HONDA_CIVIC", 18.0)
  assert other.ap1_throttle_gate is None
  assert other.ap1_comfort_brake == pytest.approx(COMFORT_BRAKE)


def test_planner_ap1_throttle_cap_is_filtered(regen_file):
  v = 18.0
  p = _planner(AP1, v)
  for _ in range(10):
    p.update(make_sm(v, 0.5, -1.0, gas_press_prob=1.0), make_toggles())
  assert p.throttle_cut == pytest.approx(0.0, abs=1e-6)
  # One "no throttle" model frame moves the cap about a quarter of the way, not all the way.
  p.update(make_sm(v, 0.5, -1.0, gas_press_prob=0.0), make_toggles())
  assert 0.15 < p.throttle_cut < 0.4
  assert p.allow_throttle
  for _ in range(12):
    p.update(make_sm(v, 0.5, -1.0, gas_press_prob=0.0), make_toggles())
  assert p.throttle_cut > 0.9
  assert not p.allow_throttle
  # Slow release back toward throttle.
  p.update(make_sm(v, 0.5, -1.0, gas_press_prob=1.0), make_toggles())
  assert p.throttle_cut > 0.85
  # disableThrottle forces the full coast cap.
  p.update(make_sm(v, 0.5, -1.0, gas_press_prob=1.0, disable_throttle=True), make_toggles())
  assert p.throttle_cut == 1.0


def test_planner_regen_comfort_brake_brakes_earlier_for_a_far_lead(regen_file):
  v = 25.0

  def run(enabled):
    regen_file.write_text("1" if enabled else "0")
    p = _planner(AP1, v)
    lead = make_lead(status=True, d_rel=90.0, v_lead=12.0, radar=True, model_prob=0.99)
    sm = make_sm(v, 0.0, -2.0, tracking_lead=True, lead_one=lead)
    sm["starpilotPlan"].vCruise = v + 5.0
    for _ in range(5):
      p.update(sm, make_toggles())
    return float(p.mpc.a_solution[2])

  # Regen comfort brake (1.0 m/s^2) starts the lead approach earlier and gentler.
  assert run(True) < run(False) - 0.05


# --- TeslaAp1CardHooks ---------------------------------------------------------

def test_card_hooks_stalk_levels_and_cluster_lift():
  from opendbc.car import structs
  from openpilot.selfdrive.car.tesla_ap1_card import TeslaAp1CardHooks
  from opendbc.car.tesla.ap1_slc_raise import V_CRUISE_UNSET_KPH
  B = structs.CarState.ButtonEvent.Type
  CS_py = SimpleNamespace(button_states={B.accelCruise: False, B.decelCruise: True, B.resumeCruise: True}, spd_ctrl_lvr=8)
  FPCS = SimpleNamespace(accelPressed=True, decelPressed=False, resumePressed=False, spdCtrlLvr=0)
  TeslaAp1CardHooks.apply_stalk_levels(CS_py, FPCS)
  assert (FPCS.accelPressed, FPCS.decelPressed, FPCS.resumePressed, FPCS.spdCtrlLvr) == (False, True, True, 8)

  class SM(dict):
    def __init__(self, seen, v):
      super().__init__(starpilotPlan=SimpleNamespace(vCruise=v))
      self.seen = {"starpilotPlan": seen}
  assert TeslaAp1CardHooks.cluster_set_kph(60.0, SM(False, 30.0)) == 60.0
  assert TeslaAp1CardHooks.cluster_set_kph(60.0, SM(True, 30.0)) == pytest.approx(108.0)
  assert TeslaAp1CardHooks.cluster_set_kph(60.0, SM(True, 10.0)) == 60.0  # never lowered (CSC)
  assert TeslaAp1CardHooks.cluster_set_kph(V_CRUISE_UNSET_KPH, SM(True, 10.0)) == pytest.approx(36.0)
