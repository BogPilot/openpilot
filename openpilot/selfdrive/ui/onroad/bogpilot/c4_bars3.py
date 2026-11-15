"""Three-bar pedal gauge inputs for the comma 4 layout: brake | regen | accel.

Thin adapter: the comma 4 painter reads only Bars3. When the shared three-bar gauge module lands, this file maps
its output to Bars3 and nothing else changes.

Signals (all existing, read only):
  brake  friction braking only: max(0, -carState.aEgo - live regen decel) on pedals.DECEL_FULL_SCALE, and only while
         the iBooster is applied: carState.brakePressed (driver) or OP applying it (pedals.op_ibooster_applied:
         longActive AND bogpilotCarState.ap1BrakePedalState ON AND no driver press). Live regen decel is
         pedals.regen_live(bogpilotCarState.ap1MotorTorqueNm) (DI_torqueMotor). At a standstill a press reads full.
  regen  regen shaft power in kW from DI_torqueMotor and DI_motorRPM (regen_aware.regen_power_kw on
         bogpilotCarState.ap1MotorTorqueNm / ap1MotorRpm), shown on a 55 kW full scale. Engaged colour while
         carControl.longActive.
  accel  pedals.accel_fraction(carState.deprecated.gas, OP accel while longActive). The driver colour while the
         pedal is pressed (carState.gasPressed or pedal > 0), else OP's while longActive and OP accel > 0.
Missing, stale or not-finite inputs read as 0 (empty bar).
"""
from __future__ import annotations

from dataclasses import dataclass

from opendbc.car.tesla_ap1 import regen_aware as RA
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED
from openpilot.selfdrive.ui.onroad.bogpilot.c4_layout import REGEN_FULL_SCALE_KW

DRIVER, OP = "driver", "op"

# Owner-picked comma 4 three-bar colours (RGB): (driver / OP disengaged, OP / engaged).
BRAKE_RGB = {DRIVER: (0xC6, 0x28, 0x28), OP: (0xB5, 0x83, 0x8D)}
REGEN_RGB = {DRIVER: (0x2E, 0x8B, 0xFF), OP: (0x8F, 0xB3, 0xE0)}
ACCEL_RGB = {DRIVER: (0x3D, 0xDC, 0x97), OP: (0x5E, 0x8A, 0x72)}


@dataclass(frozen=True)
class Bars3:
  brake: float = 0.0          # 0..1
  regen: float = 0.0          # 0..1 of REGEN_FULL_SCALE_KW
  accel: float = 0.0          # 0..1
  brake_src: str = DRIVER
  regen_src: str = DRIVER
  accel_src: str = DRIVER
  regen_kw: float = 0.0


EMPTY = Bars3()


def regen_kw(motor_torque_nm, motor_rpm) -> float:
  tq, rpm = PED.finite(motor_torque_nm), PED.finite(motor_rpm)
  if tq <= PED.MOTOR_TORQUE_SNA_NM:
    return 0.0
  return RA.regen_power_kw(tq, rpm)


def bars3(*, fresh: bool, a_ego, v_ego, brake_pressed: bool, gas_pressed: bool, pedal_pos, op_accel,
          long_active: bool, motor_torque_nm, motor_rpm, brake_pedal_state) -> Bars3:
  if not fresh:
    return EMPTY
  long_active = bool(long_active)
  op = PED.finite(op_accel) if long_active else 0.0
  op_brake = PED.op_ibooster_applied(brake_pedal_state, long_active, brake_pressed)
  applied = bool(brake_pressed) or op_brake
  brake = 0.0
  if applied:
    if PED.finite(v_ego) < PED.STANDSTILL_V:
      brake = 1.0
    else:
      live = PED.regen_live(motor_torque_nm)
      friction = max(0.0, max(0.0, -PED.finite(a_ego)) - (live or 0.0))
      brake = PED.clamp(friction / PED.DECEL_FULL_SCALE, 0.0, 1.0)
  kw = regen_kw(motor_torque_nm, motor_rpm)
  pedal = PED.finite(pedal_pos)
  driver_gas = bool(gas_pressed) or pedal > 0.0
  return Bars3(brake=brake, regen=PED.clamp(kw / REGEN_FULL_SCALE_KW, 0.0, 1.0), accel=PED.accel_fraction(pedal, op),
               brake_src=DRIVER if brake_pressed else (OP if op_brake else DRIVER),
               regen_src=OP if long_active else DRIVER,
               accel_src=DRIVER if driver_gas or not (long_active and op > 0.0) else OP,
               regen_kw=kw)
