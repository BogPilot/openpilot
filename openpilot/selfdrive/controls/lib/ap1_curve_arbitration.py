"""Single arbitration point for the AP1 acceleration request on the 0.11.2 C3X planner.

The planner picks min() over its acceleration candidates. Every candidate is individually smooth (the cruise
candidate is jerk limited in get_cruise_accel, the curve brake in ap1_curve_brake), but the min() flips between them,
and each flip is a step: lifting off from a +0.7 m/s^2 cruise request to a curve brake that starts at -0.07 m/s^2 is a
0.8 m/s^2 step in one plan frame, and the release is the same step back up.

CurveArbiter keeps the min() (it can only ever ADD braking relative to each candidate) and puts comfort bounds on the
comfort class only (cruise, curve brake):

  comfort = min(cruise, curve brake), then slewed by an elapsed-time jerk limit: at most COMFORT_JERK_DOWN m/s^3 more
            braking per second (fast: a request that is already ramping at <= 1.6 m/s^3 is never delayed, only the
            winner-switch step is absorbed) and COMFORT_JERK_UP m/s^3 less braking (the release ramp of the curve brake)
  output  = min(comfort, every other candidate)  -- lead MPC, Experimental (e2e), stopping: NEVER slewed

Bypass: a comfort request at or below BYPASS_ACCEL (close to the AP1 regen floor, -1.2 m/s^2) is passed straight
through, so a strong request is never held back by the comfort limit; every bypass episode is logged.

The record of the last arbitration (winner, candidate values, ages) is kept in `last` for logging and tests.
Units: m/s^2, m/s^3, seconds.
"""
from __future__ import annotations

import numpy as np

from openpilot.common.swaglog import cloudlog

COMFORT_JERK_DOWN = 5.0   # m/s^3, more braking
COMFORT_JERK_UP = 1.2     # m/s^3, less braking (same as the curve brake release jerk)
BYPASS_ACCEL = -1.0       # m/s^2, comfort requests at or below this are never slewed
COMFORT_NAMES = ("cruise", "curve")
DT_MIN, DT_MAX = 0.01, 0.2


class ModelClock:
  """Elapsed seconds between consecutive modelV2 frames (monotonic), bounded; fallback when the time is unknown."""

  def __init__(self, fallback: float):
    self.fallback = fallback
    self.last = None

  def step(self, sm) -> float:
    try:
      mono = int(sm.logMonoTime["modelV2"])
    except (AttributeError, KeyError, TypeError, ValueError):
      return self.fallback
    dt = self.fallback if self.last is None or mono <= self.last else (mono - self.last) * 1e-9
    self.last = mono
    return float(np.clip(dt, DT_MIN, DT_MAX))


class CurveArbiter:
  def __init__(self, dt: float):
    self.dt = dt
    self.comfort = 0.0
    self.initialized = False
    self.bypassing = False
    self.last = {}

  def reset(self, a: float = 0.0):
    self.comfort = float(a)
    self.initialized = True
    self.bypassing = False

  def arbitrate(self, candidates, dt: float, reset: bool, ages=None):
    """candidates: [(name, accel)] -> (accel, winner name, record). `reset` re-seeds the comfort state."""
    dt = float(np.clip(dt, DT_MIN, DT_MAX))
    comfort_raw = min((a for n, a in candidates if n in COMFORT_NAMES), default=None)
    comfort = comfort_raw
    bypass = False
    if comfort_raw is not None:
      if reset or not self.initialized:
        self.comfort = comfort_raw
        self.initialized = True
      elif comfort_raw <= BYPASS_ACCEL:
        self.comfort = comfort_raw
        bypass = True
      else:
        self.comfort = float(np.clip(comfort_raw, self.comfort - COMFORT_JERK_DOWN * dt, self.comfort + COMFORT_JERK_UP * dt))
      comfort = self.comfort
    if bypass and not self.bypassing:
      cloudlog.event("ap1_comfort_bypass", comfort_raw=float(comfort_raw), comfort_prev=float(self.comfort))
    self.bypassing = bypass
    others = [(n, a) for n, a in candidates if n not in COMFORT_NAMES]
    pool = others + ([("comfort", comfort)] if comfort is not None else [])
    winner, out = min(pool, key=lambda c: c[1])
    if winner == "comfort":
      winner = "curve" if any(n == "curve" and a <= comfort_raw + 1e-9 for n, a in candidates) else "cruise"
    self.last = dict(winner=winner, out=float(out), candidates={n: float(a) for n, a in candidates}, comfort_raw=comfort_raw,
                     comfort=comfort, bypass=bypass, dt=dt, ages=ages or {})
    return float(out), winner, dict(bypass=bypass, comfort_raw=comfort_raw, comfort=comfort)
