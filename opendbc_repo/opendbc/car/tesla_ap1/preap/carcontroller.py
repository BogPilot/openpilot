"""Pre-AP Model S CarController.

Lateral: DAS_steeringControl (0x488, 50 Hz, angle) plus EPB_epasControl (0x214, EACAllow = 1). A Pre-AP car has no Autopilot
ECU, so nothing else keeps the EPAS out of INHIBITED / TMP_FAULT: both frames are sent every other frame while the car is in
gear and the stack is alive (idle 0x488 holds the measured wheel angle, control type NONE).
Longitudinal: Comma Pedal GAS_COMMAND (0x551) through VirtualDAS + PedalAuthority, only when the user wants openpilot long
(CP.openpilotLongitudinalControl) AND the pedal is detected AND calibrated (pedal_long_allowed) AND CC.longActive.
Double pull (only while Always On Lateral is available): the first pull is an AOL lateral intent (carState.bogpilot.preapAolLat); openpilot is
not enabled, so carControl.longActive stays False and no pedal command is ever enabled. Steering follows CC.latActive either way.
Stock cruise cancel (STW_ACTN_RQ cancel) when the pedal takes over or lets go (StockCCSpoofer).
Pedal calibration (driver foot press, no commanded gas) runs here from CarState samples.
"""
from __future__ import annotations

from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.carlog import carlog
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.tesla_ap1.actuator_plan import apply_std_steer_angle_limits
from opendbc.car.tesla_ap1.engage_ramp import Ap1EngageSteerRamp
from opendbc.car.tesla_ap1.epas_gate import EpasGate
from opendbc.car.tesla_ap1.hso import Ap1DriverYield, ap1_lat_active
from opendbc.car.tesla_ap1.override import DriverOverrideDetector, read_sensitivity_level
from opendbc.car.tesla_ap1.teslacan import TeslaCAN
from opendbc.car.tesla_ap1.values import CANBUS, DBC, CarControllerParams
from opendbc.car.tesla_ap1.preap.calib import (
  COAST_FRAMES, PRESS_DI_FULL, PRESS_DI_MIN, PRESS_DI_ONSET, PRESS_NOT_FULL, PRESS_RELEASE_FRAMES, PRESS_WINDOW_FRAMES,
  STAGE_COAST, STAGE_COAST_OK, STAGE_IDLE, apply_calibration_result, coast_steady, compute_calibration_onset, fail_calibration,
  is_pedal_calibrated, pedal_can_bus, pedal_long_allowed, rest_stats, set_stage,
)
from opendbc.car.tesla_ap1.preap.long_controller import PreAPLongController
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys, get_bool, get_str
from opendbc.car.tesla_ap1.preap.pedal_can import PedalCommandCounter
from opendbc.car.tesla_ap1.preap.stock_cc_spoofer import StockCCSpoofer


class PreApCarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    super().__init__(dbc_names, CP)
    self.apply_angle_last = 0
    self.packer = CANPacker(dbc_names[Bus.chassis])
    self.pt_packer = CANPacker(DBC[CP.carFingerprint][Bus.pt])
    self.tesla_can = TeslaCAN(self.packer, self.pt_packer)
    self.pedal_counter = PedalCommandCounter()
    self.pedal_bus = pedal_can_bus()
    self.stock_cc = StockCCSpoofer()
    self.long_ctrl = PreAPLongController(self.pedal_counter, pedal_can_bus)
    self._reset_calib_capture()
    # Driver override: the EPAS hands flag plus the independent detector (override.py), with the same resume hold as AP1.
    self.ap1_yield = Ap1DriverYield()
    self.ap1_override = DriverOverrideDetector(read_sensitivity_level())   # Override Sensitivity, read once per drive
    # EPAS refusal gate, armed once the EPAS has been EAC_ACTIVE in this lateral session: the Pre-AP EPAS status flaps
    # outside an engaged session (no AP ECU), so only a mid-session INHIBITED or error counts.
    self.ap1_epas_gate = EpasGate(arm_on_active=True)
    # Hand-back: after a driver pause or an EPAS block the planner angle is blended in from the measured wheel
    # (the same smoothstep ramp AP1 uses) instead of being rate limited from wherever the wheel is.
    self.ap1_ramp = Ap1EngageSteerRamp()
    self.ap1_cmd_deg = None   # angle of the last ANGLE frame sent, None when the last frame was not an active command

  # ---- pedal calibration (driver press only; the panda is never unlocked for it) ----
  def _reset_calib_capture(self) -> None:
    self._calib_rest: dict[str, float] | None = None   # rest window stats (calib.rest_stats) once step 1 passed
    self._calib_coast_samples: list[float] = []
    self._calib_onset: float | None = None             # pedal reading at the first frame with DI_pedalPos >= 0.4 %
    self._calib_press_frames = 0
    self._calib_press_low = 0
    self._calib_press_peak_di = 0.0

  def _finish_calib(self, result: dict) -> None:
    if result.get("ok"):
      apply_calibration_result(result)
    else:
      fail_calibration(str(result.get("reason") or "validation failed"))
    carlog.info("preap pedal calibration: " + ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in result.items()))
    self._reset_calib_capture()

  def _update_detection_and_calib(self, CS) -> bool:
    """Run the armed driver-press calibration from CS samples (PedalDetected / PedalSeenTs are written by PreApCarState).

    Step 1: a COAST_FRAMES rest window while the car reads DI_pedalPos = 0, accepted on its medians (calib.coast_steady), not max-min.
    Step 2: the pedal reading at the first frame with DI_pedalPos >= 0.4 % (onset) and at the first frame with DI_pedalPos >= 99.6 % (full);
    calib.compute_calibration_onset turns them into zero / factor (zero never below the rest noise floor) or a failure reason.
    A press that goes back to DI 0 without passing PRESS_DI_MIN is a twitch and is ignored; a real press that is let go, or that does not
    reach full throttle within PRESS_WINDOW_FRAMES, fails with PRESS_NOT_FULL. Nothing is written unless the whole capture passes.
    """
    detected = bool(getattr(CS, "preap_pedal_detected", False))
    if get_bool(PreApParamKeys.PEDAL_CALIB_ARMED) and detected:
      raw = getattr(CS, "preap_pedal_raw", None)
      di_gas = float(getattr(CS, "di_gas", 0.0) or 0.0)   # DI_pedalPos / 100 (CarState.gas does not exist in 0.11.2)
      if raw is not None:
        raw_f = float(raw)
        if self._calib_rest is None:
          set_stage(STAGE_COAST)
          if di_gas < PRESS_DI_ONSET:
            self._calib_coast_samples.append(raw_f)
            self._calib_coast_samples = self._calib_coast_samples[-COAST_FRAMES:]
            if coast_steady(self._calib_coast_samples):
              self._calib_rest = rest_stats(self._calib_coast_samples)
              set_stage(STAGE_COAST_OK)
          else:
            self._calib_coast_samples = []
        elif self._calib_onset is None:
          if di_gas >= PRESS_DI_ONSET:
            self._calib_onset = raw_f
            self._calib_press_frames = 1
            self._calib_press_low = 0
            self._calib_press_peak_di = di_gas
        else:
          self._calib_press_frames += 1
          self._calib_press_peak_di = max(self._calib_press_peak_di, di_gas)
          self._calib_press_low = self._calib_press_low + 1 if di_gas < PRESS_DI_ONSET else 0
          if di_gas >= PRESS_DI_FULL:
            self._finish_calib(compute_calibration_onset(self._calib_rest, self._calib_onset, raw_f))
          elif self._calib_press_low >= PRESS_RELEASE_FRAMES and self._calib_press_peak_di < PRESS_DI_MIN:
            self._calib_onset = None                     # a twitch, not a press: wait for the real one
          elif self._calib_press_low >= PRESS_RELEASE_FRAMES or self._calib_press_frames >= PRESS_WINDOW_FRAMES:
            self._finish_calib({"ok": 0.0, "reason": PRESS_NOT_FULL, "onset_raw": float(self._calib_onset),
                                "peak_di": float(self._calib_press_peak_di)})
    else:
      self._reset_calib_capture()
      if get_str(PreApParamKeys.PEDAL_CALIB_STAGE) in (STAGE_COAST, STAGE_COAST_OK):
        set_stage(STAGE_IDLE)   # disarmed (Cancel / timeout / screen closed) or the pedal went quiet: no progress to show
    return detected

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators
    can_sends = []
    self.pedal_bus = int(getattr(CS, "pedal_bus", pedal_can_bus()))
    # openpilot's engaged state feeds the engagement FSM (CarState cannot see CarControl).
    CS.op_enabled = bool(CC.enabled)

    detected = self._update_detection_and_calib(CS)
    calibrated = is_pedal_calibrated()

    # ---- lateral ----
    hands = int(getattr(CS, "hands_on_level", 0) or 0)
    session = bool(CC.enabled) or bool(CC.latActive)
    override_signal = self.ap1_override.update(
      session, hands, getattr(CS.out, "steeringTorque", 0.0), getattr(CS.out, "steeringRateDeg", 0.0),
      CS.out.steeringAngleDeg, self.ap1_cmd_deg)
    driver_yield = self.ap1_yield.update(session, hands, override_signal, self.ap1_override.quiet)
    refusing = bool(getattr(CS, "preap_epas_refusing", False))   # the panda rejects ANGLE while this holds
    epas_yield = self.ap1_epas_gate.update(bool(CC.latActive), getattr(CS, "eac_status", None), getattr(CS, "steer_warning", None),
                                           bool(getattr(CS, "eac_fault", False)), refusing)
    lat_active = ap1_lat_active(CC.latActive, hands) and not driver_yield and not epas_yield and not refusing
    requested = self.ap1_ramp.update(lat_active, float(CS.out.steeringAngleDeg), float(actuators.steeringAngleDeg))
    if lat_active:
      angle = apply_std_steer_angle_limits(requested, self.apply_angle_last, CS.out.vEgo, CarControllerParams)
    else:
      angle = float(CS.out.steeringAngleDeg)
    if self.frame % 2 == 0:
      cntr = (self.frame // 2) % 16
      can_sends.append(self.tesla_can.create_steering_control(angle, lat_active, cntr))
      can_sends.append(self.tesla_can.create_epas_control(cntr, 1))
      self.apply_angle_last = angle
      self.ap1_cmd_deg = angle if lat_active else None

    # ---- longitudinal (Comma Pedal) ----
    user_wants_long = bool(self.CP.openpilotLongitudinalControl)
    long_ok = pedal_long_allowed(user_wants_long=user_wants_long, detected=detected, calibrated=calibrated)
    if user_wants_long:
      can_sends.extend(self.long_ctrl.update(CC, CS, self.frame, long_ok=long_ok, now_nanos=int(now_nanos or 0)))
    # The spoof-echo window (preap/cruise.py) is stamped by StockCCSpoofer only when our CANCEL frame is put on the bus.
    can_sends.extend(self.stock_cc.update(CS, self.frame, self.tesla_can, CANBUS.chassis))

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = float(self.apply_angle_last)
    self.frame += 1
    return new_actuators, can_sends
