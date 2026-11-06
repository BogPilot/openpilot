"""NAP-style pedal command-authority FSM and regen under-delivery monitor.

Software-only handshake over GAS_SENSOR STATE/IDX. No panda loosening.
Credit: NAP-style.
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


class PedalAuthorityState(IntEnum):
  INACTIVE = 0
  ACQUIRING = 1
  ACTIVE = 2
  FAILED = 3


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

  def _clear_acquisition(self):
    self.reset_feedback_counter = None
    self.reset_attempts = 0

  def _start_acquisition(self, feedback):
    self.state = PedalAuthorityState.ACQUIRING
    self.reset_feedback_counter = feedback.idx
    self.reset_attempts = 1
    return PedalCommandAction.RESET

  @staticmethod
  def _recoverable_timeout(feedback):
    """Live pedal reporting a firmware state that 0x551 keepalives can clear."""
    return bool(feedback.available) and feedback.interceptor_state in RECOVERABLE_PEDAL_STATES

  def update(self, authority_requested, feedback):
    if not authority_requested:
      action = PedalCommandAction.RELEASE if self.state == PedalAuthorityState.ACTIVE else PedalCommandAction.NONE
      self.state = PedalAuthorityState.INACTIVE
      self._clear_acquisition()
      return action

    if self.state == PedalAuthorityState.FAILED:
      return PedalCommandAction.NONE

    feedback_healthy = feedback.available and feedback.interceptor_state == PEDAL_STATE_NO_FAULT
    if self.state == PedalAuthorityState.ACTIVE:
      if feedback_healthy:
        return PedalCommandAction.ENABLE
      return self._start_acquisition(feedback)

    if self.state == PedalAuthorityState.ACQUIRING:
      feedback_advanced = feedback.idx != self.reset_feedback_counter
      if feedback_healthy and feedback_advanced:
        self.state = PedalAuthorityState.ACTIVE
        self._clear_acquisition()
        return PedalCommandAction.ACQUIRE

      # Keep sending ENABLE=0 zero-gas keepalives while STATE is TIMEOUT or
      # STARTUP. Tester rlogs showed 4 RESET frames were enough for the pedal
      # to briefly reach NO_FAULT, but the FSM had already latched FAILED.
      if self._recoverable_timeout(feedback):
        return PedalCommandAction.RESET

      if self.reset_attempts < self.MAX_RESET_ATTEMPTS:
        self.reset_attempts += 1
        return PedalCommandAction.RESET

      self.state = PedalAuthorityState.FAILED
      self._clear_acquisition()
      return PedalCommandAction.FAILURE

    if feedback_healthy:
      self.state = PedalAuthorityState.ACTIVE
      return PedalCommandAction.ACQUIRE

    return self._start_acquisition(feedback)

  def command_failed(self):
    self.state = PedalAuthorityState.FAILED
    self._clear_acquisition()
