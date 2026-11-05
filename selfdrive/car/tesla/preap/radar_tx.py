"""Pre-AP Bosch radar helper TX (dummy VIN + GTW_carConfig keepalive).

Panda SAFETY_TESLA_PREAP with PREAP_FLAG_RADAR_EMULATION runs NAP-style GTW
readdr in firmware (rx_all): chassis bus0 → radar bus1 at wire rate, including
0x398→0x2A9 carConfig patching and 0x118→0x169 wheel speeds. That path is what
wakes a self-installed Bosch radar so it emits RadarPoint / 0x300 status.

Userspace still sends:
  - dummy VIN_VIP (0x560) — firmware does not synthesize VIN
  - a low-rate GTW_carConfig (0x2A9) keepalive matching the NAP bitfield patch
    (Bosch forward radar, autopilot=1, optional nosecone position). Useful when
    chassis 0x398 is rare/event-triggered.

NEVER put a real VIN here. Dummy constant only.
Credit: NotAutopilot tesla_preap GTW; Tinkla Pre-AP radar VIN pattern.
"""
from __future__ import annotations

# 17-char placeholder — not a real vehicle identification number.
DUMMY_VIN = "TESTDUMMYVIN00000"
assert len(DUMMY_VIN) == 17
assert "DUMMY" in DUMMY_VIN

# Radar / chassis addresses used by Pre-AP Bosch setups.
ADDR_VIN_VIP = 0x560   # 1376
ADDR_GTW_CAR_CONFIG = 0x2A9  # 681
ADDR_STW_ANGLHP = 0x199  # 409

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
  upper = vin.upper()
  if "DUMMY" not in upper and "TEST" not in upper:
    raise ValueError("refusing non-dummy VIN")
  payload = vin.encode("ascii")[:8]
  return payload.ljust(8, b"\x00")


def pack_gtw_car_config(*, behind_nosecone: bool = False, epas_type: int = 0) -> bytes:
  """Build GTW_carConfig (0x2A9) matching NAP bitfield patch from zeros.

  NAP (tesla_preap_gtw_emulation Group B) sets:
    lo = (lo & 0xFFFFF33F) | 0x100 | 0x440   # park_assist/das + Bosch fwd radar
    hi = (hi & 0xCFFF0F0F) | 0x10000000 | (radar_position << 4) | (epas_type << 12)
  Do NOT write a checksum into byte7: opendbc tesla_radar_bosch BO_681 comment is
  "All fixed bytes, no checksum", and tesla_can.dbc maps byte7 to GTW_autopilot
  (bits 61-60) / unknown3 — a checksum would clobber autopilot=1 (0x10000000).
  """
  radar_position = 1 if behind_nosecone else 0
  epas_type = int(epas_type) & 0x0F
  lo = 0x100 | 0x440
  hi = 0x10000000 | (radar_position << 4) | (epas_type << 12)
  return lo.to_bytes(4, "little") + hi.to_bytes(4, "little")


def make_vin_can(bus: int = 1) -> tuple[int, int, bytes, int]:
  """Return (addr, 0, dat, bus) for sendcan (same 4-tuple as CANPacker.make_can_msg)."""
  return (ADDR_VIN_VIP, 0, pack_dummy_vin(), bus)


def make_gtw_car_config(bus: int = 1, *, behind_nosecone: bool = False,
                        epas_type: int = 0) -> tuple[int, int, bytes, int]:
  return (ADDR_GTW_CAR_CONFIG, 0, pack_gtw_car_config(
    behind_nosecone=behind_nosecone, epas_type=epas_type), bus)


def radar_tx_frames(*, enabled: bool, bus: int = 1,
                    behind_nosecone: bool | None = None) -> list[tuple[int, int, bytes, int]]:
  """Radar-bus helper frames. Empty when disabled (safety + carcontroller default).

  behind_nosecone: optional override; default reads TeslaRadarBehindNosecone so
  callers (incl. napcal-owned carcontroller) need no signature change.
  """
  if not enabled:
    return []
  if behind_nosecone is None:
    try:
      from openpilot.selfdrive.car.tesla.preap.params import PreApParamKeys, get_bool
      behind_nosecone = bool(get_bool(PreApParamKeys.RADAR_BEHIND_NOSECONE, False))
    except Exception:
      behind_nosecone = False
  return [
    make_vin_can(bus),
    make_gtw_car_config(bus, behind_nosecone=bool(behind_nosecone)),
  ]
