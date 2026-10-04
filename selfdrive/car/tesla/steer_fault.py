"""Temporary steer-fault gate. No CAN, no parser.

Tinkla carstate.py (501c7de) sets steerWarning unless the EPAS error name
is EAC_ERROR_IDLE. An unknown name is a warning. HANDS_ON (3) is a warning.
EAC_FAULT is steerFaultPermanent and is not decided here.

AP1 does not treat EAC_ERROR_HIGH_ANGLE_REQ (6) as a temporary fault. That
code stays latched until EPAS accepts an angle command, so warning on it
keeps lat_active false and the command never goes out. Every other non-idle
name still warns, matching Tinkla.

Model 3/Y keeps the BogPilot set from before the AP1 code-6 exception:
IDLE and HANDS_ON are not a temporary fault, and code 6 is.
"""

_BENIGN = ("EAC_ERROR_IDLE", "EAC_ERROR_HANDS_ON")
# AP1: idle, and code 6 so a real angle can be sent. Not HANDS_ON.
_AP1_NOT_WARNING = ("EAC_ERROR_IDLE", "EAC_ERROR_HIGH_ANGLE_REQ")


def steer_fault_temporary(steer_warning, ap1):
  """True when this error name should set CarState.steerFaultTemporary."""
  allowed = _AP1_NOT_WARNING if ap1 else _BENIGN
  return steer_warning not in allowed
