"""Pre-AP CarController — NotAutopilot-inspired, adapted to BogPilot 0.9.7.

Lateral: DAS_steeringControl via existing TeslaCAN (same angle API as AP1 packer).
Longitudinal: NAP-style VirtualDAS + PedalAuthority → Comma Pedal 0x551 when
user wants long AND pedal detected AND calibrated.
Radar: optional donor-VIN / GTW helper TX when TeslaRadarEnabled (safety flag).

Credit: NAP-style. User-facing product name: BogPilot.
"""
from __future__ import annotations

import time
from opendbc.can.packer import CANPacker
from openpilot.selfdrive.car.interfaces import CarControllerBase
from openpilot.selfdrive.car.tesla.preap.calib import (
  COAST_DI_MAX,
  COAST_FRAMES,
  COAST_RAW_QUIET,
  PRESS_DI_MIN,
  PRESS_RAW_DELTA,
  apply_calibration_result,
  compute_calibration,
  fail_calibration,
  is_pedal_calibrated,
  pedal_can_bus,
  pedal_long_allowed,
)
from openpilot.selfdrive.car.tesla.preap.long_controller import PreAPLongController
from openpilot.selfdrive.car.tesla.preap.params import PreApParamKeys, get_bool, get_str, set_bool, set_str
from openpilot.selfdrive.car.tesla.preap.pedal_can import PedalCommandCounter
from openpilot.selfdrive.car.tesla.preap.radar_donor_vin import (
  RadarDonorVinCommissioner,
  drain_rx_packets,
  normalize_radar_donor_vin,
)
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
    self._calib_coast_samples: list[float] = []
    self.stock_cc = StockCCSpoofer()
    self.long_ctrl = PreAPLongController(self.pedal_counter, pedal_can_bus)

    def _store_donor_vin(vin: str) -> None:
      # Never log the VIN value.
      set_str(PreApParamKeys.RADAR_DONOR_VIN, vin)
    self._vin_commissioner = RadarDonorVinCommissioner(_store_donor_vin, now=time.monotonic)
    self._read_vin_was_on = False

  def _reset_calib_capture(self) -> None:
    self._calib_coast = None
    self._calib_press = None
    self._calib_frames_coast = 0
    self._calib_coast_samples = []

  def _update_detection_and_calib(self, CS) -> bool:
    """Mirror PedalDetected; run armed driver-press calib from CS samples.

    Coast only after interceptor is quiet and DI gas is near zero. Press only
    when DI gas rises with the interceptor. Reject small-span / insane factor
    captures instead of writing Ready (driver foot only; never unlock panda for calib).
    """
    detected = bool(getattr(CS, "preap_pedal_detected", False))
    set_bool(PreApParamKeys.PEDAL_DETECTED, detected)

    if get_bool(PreApParamKeys.PEDAL_CALIB_ARMED) and detected:
      raw = getattr(CS, "preap_pedal_raw", None)
      # CS.out.gas is always DI_pedalPos/100 (interceptor only overrides gasPressed).
      di_gas = float(getattr(getattr(CS, "out", None), "gas", 0.0) or 0.0)
      if raw is not None:
        raw_f = float(raw)
        if self._calib_coast is None:
          quiet = di_gas <= COAST_DI_MAX
          if quiet:
            self._calib_coast_samples.append(raw_f)
            if len(self._calib_coast_samples) > COAST_FRAMES:
              self._calib_coast_samples = self._calib_coast_samples[-COAST_FRAMES:]
            if len(self._calib_coast_samples) >= COAST_FRAMES:
              span = max(self._calib_coast_samples) - min(self._calib_coast_samples)
              if span <= COAST_RAW_QUIET:
                self._calib_coast = sum(self._calib_coast_samples) / len(self._calib_coast_samples)
                self._calib_frames_coast = COAST_FRAMES
          else:
            self._calib_coast_samples = []
            self._calib_frames_coast = 0
        elif self._calib_press is None:
          if (raw_f > float(self._calib_coast) + PRESS_RAW_DELTA) and (di_gas >= PRESS_DI_MIN):
            self._calib_press = raw_f
            result = compute_calibration(self._calib_coast, self._calib_press)
            if result.get("ok"):
              apply_calibration_result(result)
            else:
              fail_calibration(str(result.get("reason") or "validation failed"))
            self._reset_calib_capture()
    else:
      self._reset_calib_capture()

    return detected

  def update(self, CC, CS, now_nanos, frogpilot_toggles):
    actuators = CC.actuators
    can_sends = []
    self.pedal_bus = pedal_can_bus()
    detected = self._update_detection_and_calib(CS)
    calibrated = is_pedal_calibrated()

    # NAP: lat_active = CC.latActive and hands < 3 (no CC.enabled).
    hands = int(getattr(CS, 'hands_on_level', 0) or 0)
    lat_active = bool(CC.latActive) and hands < 3
    if lat_active:
      angle = apply_std_steer_angle_limits(
        float(actuators.steeringAngleDeg), self.apply_angle_last, CS.out.vEgo, CarControllerParams)
    else:
      angle = float(CS.out.steeringAngleDeg)
    if self.frame % 2 == 0:
      cntr = (self.frame // 2) % 16
      can_sends.append(self.tesla_can.create_steering_control(angle, lat_active, cntr))
      can_sends.append(self.tesla_can.create_epas_control(cntr, 1))
      self.apply_angle_last = angle

    user_wants_long = bool(self.CP.openpilotLongitudinalControl)
    long_ok = pedal_long_allowed(user_wants_long=user_wants_long,
                                 detected=detected, calibrated=calibrated)

    # NAP-style VirtualDAS + PedalAuthority (50 Hz). Sets stock-CC cancel flags.
    if user_wants_long:
      can_sends.extend(self.long_ctrl.update(
        CC, CS, self.frame, long_ok=long_ok, now_nanos=int(now_nanos or 0)))
      if getattr(CS, "preap_cc_cancel_needed", False):
        CS.preap_last_cc_spoof_ms = int(time.monotonic() * 1000)

    can_sends.extend(self.stock_cc.update(CS, self.frame, self.tesla_can, CANBUS.chassis))

    # Phase A donor VIN F190 read — offroad / pre-engage only (from radarvin).
    radar_on = get_bool(PreApParamKeys.RADAR_ENABLED)
    read_vin_on = get_bool(PreApParamKeys.RADAR_READ_VIN, False)
    if radar_on and read_vin_on:
      force_read = read_vin_on and not self._read_vin_was_on
      self._read_vin_was_on = True
      stored = normalize_radar_donor_vin(get_str(PreApParamKeys.RADAR_DONOR_VIN, ""))
      engaged = bool(CC.enabled) or bool(getattr(CS.out, "cruiseState", None) and CS.out.cruiseState.enabled)
      can_sends.extend(self._vin_commissioner.update(
        drain_rx_packets(),
        radar_enabled=True,
        stored_vin=stored,
        engaged=engaged,
        force_read=force_read,
      ))
    else:
      self._read_vin_was_on = False

    # Radar helper TX (donor VIN when stored, else dummy) — low rate.
    if radar_on and (self.frame % 100 == 0):
      can_sends.extend(radar_tx_frames(enabled=True, bus=CANBUS.radar))

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = self.apply_angle_last
    self.frame += 1
    return new_actuators, can_sends
