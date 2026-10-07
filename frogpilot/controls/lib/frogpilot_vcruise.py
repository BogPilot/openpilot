#!/usr/bin/env python3
from cereal import car
from openpilot.common.conversions import Conversions as CV
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import COMFORT_BRAKE

from openpilot.frogpilot.common.frogpilot_variables import CRUISING_SPEED, PLANNER_TIME
from openpilot.frogpilot.controls.lib.curve_speed_controller import CurveSpeedController
from openpilot.frogpilot.controls.lib.speed_limit_controller import SpeedLimitController

ButtonType = car.CarState.ButtonEvent.Type

class FrogPilotVCruise:
  def __init__(self, FrogPilotPlanner):
    self.frogpilot_planner = FrogPilotPlanner

    self.csc = CurveSpeedController(self)
    self.slc = SpeedLimitController()

    self.forcing_stop = False
    self.override_force_stop = False

    self.override_force_stop_timer = 0
    # AP1: engage stalk policy + engaged-DECEL raise holdoff (route 23).
    from openpilot.selfdrive.car.tesla.slc_raise import Ap1RaiseHoldoff
    self.ap1_raise_holdoff = Ap1RaiseHoldoff()

  def update(self, gps_position, now, time_validated, v_cruise, v_ego, sm, frogpilot_toggles):
    force_stop = self.frogpilot_planner.cem.stop_light_detected and sm["controlsState"].enabled and frogpilot_toggles.force_stops
    force_stop &= self.frogpilot_planner.model_stopped
    force_stop &= self.override_force_stop_timer <= 0

    self.force_stop_timer = self.force_stop_timer + DT_MDL if force_stop else 0

    force_stop_enabled = self.force_stop_timer >= 1

    self.override_force_stop |= sm["carState"].gasPressed
    self.override_force_stop |= sm["frogpilotCarState"].accelPressed
    self.override_force_stop &= force_stop_enabled

    if self.override_force_stop:
      self.override_force_stop_timer = 10
    elif self.override_force_stop_timer > 0:
      self.override_force_stop_timer -= DT_MDL

    v_cruise_cluster = max(sm["controlsState"].vCruiseCluster * CV.KPH_TO_MS, v_cruise)
    v_cruise_diff = v_cruise_cluster - v_cruise

    v_ego_cluster = max(sm["carState"].vEgoCluster, v_ego)
    v_ego_diff = v_ego_cluster - v_ego

    # FrogsGoMoo's Curve Speed Controller
    if v_ego > CRUISING_SPEED and sm["controlsState"].enabled and self.frogpilot_planner.road_curvature_detected and frogpilot_toggles.curve_speed_controller:
      self.csc.update_target(v_ego)

      self.csc_controlling_speed = True

      self.csc_target = self.csc.target
    else:
      self.csc.log_data(v_ego, sm)

      self.csc_controlling_speed = False
      self.csc.target_set = False

      self.csc_target = v_cruise

    # Pfeiferj's Speed Limit Controller
    self.slc.frogpilot_toggles = frogpilot_toggles

    if frogpilot_toggles.speed_limit_controller:
      self.slc.update_limits(sm["frogpilotCarState"].dashboardSpeedLimit, gps_position, sm["frogpilotNavigation"].navigationSpeedLimit, now, time_validated, v_cruise, v_ego, sm)
      self.slc.update_override(v_cruise, v_cruise_diff, v_ego, v_ego_diff, sm)

      self.slc_offset = self.slc.offset
      self.slc_target = self.slc.target
    elif frogpilot_toggles.show_speed_limits:
      self.slc.update_limits(sm["frogpilotCarState"].dashboardSpeedLimit, gps_position, sm["frogpilotNavigation"].navigationSpeedLimit, now, time_validated, v_cruise, v_ego, sm)

      self.slc_offset = 0
      self.slc_target = self.slc.target
    else:
      self.slc_offset = 0
      self.slc_target = 0

    if force_stop_enabled and not self.override_force_stop:
      self.forcing_stop |= not sm["carState"].standstill

      self.tracked_model_length = max(self.tracked_model_length - (v_ego * DT_MDL), 0)
      v_cruise = min((self.tracked_model_length // PLANNER_TIME), v_cruise)

    else:
      self.forcing_stop = False

      self.tracked_model_length = self.frogpilot_planner.model_length

      targets = [self.csc_target, v_cruise]
      slc_desired = None
      if frogpilot_toggles.speed_limit_controller:
        slc_desired = max(self.slc.overridden_speed, self.slc_target + self.slc_offset) - v_ego_diff
        targets.append(slc_desired)

      v_cruise = min([target if target >= CRUISING_SPEED else v_cruise for target in targets])
      # AP1: lift AFTER min() so pre-lift DI/csc seed cannot undo the raise.
      # Engage policy: UP/DN → sticky vEgo; RWD → raise; engaged DECEL → holdoff.
      # No stalk TX / panda change.
      if frogpilot_toggles.speed_limit_controller and \
         str(getattr(frogpilot_toggles, "car_model", "") or "") == "TESLA_AP1_MODELS":
        from openpilot.selfdrive.car.tesla.slc_raise import apply_slc_raise_after_min
        btns = sm["carState"].buttonEvents
        up = any(be.type == ButtonType.accelCruise and be.pressed for be in btns)
        dn = any(be.type == ButtonType.decelCruise and be.pressed for be in btns)
        rwd = any(be.type == ButtonType.resumeCruise and be.pressed for be in btns)
        allow_raise, sticky_vego = self.ap1_raise_holdoff.update(
          bool(sm["carState"].cruiseState.enabled),
          dn, up, rwd, float(self.slc_target), float(v_ego),
        )
        if sticky_vego is not None:
          # UP/DN engage: hold latched current speed; SLC may still lower.
          v_cruise = float(sticky_vego)
          if slc_desired is not None and slc_desired >= CRUISING_SPEED:
            v_cruise = min(v_cruise, slc_desired)
          if self.csc_controlling_speed:
            v_cruise = min(v_cruise, self.csc_target)
        elif allow_raise:
          v_cruise = apply_slc_raise_after_min(
            v_cruise, slc_desired, self.slc_target, CRUISING_SPEED,
            self.csc_controlling_speed, self.csc_target)

    return v_cruise
