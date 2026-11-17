"""Pre-AP regen-limit alert: alert only, no change to the plan or the actuation.

A Pre-AP car brakes by regen only (the Comma Pedal lifts to the drive inverter's minimum), and the pedal command is clipped at
REGEN_MAX (opendbc tesla_ap1/preap/vdas_constants.py). The planner still plans with the stock decel range, so when it asks for
more decel than the floor the car silently delivers less. This tells the driver to brake while that lasts: planner aTarget below
the floor + MARGIN for more than HOLD_S while longitudinal is active (the NAP preap_regen pattern, selfdrived/preap_regen.py @
naponsp 92b42f772). UNPROVEN: -1.5 m/s^2 is a commanded floor copied from NAP, not a measured regen capability (it is likely
lower at highway speed), so the alert may come late; tests also cover a -0.9 floor.
"""
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.preap_arm import is_preap

try:
  from opendbc.car.tesla_ap1.preap.vdas_constants import REGEN_MAX
except ImportError:  # opendbc without the Pre-AP port
  REGEN_MAX = -1.5

MARGIN = 0.2   # m/s^2
HOLD_S = 0.3
HOLD_FRAMES = int(round(HOLD_S / DT_CTRL))


class PreapRegenWatch:
  def __init__(self, CP, floor: float | None = None):
    self.enabled = is_preap(CP) and bool(getattr(CP, "openpilotLongitudinalControl", False))
    self.floor = float(REGEN_MAX if floor is None else floor)
    self.frames = 0

  def update(self, long_active: bool, a_target: float) -> bool:
    """One selfdrived frame (100 Hz). True while the alert should show."""
    if not self.enabled or not long_active or not (a_target < self.floor + MARGIN):   # NaN: no alert, count restarts
      self.frames = 0
      return False
    self.frames += 1
    return self.frames > HOLD_FRAMES
