"""BogPilot: card's frogpilotCarState publisher (367e1fe frogpilot_card.py / card.py state_publish).

0.11.2 carries the FrogPilot car-state fields on carState.bogpilot (opendbc BogPilotCarState). The
onroad UI and the BogPilot planner read them from frogpilotCarState as 367e1fe did, so card mirrors the
shared fields here. isParked is gearShifter == park (frogpilot_card.py:281). AP1-only extras
(@21 and up in BogPilotCarState) stay on carState.bogpilot.
"""
from __future__ import annotations

from openpilot.cereal import custom, messaging

# field names shared by custom.FrogPilotCarState and car.CarState.BogPilotCarState
MIRRORED_FIELDS = (
  "accelPressed", "alwaysOnLateralAllowed", "alwaysOnLateralEnabled", "brakeLights", "dashboardSpeedLimit",
  "decelPressed", "distancePressed", "distanceLongPressed", "distanceVeryLongPressed", "ecoGear", "forceCoast",
  "pauseLateral", "pauseLongitudinal", "sportGear", "trafficModeEnabled", "resumePressed", "spdCtrlLvr",
  "ap1AmbientTempC", "ap1MotorTorqueNm", "ap1MotorRpm",
)


def frogpilot_car_state(CS):
  fpcs = custom.FrogPilotCarState.new_message()
  bp = CS.bogpilot
  for name in MIRRORED_FIELDS:
    setattr(fpcs, name, getattr(bp, name))
  fpcs.isParked = str(CS.gearShifter) == "park" or bool(bp.isParked)
  return fpcs


def frogpilot_car_state_msg(CS):
  msg = messaging.new_message("frogpilotCarState")
  msg.valid = CS.canValid
  msg.frogpilotCarState = frogpilot_car_state(CS)
  return msg
