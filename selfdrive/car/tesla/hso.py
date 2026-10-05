"""AP1 hands-on pause. No CAN.

Tinkla (501c7de) HSO, default TinklaHso True and TinklaHandsOnLevel 2.0:
EPAS_handsOnLevel >= 2 pauses path lateral (CarController sends type NONE)
and cruise is not dropped. steerTempUnavailableSilent is warning-only. It is
not no-entry and not a soft disable.

carState.steeringPressed is a separate, lower threshold: any non-zero
EPAS_handsOnLevel (AP1_DRIVER_INPUT_LEVEL). That is the stock Tesla port and
frog_ap1 mapping. It raises steerOverride, controlsd goes to the overriding
state, and the prebuilt UI draws the grey border. Logged AP1 EPAS reports
levels 0, 1 and 3 only (never 2), so a >= 2 steeringPressed only fired on the
brief level 3 peaks and the border stayed green while the driver steered.

The 50-frame numb period and the 15 degree handoff in HSO_module.py are
not applied. Resume is the next step after hands_on_level drops below 2,
if cruise is still enabled and EPAS is not EAC_FAULT. Code 6 and a latched
code 3 do not block that resume. Any other non-idle name stays a steer warning.
"""

# selfdrive/car/tesla/carstate.py: load_float_param("TinklaHandsOnLevel", 2.0)
AP1_HANDS_ON_LEVEL = 2
# carState.steeringPressed (override / grey border). Stock Tesla port and
# frog_ap1: hands_on_level > 0.
AP1_DRIVER_INPUT_LEVEL = 1

_HARSH = "steerTempUnavailable"
_SILENT = "steerTempUnavailableSilent"


def ap1_steering_pressed(hands_on_level):
  """True at the Tinkla HSO threshold (lateral pause). Level 1 does not pause."""
  return hands_on_level >= AP1_HANDS_ON_LEVEL


def ap1_driver_input(hands_on_level):
  """carState.steeringPressed on AP1: any driver torque EPAS reports.

  Display / override only. It does not by itself pause lateral; the pause is
  ap1_steering_pressed (>= 2) in CarController.
  """
  return hands_on_level >= AP1_DRIVER_INPUT_LEVEL


def ap1_lat_active(lat_active, hands_on_level):
  """Path lateral is off while hands are at or above the HSO threshold.

  This is the AP1 pause gate. controlsd keeps latActive through a level 1
  override (steeringPressed), like the stock Tesla port, so the planned angle
  is withheld here instead.
  """
  if ap1_steering_pressed(hands_on_level):
    return False
  return bool(lat_active)


def ap1_hso_event_names(names):
  """Replace the soft-disable steer event with the silent warning.

  steerUnavailable (EAC_FAULT) is left alone. That one still disables.
  Duplicate silent names are dropped.
  """
  out = []
  for name in names:
    if name == _HARSH:
      name = _SILENT
    if name not in out:
      out.append(name)
  return out
