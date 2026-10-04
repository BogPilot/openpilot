"""Temporary steer-fault gate. No CAN, no parser.

AP1 only treats EAC_ERROR_HIGH_ANGLE_REQ (DBC value 6) as not a temporary
fault. The 2026-10-04 drive at 74432fbe had that code on every chassis
0x370 frame, including before engage and with hands-on level 0, while
EPAS_eacStatus stayed EAC_AVAILABLE and EPAS_steeringFault stayed NO_FAULT.
latActive is false while steerFaultTemporary is true, so no 0x488 was sent.

Other error codes still fault. Model 3/Y does not take the AP1 set.
EAC_FAULT is steerFaultPermanent and is not decided here.
"""

_BENIGN = ("EAC_ERROR_IDLE", "EAC_ERROR_HANDS_ON")
# DBC VAL_ 880 EPAS_eacErrorCode 6 "EAC_ERROR_HIGH_ANGLE_REQ"
_AP1_BENIGN = _BENIGN + ("EAC_ERROR_HIGH_ANGLE_REQ",)


def steer_fault_temporary(steer_warning, ap1):
  """True when this error name should set CarState.steerFaultTemporary.

  On AP1, code 6 is benign regardless of EPAS_eacStatus. Requiring
  EAC_AVAILABLE would fault again as soon as EPAS goes EAC_ACTIVE, which
  is the status we expect once an angle is actually accepted. The stuck
  code was already present before any openpilot 0x488.
  """
  benign = _AP1_BENIGN if ap1 else _BENIGN
  return steer_warning not in benign
