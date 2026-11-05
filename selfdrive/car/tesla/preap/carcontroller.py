"""Pre-AP CarController — NotAutopilot-inspired, adapted to BogPilot 0.9.7.

Lateral: DAS_steeringControl via existing TeslaCAN (same angle API as AP1 packer).
Longitudinal: Comma Pedal 0x551 only when user wants long AND pedal detected AND
calibrated (DisableOpenpilotLongitudinal is the sole on/off).
Radar: optional dummy-VIN / GTW helper TX when TeslaRadarEnabled (safety flag).

Credit: NotAutopilot. User-facing product name: BogPilot.
"""
from __future__ import annotations

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
from openpilot.selfdrive.car.tesla.teslacan import TeslaCAN
from openpilot.selfdrive.car.tesla.values import CANBUS, DBC


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

    lat_active = bool(CC.latActive) and bool(CC.enabled)
    angle = float(actuators.steeringAngleDeg)
    # DAS_steeringControlCounter is 4-bit; packer rejects frame>=16 unmasked.
    steer_msg = self.tesla_can.create_steering_control(angle, lat_active, (self.frame // 2) % 16)
    can_sends.append(steer_msg)
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

    # Radar helper TX (dummy VIN) — low rate, only when enabled.
    if get_bool(PreApParamKeys.RADAR_ENABLED) and (self.frame % 100 == 0):
      can_sends.extend(radar_tx_frames(enabled=True, bus=CANBUS.radar))

    if lat_active and (self.frame % 10 == 0):
      try:
        values = {
          "EPB_epasEACAllow": 1,
          "EPB_epasControlCounter": (self.frame // 10) % 16,
          "EPB_epasControlChecksum": 0,
        }
        msg = self.packer.make_can_msg("EPB_epasControl", CANBUS.chassis, values)
        can_sends.append(msg)
      except Exception:
        pass

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = self.apply_angle_last
    self.frame += 1
    return new_actuators, can_sends
