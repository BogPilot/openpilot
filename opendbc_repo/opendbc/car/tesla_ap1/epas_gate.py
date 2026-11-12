"""EPAS refusal gate for the legacy Teslas. No CAN.

When the EPAS is INHIBITED, FAULT or SNA, or reports an error other than the
two codes that stay latched after a normal hand-back, it is not following
angle commands. Sending ANGLE anyway (or holding the last target) does not move
the wheel and, with the EPB watching, ended in a permanent "LKAS Fault".
This gate says so on the first frame it sees it, and the controller stops
commanding at once: type NONE at the measured wheel, never the old target.

Not blocking: EAC_AVAILABLE and EAC_ACTIVE with error IDLE, HANDS_ON (3) or
HIGH_ANGLE_REQ (6). Those two are latched by the EPAS after a hands-on or a
large request and clear once openpilot commands ANGLE at the measured wheel
(hso / actuator_plan hold). Every other error blocks, including
HIGH_ANGLE_RATE_SAFETY (9).

Recovery needs EPAS_CLEAN_FRAMES in a row of a clean state (about 7 EPAS
samples at 25 Hz) while the lateral session is still on. A lateral session
that ended starts clean: the gate does not carry a block across it, it
re-reads the EPAS on the next engagement. `resumed` is true for the one step the block
ends so the controller can restart the measured-angle soft-start.

Pre-AP has no AP ECU and its EPAS status flaps outside an engaged session, so
it builds the gate with arm_on_active: nothing blocks until the EPAS has
reported EAC_ACTIVE in this lateral session.
"""
from opendbc.car.tesla_ap1.override import SIGNAL_EPAS, SIGNAL_NONE

EAC_ACTIVE = "EAC_ACTIVE"
EAC_BLOCKING_STATUS = ("EAC_INHIBITED", "EAC_FAULT", "EAC_SNA")
EAC_OK_ERRORS = ("EAC_ERROR_IDLE", "EAC_ERROR_HANDS_ON", "EAC_ERROR_HIGH_ANGLE_REQ")

EPAS_CLEAN_FRAMES = 30   # 0.3 s at 100 Hz


def epas_not_ready(eac_status, steer_warning, eac_fault=False):
  """True when this EPAS state must not be commanded. None (no frame decoded yet) is not ready."""
  if eac_fault or eac_status is None or steer_warning is None:
    return True
  return eac_status in EAC_BLOCKING_STATUS or steer_warning not in EAC_OK_ERRORS


class EpasGate:
  def __init__(self, arm_on_active=False):
    self.arm_on_active = arm_on_active
    self.reset()

  def reset(self):
    self.blocked = False
    self.resumed = False
    self.clean_frames = 0
    self.armed = not self.arm_on_active

  @property
  def signal(self):
    return SIGNAL_EPAS if self.blocked else SIGNAL_NONE

  def update(self, lat_session, eac_status, steer_warning, eac_fault=False, refusing=False):
    """One call per control step. Returns True while commands must stay off.

    refusing: the panda is rejecting ANGLE (hands at level 3, or INHIBITED with error 6..9). That arms the gate even before the EPAS
    has been ACTIVE, so a refusal at the start of a session is waited out with the same clean frames as any other.
    """
    self.resumed = False
    if not lat_session:
      self.reset()
      return False
    if eac_status == EAC_ACTIVE or refusing:
      self.armed = True
    if self.armed and epas_not_ready(eac_status, steer_warning, eac_fault):
      self.blocked = True
      self.clean_frames = 0
    elif self.blocked:
      self.clean_frames += 1
      if self.clean_frames >= EPAS_CLEAN_FRAMES:
        self.blocked = False
        self.clean_frames = 0
        self.resumed = True
    return self.blocked
