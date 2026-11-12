"""Pre-AP brake press: drop longitudinal, keep steering.

Stock selfdrived disengages on any brake press (`pedalPressed`) and raises `controlsMismatch` when the panda has dropped controls_allowed
for more than 2 s while openpilot is enabled. On a Pre-AP Model S there is no brake control, so a brake press should cut only the pedal.
The car side (opendbc tesla_ap1/preap/engagement.py) reports that state as carState.bogpilot.preapLatOnly: openpilot engaged, longitudinal
dropped, set in the same car-state step that saw the press. The panda (tesla_preap.h) keeps steering on its own pull-armed permission and
blocks the pedal while the brake is pressed. Every other way the panda drops the steering permission (hands on, EPAS refusing, cancel, gear,
door, stale stream) clears preapLatOnly or disengages on that same step, so the exemptions here end with it. A gas press is not one of them
(the panda used to drop the latch on a gas edge while openpilot stayed engaged; now neither side reacts to gas). For every car but Pre-AP the flag is
always False and both helpers reduce to the stock rules.
"""


def brake_keeps_lateral(CS) -> bool:
  return bool(CS.bogpilot.preapLatOnly)


def brake_disengages(CS, CS_prev) -> bool:
  """Stock rule: a brake press disengages on its rising edge, and while moving. Not when the Pre-AP car side says the press only drops longitudinal."""
  return bool(CS.brakePressed and not brake_keeps_lateral(CS) and (not CS_prev.brakePressed or not CS.standstill))


def panda_controls_dropped_on_purpose(CS) -> bool:
  """True while openpilot is lateral-only after a Pre-AP brake press: controls_allowed is false in the panda by design, not a mismatch."""
  return brake_keeps_lateral(CS)
