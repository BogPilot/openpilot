"""Pre-AP stalk engagement: NAP-style double pull, steering first.

The engage gesture on a Pre-AP Model S is a pull of the cruise stalk toward the driver (STW_ACTN_RQ.SpdCtrlLvr_Stat == 2 "RWD",
tesla_ap1_can.dbc BO_ 69 / VAL_ 69). This module turns pull edges and car inputs into one mode. It does no CAN and reads no params;
the car state feeds it and applies the result.

Behavior follows NotAutopilot (NAP) @ e99f4dc75, opendbc @ cc39c7fa, opendbc/car/tesla/preap/engagement.py, and the same 400 ms double
pull of BogPilot 0.9.7 na-preap @ 568fea947 (selfdrive/car/tesla/preap/engagement.py:18,77):
- first pull: openpilot engages STEERING ONLY (NAP engagement.py:154-173). The pedal is never enabled outside FULL.
- second pull strictly less than WINDOW_MS after the first (NAP engagement.py:131, `<`): FULL = steering + speed control.
- window expiry: steering only stays (NAP engagement.py:95-98).
- a single pull in FULL demotes to steering only and opens a new window (NAP engagement.py:156,162-163).
- brake in FULL (pedal): speed control off, steering stays (NAP engagement.py:100-110). Speed control comes back only with a new double
  pull, with a fresh set speed, never the old one.
- cancel (stalk away, outside the echo windows), leaving D, a door, stale data: everything off.
- hands on (level 3), EPAS refusal or EPAS fault: LOCKOUT, re-engaging needs a fresh pull (panda tesla_preap.h tesla_preap_epas_state,
  as NAP / na-preap; NAP engagement.py:40-54).
Without the Comma Pedal the stock DI cruise does speed control. We may only send STW_ACTN_RQ CANCEL (the panda rejects every other lever
value), so a pull that arms stock cruise while steering-only is cancelled, and FULL is the driver's own second pull arming stock cruise,
confirmed by DI_state.DI_cruiseState (BO_ 872). NAP's SET_ACCEL spoof (stock_cc_spoofer.py:64-77) is not ported.

The result is consumed as buttonEnable (pedal mode, one tick), cruiseState.enabled (`engaged`), carState.bogpilot.preapLatOnly
(`lat_only`, which the card turns into the silent longitudinal-override event so longActive stays False) and preapFsmMode.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

# Natural double pulls land at 250-400 ms. The window is a hard cap, not a setting; compared with a strict `<` (NAP engagement.py:131).
WINDOW_MS = 400
# openpilot must raise CC.enabled within this long of an enable request, or the FSM resets.
ENABLE_TIMEOUT_MS = 1500
# No pedal: after a counted pull, a DI cruise engagement seen within this long is treated as caused by that pull.
NOPEDAL_PULL_CC_WATCH_MS = 600
# No pedal: after the second pull the DI must report stock cruise engaged within this long, or speed control did not arm.
NOPEDAL_CC_CONFIRM_MS = 600
# Below this speed the car is at a standstill for the FULL-entry rule (same bound as the SetSpeedLimit standstill guard).
STANDSTILL_SPEED_MS = 0.1

# ---- Open choices. Each constant holds the current default; change it to switch. ----
# Standstill double pull (decided: option (b), pending the safety review with the panda unchanged): double pull at a standstill with the pedal.
# True = FULL is entered but the car is held at 0 by the driver's own pedal (pedal ENABLE=0, raw <= 500, never a drive-off) until
# the driver presses the accelerator; one update after the accelerator is released normal FULL control starts. NAP enters pedal
# control at 0 too (NAP preap/engagement.py:142,243-246 capture 0 as the set speed; carcontroller.py:123-128 holds ENABLE=1 at zero
# torque); here the hold sends ENABLE=0, which is stricter. False = option (a): refuse speed control until moving (steering only).
PREAP_FULL_AT_STANDSTILL = True
# t1401 (from-stop rule). True = a standstill double pull sets the first set speed to the driver's from-stop value
# (AP1TapFromZeroMs) on the pull itself (capture_edge + capture_from_stop on the FULL entry). The accelerator release only ends
# the hold and keeps that set, including any up/down tips made while held. False = the v3 behaviour (capture
# max(rounded vEgo, from-stop) on the accelerator release).
PREAP_STOP_SET_AT_PULL = True
# t1401. True = with the pedal, an up/down tip (release edge) while steering only enters FULL with the same entry rules as a
# second pull, latching like the AP1 tap (tesla_ap1/op_long_set_speed.py rules 2-3): rolling = the current speed in whole display
# units and never SetSpeedLimit; at a standstill = the from-stop value with the standstill hold. A first pull (steering, panda
# controls_allowed) is still required. False = a tip only changes the set speed, as in v3.
PREAP_TIP_ENGAGES_LONG = True
# t1438. True = a moving pedal double pull below the from-stop speed (AP1TapFromZeroMs) sets the from-stop speed (no standstill
# hold, the car is moving). False = it captures the rounded current speed as in v3/v5. Tips are never raised (they latch the current speed).
PREAP_MOVING_PULL_RAISES_TO_FROM_STOP = True
# Open choice (single-pull cancel timing): no pedal, when to cancel stock cruise armed by a single pull. True = as soon as it is seen after the pull
# (NAP timing, default (a)). False = only when the window expires without a second pull (option (b)).
PREAP_NOPEDAL_CANCEL_ON_PULL = True
# Open choice (hands-on takeover): no pedal, hands-on takeover. False = leave stock cruise as it is (NAP parity, default).
# True = also cancel stock cruise.
PREAP_NOPEDAL_CANCEL_ON_HANDS_ON = False
# Open choice (other cruise-on act): no pedal, stock cruise turned on by a driver act other than a counted double pull (up/down tip) while
# steering only. True = follow it as FULL (default). False = cancel it.
PREAP_NOPEDAL_FOLLOW_DRIVER_CC = True
# Open choice (single pull with cruise on): no pedal, a single pull while stock cruise is already on. True = cancel it, steering only (NAP parity,
# default). False = keep it and report FULL.
PREAP_NOPEDAL_PULL_CANCELS_ACTIVE_CC = True
# (The Pre-AP speed chimes choice is in openpilot selfdrived/cruise_chimes.py, the pedal capture speed choice in
# openpilot selfdrive/car/card.py.)


class Mode(IntEnum):
  OFF = 0
  LOCKOUT = 1        # off, and a fresh pull is required (mirror of the panda's tesla_preap_need_fresh_pull)
  LAT_PENDING = 2    # steering only, double-pull window open
  LAT_ONLY = 3       # steering only
  FULL = 4           # steering + speed control


ENGAGED_MODES = (Mode.LAT_PENDING, Mode.LAT_ONLY, Mode.FULL)


@dataclass(frozen=True)
class Decision:
  engaged: bool = False          # openpilot engaged (steering, maybe speed control)
  long_wanted: bool = False      # FULL: speed control wanted
  enable_request: bool = False   # one tick: ask openpilot to engage (buttonEnable, pedal mode)
  lat_only: bool = False         # engaged, speed control off (LAT_PENDING / LAT_ONLY)
  aol_lat: bool = False          # always False: the Always On Lateral double-pull ride is retired (kept for the carState field)
  mode: int = int(Mode.OFF)
  speed_blocked: bool = False    # left FULL because a pedal ENABLE frame was blocked (userspace guard or panda)
  cc_not_armed: bool = False     # no pedal: the second pull did not arm stock cruise
  standstill_refused: bool = False  # standstill double pull (a): a double pull at a standstill was refused
  standstill_hold: bool = False     # standstill double pull (b): FULL entered at a standstill, pedal ENABLE stays 0 until the accelerator is pressed
  capture_edge: bool = False        # one tick: capture the set speed now (FULL entered; v3 option: or the hold released)
  capture_from_stop: bool = False   # with capture_edge: the FULL began at a stop (t1401: the from-stop value, set on the entry)
  capture_tip: bool = False         # with capture_edge: FULL was entered by an up/down tip (t1401: never SetSpeedLimit)
  cancel_cc: bool = False        # one tick: send one STW_ACTN_RQ CANCEL (no pedal)
  drop_cancel: bool = False      # one tick: a pending CANCEL must not be sent (the second pull beat it)
  full_edge: bool = False        # one tick: FULL was entered on this step (the card re-captures the set speed)


def preap_steer_drop(eac_status: int, hands_on_level: int = 0, eac_error_code: int = 0) -> bool:
  """Conditions under which the panda drops controls_allowed on 0x370 (tesla_preap_epas_state in opendbc/safety/modes/tesla_preap.h).

  A permanent EPAS fault (EAC_FAULT), hands on at level 3, or an EPAS refusal (INHIBITED with error 6..9). The panda clears
  controls_allowed, the cruise latch and the steer-through-brake latch on every such frame, so re-engaging needs a new stalk pull;
  the car state resets the pull FSM on the same inputs so openpilot never shows engaged while the panda blocks steering. The panda
  also ignores a pull held through the drop (tesla_preap_need_fresh_pull); the pull FSM already needs a new pull edge.
  Same drop as NAP @ e99f4dc75 (opendbc submodule @ cc39c7fa) tesla_preap.h and BogPilot na-preap safety_tesla_preap.h @ 568fea947
  (hands on / EPAS rejecting disengage).
  Level-triggered on the last EPAS_sysStatus frame, like the panda. Status SNA (4) and the undefined 5..7 do not drop (the panda
  does not either).
  """
  return eac_status == 3 or preap_epas_refusing(hands_on_level, eac_status, eac_error_code)


def preap_epas_refusing(hands_on_level, eac_status, eac_error_code) -> bool:
  """The EPAS will not follow ANGLE right now: hands on at level 3, or INHIBITED with error 6..9.

  Mirrors tesla_preap_epas_blocking in the panda. The panda rejects ANGLE while this holds and also drops controls_allowed
  (see preap_steer_drop); the car controller pauses on the same inputs, so the panda never has an ANGLE frame to reject.
  """
  return hands_on_level >= 3 or (eac_status == 0 and 6 <= eac_error_code <= 9)


class PreAPEngagement:
  """One FSM for pedal and no-pedal cars. Fail-closed: an unknown input (None) is read as the unsafe value (not in D, door open,
  stock cruise off, standstill, pedal not allowed). Power-up and every reset start in OFF."""

  def __init__(self):
    self.mode = Mode.OFF
    self._prev_brake = False
    self._prev_di_engaged = False
    self.last_valid_pull = False
    self._clear_session()

  def _clear_session(self):
    self.window_start_ms: int | None = None
    self._enable_requested_ms: int | None = None
    self._op_enabled_seen = False
    self.speed_blocked = False
    self.cc_not_armed = False
    self.standstill_refused = False
    self.standstill_hold = False
    self._hold_gas_seen = False
    self._hold_release_edge = False
    self._tip_entry = False   # t1401: the FULL entered on this step came from an up/down tip
    self._moving_pull_entry = False   # t1438: the FULL entered on this step came from a moving pedal double pull
    self._cc_watch_until_ms: int | None = None    # no pedal: a DI engagement before this is attributed to our pull
    self._cc_confirm_until_ms: int | None = None  # no pedal: second pull waiting for the DI to report stock cruise
    self._confirm_needs_rise = False
    self._cancel_req_ms: int | None = None
    self._brake_drop_until_ms: int | None = None  # no pedal: a brake left FULL; the DI's own cruise cancel is expected until this

  def reset(self, lockout: bool = False):
    self.mode = Mode.LOCKOUT if lockout else Mode.OFF
    self._clear_session()

  @property
  def engaged(self) -> bool:
    return self.mode in ENGAGED_MODES

  @property
  def long_wanted(self) -> bool:
    return self.mode == Mode.FULL

  def _window_open(self, now_ms: int) -> bool:
    # strict `<` as NAP engagement.py:131 and 0.9.7 engagement.py:77
    return self.window_start_ms is not None and (now_ms - self.window_start_ms) < WINDOW_MS

  def _open_window(self, now_ms: int, pedal: bool):
    self.mode = Mode.LAT_PENDING
    self._brake_drop_until_ms = None
    self.window_start_ms = now_ms
    self.cc_not_armed = False
    self.standstill_refused = False
    self._cc_confirm_until_ms = None
    if not pedal:
      self._cc_watch_until_ms = now_ms + NOPEDAL_PULL_CC_WATCH_MS

  def _enter_full(self):
    self.mode = Mode.FULL
    self.window_start_ms = None
    self.speed_blocked = False
    self.cc_not_armed = False
    self.standstill_refused = False
    self._cc_watch_until_ms = None
    self._cc_confirm_until_ms = None

  def update(self, now_ms: int, *, pull_edge: bool, cancel_edge: bool, brake_pressed: bool, op_enabled: bool, pedal: bool,
             gear_d, door_open, epas_drop: bool, stale: bool, di_engaged, v_ego, long_allowed, speed_block: bool = False,
             cancel_tx_ms: int = 0, gas_pressed: bool = False, pedal_bus_ok: bool = True, tip_edge: bool = False,
             auto_speed: bool = False) -> Decision:
    """One car-state step. pull_edge / cancel_edge are rising edges of the stalk lever (cancel already filtered for our own echo).
    cancel_tx_ms: monotonic ms of the last STW_ACTN_RQ CANCEL actually put on the bus (0 = never).
    tip_edge: release edge of an up/down tip (SpdCtrlLvr_Stat 4/16 up, 8/32 down; t1401, pedal only).
    auto_speed: the Pre-AP Auto Speed toggle (the car state reads it, this module reads no params). Only with it True does a moving
    double pull below the from-stop speed get raised to it; False keeps the v5 capture of the rounded current speed."""
    enable_request = cancel_cc = drop_cancel = full_edge = False
    in_d = gear_d is True
    doors_closed = door_open is False
    di_on = di_engaged is True
    v_ego = v_ego if v_ego is not None and math.isfinite(v_ego) else None   # NaN / +-inf = unknown speed: fail closed below
    brake = bool(brake_pressed)
    brake_edge = brake and not self._prev_brake
    self._prev_brake = brake
    di_rise = di_on and not self._prev_di_engaged
    self._prev_di_engaged = di_on
    self.last_valid_pull = valid_pull = bool(pull_edge) and in_d and doors_closed   # out of D or a door open: never counts (panda g1 :102-113)
    valid_tip = bool(tip_edge) and in_d and doors_closed and not valid_pull

    # T1: hands on (level 3), EPAS refusal or EPAS fault. Wins over a pull in the same step, like the carstate fresh-pull mirror.
    if epas_drop:
      if not pedal and PREAP_NOPEDAL_CANCEL_ON_HANDS_ON and di_on and self.engaged:
        cancel_cc = True
      self.reset(lockout=True)
      return self._decision(cancel_cc=cancel_cc)

    if self.engaged:
      # T2-T5: leaving D, a door, a driver cancel or stale data end the session (panda: gear :166-169, door :172-177, cancel :114-120).
      if not in_d or not doors_closed or cancel_edge or stale:
        self.reset()
        return self._decision()
      # T6: openpilot's own state is the truth about "engaged": follow it down.
      if op_enabled:
        self._op_enabled_seen = True
      elif self._op_enabled_seen or (self._enable_requested_ms is not None and (now_ms - self._enable_requested_ms) > ENABLE_TIMEOUT_MS):
        self.reset()
        return self._decision()

    if self.mode in (Mode.OFF, Mode.LOCKOUT):
      if valid_pull:
        # T7/T8. A pull held through an EPAS drop has no new rising edge, so LOCKOUT leaves only on a fresh pull.
        self._clear_session()
        if not pedal and di_on and not PREAP_NOPEDAL_PULL_CANCELS_ACTIVE_CC:
          self._enter_full()   # single pull with cruise on, alternative: keep the stock cruise that was already on
          full_edge = True
        else:
          self._open_window(now_ms, pedal)
        enable_request = True
        self._enable_requested_ms = now_ms
        self._op_enabled_seen = False
      return self._decision(enable_request=enable_request, full_edge=full_edge)

    if self.mode == Mode.FULL:
      demoted_by_pull = False
      if self.standstill_hold:
        # standstill double pull (b): the hold ends on the accelerator RELEASE edge, and only if the car is moving then; still below 0.1 m/s = keep
        # holding and wait for the next press. The set speed is captured on that edge (capture_edge, the card).
        if gas_pressed:
          self._hold_gas_seen = True
        elif self._hold_gas_seen:
          self._hold_gas_seen = False
          if v_ego is not None and v_ego >= STANDSTILL_SPEED_MS:
            self.standstill_hold = False
            self._hold_release_edge = True
      if pedal and (speed_block or pedal_bus_ok is not True):
        self.mode = Mode.LAT_ONLY      # T15: a blocked pedal ENABLE frame (userspace guard or panda) drops speed control
        # pedal_bus_ok is the interceptor-bus latch (tesla_preap.h:128-135): never-seen or a second bus also demotes
        self.speed_blocked = True
      elif brake_edge or (pedal and brake and (v_ego is None or v_ego >= STANDSTILL_SPEED_MS)):
        # The second clause: FULL entered with the brake already held at a standstill has no brake edge. If the car moves with
        # that brake still held, speed control drops as for a press while moving (panda safety.h:354 vehicle_moving,
        # tesla_preap.h:151 speed > 0.139 m/s; 0.1 m/s here is earlier).
        # T13 (NAP engagement.py:100-110): a brake in FULL ends speed control only, steering stays (LAT_ONLY, speed-off chime).
        # Pedal: the panda also blocks the pedal on brake. No pedal: the DI cancels stock cruise on the brake (expected, bench
        # check B10); demote on the brake edge itself so openpilot never sees FULL + brake, and do not read the DI's few
        # frames of cruise still on as a driver re-arm (T17).
        self.mode = Mode.LAT_ONLY
        if not pedal:
          self._brake_drop_until_ms = now_ms + NOPEDAL_CC_CONFIRM_MS
      elif not pedal and not di_on:
        self.mode = Mode.LAT_ONLY      # T14: the DI dropped stock cruise (brake, its own cancel)
      elif valid_pull:
        self._open_window(now_ms, pedal)   # T12: single re-pull demotes, a second pull inside the window re-enters FULL
        demoted_by_pull = True
      if demoted_by_pull and not pedal and di_on:
        cancel_cc = self._nopedal_steer_only_cc(now_ms)   # NAP: the demoting pull cancels stock cruise (engagement.py:164-173)
      return self._decision(cancel_cc=cancel_cc)

    # Steering-only modes from here (LAT_PENDING / LAT_ONLY).
    if not pedal and self._cc_confirm_until_ms is not None:
      # T9/T16 no pedal: the driver's second pull must arm stock cruise. If our CANCEL is already on the bus while the DI still
      # shows the first pull's engagement, only a new off->on transition counts.
      if di_rise or (di_on and not self._confirm_needs_rise):
        self._enter_full()
        full_edge = True
      elif now_ms >= self._cc_confirm_until_ms:
        self.mode = Mode.LAT_ONLY
        self._cc_confirm_until_ms = None
        self.cc_not_armed = True
      return self._decision(full_edge=full_edge)

    if (pedal and PREAP_TIP_ENGAGES_LONG and valid_tip and self._op_enabled_seen
        and (self.mode == Mode.LAT_ONLY or not self._window_open(now_ms))):
      # t1401: an up/down tip while steering only (openpilot already enabled by a pull, so the panda already allows controls)
      # enters FULL, latching like the AP1 tap. Same pedal entry rules as the second pull below. Inside the open double-pull
      # window a tip is still neither a second pull nor an entry (test_preap_tap_never_slc).
      full_edge = self._pedal_full_entry(brake, brake_edge, v_ego, long_allowed, pedal_bus_ok)
      self._tip_entry = full_edge
      return self._decision(full_edge=full_edge)

    if valid_pull and self.mode == Mode.LAT_PENDING and self._window_open(now_ms):
      if pedal:
        at_standstill = v_ego is not None and v_ego < STANDSTILL_SPEED_MS
        # Brake held at the second pull, decision: follow NAP. NAP has no brake term on the second pull and drops speed control
        # only on a brake RISING edge (NAP preap/engagement.py:101-103,131-142 @ e99f4dc75, always on, no toggle), so a brake
        # held at a stop enters pedal control. Divergence, stricter than NAP: NAP hides the brake from openpilot
        # (preap/carstate.py:134-135 brakePressed = False) and from the panda (tesla_preap.h:399-403) and holds with ENABLE=1
        # at zero torque (preap/carcontroller.py:123-128), so ENABLE=1 goes out under the held brake. Here brakePressed stays
        # visible, the hold sends ENABLE=0 (raw <= 500) until the accelerator (standstill double pull (b), the pedal guard also refuses ENABLE while
        # braking), and the panda still refuses ENABLE=1 under a brake (tesla_preap.h:254, unchanged). Releasing the brake does
        # not end the hold; only the accelerator does.
        # Refused (steering only): the brake held while moving (the panda drops controls on a brake while moving, safety.h:354)
        # or pressed on this very step (a press, not a held brake: safety.h:354 drops controls on that edge); pedal not ready,
        # or the interceptor bus not latched / mismatched (tesla_preap.h:128-135).
        if (brake and (brake_edge or not at_standstill)) or long_allowed is not True or pedal_bus_ok is not True:
          self.mode = Mode.LAT_ONLY
          self.window_start_ms = None
        elif v_ego is None or v_ego < STANDSTILL_SPEED_MS:
          if PREAP_FULL_AT_STANDSTILL and v_ego is not None:   # unknown speed is never a hold: refused (fail closed)
            self._enter_full()           # standstill double pull (b): FULL, held at 0 by the pedal guard until the accelerator is pressed
            self.standstill_hold = True
            full_edge = True
          else:
            self.mode = Mode.LAT_ONLY    # standstill double pull (a): no speed control from a standstill
            self.window_start_ms = None
            self.standstill_refused = True
        else:
          self._enter_full()
          full_edge = True
          self._moving_pull_entry = bool(auto_speed)   # t1438: a moving double pull is raised to the from-stop speed if below it, Auto Speed ON only
      else:
        drop_cancel = True
        self._confirm_needs_rise = di_on and self._cancel_req_ms is not None and cancel_tx_ms >= self._cancel_req_ms
        self._cc_watch_until_ms = None
        self._cc_confirm_until_ms = now_ms + NOPEDAL_CC_CONFIRM_MS
        if di_on and not self._confirm_needs_rise:
          self._enter_full()
          full_edge = True
      return self._decision(full_edge=full_edge, drop_cancel=drop_cancel)

    if valid_pull:
      self._open_window(now_ms, pedal)   # T11 / a late pull: new window
    elif self.mode == Mode.LAT_PENDING and not self._window_open(now_ms):
      self.mode = Mode.LAT_ONLY          # T10: window expired, steering only stays
      self.window_start_ms = None

    if not pedal and self._brake_drop_until_ms is not None and (not di_on or now_ms >= self._brake_drop_until_ms):
      self._brake_drop_until_ms = None   # the DI dropped stock cruise after the brake (or did not: handled below as usual)
    if not pedal and di_on and self.engaged and self._brake_drop_until_ms is None:
      # Only inside a session. Off, stock cruise that came on without a counted pull neither engages openpilot nor gets cancelled
      # (NAP sets cruiseState.enabled only from a pull, NAP opendbc preap/carstate.py:139 @ cc39c7fa).
      cancel_cc = self._nopedal_steer_only_cc(now_ms)
    return self._decision(cancel_cc=cancel_cc, full_edge=self.mode == Mode.FULL)

  def _pedal_full_entry(self, brake: bool, brake_edge: bool, v_ego, long_allowed, pedal_bus_ok) -> bool:
    """t1401: the pedal second-pull entry rules (update(), LAT_PENDING branch) for an up/down tip. True = FULL entered."""
    at_standstill = v_ego is not None and v_ego < STANDSTILL_SPEED_MS
    if (brake and (brake_edge or not at_standstill)) or long_allowed is not True or pedal_bus_ok is not True:
      self.mode = Mode.LAT_ONLY
      self.window_start_ms = None
      return False
    if v_ego is None or v_ego < STANDSTILL_SPEED_MS:
      if PREAP_FULL_AT_STANDSTILL and v_ego is not None:   # unknown speed is never a hold: refused (fail closed)
        self._enter_full()
        self.standstill_hold = True
        return True
      self.mode = Mode.LAT_ONLY
      self.window_start_ms = None
      self.standstill_refused = True
      return False
    self._enter_full()
    return True

  def _nopedal_steer_only_cc(self, now_ms: int) -> bool:
    """No pedal, steering only, stock cruise is on. Returns True to send one CANCEL (or moves to FULL, the other cruise-on act choice)."""
    if self._cancel_req_ms is not None and (now_ms - self._cancel_req_ms) < NOPEDAL_CC_CONFIRM_MS:
      return False                       # our CANCEL is in flight
    pull_caused = self._cc_watch_until_ms is not None and now_ms < self._cc_watch_until_ms
    if pull_caused:
      if PREAP_NOPEDAL_CANCEL_ON_PULL or self.mode == Mode.LAT_ONLY:
        self._cancel_req_ms = now_ms
        return True
      return False                       # single-pull cancel timing (b): wait for the window to expire
    if PREAP_NOPEDAL_FOLLOW_DRIVER_CC:
      self._enter_full()                 # T17: stock cruise on by a driver act (or our CANCEL did not take): report it honestly
      return False
    self._cancel_req_ms = now_ms
    return True

  def _decision(self, *, enable_request=False, cancel_cc=False, drop_cancel=False, full_edge=False) -> Decision:
    engaged = self.engaged
    release = bool(self._hold_release_edge)
    self._hold_release_edge = False
    capture_tip = bool(full_edge) and self._tip_entry
    self._tip_entry = False
    moving_pull = bool(full_edge) and self._moving_pull_entry and not capture_tip and PREAP_MOVING_PULL_RAISES_TO_FROM_STOP
    self._moving_pull_entry = False
    if PREAP_STOP_SET_AT_PULL:
      # t1401: every FULL entry captures; one that starts at a stop takes the from-stop value now. The release only ends the hold.
      # t1438: a moving pedal double pull below the from-stop speed is raised to it (card: max(rounded vEgo, from-stop), no hold).
      # A tip entry never raises (it latches the rounded current speed, even below from-stop).
      capture_from_stop = bool(full_edge) and (self.standstill_hold or moving_pull)
      capture_edge = bool(full_edge)
    else:
      capture_from_stop = release
      capture_edge = (bool(full_edge) and not self.standstill_hold) or release
    return Decision(engaged=engaged, long_wanted=self.mode == Mode.FULL, enable_request=bool(enable_request),
                    lat_only=engaged and self.mode != Mode.FULL, aol_lat=False, mode=int(self.mode),
                    speed_blocked=engaged and self.speed_blocked, cc_not_armed=engaged and self.cc_not_armed,
                    standstill_refused=engaged and self.standstill_refused,
                    standstill_hold=self.mode == Mode.FULL and self.standstill_hold, cancel_cc=bool(cancel_cc),
                    drop_cancel=bool(drop_cancel), full_edge=bool(full_edge), capture_edge=capture_edge,
                    capture_from_stop=capture_from_stop, capture_tip=capture_tip)
