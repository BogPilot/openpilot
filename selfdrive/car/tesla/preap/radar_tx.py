"""Pre-AP Bosch radar helper TX (dummy VIN + GTW_carConfig skeleton).

BogPilot 0.9.7 safety_hooks has no rx_all, so full NAP chassis→radar GTW
readdr cannot port as-is. When TeslaRadarEnabled is on, Python TX of a
whitelist of radar-bus frames is allowed by safety_tesla_preap.h behind
PREAP_FLAG_RADAR_EMULATION (default off).

NEVER put a real VIN here. Dummy constant only. Credit: Tinkla / NotAutopilot
radar VIN pattern; BogPilot product name.
"""
from __future__ import annotations

import struct

# 17-char placeholder — not a real vehicle identification number.
DUMMY_VIN = "TESTDUMMYVIN00000"
assert len(DUMMY_VIN) == 17
assert "DUMMY" in DUMMY_VIN

# Radar / chassis addresses used by Pre-AP Bosch setups (Tinkla PREAP_TX).
ADDR_VIN_VIP = 0x560   # 1376
ADDR_GTW_CAR_CONFIG = 0x2A9  # 681
ADDR_STW_ANGLHP = 0x199  # 409

# Allowed TX set when radar emulation flag is on (safety must match).
RADAR_TX_ADDRS = frozenset({
  ADDR_VIN_VIP,
  ADDR_GTW_CAR_CONFIG,
  ADDR_STW_ANGLHP,
})


def pack_dummy_vin(vin: str = DUMMY_VIN) -> bytes:
  """Pack 17-char VIN into Tesla VIN_VIP style 8-byte frames (first frame).

  Tesla VIN is often multi-frame; first 8 bytes of ASCII is enough for radar
  unlock on many Pre-AP Bosch units. Remaining frames left for a later cut.
  """
  if len(vin) != 17:
    raise ValueError("VIN must be 17 characters")
  # Never accept something that looks like a real production VIN pattern
  # without DUMMY / TEST marker — hard refuse.
  upper = vin.upper()
  if "DUMMY" not in upper and "TEST" not in upper:
    raise ValueError("refusing non-dummy VIN")
  payload = vin.encode("ascii")[:8]
  return payload.ljust(8, b"\x00")


def make_vin_can(bus: int = 1) -> tuple[int, bytes, int]:
  """Return (addr, dat, bus) for can_send."""
  return (ADDR_VIN_VIP, pack_dummy_vin(), bus)


def make_gtw_car_config(bus: int = 1) -> tuple[int, bytes, int]:
  """Minimal GTW_carConfig placeholder (zeros). Radar presence bit set in a later cut."""
  return (ADDR_GTW_CAR_CONFIG, b"\x00" * 8, bus)


def radar_tx_frames(*, enabled: bool, bus: int = 1) -> list[tuple[int, bytes, int]]:
  if not enabled:
    return []
  return [make_vin_can(bus), make_gtw_car_config(bus)]
