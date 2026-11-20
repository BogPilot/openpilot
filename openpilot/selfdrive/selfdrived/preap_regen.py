"""Pre-AP regen-limit alert: alert only, no change to the plan or the actuation.

A Pre-AP car brakes by regen only (the Comma Pedal lifts to the drive inverter's minimum), and the pedal command is clipped at
REGEN_MAX (opendbc tesla_ap1/preap/vdas_constants.py). The planner still plans with the stock decel range, so when it asks for
more decel than regen gives, the car silently delivers less. This tells the driver to brake.

t1385 (Bardo): one fixed, conservative threshold at every speed: planner aTarget below -ALERT_DECEL (1.2 m/s^2) for more than
HOLD_S (0.3 s) while openpilot longitudinal is active. Tester 1's drive measured regen at about 1.6-1.8 m/s^2, so 1.2 warns
before the shortfall starts. Once raised it stays up for at least MIN_SHOW_S so it never flickers; a brake press, longitudinal
going inactive, or another platform clear it at once. No speed-based threshold in this build. Warning only (events.py: red
border + repeating prompt; no NO_ENTRY / disable).
"""
import math

from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.preap_arm import is_preap

try:
  from opendbc.car.tesla_ap1.preap.vdas_constants import REGEN_MAX   # pedal clip, unchanged; not the alert threshold
except ImportError:  # opendbc without the Pre-AP port
  REGEN_MAX = -1.5

ALERT_DECEL = 1.2   # m/s^2, fixed at every speed
HOLD_S = 0.3
MIN_SHOW_S = 1.0
HOLD_FRAMES = int(round(HOLD_S / DT_CTRL))
MIN_SHOW_FRAMES = int(round(MIN_SHOW_S / DT_CTRL))


class PreapRegenWatch:
  def __init__(self, CP, threshold: float | None = None):
    self.enabled = is_preap(CP) and bool(getattr(CP, "openpilotLongitudinalControl", False))
    self.threshold = -abs(float(ALERT_DECEL if threshold is None else threshold))
    self.frames = 0
    self.show = 0

  def update(self, long_active: bool, a_target: float, brake_pressed: bool = False) -> bool:
    """One selfdrived frame (100 Hz). True while the alert should show."""
    if not self.enabled or not long_active or brake_pressed:
      self.frames = self.show = 0
      return False
    a = float(a_target) if a_target is not None else math.nan
    if math.isfinite(a) and a < self.threshold:   # NaN / inf: no trigger, the count restarts
      self.frames += 1
    else:
      self.frames = 0
    if self.frames > HOLD_FRAMES:
      self.show = MIN_SHOW_FRAMES
    elif self.show > 0:
      self.show -= 1
    return self.show > 0
