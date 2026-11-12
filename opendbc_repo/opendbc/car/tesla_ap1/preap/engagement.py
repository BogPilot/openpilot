"""Pre-AP stalk engagement: single-pull and AOL double-pull modes.

The engage gesture on a Pre-AP Model S is a pull of the cruise stalk toward the driver
(STW_ACTN_RQ.SpdCtrlLvr_Stat == 2). This module turns pull edges into an engagement
decision. It does no CAN and reads no params; the car state feeds it and applies the result.

single-pull mode (also the mode whenever Always On Lateral is unavailable): one pull engages lateral AND longitudinal. Brake drops
longitudinal and keeps lateral (`lat_only`, the silent long-override event); a later pull brings longitudinal back, but not while the
brake is still held (the pedal stays blocked and the pull changes nothing).: selfdrived no longer disengages
on that brake press (it reads preapLatOnly) and the panda keeps steering through it (tesla_preap.h steer-through-brake latch), so this state
is real now; before, stock selfdrived disengaged everything on the brake press and `lat_only` never survived.

double-pull mode (`double_pull` True = the saved choice AND Always On Lateral available; same ride as 0.9.7): the first pull is only an
AOL lateral intent (`aol_lat`, 0.9.7 pedalCruiseLatOnly): cruiseState.enabled stays False, no enable request, carControl.enabled and
longActive stay False, so the pedal is never commanded; steering comes from the AOL core (latActive without enabled). A second pull within
WINDOW_MS of the previous pull engages openpilot with lateral + longitudinal (enable request). A pull while engaged is a re-pull: it
demotes to the AOL lateral intent (openpilot disengages, lateral stays on AOL) and opens a new window, so a second pull inside that window
re-engages. A brake press while engaged demotes the same way. A pull on a lateral intent outside the window just opens a window.

Both modes: a cancel (stalk away) resets everything. When the stack actually disengages (CC.enabled falls, or it never rises within
ENABLE_TIMEOUT_MS of an enable request) the FSM resets with it. If AOL becomes unavailable (`double_pull` False) the lateral intent is
dropped on the next step; it never turns into an engagement.

The result is consumed as buttonEnable (one tick, the engage request), cruiseState.enabled (`engaged`), carState.bogpilot.preapAolLat
(`aol_lat`, for the AOL core) and carState.bogpilot.preapLatOnly (`lat_only`, single-pull brake demotion, which the card turns into the silent
longitudinal-override event; LongEngageGate in phase3_speed_control reads that signal pair for SLC hand-over).
"""
from __future__ import annotations

from dataclasses import dataclass

# Natural double pulls land at 250-400 ms. The window is a hard cap, not a setting.
WINDOW_MS = 400
# openpilot must raise CC.enabled within this long of an enable request, or the FSM resets.
ENABLE_TIMEOUT_MS = 1500


@dataclass(frozen=True)
class Decision:
  engaged: bool = False          # lateral (and maybe longitudinal) is wanted
  long_wanted: bool = False      # longitudinal is wanted (only meaningful while engaged)
  enable_request: bool = False   # one tick: ask openpilot to engage (buttonEnable)
  lat_only: bool = False         # engaged but longitudinal not wanted (single pull, after a brake)
  aol_lat: bool = False          # double pull: lateral intent for the AOL core, openpilot NOT engaged


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
  def __init__(self):
    self.reset()

  def reset(self):
    self.engaged = False
    self.long_wanted = False
    self.lat_latched = False
    self.last_pull_ms: int | None = None
    self._enable_requested_ms: int | None = None
    self._op_enabled_seen = False
    self._prev_brake = False

  def _window_open(self, now_ms: int) -> bool:
    return self.last_pull_ms is not None and (now_ms - self.last_pull_ms) <= WINDOW_MS

  def update(self, now_ms: int, *, pull_edge: bool, cancel_edge: bool, brake_pressed: bool,
             op_enabled: bool, double_pull: bool) -> Decision:
    """One car-state step. pull_edge / cancel_edge are rising edges of the stalk lever."""
    enable_request = False

    if cancel_edge:
      self.reset()
      self._prev_brake = bool(brake_pressed)
      return Decision()

    if self.lat_latched and not double_pull:
      self.lat_latched = False             # AOL went away: drop the lateral intent, never promote it

    # openpilot's own state is the truth about "engaged": follow it down.
    if self.engaged:
      if op_enabled:
        self._op_enabled_seen = True
      elif self._op_enabled_seen:
        self.reset()                       # it was enabled and is not any more
      elif self._enable_requested_ms is not None and (now_ms - self._enable_requested_ms) > ENABLE_TIMEOUT_MS:
        self.reset()                       # the enable request never took

    # Brake drops longitudinal. Single pull keeps lateral in openpilot; double pull hands lateral to AOL.
    if self.engaged and brake_pressed and not self._prev_brake and self.long_wanted:
      if double_pull:
        self._demote_to_aol_lat()
      else:
        self.long_wanted = False
    self._prev_brake = bool(brake_pressed)

    if pull_edge:
      if double_pull:
        if self.engaged:
          self._demote_to_aol_lat()        # re-pull while engaged: demote, open a window
        elif self.lat_latched and self._window_open(now_ms):
          self.engaged = True              # second pull inside the window: openpilot engages, lateral + longitudinal
          self.long_wanted = True
          self.lat_latched = False
          enable_request = True
          self._enable_requested_ms = now_ms
          self._op_enabled_seen = False
        else:
          self.lat_latched = True          # first pull (or a late one): lateral intent for AOL, this pull opens a window
        self.last_pull_ms = now_ms
      elif not self.engaged:
        self.engaged = True
        self.long_wanted = True
        enable_request = True
        self._enable_requested_ms = now_ms
        self._op_enabled_seen = False
        self.last_pull_ms = now_ms
      elif not brake_pressed:
        # single-pull mode: a pull on a lateral-only latch (after a brake) brings longitudinal back. With the brake still held it changes
        # nothing: the panda blocks the pedal while the brake is pressed, so longitudinal is not offered back.
        self.long_wanted = True
        self.last_pull_ms = now_ms

    return Decision(engaged=self.engaged, long_wanted=self.engaged and self.long_wanted,
                    enable_request=enable_request, lat_only=self.engaged and not self.long_wanted,
                    aol_lat=self.lat_latched and not self.engaged)

  def _demote_to_aol_lat(self):
    self.engaged = False
    self.long_wanted = False
    self.lat_latched = True
    self._enable_requested_ms = None
    self._op_enabled_seen = False
