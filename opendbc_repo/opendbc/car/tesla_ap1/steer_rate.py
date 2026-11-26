"""Steering wheel rate for the Tesla AP1 / Pre-AP car states, with an SNA guard (PREAP_STW_RATE_SNA_20261120).

carState.steeringRateDeg comes from STW_ANGLHP_STAT (0x00E, bus 0, 100 Hz, sent by the steering-column angle sensor, not by the
EPAS). StW_AnglHP_Spd is 14 bit, scale 0.5, offset -4096; raw 16383 is "SNA" (tesla_ap1_can.dbc VAL_ 14) and decodes to
+4095.5 deg/s. Some cars send it SNA all the time while the angle in the same frame (StW_AnglHP, 0.1 deg) stays valid: in the
Pre-AP drive logs the sensor that reports StW_AnglHP_Sens_Id KOSTAL does this, the one reporting DELPHI sends a real rate.

Read as a real rate, SNA made DriverOverrideDetector (override.py) fire RATE at ~1 Nm and ANGLE_ERROR at 4 deg of tracking
error, and its `quiet` flag could never be true, so Ap1DriverYield never resumed until the next disengage.

Sources, in order:
  SENSOR      StW_AnglHP_Spd when it is finite and not SNA (unchanged behaviour on cars that send it).
  ANGLE_DIFF  a first-order low-pass of the StW_AnglHP difference, one step per new frame (message counter), when only the
              rate is SNA. Fit on a car that sends both: alpha 0.2 tracks the sensor rate to 0.8 deg/s RMS with a still-wheel
              peak of 7.5 deg/s, below every override rate threshold (20 / 25-35 deg/s).
  NONE        0.0 when the angle is SNA too (the EPAS angle below when the caller passes it). RATE and ANGLE_ERROR then cannot fire; HANDS and TORQUE still do.

Column sensor status (PREAP_COLUMN_SENS_STAT_20261120). StW_AnglHP_Sens_Stat (0x00E 33|2: 0 OK, 1 INI, 2 ERR, 3 SNA) is the
sensor's own verdict on that frame. When it is not OK, neither StW_AnglHP nor StW_AnglHP_Spd is used:
  EPAS_ANGLE  a first-order low-pass of the EPAS_internalSAS difference (0x370, 25 Hz, one step per new frame by
              EPAS_sysStatusCounter, alpha 0.5). That is the EPAS's own sensor, the angle carState.steeringAngleDeg and the
              controller already use, so it does not share a failure with the column module. Fit on one Pre-AP car's logs
              (the other car's column sends no rate) against the valid column rate: 1.9 deg/s RMS, p99 error 7.5 deg/s
              (alpha 0.2 lags: 6.8 RMS; alpha 1.0 is noisier: 2.6).
              The filter runs on every update so it is warm when the column drops out.
  NONE        0.0 when the EPAS angle is SNA or stale too (or the caller passes no EPAS angle).
Not the low-resolution 0x003 (STW_ANGL_STAT): it comes from the same column module and carries the same status bits. Not a steer
fault: the column angle only feeds this rate (the override detector's RATE / ANGLE_ERROR); steering control and the panda use
the EPAS angle, so a column fault takes nothing away from lateral control. Both logged cars report OK on every frame, so nothing
changes for them.
"""
import math

from opendbc.car import DT_CTRL

STW_RATE_SNA_DPS = 4095.0     # |decoded StW_AnglHP_Spd| at or above this is SNA (raw 16383 -> 4095.5)
STW_ANGLE_SNA_DEG = 819.0     # |decoded StW_AnglHP| at or above this is SNA (raw 16383 -> 819.1)
RATE_FALLBACK_ALPHA = 0.2     # low-pass on the per-frame angle difference (see the module docstring)
COUNTER_MOD = 16              # MC_STW_ANGLHP_STAT and EPAS_sysStatusCounter
SENS_STAT_OK = 0              # StW_AnglHP_Sens_Stat: 0 OK, 1 INI, 2 ERR, 3 SNA (tesla_ap1_can.dbc VAL_ 14)
EPAS_ANGLE_SNA_DEG = 819.0    # |decoded EPAS_internalSAS| at or above this is SNA (raw 16383 -> 819.1)
EPAS_DT = 0.04                # EPAS_sysStatus period (25 Hz)
EPAS_RATE_ALPHA = 0.5         # low-pass on the per-frame EPAS angle difference (see the module docstring)
EPAS_STALE_S = 0.3            # no new EPAS frame for this long: the filter restarts (the 4-bit counter cannot measure the gap)

SOURCE_SENSOR = 0
SOURCE_ANGLE_DIFF = 1
SOURCE_NONE = 2
SOURCE_EPAS_ANGLE = 3


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
    self.column_ok = True
    self._epas_reset()

  def _epas_reset(self):
    self.epas_prev_angle = None
    self.epas_prev_counter = None
    self.epas_age = 0.0
    self.epas_rate = 0.0
    self.epas_valid = False

  def _epas_update(self, epas_angle, epas_counter):
    """Track the EPAS-angle rate on every call. Returns True while it is usable."""
    self.epas_age += self.dt
    if not (_finite(epas_angle) and abs(float(epas_angle)) < EPAS_ANGLE_SNA_DEG):
      self._epas_reset()
      return False
    angle = float(epas_angle)
    if self.epas_prev_angle is None:
      new_frame, steps = True, 0
    elif epas_counter is None or self.epas_prev_counter is None:
      new_frame, steps = angle != self.epas_prev_angle or self.epas_age >= EPAS_DT - 1e-6, 1
    else:
      steps = (int(epas_counter) - int(self.epas_prev_counter)) % COUNTER_MOD
      new_frame = steps != 0
    if new_frame:
      if self.epas_prev_angle is not None and self.epas_age <= EPAS_STALE_S + 1e-6 and steps > 0:
        diff = (angle - self.epas_prev_angle) / (steps * EPAS_DT)
        self.epas_rate += EPAS_RATE_ALPHA * (diff - self.epas_rate)
        self.epas_valid = True
      elif self.epas_prev_angle is not None:
        self.epas_rate = 0.0                     # gap the counter cannot measure: restart from this frame
        self.epas_valid = False
      self.epas_prev_angle = angle
      self.epas_prev_counter = None if epas_counter is None else int(epas_counter)
      self.epas_age = 0.0
    elif self.epas_age > EPAS_STALE_S:
      self.epas_valid = False                    # the EPAS frame stopped updating
    return self.epas_valid

  @property
  def sna(self):
    return self.source != SOURCE_SENSOR

  def update(self, rate_dps, angle_deg, counter=None, sens_stat=None, epas_angle=None, epas_counter=None):
    """rate_dps, angle_deg: StW_AnglHP_Spd / StW_AnglHP already in the car-state sign. counter: MC_STW_ANGLHP_STAT, or None to
    treat every call as a new frame. sens_stat: StW_AnglHP_Sens_Stat (None: not checked). epas_angle / epas_counter:
    EPAS_internalSAS in the car-state sign and EPAS_sysStatusCounter, the fallback when the column is not OK.
    Returns the rate to publish as carState.steeringRateDeg."""
    epas_ok = self._epas_update(epas_angle, epas_counter) if epas_angle is not None else False
    stat_ok = sens_stat is None or (_finite(sens_stat) and int(sens_stat) == SENS_STAT_OK)
    self.column_ok = stat_ok
    if not stat_ok:
      # Neither the column angle nor its rate is trusted; the angle-difference filter restarts when the column comes back.
      self.prev_angle = None
      self.prev_counter = None
      if epas_ok:
        self.rate = self.epas_rate
        self.source = SOURCE_EPAS_ANGLE
      else:
        self.rate = 0.0
        self.source = SOURCE_NONE
      return self.rate

    angle_ok = _finite(angle_deg) and abs(float(angle_deg)) < STW_ANGLE_SNA_DEG
    rate_ok = _finite(rate_dps) and abs(float(rate_dps)) < STW_RATE_SNA_DPS
    if not angle_ok:
      self.prev_angle = None
      self.prev_counter = None
      if rate_ok:
        self.rate, self.source = float(rate_dps), SOURCE_SENSOR
      elif epas_ok:
        self.rate, self.source = self.epas_rate, SOURCE_EPAS_ANGLE   # nothing from the column: the EPAS angle, as for a bad status
      else:
        self.rate, self.source = 0.0, SOURCE_NONE
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
