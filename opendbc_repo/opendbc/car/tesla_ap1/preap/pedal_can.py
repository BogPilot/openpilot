"""Comma Pedal GAS_COMMAND (0x551) packing — from the upstream legacy port TeslaCANPreAP.

Credit: the upstream legacy port. License: MIT (openpilot lineage). Keep this notice.
"""
from __future__ import annotations

import struct
from ctypes import create_string_buffer

from opendbc.car.can_definitions import CanData

# Comma Pedal protocol constants (the upstream legacy port / Comma Pedal firmware)
PEDAL_M1 = 0.050796813
PEDAL_M2 = 0.101593626
PEDAL_D = -22.85856576
GAS_COMMAND_ID = 0x551

# The pedal-command limit. ONE place defines it; the calibration check (calib.py) and the command encoder below both use it.
# PANDA_MAX_ENABLED_RAW_GAS_CMD mirrors `max_enabled_raw_gas_cmd` in opendbc/safety/modes/tesla_preap.h: the panda drops every
# enabled 0x551 frame whose raw 16-bit command is above it (a test reads the C file and pins the two to the same number).
# PEDAL_RAW_MARGIN keeps our own commands clear of that edge (integer truncation, a little rounding), so a frame we build is
# never one the panda would drop.
PANDA_MAX_ENABLED_RAW_GAS_CMD = 2500
PEDAL_RAW_MARGIN = 50
PEDAL_ENABLED_RAW_LIMIT = PANDA_MAX_ENABLED_RAW_GAS_CMD - PEDAL_RAW_MARGIN


def accel_command_to_raw(accel_command: float) -> int:
  """The 16-bit command field the panda checks (0x551 bytes 0-1), for a pedal command in percent-ish units."""
  return max(0, min(65534, int((accel_command - PEDAL_D) / PEDAL_M1)))


def raw_to_accel_command(raw: float) -> float:
  return raw * PEDAL_M1 + PEDAL_D


# Highest pedal command we ever send while enabled, in the same units as accel_command (about 101.6).
PEDAL_ENABLED_COMMAND_LIMIT = raw_to_accel_command(PEDAL_ENABLED_RAW_LIMIT)


def pedal_checksum(msg_id: int, dat: bytes) -> int:
  ret = (msg_id & 0xFF) + ((msg_id >> 8) & 0xFF)
  ret += sum(dat)
  return ret & 0xFF


class PedalCommandCounter:
  """Consecutive counter required by pedal firmware watchdog."""

  def __init__(self) -> None:
    self.idx = 0

  def next_idx(self) -> int:
    i = self.idx
    self.idx = (self.idx + 1) % 16
    return i


def create_pedal_command(accel_command: float, enable: int, counter: PedalCommandCounter,
                         pedal_can_bus: int = 2) -> CanData:
  """Build the GAS_COMMAND (0x551) frame. accel_command is percent-ish pedal units."""
  idx = counter.next_idx()
  if enable == 1:
    # Never build a frame above the shared limit: the panda would drop it and the pedal would fall back to the driver's foot.
    accel_command = min(accel_command, PEDAL_ENABLED_COMMAND_LIMIT)
    int_cmd1 = accel_command_to_raw(accel_command)
    int_cmd2 = max(0, min(65534, int((accel_command - PEDAL_D) / PEDAL_M2)))
  else:
    int_cmd1 = 0
    int_cmd2 = 0

  msg = create_string_buffer(6)
  struct.pack_into("BBBBB", msg, 0,
                   (int_cmd1 >> 8) & 0xFF, int_cmd1 & 0xFF,
                   (int_cmd2 >> 8) & 0xFF, int_cmd2 & 0xFF,
                   ((enable << 7) + idx) & 0xFF)
  struct.pack_into("B", msg, 5, pedal_checksum(GAS_COMMAND_ID, msg.raw))
  return CanData(GAS_COMMAND_ID, bytes(msg.raw), pedal_can_bus)
