"""Smooth Curve Braking (CSCTeslaSmoothing, default OFF) on the AP1 curve brake. Pure maths, no planner, runs anywhere.

Invariants: off is the stock brake bit for bit; on never brakes less than stock on any frame, never past the landing cap
(never below the curve speed), never below A_MIN, envelope onset/release jerk limited; the switch only latches while idle."""
import math

import numpy as np
import pytest

from openpilot.selfdrive.controls.lib.ap1_curve_brake import (A_MIN, RELEASE_JERK, SMOOTH_FLOOR, SMOOTH_HOLD_LEAK,
                                                              SMOOTH_ONSET_JERK, TeslaCurveBrake)
from openpilot.selfdrive.controls.tests.test_ap1_curve_brake import DT, path

def wobbly_drive(seed=0, n=240):
  """Closed-loop approach to a curve whose model curvature estimate wobbles (the brake / ease / brake case).
  Returns per-frame (csc_active, v_ego, path); the car follows the stock brake so both brakes see the same frames."""
  rng = np.random.default_rng(seed)
  v, d, frames, stock = 17.0 + seed, 110.0, [], TeslaCurveBrake(DT)
  for i in range(n):
    k = (0.009 if (i // (5 + seed)) % 2 == 0 else 0.0062) * (1.0 + 0.05 * rng.standard_normal())
    active = i % 97 > 3
    p = path(v, lambda x, k=k, d=d: k if x > d else 0.0)
    frames.append((active, v, p))
    a = stock.update(active, v, *p)
    v, d = max(8.0, v + a * DT), max(0.0, d - v * DT)
  return frames


def run(brake, frames):
  out = []
  for active, v, (t, x, vp, yr) in frames:
    out.append(brake.update(active, v, t, x, vp, yr))
  return out


@pytest.mark.parametrize("seed", range(5))
def test_off_is_the_stock_brake_bit_for_bit(seed):
  frames = wobbly_drive(seed=seed)
  stock, off = TeslaCurveBrake(DT), TeslaCurveBrake(DT)
  off.set_smooth(False)
  a = run(stock, frames)
  b = []
  for f in frames:
    off.set_smooth(False)
    b.append(off.update(f[0], f[1], *f[2]))
  assert a == b


@pytest.mark.parametrize("seed", range(5))
def test_on_only_adds_braking_within_the_landing_cap_and_a_min(seed):
  frames = wobbly_drive(seed=seed)
  stock, on = TeslaCurveBrake(DT), TeslaCurveBrake(DT)
  on.set_smooth(True)
  deeper = 0
  prev = 0.0
  for active, v, p in frames:
    s = stock.update(active, v, *p)
    o = on.update(active, v, *p)
    assert o <= s + 1e-12                                     # never less braking than stock
    assert o >= A_MIN - 1e-9                                  # never past the regen floor
    assert on.env >= -on.landing_cap - 1e-9                   # envelope target never past the landing cap (curve speed)
    assert o - prev >= -1.5 * DT - 1e-9                       # onset never faster than the stock ONSET_JERK
    deeper += o < s - 1e-6
    prev = o
  assert deeper > 0


def test_off_target_and_inactive_release_to_zero():
  b = TeslaCurveBrake(DT)
  b.set_smooth(True)
  t, x, vp, yr = path(18.0, lambda x: 0.03 if x > 20 else 0.0)
  for _ in range(60):
    b.update(True, 18.0, t, x, vp, yr)
  assert b.env_out < -0.5
  for i in range(200):
    a = b.update(False, 18.0, t, x, vp, yr)
  assert a == 0.0 and b.env_out == 0.0


def test_hold_eases_at_the_leak_while_the_curve_still_limits():
  b = TeslaCurveBrake(DT)
  b.set_smooth(True)
  hard = path(18.0, lambda x: 0.03 if x > 25 else 0.0)
  for _ in range(40):
    b.update(True, 18.0, *hard)
  held = b.env_out
  soft = path(18.0, lambda x: 0.0069 if x > 120 else 0.0)  # estimate wobbles weaker (request under the floor), curve still limits
  b.update(True, 18.0, *soft)
  assert b.landing_cap > 0
  assert b.env_out >= held and b.env_out <= held + SMOOTH_HOLD_LEAK * DT + 1e-9


def test_starts_past_the_floor_without_the_debounce():
  stock, on = TeslaCurveBrake(DT), TeslaCurveBrake(DT)
  on.set_smooth(True)
  p = path(20.0, lambda x: 0.0054 if x > 80 else 0.0)   # weak request (about -0.2): past SMOOTH_FLOOR, short of STRONG_REQUEST
  s, o = stock.update(True, 20.0, *p), on.update(True, 20.0, *p)
  assert s == 0.0 and o < 0.0 and o >= -SMOOTH_ONSET_JERK * DT - 1e-9
  assert SMOOTH_FLOOR == 0.15 and SMOOTH_ONSET_JERK == 1.0 and SMOOTH_HOLD_LEAK == 0.3 and RELEASE_JERK == 1.2


def test_switch_latches_only_while_idle():
  b = TeslaCurveBrake(DT)
  p = path(18.0, lambda x: 0.03 if x > 20 else 0.0)
  b.set_smooth(True)
  assert b.smooth
  for _ in range(20):
    b.update(True, 18.0, *p)
  assert b.a_request < 0
  b.set_smooth(False)
  assert b.smooth                                          # mid-brake: keep the braking it has
  for _ in range(200):
    b.update(False, 18.0, *p)
  b.set_smooth(False)
  assert not b.smooth
  b.update(True, 18.0, *p)
  b.set_smooth(True)
  assert not b.smooth or b.a_request == 0.0


class _Store:
  def __init__(self, smooth):
    self.smooth = smooth

  def toggle_bool(self, key, level=None):
    if key == "CSCTeslaSmoothing":
      if isinstance(self.smooth, Exception):
        raise self.smooth
      return self.smooth
    return True

  def get(self, key, default=None):
    return default


@pytest.mark.parametrize("value,expect", [(True, True), (False, False), (KeyError("unknown key"), False)])
def test_planner_side_reads_the_toggle_each_update_and_fails_closed(monkeypatch, value, expect):
  from opendbc.car.tesla_ap1.interface import CarInterface
  import openpilot.selfdrive.controls.lib.ap1_curve_speed as ACS
  cp = CarInterface.get_non_essential_params("TESLA_AP1_MODELS")
  cp.openpilotLongitudinalControl = True
  cs = ACS.Ap1CurveSpeed(cp, DT, store=_Store(value))
  monkeypatch.setattr(cs.clock, "step", lambda sm: DT)
  monkeypatch.setattr(ACS, "_service_ok", lambda sm, name: False)   # no fresh inputs: CSC inactive, toggle still read
  assert cs.update({}, 15.0, 20.0, False) == 20.0
  assert cs.brake.smooth is expect and ACS.SMOOTH_TOGGLE == "CSCTeslaSmoothing"
