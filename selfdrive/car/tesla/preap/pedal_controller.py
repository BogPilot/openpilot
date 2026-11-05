"""NAP-style Pre-AP pedal DI mapping: zero-torque learn, deadband, ramps, hysteresis.

Credit: NAP-style. DI→pedal uses BogPilot PedalCalib* (current_pedal_transform).
Passive PedalCalib* learning stays as-is.
"""
from __future__ import annotations

from math import isfinite

from numpy import clip, interp

from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.car.tesla.preap.calib import (
  current_pedal_transform,
  transform_di_to_pedal,
  transform_pedal_to_di,
)
from openpilot.selfdrive.car.tesla.preap.vdas_constants import (
  ACCEL_DEADBAND, ACCEL_MAX, PEDAL_BP, PEDAL_DI_MIN, PEDAL_DI_ZERO,
  PEDAL_HYST_GAP, PEDAL_MAX_VALUES, PEDAL_RAMP_RATE_DOWN, PEDAL_RAMP_RATE_UP,
  REGEN_MAX,
)

# Zero-torque learning (NAP PedalZeroTorque)
TORQUE_LEVEL_ACC = 0.0
TORQUE_LEVEL_DECEL = -30.0
ZERO_TORQUE_MIN_SPEED = 10.0 * CV.MPH_TO_MS
ZERO_TORQUE_SETTLE_UPDATES = 25  # 0.5s at 50 Hz
ZERO_TORQUE_ADAPT_RATE = 0.1  # DI per update


class PedalZeroTorque:
  """Learns the pedal DI position that produces zero motor torque."""

  def __init__(self):
    self.value = PEDAL_DI_ZERO
    self._target = PEDAL_DI_ZERO
    self._best_torque = TORQUE_LEVEL_DECEL
    self._settled_updates = 0

  def update(self, torque_level: float, current_pedal_di: float, v_ego: float, *,
             control_active: bool, accel_command: float):
    observation_valid = (
      control_active
      and all(isfinite(value) for value in (torque_level, current_pedal_di, v_ego, accel_command))
      and v_ego >= ZERO_TORQUE_MIN_SPEED
      and abs(accel_command) < ACCEL_DEADBAND
    )
    if observation_valid:
      self._settled_updates += 1
    else:
      self._settled_updates = 0
      self._best_torque = TORQUE_LEVEL_DECEL

    if (self._settled_updates >= ZERO_TORQUE_SETTLE_UPDATES
        and TORQUE_LEVEL_DECEL < torque_level < TORQUE_LEVEL_ACC
        and abs(torque_level) < abs(self._best_torque)):
      self._target = current_pedal_di
      self._best_torque = torque_level

    if self._settled_updates >= ZERO_TORQUE_SETTLE_UPDATES:
      self.value = float(clip(
        self._target,
        self.value - ZERO_TORQUE_ADAPT_RATE,
        self.value + ZERO_TORQUE_ADAPT_RATE,
      ))

  def get(self, v_ego: float) -> float:
    if v_ego < 5.0 * CV.MPH_TO_MS:
      return PEDAL_DI_ZERO
    return self.value


_zero_torque = PedalZeroTorque()


def get_zero_torque():
  return _zero_torque


def get_pedal_profile_values():
  return list(PEDAL_MAX_VALUES)


def di_to_pedal(val: float) -> float:
  zero, factor = current_pedal_transform()
  return transform_di_to_pedal(val, zero, factor)


def pedal_to_di(val: float) -> float:
  zero, factor = current_pedal_transform()
  return transform_pedal_to_di(val, zero, factor)


def compute_pedal_command(accel_request: float, v_ego: float, prev_pedal_di: float,
                          target_speed_kph: float | None = None) -> tuple[float, float]:
  """Convert acceleration request (m/s^2) to comma pedal command.

  Returns (pedal_cmd, updated_prev_pedal_di). Legacy open-loop path; VirtualDAS
  is the live controller. Kept for unit tests and fallback.
  """
  del target_speed_kph  # unused; NAP signature compatibility
  pedal_profile = get_pedal_profile_values()
  max_pedal_value = float(interp(v_ego, PEDAL_BP, pedal_profile))
  zero_torque_di = _zero_torque.get(v_ego)

  if abs(accel_request) < ACCEL_DEADBAND:
    accel_request = 0.0

  accel_bp = [REGEN_MAX, 0.0, ACCEL_MAX]
  accel_v = [PEDAL_DI_MIN, zero_torque_di, max_pedal_value]
  pedal_di = float(interp(accel_request, accel_bp, accel_v))
  pedal_di = float(clip(pedal_di, PEDAL_DI_MIN, max_pedal_value))
  pedal_di = float(clip(pedal_di, prev_pedal_di - PEDAL_RAMP_RATE_DOWN, prev_pedal_di + PEDAL_RAMP_RATE_UP))

  if abs(pedal_di - prev_pedal_di) < PEDAL_HYST_GAP:
    pedal_di = prev_pedal_di

  return di_to_pedal(pedal_di), pedal_di
