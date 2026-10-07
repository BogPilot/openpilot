"""AP1 low-conflict speed-limit raise (no fake stalk, no panda 0x45 loosen).

When FrogPilot's Speed Limit Controller confirms a higher posted limit, lift
openpilot's cruise target to limit+offset so longitudinal accelerates into the
faster zone. DI_cruiseSet still seeds the pcmCruise set; stalk UP/DN injection
is intentionally not used.

Engage / tip policy (simplified):
  - Stalk UP/DN engage → sticky vEgo (no immediate SLC raise)
  - Pull-toward (RWD / resumeCruise) engage → SLC+offset raise immediately
  - Classify engage from stalk pressed within the last ~0.8 s. Caller must
    feed continuous stalk *levels* (carstate.button_states via frogpilotCarState
    accelPressed / decelPressed / resumePressed), not 10 ms buttonEvents —
    frogpilot_vcruise samples at 20 Hz and misses short holds (drive26 RWD).
  - While engaged, stalk UP/DN only adjust the software set the same way both
    directions (+1 / next-5 up, −1 / next-lower-5 down). Tip base is the current
    software set (sticky latch / tip_ms / plan) — never max(plan, SLC+offset).
    No DECEL raise holdoff. Engaged RWD/pull clears tip+sticky and re-allows raise.
  - Tipped set is authority until stalk pull (re-latch SLC+offset) or disengage;
    SLC raise must not yank the set back up after a down tip. Never follow stale
    DI_cruiseSet under OP overlay. AP1 buttonEvents are binary (UP_1ST/UP_2ND
    both map to accelCruise), so full vs short is hold duration.
  - Tips adjust the software set only — they must not send cancel / FWD stalk TX
    (stock DI_cruiseState can soft-lock to STANDBY after cancel + stalk spam).

IC set digit (DAS_accSpeedLimit on 0x389) tracks the OP set via the cluster
pack path. DBC factor is 0.4. cruise_set_mph rejects V_CRUISE_UNSET (255 kph)
so standstill DI set=0 cannot pack ~158 mph / cluster digital set ~90
(route 23 segments 5/8).

Not a product. No warranty. The driver remains responsible. Comply with local law.
"""

from openpilot.common.conversions import Conversions as CV

# Matches selfdrive/controls/lib/drive_helpers.V_CRUISE_UNSET (kph).
V_CRUISE_UNSET_KPH = 255.0
V_CRUISE_UNSET_MS = V_CRUISE_UNSET_KPH * CV.KPH_TO_MS
# OP cruise ceiling (drive_helpers.V_CRUISE_MAX); overlay above this is nonsense.
V_CRUISE_MAX_MPH = 145.0 * CV.KPH_TO_MPH


def is_ap1(fingerprint: str | None) -> bool:
  from openpilot.selfdrive.car.tesla.values import CAR
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

  Used by frogpilot_vcruise after min(targets) so DI_cruiseSet sitting in
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

  Mirrors frogpilot_vcruise.py so unit tests cover the DI≥CRUISING_SPEED
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



def next_5_ms(speed_ms: float) -> float:
  """Next multiple of 5 mph above speed_ms (30→35, 36→40); exact multiples go +5."""
  mph = round(float(speed_ms) * CV.MS_TO_MPH, 4)
  return float((int(mph // 5.0) + 1) * 5.0) * CV.MPH_TO_MS


def prev_5_ms(speed_ms: float) -> float:
  """Next-lower multiple of 5 mph (31→30, 30→25, 36→35); exact multiples go −5."""
  mph = round(float(speed_ms) * CV.MS_TO_MPH, 4)
  if mph <= 0.0:
    return 0.0
  if mph % 5.0 == 0.0:
    return max(mph - 5.0, 0.0) * CV.MPH_TO_MS
  return float(int(mph // 5.0) * 5.0) * CV.MPH_TO_MS


class Ap1RaiseHoldoff:
  """AP1 raise gate: engage stalk type + tip set authority (no DECEL holdoff).

  Desired:
    UP/DN engage → sticky vEgo (no SLC raise)
    RWD (pull-toward) engage → allow raise to SLC+offset immediately
    Engage classified from stalk pressed within RECENT_S (not same-frame only)
    Caller must pass continuous stalk levels (button_states), not edge-only events
      (UP/DN/RWD via accelPressed/decelPressed/resumePressed)
    Engaged UP/DN → software set tip (±1 short / ± next-5 long); same both ways
    Tip current_set_ms from sticky latch / tip_ms / plan — never SLC+offset floor
    Tipped set is authority until RWD pull (re-latch SLC+offset) or disengage;
      never follow DI_cruiseSet; SLC raise must not reclaim after a down tip
    tip_ms fed as slc.overridden_speed so Max Set Speed gas returns to the tip
  """

  LIMIT_RISE_MS = 0.5  # ~1 mph
  RECENT_S = 0.8  # Tesla clears buttonEvents 80–240 ms before enabled rises
  TIP_STEP_MS = 1.0 * CV.MPH_TO_MS
  TIP_HOLD_S = 0.45  # full lift ≈ held past first detent; tune with drive feel
  V_CRUISE_MAX_MS = 145.0 * CV.KPH_TO_MS
  DT_DEFAULT = 0.05  # model tick; avoid importing realtime here

  def __init__(self):
    self.sticky_vego = False
    self.latched_vego_ms = 0.0
    self.tip_ms = 0.0
    self.tip_dir = 0  # +1 tip-up, -1 tip-down, 0 idle
    self._tip_base_ms = 0.0
    self._tip_hold_s = 0.0
    self._tip_press_active = False
    self._tip_upgraded = False
    self._prev_enabled = False
    self._prev_slc_target = 0.0
    self._prev_up = False
    self._prev_dn = False
    self._t = 0.0
    self._last_up_t = -1e9
    self._last_dn_t = -1e9
    self._last_rwd_t = -1e9

  def _clear_tip(self):
    self.tip_ms = 0.0
    self.tip_dir = 0
    self._tip_base_ms = 0.0
    self._tip_hold_s = 0.0
    self._tip_press_active = False
    self._tip_upgraded = False

  def update(self, enabled: bool, decel_pressed: bool, up_pressed: bool,
             rwd_pressed: bool, slc_target_ms: float, v_ego_ms: float,
             current_set_ms: float = 0.0, dt: float | None = None):
    """Update state.

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

    slc = float(slc_target_ms)
    if slc > self._prev_slc_target + self.LIMIT_RISE_MS:
      # Higher posted limit: sticky engage may raise into the new zone; tip stays
      # authority until pull / disengage (do not clear tip_ms here).
      self.sticky_vego = False
    elif slc < self._prev_slc_target - self.LIMIT_RISE_MS:
      # New lower posted limit: drop tip so Max Set Speed follows SLC+offset
      self._clear_tip()

    # Engaged tip-up / tip-down / RES: continuous levels from caller (button_states).
    # UP rising → +1; held ≥ TIP_HOLD_S → next-5 once. DN rising → −1 (no holdoff);
    # held ≥ TIP_HOLD_S → next-lower-5 once. tip_ms is the software set — never
    # follow DI_cruiseSet. RWD pull clears tip and re-allows SLC raise.
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
        self._tip_upgraded = False
        self.tip_dir = 1
        self.tip_ms = min(base + self.TIP_STEP_MS, self.V_CRUISE_MAX_MS)
      elif dn_edge:
        # Engaged DECEL: software set-down like UP (no mute / holdoff timer)
        self.sticky_vego = False
        base = max(float(self.tip_ms), float(current_set_ms), 0.0)
        self._tip_base_ms = base
        self._tip_hold_s = 0.0
        self._tip_press_active = True
        self._tip_upgraded = False
        self.tip_dir = -1
        self.tip_ms = max(base - self.TIP_STEP_MS, 0.0)
      if self._tip_press_active and not self._tip_upgraded:
        if self.tip_dir > 0 and up_pressed:
          self._tip_hold_s += dt
          if self._tip_hold_s >= self.TIP_HOLD_S:
            nxt = next_5_ms(self._tip_base_ms)
            self.tip_ms = min(max(float(self.tip_ms), nxt), self.V_CRUISE_MAX_MS)
            self._tip_upgraded = True
        elif self.tip_dir < 0 and decel_pressed:
          self._tip_hold_s += dt
          if self._tip_hold_s >= self.TIP_HOLD_S:
            self.tip_ms = max(prev_5_ms(self._tip_base_ms), 0.0)
            self._tip_upgraded = True
      # Release ends hold timing (tip_ms latched value remains until clear)
      if self.tip_dir > 0 and not up_pressed:
        self._tip_press_active = False
        self._tip_hold_s = 0.0
      if self.tip_dir < 0 and not decel_pressed:
        self._tip_press_active = False
        self._tip_hold_s = 0.0

    if rising:
      # Prefer the most recent stalk in the recent window (UP/DN sticky vs RWD raise)
      candidates = []
      if recent_up:
        candidates.append(("up", self._last_up_t))
      if recent_dn:
        candidates.append(("dn", self._last_dn_t))
      if recent_rwd:
        candidates.append(("rwd", self._last_rwd_t))
      kind = max(candidates, key=lambda c: c[1])[0] if candidates else None
      if kind in ("up", "dn"):
        self.sticky_vego = True
        self.latched_vego_ms = max(float(v_ego_ms), 0.0)
        self._clear_tip()
      elif kind == "rwd":
        self.sticky_vego = False
        self._clear_tip()
      # else: no recent stalk → default allow_raise (legacy)

    if not enabled:
      self.sticky_vego = False
      self._clear_tip()

    self._prev_enabled = enabled
    self._prev_slc_target = slc
    self._prev_up = bool(up_pressed)
    self._prev_dn = bool(decel_pressed)

    # Tip or sticky blocks SLC raise; RWD pull clears tip so raise may re-latch.
    allow_raise = (not self.sticky_vego) and (float(self.tip_ms) <= 0.0)
    sticky = self.latched_vego_ms if self.sticky_vego else None
    return allow_raise, sticky



def cluster_display_kph(v_cruise_cluster_kph: float, frogpilot_v_cruise_ms: float) -> float:
  """Comma / HUD set digit follows the SLC-raised planner cruise when higher.

  Never lowers the displayed set for curve-speed slowdowns — only lifts when
  frogpilotPlan.vCruise is above the DI-seeded cluster set.

  When pcmCruise standstill zeros DI set, VCruiseHelper publishes UNSET (255).
  Prefer the frogpilot plan digit over the sentinel so comma does not show ~158.
  """
  fp_kph = float(frogpilot_v_cruise_ms) * CV.MS_TO_KPH
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
