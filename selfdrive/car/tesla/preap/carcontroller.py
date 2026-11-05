"""Pre-AP CarController — NotAutopilot-inspired, adapted to BogPilot 0.9.7.

Lateral: DAS_steeringControl via existing TeslaCAN (same angle API as AP1 packer).
Longitudinal: Comma Pedal 0x551 only when user wants long AND pedal detected AND
calibrated (DisableOpenpilotLongitudinal is the sole on/off).
Radar: optional dummy-VIN / GTW helper TX when TeslaRadarEnabled (safety flag).

Credit: NotAutopilot. User-facing product name: BogPilot.
"""
from __future__ import annotations

import time
from opendbc.can.packer import CANPacker
from openpilot.selfdrive.car.interfaces import CarControllerBase
from openpilot.selfdrive.car.tesla.preap.accel_to_pedal import accel_to_pedal_command
from openpilot.selfdrive.car.tesla.preap.calib import (
  apply_calibration_result,
  compute_calibration,
  current_pedal_transform,
  is_pedal_calibrated,
  pedal_can_bus,
  pedal_long_allowed,
)
from openpilot.selfdrive.car.tesla.preap.params import PreApParamKeys, get_bool, set_bool
from openpilot.selfdrive.car.tesla.preap.pedal_can import PedalCommandCounter, create_pedal_command
from openpilot.selfdrive.car.tesla.preap.radar_tx import radar_tx_frames
from openpilot.selfdrive.car.tesla.preap.stock_cc_spoofer import StockCCSpoofer
from openpilot.selfdrive.car.tesla.teslacan import TeslaCAN
from openpilot.selfdrive.car import apply_std_steer_angle_limits
from openpilot.selfdrive.car.tesla.values import CANBUS, CarControllerParams, DBC


class PreApCarController(CarControllerBase):
  def __init__(self, dbc_name, CP, VM):
    self.CP = CP
    self.frame = 0
    self.apply_angle_last = 0
    self.packer = CANPacker(dbc_name)
    self.pt_packer = CANPacker(DBC[CP.carFingerprint]["pt"])
    self.tesla_can = TeslaCAN(self.packer, self.pt_packer)
    self.pedal_counter = PedalCommandCounter()
    self.pedal_bus = pedal_can_bus()
    self._calib_coast = None
    self._calib_frames_coast = 0
    self._calib_press = None
    self.stock_cc = StockCCSpoofer()
    self.prev_requested_long = False

  def _update_detection_and_calib(self, CS) -> bool:
    """Mirror PedalDetected; run armed two-step calib from CS samples."""
    detected = bool(getattr(CS, "preap_pedal_detected", False))
    set_bool(PreApParamKeys.PEDAL_DETECTED, detected)

    if get_bool(PreApParamKeys.PEDAL_CALIB_ARMED) and detected:
      raw = getattr(CS, "preap_pedal_raw", None)
      if raw is not None:
        # Phase 1: collect coast (foot off) — prefer low raw while standstill.
        if self._calib_coast is None:
          if getattr(CS.out, "gasPressed", False):
            self._calib_frames_coast = 0
          else:
            self._calib_frames_coast += 1
            if self._calib_frames_coast >= 20:
              self._calib_coast = float(raw)
        elif self._calib_press is None:
          # Phase 2: full press — require clearly above coast.
          if float(raw) > float(self._calib_coast) + 5.0:
            self._calib_press = float(raw)
            result = compute_calibration(self._calib_coast, self._calib_press)
            apply_calibration_result(result)
            self._calib_coast = None
            self._calib_press = None
            self._calib_frames_coast = 0
    else:
      self._calib_coast = None
      self._calib_press = None
      self._calib_frames_coast = 0

    return detected

  def update(self, CC, CS, now_nanos, frogpilot_toggles):
    actuators = CC.actuators
    can_sends = []
    self.pedal_bus = pedal_can_bus()
    detected = self._update_detection_and_calib(CS)
    calibrated = is_pedal_calibrated()

    # NAP: lat_active = CC.latActive and hands < 3 (no CC.enabled). Requiring
    # enabled blocked FrogPilot Always On Lateral (brake drops long, lat stays).
    hands = int(getattr(CS, 'hands_on_level', 0) or 0)
    lat_active = bool(CC.latActive) and hands < 3
    # Panda TESLA_PREAP inactive_angle_is_zero=false: idle 0x488 must stay near
    # angle_meas or steer_angle_cmd_checks TX-blocks (safetyTxBlocked). NAP
    # apply_steer_angle_limits_vm snaps inactive to measured; mirror that here.
    if lat_active:
      angle = apply_std_steer_angle_limits(
        float(actuators.steeringAngleDeg), self.apply_angle_last, CS.out.vEgo, CarControllerParams)
    else:
      angle = float(CS.out.steeringAngleDeg)
    # NAP _update_preap: 0x488 + 0x214 every 2 frames (50 Hz), same counter.
    # EPB allow is NOT gated on lat_active — gating deadlocks when EPAS is still
    # INHIBITED (needs EACAllow before AVAILABLE/ACTIVE). Checksum via teslacan.
    if self.frame % 2 == 0:
      cntr = (self.frame // 2) % 16
      can_sends.append(self.tesla_can.create_steering_control(angle, lat_active, cntr))
      can_sends.append(self.tesla_can.create_epas_control(cntr, 1))
      self.apply_angle_last = angle

    user_wants_long = bool(self.CP.openpilotLongitudinalControl)
    long_ok = pedal_long_allowed(user_wants_long=user_wants_long,
                                 detected=detected, calibrated=calibrated)
    if user_wants_long:
      long_active = bool(CC.enabled) and bool(CC.longActive) and long_ok
      zero, factor = current_pedal_transform() if calibrated else (0.0, 1.0)
      pedal_cmd, enable = accel_to_pedal_command(
        float(actuators.accel), long_active, pedal_zero=zero, pedal_factor=factor)
      # Never assert ENABLE unless gating passed.
      if not long_ok:
        enable = 0
        pedal_cmd = 0.0
      # sendcan frames are (addr, busTime, dat, bus); a 3-tuple crashes can_list_to_can_capnp.
      can_sends.append(create_pedal_command(pedal_cmd, enable, self.pedal_counter, self.pedal_bus))

    # Stock DI cruise cancel (NAP StockCCSpoofer). Pedal long must not leave
    # stock CC engaged alongside the interceptor. Bus 0 only (panda TX list).
    requested_long = bool(CC.enabled) and bool(CC.longActive) and long_ok
    if long_ok:
      cruise_btn = int(getattr(CS, "cruise_buttons", 0) or 0)
      prev_btn = int(getattr(CS, "prev_cruise_buttons", 0) or 0)
      rising = (not self.prev_requested_long) and requested_long
      falling = self.prev_requested_long and (not requested_long)
      pedal_button_press = (cruise_btn != prev_btn) and (cruise_btn != 0)
      if rising or falling or pedal_button_press:
        CS.preap_cc_cancel_needed = True
        # Mark spoof intent so carstate can suppress the CANCEL echo next tick.
        CS.preap_last_cc_spoof_ms = int(time.monotonic() * 1000)
    self.prev_requested_long = requested_long
    can_sends.extend(self.stock_cc.update(CS, self.frame, self.tesla_can, CANBUS.chassis))

    # Radar helper TX (dummy VIN) — low rate, only when enabled.
    if get_bool(PreApParamKeys.RADAR_ENABLED) and (self.frame % 100 == 0):
      can_sends.extend(radar_tx_frames(enabled=True, bus=CANBUS.radar))

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = self.apply_angle_last
    self.frame += 1
    return new_actuators, can_sends
