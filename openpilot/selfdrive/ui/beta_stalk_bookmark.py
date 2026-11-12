"""BETA-ONLY (remove before production): 3 quick FWD stalk taps after disengaging -> userBookmark.

New BogPilot beta behavior; no parity source. BogPilot 0.9.7, Tinkla/BogGyver and NAP have no stalk bookmark: FWD is
cancel only in all three. It lets a beta tester mark a moment in the logs. See docs/tesla/DIVERGENCES_beta_stalk_bookmark.md.

Observe-only. Reads carState (bogpilot.spdCtrlLvr from the bus-0 chassis parser, cruiseState.enabled,
canValid), selfdriveState.enabled and sendcan (only to see our own 0x45 TX). Sends userBookmark through the
UI's existing PubMaster. Never touches car code, buttonEvents, cruise/engagement state, CAN TX, panda,
PreAPEngagement, StockCCSpoofer, the pre-AP panda-drop latch or the Experimental FWD hold.
Default off: /data/params_bogpilot/BetaStalkBookmark must contain "1". Explicit fingerprint allow-list.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FLAG = Path('/data/params_bogpilot/BetaStalkBookmark')


@dataclass(frozen=True)
class PlatformEntry:
  fingerprint: str
  # AND carState.cruiseState.enabled into the onset-disengaged rule. selfdriveState.enabled is always used.
  # AP1: cruiseState.enabled is DI cruise (tesla_ap1/carstate.py:120-122). Never looser to keep it True: where
  # a fork forces it False (pre-AP pedal long), the AND reduces to selfdriveState alone.
  cruise_state_gate: bool
  evidence: str


# Explicit allow-list. One entry per platform, added only when its
# evidence (E1 on-car 0x45 capture + real 3-tap train, E2 for AP2, E3 real-drive replay) is in. No catch-all.
ALLOW_LIST: tuple[PlatformEntry, ...] = (
  PlatformEntry('TESLA_AP1_MODELS', True, 'real-drive replay, AP1 Model S'),
)
# Not enabled, by design (documented only; nothing reads this):
#   TESLA_PREAP_MODELS  pending E1, E3, P1 capture, P2 replay, P3 (stock DI cruise is not visible to the UI)
#   TESLA_AP1_MODELX    pending E1, E3
#   AP2 S / AP2 X       no fingerprint in tesla_ap1/values.py; pending E1, E2, E3
#   Raven/HW3, Model 3/Y and every non-legacy platform: out of scope, never listed.

COUNT_DISENGAGE_TAP = False      # the disengaging cancel never counts
N_TAPS = 3
TAP_MIN_S, TAP_MAX_S = 0.05, 0.30
GAP_MAX_S, SPAN_MAX_S = 1.00, 1.20
LOCKOUT_IDLE_S = 1.00            # no re-fire until IDLE > 1.00 s or an abort
STALE_S = 0.25                   # same as phase3_stalk_controls.MAX_SAMPLE_AGE_S
# Two distinct 0.30 s windows; they share a value but not a meaning or an edge:
DISENGAGE_GUARD_S = 0.30         # DISENGAGE GUARD: no counted tap starts < 0.30 s after the latest fall of cs OR sds
# OWN-TX DROP (defense in depth, unconditional, every platform): a FWD onset within TX_DROP_S after one of our own sendcan
# 0x45 frames is never counted, and our own 0x45 TX while a train is counting (press timed or taps counted) resets it to
# IDLE, so a dropped onset can never merge two presses into one tap. The post-fire lockout is kept (no re-fire until
# IDLE > 1.00 s). The bus-0 parser already reads src 0 only. Window from NAP, which ignores
# a stalk cancel within SPOOF_ECHO_WINDOW_MS = 300 after its own spoof TX (pre-AP engagement.py:10,187-190, opendbc
# cc39c7fa). Supporting measurement on a real pre-AP drive log: 15 own 0x45 frames, src-128 echo 2.91 / 5.20 / 6.13 ms
# (min / median / max) after the send, far inside 300 ms. Cost: a real press < 300 ms after our TX is not counted (false
# negative, never a false bookmark). AP1 also TXes 0x45 cancel (tesla_ap1/carcontroller.py:212-213).
TX_DROP_S = 0.30                 # OWN-TX DROP window (not the disengage guard)
STW_ACTN_RQ = 0x45
IDLE, FWD = 0, 1
EPS = 1e-6                       # float tolerance on the limits above (limits are inclusive)
VALID = frozenset((0, 1, 2, 4, 8, 16, 32))   # VAL_ 69 SpdCtrlLvr_Stat (tesla_ap1_can.dbc:739)


def entry_for(cp) -> PlatformEntry | None:
  if cp is None or getattr(cp, 'dashcamOnly', True) or getattr(cp, 'passive', True):
    return None
  fp = str(getattr(cp, 'carFingerprint', ''))
  for e in ALLOW_LIST:
    if fp == e.fingerprint:
      return e
  return None


def flag_on(path: Path = FLAG) -> bool:
  try:
    return path.is_file() and path.read_text().strip() == '1'
  except OSError:
    return False


class Detector:
  """Pure. update(t, spd, cs_en, sds_en, ok) returns True once, at the 3rd counted tap's release."""

  def __init__(self, cruise_state_gate: bool = True):
    self.cs_gate = cruise_state_gate
    self.prev_t = None
    self.prev_spd = None
    self.prev_cs = True            # assume engaged until seen otherwise
    self.prev_sds = True
    self.disarmed = True           # need IDLE first (stalk held at onroad start)
    self.t_dis = None              # most recent falling edge of cs OR sds
    self.t_tx = None               # most recent own 0x45 TX
    self.locked = False            # V1 lockout after firing
    self.idle_since = None
    self._reset()

  def _reset(self):
    self.taps = []
    self.press_t = None
    self.counting = False
    self.last_rel = None

  def _abort(self, disarm=False):
    self._reset()
    self.locked = False
    if disarm:
      self.disarmed = True

  def counting_train(self) -> bool:
    """A COUNTING state: a press being timed, or counted taps. The post-fire lockout is not a counting state."""
    return self.counting or bool(self.taps)

  def note_own_tx(self, t):
    """Our own STW_ACTN_RQ went out (sendcan, any bus). A FWD onset within TX_DROP_S after it is never counted, and a
    counting train (press being timed or counted taps) is reset to IDLE. The post-fire lockout is KEPT, so there is
    still no re-fire until IDLE > LOCKOUT_IDLE_S. No disarm: the next real press after the window starts a new train."""
    self.t_tx = t
    if self.counting_train():
      self._reset()

  def update(self, t, spd, cs_en, sds_en, ok):
    fire = False
    cs_en = bool(cs_en) if self.cs_gate else False
    sds_en = bool(sds_en)
    if (self.prev_cs and not cs_en) or (self.prev_sds and not sds_en):
      self.t_dis = t
    engage_edge = (cs_en and not self.prev_cs) or (sds_en and not self.prev_sds)
    stale = self.prev_t is not None and t - self.prev_t > STALE_S + EPS
    if stale or not ok or spd not in VALID or engage_edge or spd not in (IDLE, FWD):
      self._abort(disarm=(not ok or spd not in VALID or stale))
      self.idle_since = None
    elif spd == IDLE:
      if self.prev_spd != IDLE or self.idle_since is None:
        self.idle_since = t
      self.disarmed = False
      if self.prev_spd == FWD and self.counting:                     # release
        d = t - self.press_t
        if TAP_MIN_S - EPS <= d <= TAP_MAX_S + EPS:
          self.taps.append((self.press_t, t))
          self.last_rel = t
          if self.taps[-1][1] - self.taps[0][0] > SPAN_MAX_S + EPS:
            self._abort()
          elif len(self.taps) == N_TAPS:
            fire = True                                               # fire at the 3rd release (v4)
            self._reset()
            self.locked = True
        else:
          self._abort()
        self.counting = False
      if self.taps and self.last_rel is not None and t - self.last_rel > GAP_MAX_S + EPS:
        self._reset()                                                 # 1 or 2 taps, then nothing: train over
      if self.locked and t - self.idle_since > LOCKOUT_IDLE_S + EPS:
        self.locked = False
    elif spd == FWD and self.prev_spd == IDLE and not self.disarmed:   # rising edge
      if self.locked and self.idle_since is not None and t - self.idle_since > LOCKOUT_IDLE_S + EPS:
        self.locked = False                                           # IDLE lasted > 1.00 s: train over
      self.idle_since = None
      onset_disengaged = not (cs_en or self.prev_cs or sds_en or self.prev_sds)
      guarded = self.t_dis is not None and t - self.t_dis < DISENGAGE_GUARD_S - EPS
      own_tx = self.t_tx is not None and -EPS <= t - self.t_tx <= TX_DROP_S + EPS
      gap_bad = self.last_rel is not None and self.taps and t - self.last_rel > GAP_MAX_S + EPS
      if self.locked:
        pass                                                          # extra taps neither cancel nor re-fire
      elif (not onset_disengaged and not COUNT_DISENGAGE_TAP) or guarded or own_tx:
        self._reset()                                                 # cancel push / bounce / our own TX: never counted
      else:
        if gap_bad:
          self._reset()
        self.press_t, self.counting = t, True
    elif spd == FWD:
      self.idle_since = None
      if self.press_t is not None and self.counting and t - self.press_t > TAP_MAX_S + EPS:
        self._abort(disarm=True)                                      # > 300 ms aborts and disarms until IDLE
    self.prev_t, self.prev_spd, self.prev_cs, self.prev_sds = t, spd, cs_en, sds_en
    return fire


def has_own_0x45(sendcan_msg) -> bool:
  try:
    return any(int(c.address) == STW_ACTN_RQ for c in sendcan_msg.sendcan)
  except Exception:
    return False


_state = None


def tick(pm, ui_state):
  """BETA hook, called once per UI frame from MainLayout._render. Any error turns the module off for the drive."""
  global _state
  try:
    if not ui_state.started:
      _state = None
      return
    if _state is None:
      entry = entry_for(ui_state.sm['carParams'])
      if entry is None or not flag_on():
        _state = False
        return
      import openpilot.cereal.messaging as messaging
      _state = (messaging, [messaging.sub_sock(s, conflate=False) for s in ('carState', 'selfdriveState', 'sendcan')],
                Detector(entry.cruise_state_gate), [True])
    if not _state:
      return
    messaging, socks, det, sds_en = _state
    msgs = []
    for s in socks:
      msgs += messaging.drain_sock(s)
    for m in sorted(msgs, key=lambda m: m.logMonoTime):
      t = m.logMonoTime * 1e-9
      w = m.which()
      if w == 'sendcan':
        if has_own_0x45(m):
          det.note_own_tx(t)
      elif w == 'selfdriveState':
        sds_en[0] = bool(m.selfdriveState.enabled)
      else:
        cs = m.carState
        if det.update(t, int(cs.bogpilot.spdCtrlLvr), bool(cs.cruiseState.enabled), sds_en[0], bool(m.valid and cs.canValid)):
          pm.send('userBookmark', messaging.new_message('userBookmark', valid=True))   # userBookmark only
  except Exception:
    _state = False
