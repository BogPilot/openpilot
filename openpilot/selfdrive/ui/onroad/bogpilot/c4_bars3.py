"""Three-bar pedal gauge inputs for the comma 4 layout: brake | regen | accel.

Same shape as the shared three-bar gauge: a pure state function (GaugeInputs -> Bars3: three fill fractions plus
colours) and a separate painter that takes a rect (c4_paint.paint_gauge). When the shared module lands, gauge_state and
inputs_from_signals map onto it and the painter's callers do not change.

Signals (all existing, read only):
  brake  friction braking only: max(0, -carState.aEgo - live regen decel) on pedals.DECEL_FULL_SCALE, and only while
         the iBooster is applied: carState.brakePressed (driver) or OP applying it (pedals.op_ibooster_applied:
         longActive AND bogpilotCarState.ap1BrakePedalState ON AND no driver press). Live regen decel is
         pedals.regen_live(bogpilotCarState.ap1MotorTorqueNm) (DI_torqueMotor). At a standstill a press reads full.
  regen  regen shaft power in kW (negative while regenerating) from DI_torqueMotor and DI_motorRPM
         (regen_aware.regen_power_kw on bogpilotCarState.ap1MotorTorqueNm / ap1MotorRpm), on a -55 kW full scale.
         Engaged colour while carControl.longActive. Missing motor inputs (no bogpilotCarState) leave the bar empty.
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
class GaugeInputs:
  """The shared three-bar gauge contract: friction 0..1, regen in kW (negative = regenerating, full scale per model,
  default -55 kW), accel 0..1, engaged, and who is pressing (the driver's pedal wins over OP)."""
  friction: float = 0.0
  regen_kw: float = 0.0
  accel: float = 0.0
  engaged: bool = False
  friction_src: str = DRIVER
  accel_src: str = DRIVER
  model: str = ""
  regen_full_scale_kw: float = -REGEN_FULL_SCALE_KW


@dataclass(frozen=True)
class Bars3:
  brake: float = 0.0          # 0..1
  regen: float = 0.0          # 0..1 of the regen full scale
  accel: float = 0.0          # 0..1
  brake_src: str = DRIVER
  regen_src: str = DRIVER
  accel_src: str = DRIVER
  regen_kw: float = 0.0       # signed: negative while regenerating

  @property
  def fills(self):
    return (self.brake, self.regen, self.accel)

  @property
  def colours(self):
    """(brake, regen, accel) RGB for the current sources."""
    return (BRAKE_RGB[self.brake_src], REGEN_RGB[self.regen_src], ACCEL_RGB[self.accel_src])


EMPTY = Bars3()


def gauge_state(inp: GaugeInputs) -> Bars3:
  """Pure state function: three fill fractions plus their colours. Not-finite inputs read as empty bars."""
  fs = PED.finite(inp.regen_full_scale_kw)
  kw = min(0.0, PED.finite(inp.regen_kw))
  regen = PED.clamp(kw / fs, 0.0, 1.0) if fs < 0.0 else 0.0
  return Bars3(brake=PED.clamp(PED.finite(inp.friction), 0.0, 1.0), regen=regen,
               accel=PED.clamp(PED.finite(inp.accel), 0.0, 1.0),
               brake_src=OP if inp.friction_src == OP else DRIVER, regen_src=OP if inp.engaged else DRIVER,
               accel_src=OP if inp.accel_src == OP else DRIVER, regen_kw=kw)


def regen_kw(motor_torque_nm, motor_rpm) -> float:
  """Signed regen power (kW, negative while regenerating) from DI_torqueMotor / DI_motorRPM; SNA or missing = 0."""
  if motor_torque_nm is None or motor_rpm is None:
    return 0.0
  tq, rpm = PED.finite(motor_torque_nm), PED.finite(motor_rpm)
  if tq <= PED.MOTOR_TORQUE_SNA_NM:
    return 0.0
  return -RA.regen_power_kw(tq, rpm)


def inputs_from_signals(*, fresh: bool, a_ego, v_ego, brake_pressed: bool, gas_pressed: bool, pedal_pos, op_accel,
                        long_active: bool, motor_torque_nm, motor_rpm, brake_pedal_state, model: str = "") -> GaugeInputs:
  if not fresh:
    return GaugeInputs(model=model)
  long_active = bool(long_active)
  op = PED.finite(op_accel) if long_active else 0.0
  op_brake = PED.op_ibooster_applied(brake_pedal_state, long_active, brake_pressed)
  applied = bool(brake_pressed) or op_brake
  friction = 0.0
  if applied:
    if PED.finite(v_ego) < PED.STANDSTILL_V:
      friction = 1.0
    else:
      live = PED.regen_live(motor_torque_nm) if motor_torque_nm is not None else None
      decel = max(0.0, max(0.0, -PED.finite(a_ego)) - (live or 0.0))
      friction = PED.clamp(decel / PED.DECEL_FULL_SCALE, 0.0, 1.0)
  pedal = PED.finite(pedal_pos)
  driver_gas = bool(gas_pressed) or pedal > 0.0
  return GaugeInputs(friction=friction, regen_kw=regen_kw(motor_torque_nm, motor_rpm),
                     accel=PED.accel_fraction(pedal, op), engaged=long_active,
                     friction_src=DRIVER if brake_pressed else (OP if op_brake else DRIVER),
                     accel_src=DRIVER if driver_gas or not (long_active and op > 0.0) else OP, model=model)


def bars3(**signals) -> Bars3:
  """Signals -> gauge state (inputs_from_signals + gauge_state)."""
  return gauge_state(inputs_from_signals(**signals))
