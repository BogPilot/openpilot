"""Pre-AP Phase A: read-only Bosch radar donor VIN (UDS F190).

Opt-in (TeslaRadarReadVin, default off). Offroad / pre-engage only. Never
writes F190, never runs routine 0x0A03, never uses ALLOUTPUT. Stored value
lives under /data/params_bogpilot only — never log or commit a real VIN.

Credit: NotAutopilot / IRIT-able NAP-lineage radar_donor_vin (read-only path).
User-facing product name: BogPilot.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

RADAR_UDS_TX = 0x641
RADAR_UDS_RX = 0x651
RADAR_UDS_BUS = 1
ADDR_RADAR_ALERT = 0x501

TESTER_PRESENT = b"\x3e\x00"
DEFAULT_SESSION = b"\x10\x01"
EXTENDED_SESSION = b"\x10\x03"
READ_F190 = b"\x22\xf1\x90"
CLEANUP_MARKER = b"\x3e\x80"

# Exact ISO-TP payloads panda must allow (bus 1, addr 0x641). Match NAP F190 cut.
F190_ALLOWED_FRAMES = (
  bytes([0x02, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # tester present
  bytes([0x02, 0x10, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]),  # default session
  bytes([0x02, 0x10, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00]),  # extended session
  bytes([0x03, 0x22, 0xF1, 0x90, 0x00, 0x00, 0x00, 0x00]),  # ReadDataByIdentifier F190
  bytes([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # flow control
  bytes([0x02, 0x3E, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00]),  # cleanup marker
)

VIN_VALIDITY_BYTE = 4
VIN_VALIDITY_MASK = 0x10
FLOW_CONTROL_FRAME = (RADAR_UDS_TX, 0, F190_ALLOWED_FRAMES[4], RADAR_UDS_BUS)

# Shared RX stash: RadarInterface feeds, CarController drains for the commissioner.
_rx_stash: list[tuple[int, bytes, int]] = []


def normalize_radar_donor_vin(value) -> str:
  """Return a 17-char alphanumeric VIN, or empty if invalid. Never logs."""
  if value is None:
    text = ""
  elif isinstance(value, (bytes, bytearray)):
    text = bytes(value).decode("ascii", errors="ignore")
  else:
    text = str(value)
  vin = "".join(ch for ch in text.upper() if ch.isalnum())
  return vin if len(vin) == 17 else ""


def radar_alert_vin_validity(data: bytes) -> bool:
  return len(data) == 8 and (data[VIN_VALIDITY_BYTE] & VIN_VALIDITY_MASK) != 0


def _uds_frame(payload: bytes) -> tuple[int, int, bytes, int]:
  dat = (bytes([len(payload)]) + payload).ljust(8, b"\x00")
  return (RADAR_UDS_TX, 0, dat, RADAR_UDS_BUS)


def feed_can_strings(can_strings) -> None:
  """Append radar-bus UDS RX / alert frames from cereal can Event bytes."""
  global _rx_stash
  if not can_strings:
    return
  try:
    from cereal.messaging import log_from_bytes
  except Exception:
    return
  for raw in can_strings:
    try:
      msg = log_from_bytes(raw)
      cans = getattr(msg, "can", None)
      if cans is None:
        continue
      for c in cans:
        addr = int(c.address)
        bus = int(c.src)
        if bus == RADAR_UDS_BUS and addr in (RADAR_UDS_RX, ADDR_RADAR_ALERT):
          _rx_stash.append((addr, bytes(c.dat), bus))
    except Exception:
      continue
  # Cap stash so a stuck consumer cannot grow forever.
  if len(_rx_stash) > 256:
    _rx_stash = _rx_stash[-128:]


def drain_rx_packets() -> list[tuple[int, bytes, int]]:
  global _rx_stash
  out = _rx_stash
  _rx_stash = []
  return out


class RadarDonorVinState(Enum):
  IDLE = auto()
  TESTER_PRESENT = auto()
  DEFAULT_SESSION = auto()
  EXTENDED_SESSION = auto()
  READINESS = auto()
  READ_F190 = auto()
  CLEANUP = auto()
  COMPLETE = auto()
  FAILED = auto()


class RadarDonorVinFailure(Enum):
  ABORTED = auto()
  TIMEOUT = auto()
  MALFORMED_RESPONSE = auto()
  UNEXPECTED_RESPONSE = auto()
  NEGATIVE_RESPONSE = auto()
  INVALID_VIN = auto()


class _IsoTpState(Enum):
  INCOMPLETE = auto()
  COMPLETE = auto()
  MALFORMED = auto()


@dataclass(frozen=True)
class _IsoTpResult:
  state: _IsoTpState
  payload: bytes | None = None
  can_sends: tuple[tuple[int, int, bytes, int], ...] = ()


class _IsoTpAssembler:
  def __init__(self):
    self.reset()

  def consume(self, data: bytes, expected_prefix: bytes) -> _IsoTpResult:
    if len(data) != 8:
      return self._malformed()
    frame_type = data[0] >> 4
    if frame_type == 0:
      length = data[0] & 0x0F
      if self._length is not None or not 1 <= length <= 7:
        return self._malformed()
      payload = data[1:1 + length]
      if not payload.startswith(expected_prefix) and not payload.startswith(b"\x7f"):
        return self._malformed()
      return _IsoTpResult(_IsoTpState.COMPLETE, payload)
    if frame_type == 1:
      length = ((data[0] & 0x0F) << 8) | data[1]
      if self._length is not None or length <= 7:
        return self._malformed()
      prefix = data[2:]
      if not prefix.startswith(expected_prefix) and not prefix.startswith(b"\x7f"):
        return self._malformed()
      self._payload = bytearray(prefix)
      self._length = length
      self._sequence = 1
      return _IsoTpResult(_IsoTpState.INCOMPLETE, can_sends=(FLOW_CONTROL_FRAME,))
    if frame_type == 2:
      sequence = data[0] & 0x0F
      if self._length is None or sequence != self._sequence:
        return self._malformed()
      self._sequence = (self._sequence + 1) & 0x0F
      remaining = self._length - len(self._payload)
      self._payload.extend(data[1:1 + remaining])
      if len(self._payload) < self._length:
        return _IsoTpResult(_IsoTpState.INCOMPLETE)
      payload = bytes(self._payload)
      self.reset()
      return _IsoTpResult(_IsoTpState.COMPLETE, payload)
    return self._malformed()

  def reset(self) -> None:
    self._payload = bytearray()
    self._length: int | None = None
    self._sequence = 1

  def _malformed(self) -> _IsoTpResult:
    self.reset()
    return _IsoTpResult(_IsoTpState.MALFORMED)


@dataclass(frozen=True)
class RadarDonorVinOutput:
  state: RadarDonorVinState
  can_sends: tuple[tuple[int, int, bytes, int], ...] = ()
  vin: str | None = None
  failure: RadarDonorVinFailure | None = None


class RadarDonorVinReader:
  """One-shot F190 read. Offroad only; caller aborts when engaged."""

  RESPONSE_TIMEOUT = 3.0
  CLEANUP_TIMEOUT = 3.0
  OVERALL_TIMEOUT = 20.0

  def __init__(self, now: Callable[[], float] | None = None):
    self._now = now or (lambda: 0.0)
    self._assembler = _IsoTpAssembler()
    self.state = RadarDonorVinState.IDLE
    self.failure: RadarDonorVinFailure | None = None
    self.vin: str | None = None
    self._started_at = 0.0
    self._step_deadline: float | None = None
    self._request_sent = False

  def start(self) -> RadarDonorVinOutput:
    self.failure = None
    self.vin = None
    self._assembler.reset()
    self._started_at = self._now()
    return self._enter(RadarDonorVinState.TESTER_PRESENT, TESTER_PRESENT, self.RESPONSE_TIMEOUT)

  def abort(self) -> RadarDonorVinOutput:
    if self.state not in (RadarDonorVinState.IDLE, RadarDonorVinState.COMPLETE, RadarDonorVinState.FAILED):
      return self._fail(RadarDonorVinFailure.ABORTED)
    return RadarDonorVinOutput(self.state, vin=self.vin, failure=self.failure)

  def update(self, packets: list[tuple[int, bytes, int]]) -> RadarDonorVinOutput:
    if self.state in (RadarDonorVinState.IDLE, RadarDonorVinState.COMPLETE, RadarDonorVinState.FAILED):
      return RadarDonorVinOutput(self.state, vin=self.vin, failure=self.failure)

    now = self._now()
    if now - self._started_at >= self.OVERALL_TIMEOUT:
      return self._fail(RadarDonorVinFailure.TIMEOUT)
    if self._step_deadline is not None and now > self._step_deadline:
      return self._fail(RadarDonorVinFailure.TIMEOUT)

    if self.state == RadarDonorVinState.TESTER_PRESENT:
      return self._handle_uds(packets, b"\x7e\x00", RadarDonorVinState.DEFAULT_SESSION, DEFAULT_SESSION)
    if self.state == RadarDonorVinState.DEFAULT_SESSION:
      return self._handle_uds(packets, b"\x50\x01", RadarDonorVinState.EXTENDED_SESSION, EXTENDED_SESSION)
    if self.state == RadarDonorVinState.EXTENDED_SESSION:
      return self._handle_uds(packets, b"\x50\x03", RadarDonorVinState.READINESS, None)
    if self.state == RadarDonorVinState.READINESS:
      if any(bus == RADAR_UDS_BUS and addr == ADDR_RADAR_ALERT and radar_alert_vin_validity(data)
             for addr, data, bus in packets):
        return self._enter(RadarDonorVinState.READ_F190, READ_F190, self.RESPONSE_TIMEOUT)
      return RadarDonorVinOutput(self.state)
    if self.state == RadarDonorVinState.READ_F190:
      return self._handle_f190(packets)
    if self.state == RadarDonorVinState.CLEANUP:
      self.state = RadarDonorVinState.COMPLETE
      self._request_sent = False
      self._step_deadline = None
      return RadarDonorVinOutput(self.state, vin=self.vin)
    return RadarDonorVinOutput(self.state)

  def _handle_uds(self, packets, expected_prefix, next_state, next_payload):
    if not self._request_sent:
      return self._resend()
    for addr, data, bus in packets:
      if bus != RADAR_UDS_BUS or addr != RADAR_UDS_RX:
        continue
      result = self._assembler.consume(data, expected_prefix)
      if result.state == _IsoTpState.MALFORMED:
        return self._fail(RadarDonorVinFailure.MALFORMED_RESPONSE)
      if result.state == _IsoTpState.INCOMPLETE:
        return RadarDonorVinOutput(self.state, can_sends=result.can_sends)
      assert result.payload is not None
      if result.payload.startswith(b"\x7f"):
        return self._fail(RadarDonorVinFailure.NEGATIVE_RESPONSE)
      if not result.payload.startswith(expected_prefix):
        return self._fail(RadarDonorVinFailure.UNEXPECTED_RESPONSE)
      if next_payload is None:
        return self._enter(next_state, None, None)
      return self._enter(next_state, next_payload, self.RESPONSE_TIMEOUT)
    return RadarDonorVinOutput(self.state)

  def _handle_f190(self, packets):
    if not self._request_sent:
      return self._resend()
    for addr, data, bus in packets:
      if bus != RADAR_UDS_BUS or addr != RADAR_UDS_RX:
        continue
      result = self._assembler.consume(data, b"\x62\xf1\x90")
      if result.state == _IsoTpState.MALFORMED:
        return self._fail(RadarDonorVinFailure.MALFORMED_RESPONSE)
      if result.state == _IsoTpState.INCOMPLETE:
        return RadarDonorVinOutput(self.state, can_sends=result.can_sends)
      assert result.payload is not None
      if result.payload.startswith(b"\x7f"):
        return self._fail(RadarDonorVinFailure.NEGATIVE_RESPONSE)
      if not result.payload.startswith(b"\x62\xf1\x90"):
        return self._fail(RadarDonorVinFailure.UNEXPECTED_RESPONSE)
      vin = normalize_radar_donor_vin(result.payload[3:])
      if not vin:
        return self._fail(RadarDonorVinFailure.INVALID_VIN)
      self.vin = vin
      return self._enter(RadarDonorVinState.CLEANUP, CLEANUP_MARKER, self.CLEANUP_TIMEOUT)
    return RadarDonorVinOutput(self.state)

  def _enter(self, state, payload, timeout):
    self.state = state
    self._assembler.reset()
    self._request_sent = payload is not None
    self._step_deadline = None if timeout is None else self._now() + timeout
    can_sends = (_uds_frame(payload),) if payload is not None else ()
    return RadarDonorVinOutput(self.state, can_sends=can_sends, vin=self.vin)

  def _resend(self):
    payload = {
      RadarDonorVinState.TESTER_PRESENT: TESTER_PRESENT,
      RadarDonorVinState.DEFAULT_SESSION: DEFAULT_SESSION,
      RadarDonorVinState.EXTENDED_SESSION: EXTENDED_SESSION,
      RadarDonorVinState.READ_F190: READ_F190,
      RadarDonorVinState.CLEANUP: CLEANUP_MARKER,
    }[self.state]
    self._request_sent = True
    return RadarDonorVinOutput(self.state, can_sends=(_uds_frame(payload),))

  def _fail(self, failure):
    self.state = RadarDonorVinState.FAILED
    self.failure = failure
    self._request_sent = False
    self._step_deadline = None
    return RadarDonorVinOutput(self.state, failure=failure)


class RadarDonorVinCommissioner:
  """Read F190 when vinValidity sticks, or when the UI toggle asks once.

  Timing matches NAP card.py: abort when engaged; auto when no stored VIN and
  0x501 vinValidity sticky for STABLE_FRAMES; force_read for a one-shot.
  """

  STABLE_FRAMES = 8

  def __init__(self, store_vin: Callable[[str], None], now: Callable[[], float] | None = None):
    self.store_vin = store_vin
    self._now = now or (lambda: 0.0)
    self.reader = RadarDonorVinReader(now=self._now)
    self._vin_fault_frames = 0
    self._attempted = False
    self._force_used = False
    self._persisted = False

  @property
  def read_finished(self) -> bool:
    return self.reader.state in (RadarDonorVinState.COMPLETE, RadarDonorVinState.FAILED)

  def _persist(self, vin: str | None) -> None:
    if not vin or self._persisted:
      return
    self.store_vin(vin)
    self._persisted = True

  def _start(self) -> tuple[tuple[int, int, bytes, int], ...]:
    self._attempted = True
    self._persisted = False
    self._vin_fault_frames = 0
    return self.reader.start().can_sends

  def update(self, packets: list[tuple[int, bytes, int]], *, radar_enabled: bool,
             stored_vin: str, engaged: bool, force_read: bool = False
             ) -> tuple[tuple[int, int, bytes, int], ...]:
    if not radar_enabled:
      return ()

    running = self.reader.state not in (
      RadarDonorVinState.IDLE, RadarDonorVinState.COMPLETE, RadarDonorVinState.FAILED,
    )
    if engaged:
      if running:
        return self.reader.abort().can_sends
      return ()

    if not force_read:
      self._force_used = False
    elif force_read and not self._force_used and not running:
      self._force_used = True
      # start() already emits tester-present; return it (do not call update yet —
      # that would see _request_sent and drop the frame when packets are empty).
      return self._start()

    if self.reader.state in (RadarDonorVinState.COMPLETE, RadarDonorVinState.FAILED):
      self._persist(self.reader.vin)
      return ()
    if running:
      output = self.reader.update(packets)
      self._persist(output.vin)
      return output.can_sends

    if stored_vin or self._attempted:
      return ()
    for addr, data, bus in packets:
      if bus == RADAR_UDS_BUS and addr == ADDR_RADAR_ALERT and radar_alert_vin_validity(data):
        self._vin_fault_frames += 1
      elif bus == RADAR_UDS_BUS and addr == ADDR_RADAR_ALERT:
        self._vin_fault_frames = 0
    if self._vin_fault_frames < self.STABLE_FRAMES:
      return ()
    start_sends = self._start()
    output = self.reader.update(packets)
    self._persist(output.vin)
    return start_sends + output.can_sends
