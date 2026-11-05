"""Pre-AP pedal HUD helpers (NAP-style).

RegenDemandCheck prompts when planned deceleration sits below the regen
envelope floor. FrogPilotCarState.pedalMaxRegen covers weak regen that
fails to deliver an in-envelope request.

update_preap_chimes edge-detects long engage/disengage for Pedal Cruise
Engaged / Disengaged prompts. Credit: NAP-style.
"""
from __future__ import annotations

import math
from typing import NamedTuple

from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.car.tesla.preap.accel_limits import get_preap_accel_limits

REGEN_DEMAND_EVIDENCE_COUNT = int(0.3 / DT_CTRL)
REGEN_DEMAND_TRIGGER_MARGIN = 0.2  # m/s^2 below the envelope floor
REGEN_DEMAND_CLEAR_MARGIN = 0.05  # m/s^2
REGEN_DEMAND_MIN_SPEED = 2.0  # m/s
REGEN_DEMAND_CLEAR_SPEED = 1.0  # m/s


class PreAPChimeState(NamedTuple):
  lat_engaged: bool = False
  long_engaged: bool = False


class PreAPChimes(NamedTuple):
  lat_engage: bool = False
  lat_disengage: bool = False
  long_engage: bool = False
  long_disengage: bool = False


def update_preap_chimes(*, lat_engaged: bool, long_engaged: bool,
                        prev: PreAPChimeState) -> tuple[PreAPChimes, PreAPChimeState]:
  """Rising/falling edges for Pre-AP lat and long driver prompts."""
  chimes = PreAPChimes(
    lat_engage=lat_engaged and not prev.lat_engaged,
    lat_disengage=(not lat_engaged) and prev.lat_engaged,
    long_engage=long_engaged and not prev.long_engaged,
    long_disengage=(not long_engaged) and prev.long_engaged,
  )
  return chimes, PreAPChimeState(lat_engaged, long_engaged)


class RegenDemandCheck:
  """Prompt when planned deceleration exceeds what the regen envelope allows."""

  def __init__(self):
    self.active = False
    self.evidence_updates = 0

  def reset(self):
    self.active = False
    self.evidence_updates = 0

  def update(self, *, pedal_long_active: bool, brake_pressed: bool,
             a_target: float, v_ego: float) -> bool:
    if not pedal_long_active or brake_pressed or not math.isfinite(a_target):
      self.reset()
      return False

    accel_floor, _ = get_preap_accel_limits(v_ego)

    if self.active:
      keep_prompting = (
        v_ego > REGEN_DEMAND_CLEAR_SPEED
        and a_target <= accel_floor - REGEN_DEMAND_CLEAR_MARGIN
      )
      if not keep_prompting:
        self.reset()
      return self.active

    demanding = (
      v_ego >= REGEN_DEMAND_MIN_SPEED
      and a_target <= accel_floor - REGEN_DEMAND_TRIGGER_MARGIN
    )
    if demanding:
      self.evidence_updates = min(self.evidence_updates + 1, REGEN_DEMAND_EVIDENCE_COUNT)
    else:
      self.evidence_updates = max(self.evidence_updates - 1, 0)
    self.active = self.evidence_updates >= REGEN_DEMAND_EVIDENCE_COUNT
    return self.active
