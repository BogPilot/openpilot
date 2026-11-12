"""Pre-AP: tell the driver quickly when openpilot is enabled but the panda is not armed.

The panda's controls_allowed comes from the Pre-AP stalk pull (tesla_preap.h). When openpilot enables and the panda never armed (for
example the pull was seen by the car but not by the panda), every steering frame is blocked and the stock path used to take 2 s of
"controlsMismatch" before saying anything, with a message that means nothing to a driver. This raises preapNotArmed ("Cruise didn't arm /
Pull the stalk again") after 0.3 s instead. Pre-AP cars only; every other car keeps the generic 2 s controlsMismatch.

`dropped_on_purpose` is for a panda that is deliberately not armed while openpilot stays engaged (the steer-through-brake latch): it
restarts the count, so that case never raises this.
"""
from openpilot.common.realtime import DT_CTRL

PREAP = "TESLA_PREAP_MODELS"
NOT_ARMED_SECONDS = 0.3
NOT_ARMED_FRAMES = int(round(NOT_ARMED_SECONDS / DT_CTRL))


def is_preap(CP) -> bool:
  return str(getattr(CP, "carFingerprint", "")) == PREAP


class PreapArmWatch:
  def __init__(self, CP):
    self.preap = is_preap(CP)
    self.count = 0

  def update(self, enabled: bool, panda_states, ignored_safety_modes=(), dropped_on_purpose: bool = False) -> bool:
    """Call once per selfdrived frame. True while openpilot has been enabled with no armed panda for NOT_ARMED_SECONDS."""
    if not self.preap or not enabled or dropped_on_purpose:
      self.count = 0
      return False
    not_armed = any(not ps.controlsAllowed for ps in panda_states if ps.safetyModel not in ignored_safety_modes)
    self.count = self.count + 1 if not_armed else 0
    return self.count >= NOT_ARMED_FRAMES
