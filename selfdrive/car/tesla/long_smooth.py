"""AP1 comfort-band accel slew for DAS_control (CarController side only).

Route 0000002a: the planner aTarget is the only source of request jitter.
CarController passes it straight through (LongControl PID gains are 0) and
DAS_control tells the DI it may follow at +/-8 m/s^3 (stock AP1 DAS sends
roughly +/-0.2 to +/-1.2). Planner jerk on that drive: p95 0.7, p99 1.9
m/s^3; the larger steps cluster around radar lead jumps and show up as
one-plan-step reversals (brake blip then back to gas, gas blip then back).

Rising requests (more accel, or a brake release) are slewed at
AP1_RISE_JERK. Falling requests are slewed at AP1_FALL_JERK only while the
planner value is above AP1_BRAKE_BYPASS_ACCEL. A request at or below
AP1_BRAKE_BYPASS_ACCEL that is lower than the last output is passed
through on the same step, so hard braking, FCW and cut-ins are never
delayed, and in the comfort band the extra delay to reach -0.5 m/s^2 is at
most 0.1 s. The output always lies between the last output and the planner
value. ACCEL_MIN/MAX, the panda limits, STOP_DISTANCE and the planner are
untouched.

Below AP1_SLEW_MIN_SPEED the request passes through (and seeds the slew):
the standstill hold sits at -2.0 and the launch jumps to about +0.3, which
a 2.5 m/s^3 slew would delay by ~0.9 s.

Inactive (no DAS_control) resets. The gas-neutral frame seeds 0.0, which is
what the DI last saw, so the request after a driver press ramps from 0.

Ap1JerkLimit picks the DAS_jerkMin / DAS_jerkMax magnitude sent with each
0x2b9 frame. Stock AP1 DAS sent about +/-0.2 to +/-1.2 m/s^3 on 02a (wider
with a wider accel window); openpilot always sent +/-8. In the comfort band
this sends +/-AP1_COMFORT_JERK_LIMIT. As the request (the lower of the planner
value and the slewed value) falls from AP1_JERK_BLEND_START to
AP1_BRAKE_BYPASS_ACCEL the magnitude blends linearly up to the full 8, and at
or below AP1_BRAKE_BYPASS_ACCEL it is the full 8, so real braking is never
held back by the DI. Widening is immediate; narrowing back to the comfort
value is rate limited (AP1_JERK_LIMIT_NARROW_RATE) so the limit itself never
steps down. Below AP1_SLEW_MIN_SPEED, while inactive, and on the gas-neutral
frame it is the full 8 (the old behavior).
"""

from openpilot.common.realtime import DT_CTRL

# m/s^3. Above the planner's p99 on 02a, so normal plans pass unchanged.
AP1_RISE_JERK = 2.5
AP1_FALL_JERK = 5.0
# m/s^2. A falling request at or below this is never slewed.
AP1_BRAKE_BYPASS_ACCEL = -0.5
# m/s. Standstill hold, launch and creep pass through unchanged.
AP1_SLEW_MIN_SPEED = 1.0

# DAS_jerkMin/Max magnitudes (m/s^3). FULL matches CarControllerParams.JERK_LIMIT_MAX.
AP1_FULL_JERK_LIMIT = 8.0
AP1_COMFORT_JERK_LIMIT = 1.5
# m/s^2. Blend from comfort (at or above this) to full (at or below the bypass).
AP1_JERK_BLEND_START = -0.3
# (m/s^3) per s. Full -> comfort takes (8 - 1.5) / 10 = 0.65 s.
AP1_JERK_LIMIT_NARROW_RATE = 10.0


class Ap1AccelSmoother:
  def __init__(self, rise_jerk=AP1_RISE_JERK, fall_jerk=AP1_FALL_JERK,
               brake_bypass=AP1_BRAKE_BYPASS_ACCEL, min_speed=AP1_SLEW_MIN_SPEED):
    self.rise_jerk = rise_jerk
    self.fall_jerk = fall_jerk
    self.brake_bypass = brake_bypass
    self.min_speed = min_speed
    self.last = None

  def reset(self):
    self.last = None

  def update(self, target, active, v_ego, gas_neutral=False, dt=DT_CTRL):
    target = float(target)
    if gas_neutral:
      self.last = 0.0
      return 0.0
    if not active:
      self.last = None
      return target
    if self.last is None or v_ego < self.min_speed:
      self.last = target
      return target
    if target >= self.last:
      out = min(target, self.last + self.rise_jerk * dt)
    elif target <= self.brake_bypass:
      out = target
    else:
      out = max(target, self.last - self.fall_jerk * dt)
    self.last = out
    return out


def ap1_jerk_limit_target(accel):
  """Jerk-field magnitude for a request, before the narrowing rate limit."""
  accel = float(accel)
  if accel <= AP1_BRAKE_BYPASS_ACCEL:
    return AP1_FULL_JERK_LIMIT
  if accel >= AP1_JERK_BLEND_START:
    return AP1_COMFORT_JERK_LIMIT
  frac = (AP1_JERK_BLEND_START - accel) / (AP1_JERK_BLEND_START - AP1_BRAKE_BYPASS_ACCEL)
  return AP1_COMFORT_JERK_LIMIT + frac * (AP1_FULL_JERK_LIMIT - AP1_COMFORT_JERK_LIMIT)


class Ap1JerkLimit:
  def __init__(self):
    self.last = AP1_FULL_JERK_LIMIT

  def update(self, accel, active, v_ego, gas_neutral=False, dt=DT_CTRL):
    """Returns (jerk_min, jerk_max) for DAS_control."""
    if gas_neutral or not active or v_ego < AP1_SLEW_MIN_SPEED:
      target = AP1_FULL_JERK_LIMIT
    else:
      target = ap1_jerk_limit_target(accel)
    if target >= self.last:
      self.last = target
    else:
      self.last = max(target, self.last - AP1_JERK_LIMIT_NARROW_RATE * dt)
    return -self.last, self.last
