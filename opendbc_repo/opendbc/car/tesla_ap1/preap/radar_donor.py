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
Stream: in any gear, as NAP, which sends it at 10 Hz whenever the radar is on (opendbc/car/tesla/preap/sp/carcontroller.py:69-77
@ 5dbe36d37), so the panda has the full config within 0.3 s of any safety init, even one while the car is already in Drive.
Divergence (docs/tesla/DIVERGENCES_preap_radar_donor_vin.md): not sent while openpilot is engaged or steering (the panda ignores
0x560 then anyway). The panda counts every consumed 0x560 as a blocked TX; card.py takes this stream's own frames back out of that
count (OwnBlockedTx below), so the Pre-AP pull FSM sees only other blocked TX as a pedal refusal.
Never log the VIN. Raw CAN still carries it: these frames are in sendcan and come back as rejected echoes in can.
"""
from __future__ import annotations

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
  """Sends the 3 records, one every 10 frames (10 Hz at 100 Hz), only with flag 256, in any gear, only while disengaged and not steering.

  The panda clears the config on every safety init (the switch to the car's safety mode comes ~15 s after start, when the driver may
  already be in Drive) and keeps its radar gateway closed until all three records arrived, so the stream does not wait for Park:
  the gateway opens <= 0.3 s after any safety init while disengaged. The panda ignores 0x560 while controls are allowed or its
  steering latch is armed, and so does this stream while engaged or steering; the config set before engaging stays in place.
  """

  def __init__(self, radar_emulation: bool, donor_vin: str, position: int):
    self.radar_emulation = bool(radar_emulation)
    self.vin = normalize_radar_donor_vin(donor_vin)
    self.position = position if type(position) is int and position in (0, 1, 2) else 0
    self.idx = 0

  @property
  def donor_active(self) -> bool:
    return self.vin != ""

  def update(self, frame: int, enabled: bool, steering: bool = False) -> list[CanData]:
    if not self.radar_emulation or enabled or steering or (frame % 10) != 0:
      return []
    msg = create_radar_vin_msg(self.idx, self.vin, True, self.position, 0)
    self.idx = (self.idx + 1) % 3
    return [msg]


class OwnBlockedTx:
  """Takes this stream's own 0x560 frames back out of the panda's blocked-TX count (pandaStates.safetyTxBlocked).

  The panda counts every 0x560 as a blocked TX (can_common.h can_send): ELM327 refuses it, the car's mode consumes it. card sees
  the total at 10 Hz. sent() records each step's 0x560 frames as credits, at send time, so a credit always exists before the
  sample that counts its frame. take() spends credits against a counter increase and returns the rest, which is blocked TX of
  any other address. Never negative, and never more subtracted than 0x560 frames were really sent.
  A credit expires after ttl_steps card steps (0.3 s at 100 Hz, 3 samples). Credits are spent newest first, so a credit left by
  a frame the panda never counted (sendcan lost, panda gone) ages out instead of standing in for newer frames. Only such a
  credit can hide another blocked frame, one for one, for at most those 0.3 s (at most 3 at 10 Hz); a refusal blocks every
  command frame (50 Hz and up).
  The rejected echoes (src + 0xC0 in can) are not used: they come back on another path than the 10 Hz counter sample, so an echo
  can arrive after the sample that counted it, and they are dropped on an rx overflow.
  """

  def __init__(self, ttl_steps: int = 30):
    self.ttl_steps = int(ttl_steps)
    self.credits: list[list[int]] = []   # [step sent, frames left]

  @staticmethod
  def count(can_sends) -> int:
    return sum(1 for m in can_sends if m[0] == RADAR_VIN_ADDR and m[2] == RADAR_VIN_BUS)

  def sent(self, n: int, step: int) -> None:
    if n > 0:
      self.credits.append([int(step), int(n)])

  def take(self, delta: int, step: int) -> int:
    self.credits = [c for c in self.credits if step - c[0] <= self.ttl_steps]
    left = max(int(delta), 0)
    for c in reversed(self.credits):
      used = min(left, c[1])
      c[1] -= used
      left -= used
    self.credits = [c for c in self.credits if c[1] > 0]
    return left
