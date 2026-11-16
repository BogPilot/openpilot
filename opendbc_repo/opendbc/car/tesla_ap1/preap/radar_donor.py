"""Pre-AP Bosch radar donor-VIN config: the host-to-panda 0x560 stream.

0x560 never goes on the car: the panda consumes it (tesla_preap.h tesla_preap_tx_hook) and, with flag 256, keeps the radar
gateway silent until all three records have arrived (NAP 604b9c49). With a donor VIN set (TeslaRadarDonorVin, 17 letters or
digits, entered by hand), the panda puts that VIN in the radar's 0x2B9 VIN records and sets the 0x2A9 4WD bit from VIN char 8,
so a salvage radar sees the car it came from. Empty (the default) = 17 spaces = this car, no substitution.

Layout: NAP opendbc/car/tesla/preap/teslacan.py:83-97 (create_radar_vin_msg, the Tinkla 0.6.6 packing) and
nap_conf.py:46-52 (normalize_radar_donor_vin) @ opendbc 5dbe36d37 (openpilot naponsp-alpha-prebuilt 7eb09d2a7).
Record 0 also carries the 0x2A9 radar position and EPAS type, which the panda applies (NAP f00c8cb9). Position is the Radar
Donor Type setting (TeslaRadarDonorType: 0 pre-facelift Model S, 1 facelift Model S, 2 Model X, default 0, as NAP
NAPRadarPosition), not the Radar Behind Nosecone toggle. EPAS 0.
Divergence (docs/tesla/DIVERGENCES.md): the stream is sent only while disengaged and not in Drive, because the panda counts every
consumed 0x560 as a blocked TX and the Pre-AP pull FSM treats a blocked TX as a pedal refusal. NAP streams it at 10 Hz all the time.
Never log the VIN. Raw CAN still carries it: these frames are in sendcan and come back as rejected echoes in can.
"""
from __future__ import annotations

from opendbc.car import structs
from opendbc.car.can_definitions import CanData

RADAR_VIN_ADDR = 0x560
RADAR_VIN_BUS = 0
VIN_LEN = 17
_VIN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def normalize_radar_donor_vin(value) -> str:
  """Return a 17-character donor VIN (A-Z, 0-9; separators dropped), or "" if the value is not one."""
  if isinstance(value, bytes):
    text = value.decode("ascii", errors="ignore")
  else:
    text = "" if value is None else str(value)
  vin = "".join(ch for ch in text.upper() if ch in _VIN_CHARS)
  return vin if len(vin) == VIN_LEN else ""


def create_radar_vin_msg(fragment: int, vin: str, use_radar: bool, position: int, epas_type: int) -> CanData:
  """One 0x560 record (0, 1 or 2). Record 0: useRadar / position / EPAS flags + VIN[0:3]; 1: VIN[3:10]; 2: VIN[10:17]."""
  padded = (vin + " " * VIN_LEN)[:VIN_LEN]
  if fragment == 0:
    flags = (1 if use_radar else 0) | ((position & 0x03) << 1) | ((epas_type & 0x07) << 3)
    dat = bytes((0, 1, flags, 0, 0, *padded[0:3].encode("ascii")))
  elif fragment == 1:
    dat = bytes((1, *padded[3:10].encode("ascii")))
  elif fragment == 2:
    dat = bytes((2, *padded[10:17].encode("ascii")))
  else:
    raise ValueError("0x560 record must be 0, 1 or 2")
  return CanData(RADAR_VIN_ADDR, dat, RADAR_VIN_BUS)


class RadarDonorStream:
  """Sends the 3 records, one every 10 frames (10 Hz at 100 Hz), only with flag 256, only while disengaged and not in Drive.

  The car starts in Park, so the panda has the full config ~0.3 s after start, before the car can move. The panda keeps it until
  its next safety init; it ignores 0x560 while engaged anyway.
  """

  def __init__(self, radar_emulation: bool, donor_vin: str, position: int):
    self.radar_emulation = bool(radar_emulation)
    self.vin = normalize_radar_donor_vin(donor_vin)
    self.position = position if type(position) is int and position in (0, 1, 2) else 0
    self.idx = 0

  @property
  def donor_active(self) -> bool:
    return self.vin != ""

  def update(self, frame: int, enabled: bool, gear_shifter) -> list[CanData]:
    if not self.radar_emulation or enabled or gear_shifter == structs.CarState.GearShifter.drive or (frame % 10) != 0:
      return []
    msg = create_radar_vin_msg(self.idx, self.vin, True, self.position, 0)
    self.idx = (self.idx + 1) % 3
    return [msg]
