"""AP1 low-conflict speed-limit raise (no fake stalk, no panda 0x45 loosen).

When BogPilot's Speed Limit Controller confirms a higher posted limit, lift
openpilot's cruise target to limit+offset so longitudinal accelerates into the
faster zone. DI_cruiseSet still seeds the pcmCruise set; stalk UP/DN injection
is intentionally not used.

Engage / tip policy (simplified):
  - Stalk UP/DN engage → sticky vEgo. The sticky set holds through posted-limit
    changes in BOTH directions (no auto-raise into a faster zone, no cap by a
    lower limit) until RWD pull or disengage — same as a tipped set.
  - Pull-toward (RWD / resumeCruise) engage → SLC+offset raise immediately
  - Classify engage from stalk pressed within the last ~0.8 s of the CRUISE
    engage edge (cruiseState.enabled rising, BogPilot 0.9.7
    frogpilot_vcruise.py:119 @04d560f3e), remember it (updated by newer presses)
    until openpilot longitudinal is active, and apply it then. A tap (or an
    engage with no stalk seen) latches vEgo as of the tap / engage edge; only a
    pull hands the set to SLC. There is no SLC fallback for an unclassified
    rolling engage. Caller must
    feed continuous stalk *levels* (carstate.button_states via bogpilotCarState
    accelPressed / decelPressed / resumePressed), not 10 ms buttonEvents —
    bogpilot_vcruise samples at 20 Hz and misses short holds.
  - While engaged, stalk UP/DN only adjust the software set the same way both
    directions (+1 / next-5 up, −1 / next-lower-5 down). Tip base is the current
    software set (sticky latch / tip_ms / raised set). Sticky still wins first
    (never max(plan, SLC) while sticky — drive26/27). After RWD raise, vcruise
    floors set_hint with slc_desired (no tip seed — SLC tracking, drive 2a) so
    tips never base off DI_cruiseSet (~vEgo/2 under overlay — drive28).
    No DECEL raise holdoff. Engaged RWD/pull clears tip+sticky and re-allows raise.
  - Tipped / post-raise set is authority until stalk pull (re-latch SLC+offset)
    or disengage; SLC raise must not yank the set back up after a down tip.
    Never follow stale DI_cruiseSet under OP overlay. AP1 buttonEvents are binary
    (UP_1ST/UP_2ND both map to accelCruise), so full vs short tip comes from raw
    SpdCtrlLvr_Stat (bogpilotCarState.spdCtrlLvr): UP_2ND/DN_2ND (4/8) on the
    rising edge = full tip (next/prev 5); UP_1ST/DN_1ST (16/32) = ±1. A hold past
    TIP_HOLD_S upgrades a ±1 press to next/prev 5 once, as a fallback only.
  - Tips adjust the software set only — they must not send cancel / FWD stalk TX
    (stock DI_cruiseState can soft-lock to STANDBY after cancel + stalk spam).

IC set digit (DAS_accSpeedLimit on 0x389) tracks the OP set via the cluster
pack path. DBC factor is 0.4. cruise_set_mph rejects V_CRUISE_UNSET (255 kph)
so standstill DI set=0 cannot pack ~158 mph / cluster digital set ~90
(route 23 segments 5/8).

Not a product. No warranty. The driver remains responsible. Comply with local law.
"""

import math

from opendbc.car.common.conversions import Conversions as CV

# Matches selfdrive/controls/lib/drive_helpers.V_CRUISE_UNSET (kph).
V_CRUISE_UNSET_KPH = 255.0
V_CRUISE_UNSET_MS = V_CRUISE_UNSET_KPH * CV.KPH_TO_MS
# OP cruise ceiling (drive_helpers.V_CRUISE_MAX); overlay above this is nonsense.
V_CRUISE_MAX_MPH = 145.0 * CV.KPH_TO_MPH


def is_ap1(fingerprint: str | None) -> bool:
  from opendbc.car.tesla_ap1.values import CAR
  return fingerprint == CAR.TESLA_AP1_MODELS


def lift_cruise_ms(v_cruise_ms: float, slc_desired_ms: float, slc_target_ms: float,
                   cruising_speed_ms: float) -> float:
  """Raise v_cruise toward a confirmed higher SLC target.

  Intended to run AFTER the min() merge so a pre-lift DI/csc seed cannot undo
  the raise. Caller re-caps with CSC only when CSC is actively controlling.
  No-op when the SLC target is missing or below cruising speed.
  """
  if slc_target_ms < cruising_speed_ms or slc_desired_ms < cruising_speed_ms:
    return v_cruise_ms
  if slc_desired_ms > v_cruise_ms:
    return slc_desired_ms
  return v_cruise_ms


def apply_slc_raise_after_min(v_cruise_ms: float, slc_desired_ms: float, slc_target_ms: float,
                              cruising_speed_ms: float, csc_controlling_speed: bool,
                              csc_target_ms: float) -> float:
  """AP1 post-min raise: lift, then re-min with CSC only if CSC is active.

  Used by bogpilot_vcruise after min(targets) so DI_cruiseSet sitting in
  csc_target (CSC inactive) cannot collapse a confirmed SLC raise.
  """
  v = lift_cruise_ms(v_cruise_ms, slc_desired_ms, slc_target_ms, cruising_speed_ms)
  if csc_controlling_speed:
    v = min(v, csc_target_ms)
  return v


def merge_vcruise_with_slc(v_cruise_ms: float, csc_target_ms: float, slc_desired_ms: float,
                           slc_target_ms: float, cruising_speed_ms: float,
                           csc_controlling_speed: bool = False,
                           raise_holdoff: bool = False) -> float:
  """Full AP1 merge order: min(targets) then apply_slc_raise_after_min.

  Mirrors bogpilot_vcruise.py so unit tests cover the DI≥CRUISING_SPEED
  regression (raise must stick at 30 when DI=11.5, limit 25, offset +5).
  When raise_holdoff is True (tip/sticky authority — skip SLC lift), return min only.
  """
  targets = [csc_target_ms, v_cruise_ms, slc_desired_ms]
  v = min(t if t >= cruising_speed_ms else v_cruise_ms for t in targets)
  if raise_holdoff:
    return v
  return apply_slc_raise_after_min(
    v, slc_desired_ms, slc_target_ms, cruising_speed_ms,
    csc_controlling_speed, csc_target_ms)


def _speed_units(speed_ms: float, round_whole: bool, is_metric: bool) -> tuple[float, float]:
  """Set speed in tip units and the factor back to m/s.

  round_whole=False (legacy): mph, rounded to 4 decimals only (float noise).
  round_whole=True (AP1TipRoundSet): the display unit (km/h when metric, else
  mph), rounded half-up to a whole number first. The cluster and the comma UI
  show whole numbers only, so a 14.8 mph tip-engage latch reads as 15 and a +5
  tip goes to 20 instead of 15.
  """
  if not round_whole:
    return round(float(speed_ms) * CV.MS_TO_MPH, 4), CV.MPH_TO_MS
  to_unit = CV.MS_TO_KPH if is_metric else CV.MS_TO_MPH
  to_ms = CV.KPH_TO_MS if is_metric else CV.MPH_TO_MS
  value = round(float(speed_ms) * to_unit, 4)
  return float(math.floor(value + 0.5)), to_ms


def next_5_ms(speed_ms: float, round_whole: bool = False, is_metric: bool = False) -> float:
  """Next multiple of 5 above speed_ms (30→35, 36→40); exact multiples go +5.

  Legacy (round_whole=False): mph, fractional base (14.8→15).
  round_whole=True: base rounded to a whole display unit first (14.8→15→20,
  49.6→50→55); steps in km/h when is_metric.
  """
  value, to_ms = _speed_units(speed_ms, round_whole, is_metric)
  return float((int(value // 5.0) + 1) * 5.0) * to_ms


def prev_5_ms(speed_ms: float, round_whole: bool = False, is_metric: bool = False) -> float:
  """Next-lower multiple of 5 (31→30, 30→25, 36→35); exact multiples go −5.

  round_whole=True: base rounded to a whole display unit first (15.2→15→10,
  49.6→50→45); steps in km/h when is_metric.
  """
  value, to_ms = _speed_units(speed_ms, round_whole, is_metric)
  if value <= 0.0:
    return 0.0
  if value % 5.0 == 0.0:
    return max(value - 5.0, 0.0) * to_ms
  return float(int(value // 5.0) * 5.0) * to_ms


def step_1_ms(speed_ms: float, direction: int, round_whole: bool = False, is_metric: bool = False) -> float:
  """First-detent tip: ±1 unit from the base.

  Legacy: base ± 1 mph (fractional base kept: 14.8→15.8).
  round_whole=True: whole display unit first, then ±1 (14.8→15→16; km/h when metric).
  Caller clamps to TIP_MIN_MS / V_CRUISE_MAX_MS.
  """
  if not round_whole:
    return float(speed_ms) + float(direction) * 1.0 * CV.MPH_TO_MS
  value, to_ms = _speed_units(speed_ms, round_whole, is_metric)
  return (value + float(direction)) * to_ms


class Ap1RaiseHoldoff:
  """AP1 raise gate: engage stalk type + tip set authority (no DECEL holdoff).

  Desired:
    UP/DN engage → sticky vEgo (no SLC raise; holds through limit changes in
      both directions until RWD pull or disengage)
    RWD (pull-toward) engage → allow raise to SLC+offset immediately
    Engage classified from stalk pressed within RECENT_S of the cruise engage
      edge (cruise_on rising; == enabled when the caller passes no cruise_on),
      remembered as engage_kind until the longitudinal (enabled) edge and
      updated by newer presses while cruise is on. Taps and unclassified rolling
      engages latch vEgo from the tap / cruise edge (never SLC); an unclassified
      standstill engage keeps the standstill rule (car-layer set / NO_ENTRY).
      A longitudinal re-rise in the same cruise session (gas override longer
      than LongEngageGate.DROP_S) restores the driver's latched set; only a
      pull returns to SLC. Cleared when cruise turns off (cancel, brake, any
      disengage) or by forget_engage().
    Caller must pass continuous stalk levels (button_states), not edge-only events
      (UP/DN/RWD via accelPressed/decelPressed/resumePressed)
    Engaged UP/DN → tip (±1 SpdCtrl 16/32 / next-5 SpdCtrl 4/8 on the rising
      edge); a hold ≥ TIP_HOLD_S upgrades a ±1 press once as a fallback
    Tip current_set_ms from sticky latch / tip_ms / raised set — sticky first
      (never SLC floor while sticky); after pull raise, set_hint floors with
      slc_desired (no tip seed; never DI half-seed)
    Tipped set is authority until RWD pull or disengage (zone changes do not
      clear tip); never follow DI_cruiseSet; SLC raise must not reclaim after tip.
    RWD pull clears tip and re-allows SLC raise (SLC tracking mode — no tip seed)
    tip_ms fed as slc.overridden_speed so Max Set Speed gas returns to the tip
  """

  RECENT_S = 0.8  # Tesla clears buttonEvents 80–240 ms before enabled rises
  TIP_STEP_MS = 1.0 * CV.MPH_TO_MS
  # Lowest software set a down tip can reach when the base is already at or
  # above this. A DN tip must never raise the set, so a crawl latch below 1 mph
  # stays at the latch (still > 0). tip_ms == 0 means "no tip", so a tip to 0
  # used to drop into SLC tracking (raise to posted+offset). Not tied to the
  # SLC posted-limit guard (15 mph floor) — tips may go below 15 mph.
  TIP_MIN_MS = 1.0 * CV.MPH_TO_MS
  TIP_HOLD_S = 0.45  # fallback only: hold upgrades ±1 → next/prev 5 once
  # Float slack: nine 50 ms ticks sum to 0.44999999999999996, which must count as 0.45 s.
  TIP_HOLD_EPS_S = 1e-6
  V_CRUISE_MAX_MS = 145.0 * CV.KPH_TO_MS
  DT_DEFAULT = 0.05  # model tick; avoid importing realtime here

  def __init__(self, round_whole: bool = False, is_metric: bool = False):
    # AP1TipRoundSet (toggle default on for this test branch; the class default
    # stays off and bogpilot_vcruise sets it): round the tip base to a whole display unit
    # before ±1 / next-5 / prev-5. Caller may update both attributes.
    self.round_whole = bool(round_whole)
    self.is_metric = bool(is_metric)
    self.sticky_vego = False
    self.latched_vego_ms = 0.0
    # AP1 openpilot long only (Ap1SpeedControl sets it): a stalk tap from 0 sets this instead of latching 0
    # (0.9.7 latched 0 here, bogpilot_vcruise.py @568fea947). 0 = off, the legacy behavior.
    self.tap_from_zero_ms = 0.0
    self.tip_ms = 0.0
    self.tip_dir = 0  # +1 tip-up, -1 tip-down, 0 idle
    self._tip_base_ms = 0.0
    self._tip_hold_s = 0.0
    self._tip_press_active = False
    self._tip_upgraded = False
    self._prev_enabled = False
    self._prev_up = False
    self._prev_dn = False
    self._t = 0.0
    self._last_up_t = -1e9
    self._last_dn_t = -1e9
    self._last_rwd_t = -1e9
    # Engage stalk action for the current cruise session: "tap", "pull", "none" (no stalk seen at the cruise edge)
    # or None (cruise off). Set on the cruise edge, updated by newer presses, applied on the longitudinal edge.
    self.engage_kind = None
    self.engage_vego_ms = 0.0     # vEgo as of the tap / cruise-engage edge that set engage_kind
    self._tap_vego_ms = 0.0       # vEgo on the latest UP/DN press edge
    self._session_set_ms = 0.0    # driver latch (sticky / tip) last seen while long was engaged this cruise session
    self._prev_cruise = False
    self._prev_rwd = False

  @property
  def driver_set_ms(self) -> float:
    """The set the driver chose this cruise session, in m/s; 0 when there is none (pull engage, SLC tracking).

    A sticky tap / vEgo latch or an engaged tip; while longitudinal is briefly not ours (gas override) the last one
    seen while it was ours. Used as the Max Set Speed source under AP1 openpilot long.
    """
    if self.sticky_vego and float(self.latched_vego_ms) > 0.0:
      return float(self.latched_vego_ms)
    if float(self.tip_ms) > 0.0:
      return float(self.tip_ms)
    return max(float(self._session_set_ms), 0.0)

  def forget_engage(self):
    """Drop the remembered engage action (cruise off, cancel, brake, any disengage)."""
    self.engage_kind = None
    self.engage_vego_ms = 0.0
    self._session_set_ms = 0.0

  def _clear_tip(self):
    self.tip_ms = 0.0
    self.tip_dir = 0
    self._tip_base_ms = 0.0
    self._tip_hold_s = 0.0
    self._tip_press_active = False
    self._tip_upgraded = False

  def _dn_set_ms(self, base_ms: float, candidate_ms: float) -> float:
    """Clamp a decrease: never below TIP_MIN when the base is at or above it,
    and never raise a latch that is already below TIP_MIN (still > 0)."""
    return min(float(base_ms), max(float(candidate_ms), self.TIP_MIN_MS))

  def update(self, enabled: bool, decel_pressed: bool, up_pressed: bool,
             rwd_pressed: bool, slc_target_ms: float, v_ego_ms: float,
             current_set_ms: float = 0.0, dt: float | None = None,
             tip_full: bool = False, cruise_on: bool | None = None):
    """Update state.

    enabled: openpilot longitudinal is ours (the hand-over edge).
    cruise_on: cruiseState.enabled (the engage edge the stalk action is classified on). None = same as enabled
    (single-edge callers and the 0.9.7 shape).

    tip_full: True when SpdCtrl is UP_2ND (4) or DN_2ND (8) — next-5 on rising
    edge (and mid-press upgrade). False → ±1 on edge; hold ≥ TIP_HOLD_S upgrades.

    Returns (allow_raise, sticky_vego_ms|None).
    sticky_vego_ms is the latched engage speed when UP/DN sticky mode is active.
    tip_ms (attribute) is the engaged tip latch in m/s when > 0 (authority).
    """
    enabled = bool(enabled)
    rising = enabled and not self._prev_enabled
    dt = self.DT_DEFAULT if dt is None else float(dt)
    self._t += dt

    if up_pressed:
      self._last_up_t = self._t
    if decel_pressed:
      self._last_dn_t = self._t
    if rwd_pressed:
      self._last_rwd_t = self._t

    recent_up = (self._t - self._last_up_t) <= self.RECENT_S
    recent_dn = (self._t - self._last_dn_t) <= self.RECENT_S
    recent_rwd = (self._t - self._last_rwd_t) <= self.RECENT_S
    up_edge = bool(up_pressed) and not self._prev_up
    dn_edge = bool(decel_pressed) and not self._prev_dn
    rwd_edge = bool(rwd_pressed) and not self._prev_rwd
    cruise = enabled if cruise_on is None else bool(cruise_on)
    cruise_rising = cruise and not self._prev_cruise
    if up_edge or dn_edge:
      self._tap_vego_ms = max(float(v_ego_ms), 0.0)

    tip_full = bool(tip_full)
    # Posted-limit changes never touch sticky or tip: a stalk-tip engage (sticky)
    # or engaged tip holds through higher AND lower limits until RWD pull or
    # disengage (never auto-raise into a faster zone). slc_target_ms is unused
    # here; SLC tracking (after a pull) follows limits in bogpilot_vcruise.

    # Engaged tip-up / tip-down / RES: continuous levels from caller (button_states).
    # tip_full (SpdCtrl 4/8) → next-5 / prev-5 on rising edge; else ±1.
    # Hold ≥ TIP_HOLD_S upgrades once when detent unknown. Mid-press tip_full
    # also upgrades once (DN_1ST→DN_2ND). RWD pull clears tip → SLC tracking.
    # Do not clear sticky on sustained UP after an UP-engage (only on up_edge / RWD).
    if enabled and self._prev_enabled:
      if rwd_pressed:
        self.sticky_vego = False
        self._clear_tip()
      elif up_edge:
        self.sticky_vego = False
        base = max(float(self.tip_ms), float(current_set_ms), 0.0)
        self._tip_base_ms = base
        self._tip_hold_s = 0.0
        self._tip_press_active = True
        self.tip_dir = 1
        if self.tap_from_zero_ms > 0.0 and base <= 0.0 and float(v_ego_ms) < 0.1:
          self.tip_ms = float(self.tap_from_zero_ms)  # standstill tap from 0 (AP1 openpilot long)
          self._tip_upgraded = True
        elif base <= 0.0:
          # Rolling with no existing set: latch exact vEgo (no 5 mph rounding, no tap-from-0).
          self.tip_ms = max(float(v_ego_ms), 0.0)
          self._tip_upgraded = True
        elif tip_full:
          self.tip_ms = min(next_5_ms(base, round_whole=self.round_whole, is_metric=self.is_metric), self.V_CRUISE_MAX_MS)
          self._tip_upgraded = True
        else:
          up1 = step_1_ms(base, 1, round_whole=True, is_metric=self.is_metric) if self.round_whole else base + self.TIP_STEP_MS
          self.tip_ms = min(up1, self.V_CRUISE_MAX_MS)
          self._tip_upgraded = False
      elif dn_edge:
        self.sticky_vego = False
        base = max(float(self.tip_ms), float(current_set_ms), 0.0)
        self._tip_base_ms = base
        self._tip_hold_s = 0.0
        self._tip_press_active = True
        self.tip_dir = -1
        if self.tap_from_zero_ms > 0.0 and base <= 0.0 and float(v_ego_ms) < 0.1:
          self.tip_ms = float(self.tap_from_zero_ms)  # standstill tap from 0 (AP1 openpilot long)
          self._tip_upgraded = True
        elif base <= 0.0:
          self.tip_ms = max(float(v_ego_ms), 0.0)
          self._tip_upgraded = True
        elif tip_full:
          self.tip_ms = self._dn_set_ms(base, prev_5_ms(base, round_whole=self.round_whole, is_metric=self.is_metric))
          self._tip_upgraded = True
        else:
          dn1 = step_1_ms(base, -1, round_whole=True, is_metric=self.is_metric) if self.round_whole else base - self.TIP_STEP_MS
          self.tip_ms = self._dn_set_ms(base, dn1)
          self._tip_upgraded = False
      if self._tip_press_active and not self._tip_upgraded:
        # Mid-press reach of pos2, or long hold without detent info
        if tip_full:
          if self.tip_dir > 0:
            nxt = next_5_ms(self._tip_base_ms, round_whole=self.round_whole, is_metric=self.is_metric)
            self.tip_ms = min(max(float(self.tip_ms), nxt), self.V_CRUISE_MAX_MS)
          elif self.tip_dir < 0:
            self.tip_ms = self._dn_set_ms(self._tip_base_ms, prev_5_ms(self._tip_base_ms, round_whole=self.round_whole, is_metric=self.is_metric))
          self._tip_upgraded = True
        elif self.tip_dir > 0 and up_pressed:
          self._tip_hold_s += dt
          if self._tip_hold_s >= self.TIP_HOLD_S - self.TIP_HOLD_EPS_S:
            nxt = next_5_ms(self._tip_base_ms, round_whole=self.round_whole, is_metric=self.is_metric)
            self.tip_ms = min(max(float(self.tip_ms), nxt), self.V_CRUISE_MAX_MS)
            self._tip_upgraded = True
        elif self.tip_dir < 0 and decel_pressed:
          self._tip_hold_s += dt
          if self._tip_hold_s >= self.TIP_HOLD_S - self.TIP_HOLD_EPS_S:
            self.tip_ms = self._dn_set_ms(self._tip_base_ms, prev_5_ms(self._tip_base_ms, round_whole=self.round_whole, is_metric=self.is_metric))
            self._tip_upgraded = True
      # Release ends hold timing (tip_ms latched value remains until clear)
      if self.tip_dir > 0 and not up_pressed:
        self._tip_press_active = False
        self._tip_hold_s = 0.0
      if self.tip_dir < 0 and not decel_pressed:
        self._tip_press_active = False
        self._tip_hold_s = 0.0

    # Engage stalk action: classified on the CRUISE edge (0.9.7 frogpilot_vcruise.py:119 @04d560f3e), not on the
    # longitudinal edge. With the gas held longActive can rise seconds after the stalk, past RECENT_S.
    if not cruise:
      self.forget_engage()
    elif cruise_rising:
      # Prefer the most recent stalk in the recent window (UP/DN tap vs RWD pull)
      candidates = []
      if recent_up:
        candidates.append(("up", self._last_up_t))
      if recent_dn:
        candidates.append(("dn", self._last_dn_t))
      if recent_rwd:
        candidates.append(("rwd", self._last_rwd_t))
      kind = max(candidates, key=lambda c: c[1])[0] if candidates else None
      self._session_set_ms = 0.0
      if kind == "rwd":
        self.engage_kind, self.engage_vego_ms = "pull", max(float(v_ego_ms), 0.0)
      elif kind in ("up", "dn"):
        self.engage_kind, self.engage_vego_ms = "tap", float(self._tap_vego_ms)   # vEgo at the tap
      else:
        self.engage_kind, self.engage_vego_ms = "none", max(float(v_ego_ms), 0.0)  # vEgo at the engage edge
    elif rwd_edge:
      # A newer pull while cruise is on (lat-only second pull, or a re-pull while engaged) -> SLC.
      self.engage_kind, self._session_set_ms = "pull", 0.0
    elif (up_edge or dn_edge) and not enabled:
      # A newer tap while cruise is on but long is not ours (lat-only / gas held): latch vEgo at this tap.
      self.engage_kind, self.engage_vego_ms, self._session_set_ms = "tap", max(float(v_ego_ms), 0.0), 0.0
    elif (up_edge or dn_edge) and enabled:
      self.engage_kind = "tap"   # engaged tip: leaves SLC; the tipped set is remembered below

    if rising:
      kind = self.engage_kind
      if kind == "pull":
        self.sticky_vego = False
        self._clear_tip()
      else:
        latched = self._session_set_ms if self._session_set_ms > 0.0 else max(float(self.engage_vego_ms), 0.0)
        if kind != "tap" and latched < 0.1:
          # Unclassified engage at a standstill: no vEgo-0 latch. The standstill rule is unchanged
          # (op_long_set_speed: limit+offset, a fresh tap's 15 mph, or NO_ENTRY ap1SpeedLimitUnknown).
          self.sticky_vego = False
        else:
          self.sticky_vego = True
          self.latched_vego_ms = latched
          if self.tap_from_zero_ms > 0.0 and self.latched_vego_ms < 0.1:
            # AP1 openpilot long: a tap engage at a standstill sets 15 mph, not a sticky 0 (0.9.7 latched vEgo 0).
            self.latched_vego_ms = float(self.tap_from_zero_ms)
        self._clear_tip()

    if enabled and cruise:
      # Remember the driver's latch so a long re-rise in this cruise session (gas override > DROP_S) restores it.
      if self.sticky_vego and float(self.latched_vego_ms) > 0.0:
        self._session_set_ms = float(self.latched_vego_ms)
      elif float(self.tip_ms) > 0.0:
        self._session_set_ms = float(self.tip_ms)
      else:
        self._session_set_ms = 0.0   # SLC tracking (pull): nothing to restore

    if not enabled:
      self.sticky_vego = False
      self._clear_tip()

    self._prev_enabled = enabled
    self._prev_cruise = cruise
    self._prev_rwd = bool(rwd_pressed)
    self._prev_up = bool(up_pressed)
    self._prev_dn = bool(decel_pressed)

    # Tip or sticky blocks SLC raise; RWD pull clears tip so raise may re-latch.
    allow_raise = (not self.sticky_vego) and (float(self.tip_ms) <= 0.0)
    sticky = self.latched_vego_ms if self.sticky_vego else None
    if self.tap_from_zero_ms > 0.0 and sticky is not None and sticky <= 0.0:
      sticky = None  # AP1 openpilot long: a sticky 0 is no set
    return allow_raise, sticky


class Ap1SlcLimitGuard:
  """AP1 posted-limit sanity filter for SLC (drive 2a seg 5: 45→5 mph blip ~1.4 s).

  Applied in bogpilot_vcruise to the SLC target/offset it uses and publishes
  (bogpilotPlan.slcSpeedLimit[+Offset]), so SLC tracking after a pull, pull
  engage (controlsd initialize_v_cruise) and the speed-limit sign all see it.
  Tip-engage / engaged-tip holds ignore limits anyway.

    - 0 / no limit (< 1 m/s): passed through unchanged (existing SLC behaviour).
    - Posted limit below MIN_VALID_MPH (15): not a limit — keep the previous
      accepted limit. 15 itself is valid (school zones).
    - Rises and normal drops: accepted immediately (as before).
    - Sudden drop (more than SUDDEN_DROP_MPH, or below SUDDEN_DROP_RATIO of the
      accepted limit): must persist CONFIRM_S before it is accepted.
    - Except a drop straight back to the limit that was in force before a rise
      less than RETURN_WINDOW_S ago: accepted immediately (drive 35: a bogus
      35->80 rise was otherwise held 2 s longer on the way back to 35).
  The offset is the one SLC reported for the accepted limit.
  """

  MIN_VALID_MPH = 15.0
  SUDDEN_DROP_MPH = 15.0   # 45→30 / 55→40 (−15) stay immediate; 45→25 confirms
  SUDDEN_DROP_RATIO = 0.5  # 30→15 stays immediate; 40→15 confirms
  CONFIRM_S = 2.0          # 02a blip lasted ~1.4 s
  SAME_MPH = 1.0           # candidate counts as "the same" within ±1 mph
  EPS_MPH = 0.25           # kph/mph float noise around the thresholds
  RETURN_WINDOW_S = 30.0   # drop back to the pre-rise limit within this time is immediate

  def __init__(self):
    self.target_ms = 0.0
    self.offset_ms = 0.0
    self._pending_ms = 0.0
    self._pending_s = 0.0
    self._pre_rise_ms = 0.0
    self._since_rise_s = 0.0

  def _accept(self, target_ms: float, offset_ms: float):
    if self.target_ms >= 1.0 and float(target_ms) > self.target_ms + 1e-3:
      self._pre_rise_ms = self.target_ms
      self._since_rise_s = 0.0
    self.target_ms = float(target_ms)
    self.offset_ms = float(offset_ms)
    self._pending_ms = 0.0
    self._pending_s = 0.0

  def update(self, raw_target_ms: float, raw_offset_ms: float, dt: float = 0.05):
    """Returns (target_ms, offset_ms) to use for SLC."""
    raw = float(raw_target_ms)
    raw_mph = raw * CV.MS_TO_MPH
    cur_mph = self.target_ms * CV.MS_TO_MPH
    self._since_rise_s += float(dt)
    back_to_pre_rise = (self._pre_rise_ms >= 1.0 and self._since_rise_s <= self.RETURN_WINDOW_S and
                        abs(raw - self._pre_rise_ms) * CV.MS_TO_MPH <= self.SAME_MPH)
    if raw < 1.0:
      self._accept(raw, raw_offset_ms)
    elif raw_mph < self.MIN_VALID_MPH - self.EPS_MPH:
      self._pending_ms = 0.0
      self._pending_s = 0.0
    else:
      sudden = cur_mph > 0.0 and raw_mph < cur_mph and (
        (cur_mph - raw_mph) > self.SUDDEN_DROP_MPH + self.EPS_MPH or
        raw_mph < cur_mph * self.SUDDEN_DROP_RATIO - self.EPS_MPH)
      if not sudden or back_to_pre_rise:
        self._accept(raw, raw_offset_ms)
      else:
        if self._pending_s > 0.0 and abs(raw - self._pending_ms) * CV.MS_TO_MPH <= self.SAME_MPH:
          self._pending_s += float(dt)
        else:
          self._pending_ms = raw
          self._pending_s = float(dt)
        if self._pending_s >= self.CONFIRM_S - 1e-6:
          self._accept(raw, raw_offset_ms)
    return self.target_ms, self.offset_ms


def ap1_cruise_ms(v_cruise_ms: float, sticky_vego_ms: float | None, tip_ms: float,
                  allow_raise: bool, slc_desired_ms: float | None, slc_target_ms: float,
                  cruising_speed_ms: float, csc_controlling_speed: bool,
                  csc_target_ms: float, sticky_zero_is_none: bool = False) -> float:
  """AP1 set authority after Ap1RaiseHoldoff.update (used by bogpilot_vcruise).

  Sticky (stalk-tip engage) and tipped set are the driver's set: they hold
  through posted-limit changes in BOTH directions until RWD pull / disengage.
  Only an active Curve Speed Controller may lower them temporarily.
  SLC tracking (after a pull, allow_raise) keeps the post-min value (follows
  lower limits) and lifts to SLC+offset on higher limits.
  """
  if sticky_zero_is_none and sticky_vego_ms is not None and float(sticky_vego_ms) <= 0.0:
    sticky_vego_ms = None  # AP1 openpilot long: a sticky 0 (0.9.7 standstill tap engage) is no set
  if sticky_vego_ms is not None:
    v = float(sticky_vego_ms)
    if csc_controlling_speed:
      v = min(v, csc_target_ms)
    return v
  if float(tip_ms) > 0.0:
    v = float(tip_ms)
    if csc_controlling_speed:
      v = min(v, csc_target_ms)
    return v
  if allow_raise:
    return apply_slc_raise_after_min(
      v_cruise_ms, slc_desired_ms, slc_target_ms, cruising_speed_ms,
      csc_controlling_speed, csc_target_ms)
  return v_cruise_ms


def cluster_display_kph(v_cruise_cluster_kph: float, bogpilot_v_cruise_ms: float) -> float:
  """Comma / HUD set digit follows the SLC-raised planner cruise when higher.

  Never lowers the displayed set for curve-speed slowdowns — only lifts when
  bogpilotPlan.vCruise is above the DI-seeded cluster set.

  When pcmCruise standstill zeros DI set, VCruiseHelper publishes UNSET (255).
  Prefer the bogpilot plan digit over the sentinel so comma does not show ~158.
  """
  fp_kph = float(bogpilot_v_cruise_ms) * CV.MS_TO_KPH
  cluster = float(v_cruise_cluster_kph)
  if cluster >= V_CRUISE_UNSET_KPH - 0.5:
    return fp_kph if fp_kph > 0.0 else cluster
  if fp_kph > cluster:
    return fp_kph
  return cluster


def cruise_set_mph(set_speed_ms: float | None) -> float | None:
  """Convert OP set speed (m/s) to mph for DAS_accSpeedLimit (DBC factor 0.4).

  Returns None (keep stock IC set) for missing/non-positive speeds and for the
  V_CRUISE_UNSET sentinel (255 kph ≈ 158 mph) that pcmCruise publishes when
  DI_cruiseSet is 0 at standstill — packing that onto 0x389 made the cluster digital set lock ~90
  (route 23 --5/--8). Also rejects values above V_CRUISE_MAX.
  """
  if set_speed_ms is None:
    return None
  speed = float(set_speed_ms)
  if speed <= 0.0:
    return None
  # UNSET leak: hud.setSpeed = 255 kph * KPH_TO_MS
  if speed >= V_CRUISE_UNSET_MS * 0.95:
    return None
  mph = speed * CV.MS_TO_MPH
  if mph <= 0.0 or mph > V_CRUISE_MAX_MPH + 0.5:
    return None
  return mph
