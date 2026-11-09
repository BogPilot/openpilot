import numpy as np
from opendbc.car.structs import car
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.common.pid import PIDController
from openpilot.common.swaglog import cloudlog
try:  # optional Gas/Brake consumer: an import failure must fall back to stock LongControl, never crash controlsd
  from openpilot.selfdrive.controls.lib.phase3_long_accel import advanced_values
except Exception:
  advanced_values = None
from openpilot.selfdrive.modeld.constants import ModelConstants

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]

LongCtrlState = car.CarControl.Actuators.LongControlState


def long_control_state_trans(active, long_control_state, should_stop, brake_pressed, cruise_standstill):
  starting_condition = (not should_stop and
                        not cruise_standstill and
                        not brake_pressed)

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state == LongCtrlState.off:
      if not starting_condition:
        long_control_state = LongCtrlState.stopping
      else:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.stopping:
      if starting_condition:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.pid:
      if should_stop:
        long_control_state = LongCtrlState.stopping

  return long_control_state

class LongControl:
  def __init__(self, CP, stopping_store=None):
    self.CP = CP
    # One shared reader for the stopping tune and the actuator cap (injectable for tests).
    # Any settings-store failure leaves it None = exact stock stopping and no actuator cap.
    try:
      if stopping_store is not None:
        self.long_accel_store = stopping_store
      else:
        from openpilot.common.bogpilot_store import ParamStore
        self.long_accel_store = ParamStore(cache_ttl=1.0)
    except Exception:
      cloudlog.exception("LongControl: BogPilot settings store unavailable; stock behaviour")
      self.long_accel_store = None
    self.stopping_store = self.long_accel_store
    self.long_control_state = LongCtrlState.off
    self.pid = PIDController(0.0, (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0

  def reset(self):
    self.pid.reset()

  def update(self, active, CS, a_target, should_stop, accel_limits):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]

    self.long_control_state = long_control_state_trans(active, self.long_control_state, should_stop,
                                                       CS.brakePressed, CS.cruiseState.standstill)
    if self.long_control_state == LongCtrlState.off:
      self.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      try:
        from openpilot.selfdrive.controls.lib.phase3_long_stopping import native_stopping_tune, read_runtime_stopping, stopping_accel
        tune = native_stopping_tune(self.CP)
        try:
          tune = read_runtime_stopping(self.stopping_store, self.CP)
        except Exception:
          # Preserve exact stock stopping if Params/cache is unavailable.
          pass
        output_accel = stopping_accel(self.last_output_accel, tune, DT_CTRL, accel_limits)
      except Exception:
        # Phase3 stopping module/tune failed: exact stock (feae) stopping behaviour.
        output_accel = self.last_output_accel
        if output_accel > self.CP.stopAccel:
          output_accel = min(output_accel, 0.0)
          output_accel -= 1.0 * DT_CTRL
      self.reset()

    else:  # LongCtrlState.pid
      error = a_target - CS.aEgo
      output_accel = self.pid.update(error, speed=CS.vEgo,
                                     feedforward=a_target)

    # Match 0.9.7 actuator-stage cap, without altering disengagement or stop-state rules.
    cap = None
    if self.CP.openpilotLongitudinalControl and advanced_values is not None and self.long_accel_store is not None:
      try:
        _, cap = advanced_values(self.long_accel_store, self.CP)
      except Exception:
        cap = None  # settings unavailable: stock limits only
    if cap is not None:
      output_accel = min(output_accel, cap)
    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel
