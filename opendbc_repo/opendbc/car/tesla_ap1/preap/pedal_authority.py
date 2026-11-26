"""Pedal command-authority FSM and regen under-delivery monitor.

Software-only handshake over GAS_SENSOR STATE/IDX. No panda loosening.
Credit: adapted from NotAutopilot (NAP) opendbc `opendbc/car/tesla/preap/carcontroller.py` (MIT, https://github.com/NotAutopilot/opendbc);
BogPilot changes: the authority logic is split out into its own module.
"""
from __future__ import annotations

from enum import IntEnum

import numpy as np


ENGAGE_GRACE_FRAMES = 50  # 0.5s at 100Hz
ENGAGE_GRACE_PEDAL_RAMP_RATE_UP = 0.9  # DI/update at 50Hz

REGEN_DECEL_PROMPT_DWELL_UPDATES = 40
REGEN_DECEL_PROMPT_MIN_SPEED = 2.0
REGEN_DECEL_PROMPT_CLEAR_SPEED = 1.0
REGEN_DECEL_SHORTFALL_TRIGGER = 0.35
REGEN_DECEL_SHORTFALL_CLEAR = 0.15
REGEN_COMMAND_TRIGGER_DI = -2.0
REGEN_COMMAND_CLEAR_DI = -1.0
REGEN_DECEL_REQUEST_TRIGGER = -0.5
REGEN_DECEL_REQUEST_CLEAR = -0.2

# GAS_SENSOR STATE nibble (NAP test_tesla_preap.py). ENABLE=0 zero-gas
# GAS_COMMAND (0x551) clears FAULT_TIMEOUT / FAULT_STARTUP firmware-side.
PEDAL_STATE_NO_FAULT = 0
PEDAL_STATE_FAULT_STARTUP = 4
PEDAL_STATE_FAULT_TIMEOUT = 5
RECOVERABLE_PEDAL_STATES = (PEDAL_STATE_FAULT_STARTUP, PEDAL_STATE_FAULT_TIMEOUT)

# a failed acquisition is not final. While openpilot still wants pedal longitudinal the authority waits, then tries the 4-RESET
# handshake again. Waits are in authority updates (50 Hz): 0.5 s, 1 s, 2 s, then 3 s between tries.
RETRY_BACKOFF_UPDATES = (25, 50, 100, 150)
# A real pedal state does not move that fast. Three different STATE values inside one 4-update acquisition means the nibble being read
# is really the 4-bit counter (a DBC nibble mix-up).
MISMATCH_DISTINCT_STATES = 3
# A pedal that stays in STARTUP/TIMEOUT keeps getting zero-gas keepalives. Previously that went on silently forever; after 3 s (150 updates)
# it is reported as a STATE_FAULT failure (the alert says so) and retried like any other failure.
RECOVERABLE_GIVE_UP_UPDATES = 150


class PedalAuthorityState(IntEnum):
  INACTIVE = 0
  ACQUIRING = 1
  ACTIVE = 2
  FAILED = 3


class PedalFailCause(IntEnum):
  """Why the last acquisition failed (carState.bogpilot.preapPedalFailCause; the alert detail is chosen from it)."""
  NONE = 0
  NO_STREAM = 1       # the pedal is not talking (counter not moving, or no GAS_SENSOR)
  STATE_FAULT = 2     # the pedal talks but stays in a fault state (startup / timeout / ...) after our zero-gas keepalives
  DATA_MISMATCH = 3   # the "state" field behaves like a counter: counter and state read the wrong way round
  COUNTER_STUCK = 4   # state is fine but the counter has not moved since the reset
  COMMAND_ERROR = 5   # building the pedal command raised (latched until the driver re-engages)
  NO_RESPONSE = 6     # none of the above: the pedal heard the commands and still did not take authority


class PedalCommandAction(IntEnum):
  NONE = 0
  RESET = 1
  ACQUIRE = 2
  ENABLE = 3
  RELEASE = 4
  FAILURE = 5


class RegenDecelMonitor:
  """Detect when the regen path cannot deliver the requested deceleration."""

  def __init__(self):
    self.active = False
    self.evidence_updates = 0

  def reset(self):
    self.active = False
    self.evidence_updates = 0

  def update(self, *, pedal_control_active, in_engage_grace, pedal_di,
             limited_accel, actual_accel, v_ego):
    values_are_finite = all(np.isfinite((pedal_di, limited_accel, actual_accel, v_ego)))
    decel_shortfall = actual_accel - limited_accel
    monitoring_allowed = (
      pedal_control_active
      and not in_engage_grace
      and values_are_finite
      and limited_accel < 0.0
    )

    if self.active:
      keep_prompting = (
        monitoring_allowed
        and v_ego > REGEN_DECEL_PROMPT_CLEAR_SPEED
        and pedal_di <= REGEN_COMMAND_CLEAR_DI
        and limited_accel <= REGEN_DECEL_REQUEST_CLEAR
        and decel_shortfall > REGEN_DECEL_SHORTFALL_CLEAR
      )
      if not keep_prompting:
        self.reset()
      return self.active

    under_delivering = (
      monitoring_allowed
      and v_ego >= REGEN_DECEL_PROMPT_MIN_SPEED
      and pedal_di <= REGEN_COMMAND_TRIGGER_DI
      and limited_accel <= REGEN_DECEL_REQUEST_TRIGGER
      and decel_shortfall >= REGEN_DECEL_SHORTFALL_TRIGGER
    )
    if under_delivering:
      self.evidence_updates = min(self.evidence_updates + 1, REGEN_DECEL_PROMPT_DWELL_UPDATES)
    else:
      self.evidence_updates = max(self.evidence_updates - 1, 0)
    self.active = self.evidence_updates >= REGEN_DECEL_PROMPT_DWELL_UPDATES
    return self.active


class PedalAuthority:
  """Owns the pedal command-authority lifecycle (software GAS_SENSOR handshake)."""

  MAX_RESET_ATTEMPTS = 4

  def __init__(self):
    self.state = PedalAuthorityState.INACTIVE
    self.reset_feedback_counter = None
    self.reset_attempts = 0
    self.fail_cause = PedalFailCause.NONE
    self.retries = 0
    self._backoff_updates = 0
    self._latched = False
    self._states_seen: set[int] = set()
    self._recoverable_updates = 0

  def _clear_acquisition(self):
    self.reset_feedback_counter = None
    self.reset_attempts = 0

  def _start_acquisition(self, feedback):
    self.state = PedalAuthorityState.ACQUIRING
    self.reset_feedback_counter = feedback.idx
    self.reset_attempts = 1
    self._states_seen = {int(feedback.interceptor_state)}
    self._recoverable_updates = 0
    return PedalCommandAction.RESET

  def _diagnose(self, feedback) -> PedalFailCause:
    """The real cause of an exhausted acquisition, from what the pedal reported while we tried."""
    if len(self._states_seen) >= MISMATCH_DISTINCT_STATES:
      return PedalFailCause.DATA_MISMATCH
    if not feedback.available:
      return PedalFailCause.NO_STREAM
    if feedback.interceptor_state != PEDAL_STATE_NO_FAULT:
      return PedalFailCause.STATE_FAULT
    if feedback.idx == self.reset_feedback_counter:
      return PedalFailCause.COUNTER_STUCK
    return PedalFailCause.NO_RESPONSE

  @staticmethod
  def _recoverable_timeout(feedback):
    """Live pedal reporting a firmware state that 0x551 keepalives can clear."""
    return bool(feedback.available) and feedback.interceptor_state in RECOVERABLE_PEDAL_STATES

  def update(self, authority_requested, feedback):
    if not authority_requested:
      action = PedalCommandAction.RELEASE if self.state == PedalAuthorityState.ACTIVE else PedalCommandAction.NONE
      self.state = PedalAuthorityState.INACTIVE
      self._clear_acquisition()
      self.fail_cause = PedalFailCause.NONE      # a new engage starts clean: no leftover cause, retry count or back-off
      self.retries = 0
      self._backoff_updates = 0
      self._latched = False
      return action

    if self.state == PedalAuthorityState.FAILED:
      if self._latched:
        return PedalCommandAction.NONE            # a command error stays until the driver re-engages
      # Not final: wait out the back-off, then run the RESET handshake again (openpilot is still asking for pedal longitudinal).
      self._backoff_updates += 1
      if self._backoff_updates >= RETRY_BACKOFF_UPDATES[min(self.retries, len(RETRY_BACKOFF_UPDATES) - 1)]:
        self.retries += 1
        self._backoff_updates = 0
        return self._start_acquisition(feedback)
      return PedalCommandAction.NONE

    feedback_healthy = feedback.available and feedback.interceptor_state == PEDAL_STATE_NO_FAULT
    if self.state == PedalAuthorityState.ACTIVE:
      if feedback_healthy:
        return PedalCommandAction.ENABLE
      return self._start_acquisition(feedback)

    if self.state == PedalAuthorityState.ACQUIRING:
      self._states_seen.add(int(feedback.interceptor_state))
      feedback_advanced = feedback.idx != self.reset_feedback_counter
      if feedback_healthy and feedback_advanced:
        self.state = PedalAuthorityState.ACTIVE
        self._clear_acquisition()
        self.fail_cause = PedalFailCause.NONE
        self.retries = 0
        return PedalCommandAction.ACQUIRE

      # Keep sending ENABLE=0 zero-gas keepalives while STATE is TIMEOUT or
      # STARTUP. Drive rlogs showed 4 RESET frames were enough for the pedal
      # to briefly reach NO_FAULT, but the FSM had already latched FAILED.
      if self._recoverable_timeout(feedback):
        self._recoverable_updates += 1
        if self._recoverable_updates < RECOVERABLE_GIVE_UP_UPDATES:
          return PedalCommandAction.RESET
      elif self.reset_attempts < self.MAX_RESET_ATTEMPTS:
        self.reset_attempts += 1
        return PedalCommandAction.RESET

      self.fail_cause = self._diagnose(feedback)
      self.state = PedalAuthorityState.FAILED
      self._backoff_updates = 0
      self._clear_acquisition()
      return PedalCommandAction.FAILURE

    if feedback_healthy:
      self.state = PedalAuthorityState.ACTIVE
      return PedalCommandAction.ACQUIRE

    return self._start_acquisition(feedback)

  def command_failed(self):
    self.state = PedalAuthorityState.FAILED
    self.fail_cause = PedalFailCause.COMMAND_ERROR
    self._latched = True
    self._clear_acquisition()
