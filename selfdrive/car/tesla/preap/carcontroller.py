"""Pre-AP CarController — NotAutopilot-inspired, adapted to BogPilot 0.9.7.

Lateral: DAS_steeringControl via existing TeslaCAN (same angle API as AP1 packer).
Longitudinal: Comma Pedal 0x551 when openpilotLongitudinalControl is set.
Stalk spoof / VirtualDAS / radar GTW / stock-CC-only mode: not in this cut.

Credit: NotAutopilot. User-facing product name: BogPilot.
"""
from __future__ import annotations

from opendbc.can.packer import CANPacker
from openpilot.selfdrive.car.interfaces import CarControllerBase
from openpilot.selfdrive.car.tesla.preap.accel_to_pedal import accel_to_pedal_command
from openpilot.selfdrive.car.tesla.preap.pedal_can import PedalCommandCounter, create_pedal_command
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
    # Default pedal on party/chassis bus 2 (NotAutopilot default); overridable later.
    self.pedal_bus = 2

  def update(self, CC, CS, now_nanos, frogpilot_toggles):
    actuators = CC.actuators
    can_sends = []

    lat_active = bool(CC.latActive) and bool(CC.enabled)
    # Angle command — TeslaCAN.create_steering_control(angle, enabled, counter)
    angle = float(actuators.steeringAngleDeg)
    steer_msg = self.tesla_can.create_steering_control(angle, lat_active, self.frame)
    can_sends.append(steer_msg)
    self.apply_angle_last = angle

    if self.CP.openpilotLongitudinalControl:
      long_active = bool(CC.enabled) and bool(CC.longActive)
      pedal_cmd, enable = accel_to_pedal_command(float(actuators.accel), long_active)
      addr, dat, bus = create_pedal_command(pedal_cmd, enable, self.pedal_counter, self.pedal_bus)
      can_sends.append((addr, dat, bus))

    # EPAS enable frame at low rate when lat active (0x214) — pack via chassis dbc if present.
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
        pass  # DBC may lack EPB_epasControl on this chassis packer

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = self.apply_angle_last
    self.frame += 1
    return new_actuators, can_sends
