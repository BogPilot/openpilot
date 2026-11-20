"""Steering wheel rate for the Tesla AP1 / Pre-AP car states, with an SNA guard (PREAP_STW_RATE_SNA_20261120).

carState.steeringRateDeg comes from STW_ANGLHP_STAT (0x00E, bus 0, 100 Hz, sent by the steering-column angle sensor, not by the
EPAS). StW_AnglHP_Spd is 14 bit, scale 0.5, offset -4096; raw 16383 is "SNA" (tesla_ap1_can.dbc VAL_ 14) and decodes to
+4095.5 deg/s. Some cars send it SNA all the time while the angle in the same frame (StW_AnglHP, 0.1 deg) stays valid: in the
Pre-AP tester logs the sensor that reports StW_AnglHP_Sens_Id KOSTAL does this, the one reporting DELPHI sends a real rate.

Read as a real rate, SNA made DriverOverrideDetector (override.py) fire RATE at ~1 Nm and ANGLE_ERROR at 4 deg of tracking
error, and its `quiet` flag could never be true, so Ap1DriverYield never resumed until the next disengage.

Sources, in order:
  SENSOR      StW_AnglHP_Spd when it is finite and not SNA (unchanged behaviour on cars that send it).
  ANGLE_DIFF  a first-order low-pass of the StW_AnglHP difference, one step per new frame (message counter), when only the
              rate is SNA. Fit on a car that sends both: alpha 0.2 tracks the sensor rate to 0.8 deg/s RMS with a still-wheel
              peak of 7.5 deg/s, below every override rate threshold (20 / 25-35 deg/s).
  NONE        0.0 when the angle is SNA too. RATE and ANGLE_ERROR then cannot fire; HANDS and TORQUE still do.
"""
import math

from opendbc.car import DT_CTRL

STW_RATE_SNA_DPS = 4095.0     # |decoded StW_AnglHP_Spd| at or above this is SNA (raw 16383 -> 4095.5)
STW_ANGLE_SNA_DEG = 819.0     # |decoded StW_AnglHP| at or above this is SNA (raw 16383 -> 819.1)
RATE_FALLBACK_ALPHA = 0.2     # low-pass on the per-frame angle difference (see the module docstring)
COUNTER_MOD = 16              # MC_STW_ANGLHP_STAT

SOURCE_SENSOR = 0
SOURCE_ANGLE_DIFF = 1
SOURCE_NONE = 2


def _finite(x):
  try:
    return math.isfinite(float(x))
  except (TypeError, ValueError):
    return False


class SteerRateFallback:
  def __init__(self, dt=DT_CTRL):
    self.dt = float(dt)
    self.reset()

  def reset(self):
    self.prev_angle = None
    self.prev_counter = None
    self.rate = 0.0
    self.source = SOURCE_SENSOR

  @property
  def sna(self):
    return self.source != SOURCE_SENSOR

  def update(self, rate_dps, angle_deg, counter=None):
    """rate_dps, angle_deg: StW_AnglHP_Spd / StW_AnglHP already in the car-state sign. counter: MC_STW_ANGLHP_STAT, or None to
    treat every call as a new frame. Returns the rate to publish as carState.steeringRateDeg."""
    angle_ok = _finite(angle_deg) and abs(float(angle_deg)) < STW_ANGLE_SNA_DEG
    rate_ok = _finite(rate_dps) and abs(float(rate_dps)) < STW_RATE_SNA_DPS
    if not angle_ok:
      self.prev_angle = None
      self.prev_counter = None
      self.rate = float(rate_dps) if rate_ok else 0.0
      self.source = SOURCE_SENSOR if rate_ok else SOURCE_NONE
      return self.rate

    angle = float(angle_deg)
    steps = 1
    if counter is not None and self.prev_counter is not None:
      steps = (int(counter) - int(self.prev_counter)) % COUNTER_MOD
    new_frame = steps != 0 or counter is None or self.prev_counter is None

    if rate_ok:
      self.rate = float(rate_dps)    # the filter restarts from the last real rate if SNA begins later
      self.source = SOURCE_SENSOR
    elif new_frame:
      if self.prev_angle is not None:
        diff = (angle - self.prev_angle) / (max(steps, 1) * self.dt)
        self.rate += RATE_FALLBACK_ALPHA * (diff - self.rate)
      self.source = SOURCE_ANGLE_DIFF
    else:
      self.source = SOURCE_ANGLE_DIFF   # same frame again: hold the rate

    if new_frame:
      self.prev_angle = angle
      if counter is not None:
        self.prev_counter = int(counter)
    return self.rate
