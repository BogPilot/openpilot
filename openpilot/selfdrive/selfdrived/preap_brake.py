"""Pre-AP brake press: drop longitudinal, keep steering.

Stock selfdrived disengages on any brake press (`pedalPressed`) and raises `controlsMismatch` when the panda has dropped controls_allowed
for more than 2 s while openpilot is enabled. On a Pre-AP Model S there is no brake control, so a brake press should cut only the pedal.
The car side (opendbc tesla_ap1/preap/engagement.py) reports that state as carState.bogpilot.preapLatOnly: openpilot engaged, longitudinal
dropped, set in the same car-state step that saw the press. The panda (tesla_preap.h) keeps steering on its own pull-armed permission and
blocks the pedal while the brake is pressed. Every other way the panda drops the steering permission (hands on, EPAS refusing, cancel, gear,
door, stale stream) clears preapLatOnly or disengages on that same step, so the exemptions here end with it. A gas press is not one of them
(the panda used to drop the latch on a gas edge while openpilot stayed engaged; now neither side reacts to gas). For every car but Pre-AP the flag is
always False and both helpers reduce to the stock rules.
"""
import math

from openpilot.selfdrive.selfdrived.preap_arm import is_preap


def brake_keeps_lateral(CS) -> bool:
  return bool(CS.bogpilot.preapLatOnly)


# carState.bogpilot.preapFsmMode value for FULL (opendbc tesla_ap1/preap/engagement.py Mode.FULL); 0 on every other car
PREAP_FSM_FULL = 4
# same bound as the car side's standstill rule (engagement.py STANDSTILL_SPEED_MS)
PREAP_STANDSTILL_SPEED_MS = 0.1


def _at_preap_standstill(v) -> bool:
  # fail closed: NaN, +inf and -inf are not a standstill
  return math.isfinite(v) and v < PREAP_STANDSTILL_SPEED_MS


class PreapHeldBrake:
  """Pre-AP speed control entered by a double pull with the brake already held at a standstill (standstill hold, pedal ENABLE=0).

  The stock rule does not disengage on a brake held at a standstill. On Pre-AP carState.standstill is the DI STANDSTILL state, which a
  Comma Pedal car never reports, so the stock rule would disengage on the held brake every frame. update() returns True only while
  all of these hold: the car is Pre-AP (CP fingerprint), the pull FSM is FULL (preapFsmMode), the brake was already pressed on the
  frame before FULL was entered and has stayed pressed on every frame since, and both vEgo and vEgoRaw are finite and < 0.1 m/s on
  every one of those frames (vEgoRaw too: the filtered vEgo lags a fast start). A release ends it for the rest of that FULL session
  (a re-press is a fresh press: stock rule), and so does any motion >= 0.1 m/s or a non-finite speed.
  The car side keeps pedal ENABLE=0 throughout: the standstill hold, and the pedal guard refuses ENABLE while the brake is pressed.
  Call update() once per frame, every frame."""

  def __init__(self, CP):
    self.enabled = is_preap(CP)
    self.held = False
    self._prev_full = False
    self._prev_brake = False

  def update(self, CS) -> bool:
    full = self.enabled and getattr(CS.bogpilot, "preapFsmMode", 0) == PREAP_FSM_FULL
    brake = bool(CS.brakePressed)
    if not full:
      self.held = False
    elif not self._prev_full:
      self.held = brake and self._prev_brake   # FULL entered with the brake already held, not pressed on the entry frame
    else:
      self.held = self.held and brake          # continuously held since entry
    if not (_at_preap_standstill(CS.vEgo) and _at_preap_standstill(CS.vEgoRaw)):
      self.held = False                        # any motion, or a non-finite speed, ends it for this session
    self._prev_full, self._prev_brake = full, brake
    return self.held


def brake_disengages(CS, CS_prev, preap_brake_held: bool = False) -> bool:
  """Stock rule: a brake press disengages on its rising edge, and while moving. Not when the Pre-AP car side says the press only drops longitudinal,
  and not for a Pre-AP brake held since FULL entry at a standstill (PreapHeldBrake.update, passed in as preap_brake_held)."""
  return bool(CS.brakePressed and not brake_keeps_lateral(CS) and not preap_brake_held
              and (not CS_prev.brakePressed or not CS.standstill))


def panda_controls_dropped_on_purpose(CS) -> bool:
  """True while openpilot is lateral-only after a Pre-AP brake press AND the panda's steer-through-brake latch is set
  (carState.bogpilot.preapSteerLatch mirrors tesla_preap.h steer_armed && steer_brake_seen): controls_allowed is false in the panda by
  design, not a mismatch. Steering only without that latch (no brake involved) keeps the normal not-armed / mismatch checks."""
  return brake_keeps_lateral(CS) and bool(getattr(CS.bogpilot, "preapSteerLatch", False))
