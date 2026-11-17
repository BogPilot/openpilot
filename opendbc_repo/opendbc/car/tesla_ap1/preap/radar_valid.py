"""Pre-AP radar-valid gate: is the retrofit Bosch radar configured and seeing the car, or starved / rejecting its config?

Pre-AP only (radar_interface.py). While the gate is not valid, radar_interface publishes no points and the pull FSM allows no
speed control: FULL is refused on the second pull and dropped if it is on (carstate.py, card.py feeds it). Lateral is not
touched. Conditions, from bus-1 CAN only:
- D1 no gateway: with flag 256, no returned echo (src 129) of any frame the panda's radar gateway sends (preap/panda_link.py)
  for HOLD_S. The radar then gets no vehicle data at all.
- D2 starved: TeslaRadarAlertMatrix (0x501) bdy / esp / gtw / sccm MIA bits (a011-a014) set in 2 consecutive frames and held
  for HOLD_S.
- D3 config rejected: 0x501 a061 radPositionMismatch, a037 vinValidity or a042 xwdValidity set in 2 consecutive frames and
  held for HOLD_S.
- D6 frozen: FROZEN_MIN_POINTS or more valid points whose (dRel, yRel, vRel) table has not changed for FROZEN_S while
  TeslaRadarSguInfo SGUFail is set (NAP BoschTableFreezeWatch, opendbc car/tesla/preap/radar_table_freeze.py:12-36 @
  naponsp-alpha-prebuilt 7eb09d2a7, with NAP's MIN_POINTS 4 lowered to 3 and its 40 cycles expressed in seconds).
Warm-up: the gate starts invalid, and becomes valid only after every condition AND SGUFail have been clear for CLEAR_S (the
radar reported itself healthy). Once valid, SGUFail alone does not invalidate it: NAP keeps engage allowed on SGUFail, because
the radar raises it for the adjustment triad while tracks are live and driving clears it (car/tesla/radar_interface.py:203-210
@ 7eb09d2a7). Stricter than NAP: a radar that never reports SGUFail clear never gets speed control. After an invalid period
the same warm-up applies again. HWFail keeps its radarFault. Times come from the CAN packets' log time.
"""
from __future__ import annotations

from dataclasses import dataclass

HOLD_S = 2.0
CLEAR_S = 2.0
FROZEN_S = 5.0
FROZEN_MIN_POINTS = 3
MIA_BITS = ("RADC_a011_bdyMIA", "RADC_a012_espMIA", "RADC_a013_gtwMIA", "RADC_a014_sccmMIA")
REJECT_BITS = ("RADC_a061_radPositionMismatch", "RADC_a037_vinValidity", "RADC_a042_xwdValidity")
D1, D2, D3, D6 = 1, 2, 4, 8   # reason bits


@dataclass
class _Held:
  since: float | None = None
  frames: int = 0

  def update(self, on: bool, now: float) -> None:
    if on:
      self.frames += 1
      if self.since is None:
        self.since = now
    else:
      self.since, self.frames = None, 0

  def held(self, now: float, hold: float, min_frames: int = 1) -> bool:
    return self.since is not None and self.frames >= min_frames and now - self.since >= hold


class RadarValidGate:
  def __init__(self, radar_emulation: bool):
    self.radar_emulation = bool(radar_emulation)
    self.t0: float | None = None
    self.last_echo: float | None = None
    self.mia = _Held()
    self.reject = _Held()
    self.sig = None
    self.sig_since: float | None = None
    self.reasons = 0
    self.valid = False          # fail closed until the radar has been seen clean for CLEAR_S
    self.clear_since: float | None = None
    self.faults = 0             # invalid edges, for the status line

  def on_echo(self, now: float) -> None:
    self.last_echo = now

  def on_alert_matrix(self, now: float, vl) -> None:
    """One new 0x501 frame (parser values)."""
    self.mia.update(any(bool(vl[b]) for b in MIA_BITS), now)
    self.reject.update(any(bool(vl[b]) for b in REJECT_BITS), now)

  def on_points(self, now: float, points, sgu_fail: bool) -> None:
    """One radar cycle: the valid points before the gate drops them."""
    rows = tuple(sorted((round(float(p.dRel), 2), round(float(p.yRel), 2), round(float(p.vRel), 2)) for p in points))
    if len(rows) < FROZEN_MIN_POINTS or not sgu_fail:
      self.sig, self.sig_since = None, None
    elif rows != self.sig:
      self.sig, self.sig_since = rows, now
    # else: unchanged, keep sig_since

  def update(self, now: float, sgu_fail: bool = False) -> bool:
    if self.t0 is None:
      self.t0 = now
    r = 0
    if self.radar_emulation:
      ref = self.last_echo if self.last_echo is not None else self.t0
      if now - ref >= HOLD_S:
        r |= D1
    if self.mia.held(now, HOLD_S, 2):
      r |= D2
    if self.reject.held(now, HOLD_S, 2):
      r |= D3
    if self.sig_since is not None and now - self.sig_since >= FROZEN_S:
      r |= D6
    self.reasons = r
    if r:
      if self.valid:
        self.faults += 1
      self.valid = False
      self.clear_since = None
    elif not self.valid:
      if sgu_fail:
        self.clear_since = None
      else:
        if self.clear_since is None:
          self.clear_since = now
        if now - self.clear_since >= CLEAR_S:
          self.valid = True
    return self.valid
