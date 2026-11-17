"""Pre-AP radar-valid gate: did the retrofit Bosch radar ACCEPT its config and see the road, not just receive frames?

Pre-AP only (radar_interface.py). While the gate is not valid, radar_interface publishes no points and the pull FSM allows no
speed control: FULL is refused on the second pull and dropped if it is on (carstate.py; card.py feeds it). Lateral is not
touched. Two separate questions, both reported in the log-only status line:
- echoed: with flag 256, the panda's radar gateway is sending (returned TX echoes, src 129, of the frames in
  preap/panda_link.py GTW_ECHO_ADDRS). An echo only proves we sent the frames.
- accepted: the radar itself says it is configured and working: TeslaRadarSguInfo RADC_SGU_ITC == 0 (DBC generator
  dbc/generator/tesla/tesla_radar_bosch.py:50), the last TeslaRadarAlertMatrix (0x501) frame has none of REJECT_BITS
  (radPositionMismatch :129, vinValidity :105, xwdValidity :110), and a moving track (|vRel| >= MOVING_VREL) has been
  seen, all together for CLEAR_S. SGUFail (:54) is NOT part of acceptance: a healthy radar raises it while it aligns
  (NAP keeps engage allowed on it, car/tesla/radar_interface.py:203-210 @ naponsp-alpha-prebuilt 7eb09d2a7).
Valid = accepted and none of these, each of which also drops acceptance (it must be earned again):
- D1 no gateway: with flag 256, no echo for HOLD_S (the radar then gets no vehicle data at all).
- D2 starved: 0x501 bdy / esp / gtw / sccm MIA bits (:79-82) set in 2 consecutive frames and held for HOLD_S.
- D3 config rejected: any REJECT_BITS set in 2 consecutive frames and held for HOLD_S.
- D6 frozen: 1 or more valid points whose (dRel, yRel, vRel) table has not changed for FROZEN_S while SGUFail is set (NAP
  BoschTableFreezeWatch, opendbc car/tesla/preap/radar_table_freeze.py:12-36 @ 7eb09d2a7, with NAP's MIN_POINTS 4 lowered
  to 1 as the tester-2 table had 3 points, and its 40 cycles expressed in seconds).
NOT_ACCEPTED (label only, for the status line): echoed, or no gateway needed, for ACCEPT_S without acceptance.
HWFail keeps its radarFault. Times come from the CAN packets' log time.
"""
from __future__ import annotations

from dataclasses import dataclass

HOLD_S = 2.0
CLEAR_S = 2.0
FROZEN_S = 5.0
FROZEN_MIN_POINTS = 1
ACCEPT_S = 20.0
MOVING_VREL = 0.5   # m/s
MIA_BITS = ("RADC_a011_bdyMIA", "RADC_a012_espMIA", "RADC_a013_gtwMIA", "RADC_a014_sccmMIA")
REJECT_BITS = ("RADC_a061_radPositionMismatch", "RADC_a037_vinValidity", "RADC_a042_xwdValidity")
D1, D2, D3, D6, NOT_ACCEPTED = 1, 2, 4, 8, 16   # reason bits; NOT_ACCEPTED never invalidates on its own
INVALIDATING = D1 | D2 | D3 | D6


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
    self.echo_since: float | None = None
    self.mia = _Held()
    self.reject = _Held()
    self.reject_now = False
    self.itc: int | None = None
    self.last_move: float | None = None
    self.sig = None
    self.sig_since: float | None = None
    self.reasons = 0
    self.echoed = not self.radar_emulation
    self.accepted = False
    self.accept_since: float | None = None
    self.wait_since: float | None = None
    self.valid = False          # fail closed until the radar has accepted its config
    self.faults = 0             # valid -> invalid edges

  def on_echo(self, now: float) -> None:
    if self.last_echo is None or now - self.last_echo >= HOLD_S:
      self.echo_since = now
    self.last_echo = now

  def on_alert_matrix(self, now: float, vl) -> None:
    """One new 0x501 frame (parser values)."""
    self.mia.update(any(bool(vl[b]) for b in MIA_BITS), now)
    self.reject_now = any(bool(vl[b]) for b in REJECT_BITS)
    self.reject.update(self.reject_now, now)

  def on_points(self, now: float, points, sgu_fail: bool, itc: int | None = None) -> None:
    """One radar cycle: the valid points before the gate drops them, SGUFail and the SGU ITC."""
    if itc is not None:
      self.itc = int(itc)
    if any(abs(float(p.vRel)) >= MOVING_VREL for p in points):
      self.last_move = now
    rows = tuple(sorted((round(float(p.dRel), 2), round(float(p.yRel), 2), round(float(p.vRel), 2)) for p in points))
    if len(rows) < FROZEN_MIN_POINTS or not sgu_fail:
      self.sig, self.sig_since = None, None
    elif rows != self.sig:
      self.sig, self.sig_since = rows, now

  def update(self, now: float, sgu_fail: bool = False) -> bool:
    if self.t0 is None:
      self.t0 = now
    r = 0
    if self.radar_emulation:
      self.echoed = self.last_echo is not None and now - self.last_echo < HOLD_S
      ref = self.last_echo if self.last_echo is not None else self.t0
      if now - ref >= HOLD_S:
        r |= D1
    if self.mia.held(now, HOLD_S, 2):
      r |= D2
    if self.reject.held(now, HOLD_S, 2):
      r |= D3
    if self.sig_since is not None and now - self.sig_since >= FROZEN_S:
      r |= D6

    if r:
      self.accepted, self.accept_since = False, None
    elif not self.accepted:
      ok = (self.itc == 0 and not self.reject_now and self.last_move is not None and now - self.last_move < CLEAR_S)
      if not ok:
        self.accept_since = None
      else:
        if self.accept_since is None:
          self.accept_since = now
        if now - self.accept_since >= CLEAR_S:
          self.accepted = True

    if self.accepted or (r & D1):
      self.wait_since = None
    else:
      if self.wait_since is None:
        self.wait_since = (self.echo_since if self.radar_emulation and self.echo_since is not None else now)
      if now - self.wait_since >= ACCEPT_S:
        r |= NOT_ACCEPTED
    self.reasons = r

    valid = self.accepted and not (r & INVALIDATING)
    if self.valid and not valid:
      self.faults += 1
    self.valid = valid
    return valid

  def status(self) -> dict:
    """For the log-only status line: echoed and accepted are reported separately."""
    return dict(echoed=self.echoed, accepted=self.accepted, valid=self.valid, reasons=self.reasons, itc=self.itc,
                reject=self.reject_now, faults=self.faults)
