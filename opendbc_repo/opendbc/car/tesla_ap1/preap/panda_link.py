"""Pre-AP host view of the panda, from what the panda itself reports: card feeds it, the 0x560 stream and the pull FSM read it.

Two inputs, both already on the host (no panda change):
- pandaStates (10 Hz): safetyModel / safetyParam, uptime, heartbeatLost, controlsAllowed, safetyTxBlocked (cereal log.capnp:547-570).
- The panda's TX echoes in 'can' (selfdrive/pandad/panda.cc:262-270): a frame the safety tx hook refused comes back with
  src = bus + 0xC0 (REJECTED, panda/board/drivers/can_common.h can_send), a frame the panda put on a bus comes back with
  src = bus + 0x80 (RETURNED). The Pre-AP radar gateway sends every emulated frame with can_send(pkt, 1, true)
  (opendbc/safety/modes/tesla_preap_radar.h), so each one returns on src 129: that is the proof the gateway is open.

GTW_ECHO_ADDRS is every address tesla_preap_radar.h puts on bus 1 (tests/test_preap_panda_link.py re-reads the header).
Nothing here logs frame data; counts only.
"""
from __future__ import annotations

from dataclasses import dataclass

from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.values import TeslaAp1SafetyFlags

CAN_RETURNED_BUS_OFFSET = 0x80   # selfdrive/pandad/panda.h
CAN_REJECTED_BUS_OFFSET = 0xC0
RADAR_BUS = 1
GTW_ECHO_SRC = RADAR_BUS + CAN_RETURNED_BUS_OFFSET   # 129

# tesla_preap_radar.h: re-addressed (0x219 0x109 0x149 0x159 0x209 0x2D9 0x129 0x119) and built (0x2A9 0x2B9 0x199 0x1A9 0x169) frames.
GTW_ECHO_ADDRS = frozenset((0x109, 0x119, 0x129, 0x149, 0x159, 0x169, 0x199, 0x1A9, 0x209, 0x219, 0x2A9, 0x2B9, 0x2D9))

PEDAL_ADDR = 0x551        # preap/pedal_can.py GAS_COMMAND, bus 0 or 2 (tesla_preap.h TX list)
STEER_ADDR = 0x488        # DAS_steeringControl, bus 0
RADAR_VIN_ADDR = 0x560    # preap/radar_donor.py, host to panda only, always refused by design
OWN_CONTROL_TX = frozenset(((PEDAL_ADDR, 0), (PEDAL_ADDR, 2), (STEER_ADDR, 0)))
PANDA_BUSES = 4           # sendcan bus b goes to panda b // 4 (selfdrive/pandad/panda.cc:176)

SAFETY_TESLA = int(CarParams.SafetyModel.tesla)   # car.capnp SafetyModel tesla @10; tesla_preap.h hooks need the PREAP flag
FLAG_PREAP = int(TeslaAp1SafetyFlags.PREAP)
FLAG_AP1 = int(TeslaAp1SafetyFlags.AP1)


def preap_mode_ok(safety_model: int, safety_param: int, expect) -> bool:
  """True only when one pandaStates entry shows the Pre-AP car mode: SafetyModel.tesla with the PREAP flag (never the AP1 flag)
  and exactly the param card expects for that panda (expect: (model, param) from CarParams.safetyConfigs). Every other mode
  (ELM327, noOutput, allOutput, silent, another param) is False."""
  if expect is None:
    return False
  model, param = int(safety_model), int(safety_param)
  return (model == SAFETY_TESLA and (param & FLAG_PREAP) != 0 and (param & FLAG_AP1) == 0
          and (model, param) == (int(expect[0]), int(expect[1])))


@dataclass
class EchoCounts:
  """One card step of TX echoes."""
  gtw: int = 0              # returned radar-gateway frames (src 129)
  rejected_control: int = 0  # refused 0x551 / 0x488 (the pull FSM's refusal input)
  rejected_560: int = 0      # refused 0x560 (expected, never a refusal)
  rejected_other: int = 0    # any other refused frame


def scan_echoes(can_list) -> EchoCounts:
  """can_list: card's can_capnp_to_list output, [(nanos, [(address, dat, src), ...]), ...]."""
  out = EchoCounts()
  for _, msgs in can_list:
    for addr, _dat, src in msgs:
      if src == GTW_ECHO_SRC:
        if addr in GTW_ECHO_ADDRS:
          out.gtw += 1
      elif src >= CAN_REJECTED_BUS_OFFSET:
        bus = src - CAN_REJECTED_BUS_OFFSET
        if (addr, bus) in OWN_CONTROL_TX:
          out.rejected_control += 1
        elif addr == RADAR_VIN_ADDR:
          out.rejected_560 += 1
        else:
          out.rejected_other += 1
  return out


@dataclass(frozen=True)
class PandaSample:
  """The fields of one pandaStates entry the Pre-AP link needs (plain values, no capnp)."""
  safety_model: int
  safety_param: int
  uptime: int
  heartbeat_lost: bool
  controls_allowed: bool
  tx_blocked: int


@dataclass
class LinkInput:
  """What card hands the CarController each step (CS.preap_link)."""
  safety_ok: bool = False          # panda 0 (bus 0, where 0x560 and our control frames go) shows the Pre-AP car mode (preap_mode_ok)
  safety_key: tuple | None = None  # (model, param) of that panda, for transition detection
  uptime: int | None = None
  heartbeat_lost: bool = False
  controls_allowed: bool = False
  new_sample: bool = False         # a new pandaStates sample arrived this step
  gtw_echo: bool = False           # a radar-gateway echo arrived this step


def u32_delta(new: int, old: int | None) -> int | None:
  """Increase of a u32 running total; None after a reset (the panda re-init clears it, a reboot too)."""
  if old is None:
    return None
  if new >= old:
    return new - old
  if old - new > 0x7FFFFFFF:          # wrapped
    return new + 0x100000000 - old
  return None


class RateLimitedLog:
  """At most one message per period_s; the next one carries how many were held back."""

  def __init__(self, log_fn, period_s: float = 10.0):
    self.log_fn = log_fn
    self.period_s = period_s
    self.last: float | None = None
    self.suppressed = 0

  def __call__(self, now: float, msg: str) -> bool:
    if self.last is not None and now - self.last < self.period_s:
      self.suppressed += 1
      return False
    extra = f" (+{self.suppressed} suppressed)" if self.suppressed else ""
    self.last, self.suppressed = now, 0
    self.log_fn(msg + extra)
    return True


class TxRefusalWatch:
  """The pull FSM's blocked-TX input: refusals of OUR OWN 0x551 / 0x488 frames, read from their rejected echoes.

  A 0x560 echo has another address, so the radar config stream can never read as a pedal refusal, whatever the timing.
  The global counter (pandaStates.safetyTxBlocked) is only a cross-check: per sample, the blocked increase is matched against
  the rejected echoes card saw (every address). Echoes may arrive one sample late, so a shortfall is carried for one sample.
  A shortfall still open after that means rejected echoes were lost (the panda drops them on an rx queue overflow).
  Then, fail-safe, the lost count is passed to the FSM as refusals, unless card sent a 0x560 in this or the previous two
  sample windows (the lost echo could be ours): that case is logged only. In FULL card sends no 0x560 (radar_donor.py), so a
  refusal whose echo was lost still demotes there.
  Refusals count only once pandaStates shows the car's mode (car_mode, from card): before the switch the panda runs ELM327 and
  refuses every frame on bus 0, which is not a pedal or steering refusal. Those are counted in ignored_pre_mode only, and the
  cross-check restarts, so nothing from before the switch is carried into it.
  """

  def __init__(self):
    self.prev_total: int | None = None
    self.echoes_since_sample = 0
    self.carry = 0
    self.sent_560_windows = [0, 0, 0]   # this window, previous, the one before
    self.unexplained = 0                # lost echoes seen so far (counts, for the status line)
    self.ignored_pre_mode = 0           # refused own control frames while the panda was not yet in the car's mode

  def step(self, echoes: EchoCounts, sent_560: int, totals: list[int] | None, car_mode: bool = True) -> tuple[int, int]:
    """One card step. totals: per-panda safetyTxBlocked when a NEW pandaStates sample arrived, else None.
    car_mode: pandaStates showed the car's mode on this and the previous step (card). Returns (refusals for the FSM, lost
    echoes logged only)."""
    if not car_mode:
      self.ignored_pre_mode += int(echoes.rejected_control)
      if totals is not None:
        self.prev_total = sum(int(t) for t in totals)
      self.carry = 0
      self.echoes_since_sample = 0
      self.sent_560_windows = [0, 0, 0]
      return 0, 0
    refusals = int(echoes.rejected_control)
    logged = 0
    self.echoes_since_sample += echoes.rejected_control + echoes.rejected_560 + echoes.rejected_other
    self.sent_560_windows[0] += max(int(sent_560), 0)
    if totals is not None:
      total = sum(int(t) for t in totals)
      delta = u32_delta(total, self.prev_total)
      self.prev_total = total
      if delta is None:
        self.carry = 0                  # counter reset (panda init / reboot): start over
      else:
        d = delta - self.echoes_since_sample
        if d < 0:                       # late echoes for the previous sample's count
          self.carry = max(0, self.carry + d)
          d = 0
        lost, self.carry = self.carry, d
        if lost > 0:
          self.unexplained += lost
          if sum(self.sent_560_windows) > 0:
            logged = lost
          else:
            refusals += lost
      self.echoes_since_sample = 0
      self.sent_560_windows = [0] + self.sent_560_windows[:2]
    return refusals, logged


def count_sent(can_sends, addr: int) -> int:
  return sum(1 for m in can_sends if m[0] == addr)
