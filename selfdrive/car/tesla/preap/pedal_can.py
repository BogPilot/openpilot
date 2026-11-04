"""Comma Pedal GAS_COMMAND (0x551) packing — from NotAutopilot TeslaCANPreAP.

Credit: NotAutopilot. License: MIT (openpilot lineage). Keep this notice.
"""
from __future__ import annotations

import struct
from ctypes import create_string_buffer

# Comma Pedal protocol constants (NotAutopilot / Comma Pedal firmware)
PEDAL_M1 = 0.050796813
PEDAL_M2 = 0.101593626
PEDAL_D = -22.85856576
GAS_COMMAND_ID = 0x551


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
                         pedal_can_bus: int = 2) -> tuple[int, bytes, int]:
  """Build (addr, data, bus) for GAS_COMMAND. accel_command is percent-ish pedal units."""
  idx = counter.next_idx()
  if enable == 1:
    int_cmd1 = max(0, min(65534, int((accel_command - PEDAL_D) / PEDAL_M1)))
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
  return (GAS_COMMAND_ID, bytes(msg.raw), pedal_can_bus)
