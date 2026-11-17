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
Stream: in any gear, including after a card start already in Drive, as long as openpilot is disengaged. NAP sends it at 10 Hz
whenever the radar is on, engaged or not (opendbc/car/tesla/preap/sp/carcontroller.py:69-77 @ 5dbe36d37; nap-alpha 92b42f772,
opendbc 508d26fcb: opendbc/car/tesla/carcontroller.py:143-152; donor position from 0x560 in NAP f00c8cb9).
Divergence (docs/tesla/DIVERGENCES_preap_radar_donor_vin.md): closed-loop, not always-on. The stream follows what the panda
reports (RadarDonorStream below): it runs only while the panda is in the car's mode with flag 256 and its gateway is not seen
open (no echo on src 129), and stops as soon as the gateway frames come back. If those echoes later stop, or the panda
re-inits or reboots, it starts again. It never runs while openpilot is engaged, steering, the pull FSM is in an engaged mode
or the panda allows controls (the panda ignores 0x560 then anyway, tesla_preap.h tesla_preap_radar_apply_vin_msg). The pull
FSM reads only refusals of our own pedal and steering frames (preap/panda_link.py TxRefusalWatch), so a 0x560 can never look
like one. Never log the VIN. Raw CAN still carries it: these frames are in sendcan and come back as rejected echoes in can.
"""
from __future__ import annotations

from enum import IntEnum

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


class Link(IntEnum):
  OFF = 0           # flag 256 not set: never sends
  WAIT_SAFETY = 1   # no panda in the car's mode with the expected param yet (ELM327, other mode, no pandaStates)
  STREAM = 2        # gateway not seen open: send the 3 records at 10 Hz while allowed
  OPEN = 3          # a gateway echo arrived within OPEN_HOLD_FRAMES: stop


OPEN_HOLD_FRAMES = 30     # 0.3 s at 100 Hz: echoes seen this recently = open (several gateway frames repeat every 10-20 ms,
                          # measured on a Pre-AP car, so an open gateway always echoes within this)
LOST_FRAMES = 30          # 0.3 s without an echo while OPEN, panda in the car's mode: re-arm. A same-mode re-init shows nothing
                          # else in pandaStates; a false re-arm only re-sends the same 3 records while disengaged


class RadarDonorStream:
  """The 0x560 config as a link state machine keyed on what the panda reports (CS.preap_link from card, panda_link.LinkInput).

  Re-arms to STREAM on a safety model/param transition, a panda uptime decrease (reboot), heartbeatLost, or gateway echoes
  absent for LOST_FRAMES. The panda clears the config on every safety init (tesla_preap.h tesla_preap_init_config) and keeps
  its gateway closed until all three records arrived; a re-init forces controls_allowed off (safety.h), so the car
  disengages and the stream resumes. Sends only while disengaged: not while enabled, steering, the pull FSM is engaged, or
  the panda allows controls. A card start whose first pandaStates sample already shows the car's mode (already in Drive)
  still streams: the panda may have no config at all (fresh boot) or may have been re-inited, and holding for Park was
  leaving the radar without car data for the whole drive.
  """

  def __init__(self, radar_emulation: bool, donor_vin: str, position: int, log_fn=None):
    self.radar_emulation = bool(radar_emulation)
    self.vin = normalize_radar_donor_vin(donor_vin)
    self.position = position if type(position) is int and position in (0, 1, 2) else 0
    self.idx = 0
    self.state = Link.OFF if not self.radar_emulation else Link.WAIT_SAFETY
    self.frame = 0
    self.last_echo_frame: int | None = None
    self.safety_key = None
    self.uptime: int | None = None
    self.rearms = 0
    self.sent = 0
    self.held_mode = 0

  @property
  def donor_active(self) -> bool:
    return self.vin != ""

  def _rearm(self, reinit: bool) -> None:
    self.rearms += 1
    self.last_echo_frame = None
    self.state = Link.STREAM

  def observe(self, link) -> None:
    """One step of panda evidence (panda_link.LinkInput or None)."""
    self.frame += 1
    if not self.radar_emulation:
      return
    if link is None:
      self.state = Link.WAIT_SAFETY
      return
    if link.gtw_echo:
      self.last_echo_frame = self.frame
    if link.new_sample:
      reinit = False
      if self.safety_key is not None and link.safety_key != self.safety_key:
        reinit = True
      if self.uptime is not None and link.uptime is not None and link.uptime < self.uptime:
        reinit = True
      if link.heartbeat_lost:
        reinit = True
      self.safety_key = link.safety_key
      self.uptime = link.uptime
      if not link.safety_ok:
        self.state = Link.WAIT_SAFETY
        self.last_echo_frame = None
        return
      if reinit or self.state == Link.WAIT_SAFETY:
        self._rearm(reinit)
    if self.state == Link.WAIT_SAFETY:
      return
    recent = self.last_echo_frame is not None and self.frame - self.last_echo_frame <= OPEN_HOLD_FRAMES
    if self.state == Link.STREAM and recent:
      self.state = Link.OPEN
    elif self.state == Link.OPEN:
      gone = self.last_echo_frame is None or self.frame - self.last_echo_frame > LOST_FRAMES
      if gone and not link.controls_allowed:
        self._rearm(False)

  def update(self, frame: int, enabled: bool, steering: bool = False, link=None, fsm_engaged: bool = False) -> list[CanData]:
    self.observe(link)
    if self.state != Link.STREAM or (frame % 10) != 0:
      return []
    if link is None or not link.safety_ok:
      # checked every step on the latest pandaStates, not only on a new sample: any other mode stops the stream at once
      self.held_mode += 1
      return []
    if enabled or steering or fsm_engaged or (link is not None and link.controls_allowed):
      return []
    msg = create_radar_vin_msg(self.idx, self.vin, True, self.position, 0)
    self.idx = (self.idx + 1) % 3
    self.sent += 1
    return [msg]
