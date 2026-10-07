"""AP1 comfort-band accel slew for DAS_control (CarController side only).

Route 0000002a: the planner aTarget is the only source of request jitter.
CarController passes it straight through (LongControl PID gains are 0) and
DAS_control tells the DI it may follow at +/-8 m/s^3 (stock AP1 DAS sends
roughly +/-0.2 to +/-1.2). Planner jerk on that drive: p95 0.7, p99 1.9
m/s^3; the larger steps cluster around radar lead jumps and show up as
one-plan-step reversals (brake blip then back to gas, gas blip then back).

Rising requests (more accel, or a brake release) are slewed at
AP1_RISE_JERK. Falling requests are slewed as described under "Regen onset
ramp" below; a request at or below AP1_BRAKE_HARD_ACCEL, an FCW, or the
LongControl stopping state passes through on the same step. The output
always lies between the last output and the planner value. ACCEL_MIN/MAX,
the panda limits, STOP_DISTANCE and the planner are untouched.

Below AP1_SLEW_MIN_SPEED the request passes through (and seeds the slew):
the standstill hold sits at -2.0 and the launch jumps to about +0.3, which
a 2.5 m/s^3 slew would delay by ~0.9 s.

Inactive (no DAS_control) resets. The gas-neutral frame seeds 0.0, which is
what the DI last saw, so the request after a driver press ramps from 0.

Ap1JerkLimit picks the DAS_jerkMin / DAS_jerkMax magnitude sent with each
0x2b9 frame. Stock AP1 DAS sent about +/-0.2 to +/-1.2 m/s^3 on 02a (wider
with a wider accel window); openpilot always sent +/-8. In the comfort band
this sends +/-AP1_COMFORT_JERK_LIMIT. As the request sent falls from
AP1_JERK_BLEND_START to AP1_BRAKE_BYPASS_ACCEL the magnitude blends linearly
up to the full 8, and at or below AP1_BRAKE_BYPASS_ACCEL (or on an urgent
frame) it is the full 8, so real braking is never held back by the DI.
The field is always at least the regen ramp jerk being sent once the request
is past AP1_BRAKE_BYPASS_ACCEL. Widening is immediate; narrowing back to the comfort
value is rate limited (AP1_JERK_LIMIT_NARROW_RATE) so the limit itself never
steps down. Below AP1_SLEW_MIN_SPEED, while inactive, and on the gas-neutral
frame it is the full 8 (the old behavior).

Regen onset ramp (road test of 6914de87, route 0000002e). The planner turns
a sudden drop in its plan into an overshooting step: aTarget is
2 * (v(0.55 s) - v0) / 0.55 - a0, so when the plan's current accel a0 is
+1.2 and the plan falls to about -0.2 (allowThrottle going false, or a lead
first seen at 86 m), aTarget lands near -1.1 (clipped to -0.88) in one 50 ms
step while the plan itself only reaches -0.4 to -0.6 over the next second.
6914de87 passed every falling request at or below -0.5 through on the same
step, so DAS_control went from +1.36 to -0.92 in one frame and the DI swung
motor torque from +106 to -73 Nm in about 0.3 s.

Falling requests now follow the stock DI's shape after a cruise cancel:
drive torque is released quickly (AP1_FALL_JERK while the last output is
above 0) and regen ramps in (AP1_BRAKE_ONSET_JERK once at or below 0). The
regen ramp jerk grows with the depth of the request, from
AP1_BRAKE_ONSET_JERK at AP1_BRAKE_URGENT_ACCEL to the full 8 m/s^3 at
AP1_BRAKE_HARD_ACCEL, and a request at or below AP1_BRAKE_HARD_ACCEL, an FCW,
or the LongControl stopping state passes through on the same step (urgent).
Time to reach a falling request from 0: -0.9 in 0.45 s, -1.0 in 0.50 s,
-1.5 in 0.30 s, -1.95 in 0.26 s, -2.0 or below at once; from +1.5 add about
0.3 s for the drive release (worst case -1.0 from +1.5 in 0.80 s). ACCEL_MIN, the planner and panda safety are unchanged.

The jerk fields follow the ramped request (not the raw planner value), so
they widen as the request deepens rather than snapping to 8 at the planner
step; urgent frames send the full 8 immediately.
"""

from cereal import car
from openpilot.common.realtime import DT_CTRL

_FCW = car.CarControl.HUDControl.VisualAlert.fcw
_STOPPING = car.CarControl.Actuators.LongControlState.stopping

# m/s^3. Above the planner's p99 on 02a, so normal plans pass unchanged.
AP1_RISE_JERK = 2.5
AP1_FALL_JERK = 5.0
# m/s^2. Jerk fields are the full 8 at or below this request (blend end).
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

# Regen onset ramp (m/s^3). Deepening a request at or below 0 m/s^2. ISO 15622
# ACC comfort guidance is 2.5 m/s^3 above 20 m/s; the stock DI's own lift-off
# regen ramp after a cruise cancel on 0000002e averaged about 0.6 m/s^3
# (peaks 1.0-2.6). 2.0 sits between the two.
AP1_BRAKE_ONSET_JERK = 2.0
# m/s^2. The regen ramp jerk blends from AP1_BRAKE_ONSET_JERK at this request
# to AP1_FULL_JERK_LIMIT at AP1_BRAKE_HARD_ACCEL.
AP1_BRAKE_URGENT_ACCEL = -1.0
# m/s^2. A falling request at or below this passes through on the same step.
AP1_BRAKE_HARD_ACCEL = -2.0


def ap1_brake_urgent(CC):
  """FCW on the HUD, or LongControl in its stopping state (it ramps itself)."""
  return bool(CC.hudControl.visualAlert == _FCW or CC.actuators.longControlState == _STOPPING)


def ap1_brake_ramp_jerk(target):
  """Regen ramp jerk (m/s^3) for a falling request at or below 0."""
  target = float(target)
  if target >= AP1_BRAKE_URGENT_ACCEL:
    return AP1_BRAKE_ONSET_JERK
  if target <= AP1_BRAKE_HARD_ACCEL:
    return AP1_FULL_JERK_LIMIT
  frac = (AP1_BRAKE_URGENT_ACCEL - target) / (AP1_BRAKE_URGENT_ACCEL - AP1_BRAKE_HARD_ACCEL)
  return AP1_BRAKE_ONSET_JERK + frac * (AP1_FULL_JERK_LIMIT - AP1_BRAKE_ONSET_JERK)


class Ap1AccelSmoother:
  def __init__(self, rise_jerk=AP1_RISE_JERK, fall_jerk=AP1_FALL_JERK,
               hard_brake=AP1_BRAKE_HARD_ACCEL, min_speed=AP1_SLEW_MIN_SPEED):
    self.rise_jerk = rise_jerk
    self.fall_jerk = fall_jerk
    self.hard_brake = hard_brake
    self.min_speed = min_speed
    self.last = None

  def reset(self):
    self.last = None

  def update(self, target, active, v_ego, gas_neutral=False, urgent=False, dt=DT_CTRL):
    """urgent: FCW or LongControl stopping. A falling request passes through."""
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
    elif urgent or target <= self.hard_brake:
      out = target
    else:
      jerk = ap1_brake_ramp_jerk(target)
      if self.last > 0.0:
        # Releasing drive torque: at least the comfort fall rate.
        jerk = max(self.fall_jerk, jerk)
      out = max(target, self.last - jerk * dt)
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

  def update(self, accel, active, v_ego, gas_neutral=False, urgent=False, dt=DT_CTRL):
    """Returns (jerk_min, jerk_max) for DAS_control. accel is the request as sent."""
    if gas_neutral or urgent or not active or v_ego < AP1_SLEW_MIN_SPEED:
      target = AP1_FULL_JERK_LIMIT
    else:
      target = ap1_jerk_limit_target(accel)
    if target >= self.last:
      self.last = target
    else:
      self.last = max(target, self.last - AP1_JERK_LIMIT_NARROW_RATE * dt)
    return -self.last, self.last
