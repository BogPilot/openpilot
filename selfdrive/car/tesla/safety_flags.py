"""Tesla panda safety-param values. No CarParams and no actuation.

TESLA_FLAG_AP1 is bit 3, value 8 (Panda.FLAG_TESLA_AP1). Only CAR.TESLA_AP1_MODELS
gets that bit. dashcam_only_for_candidate is false only for that candidate.
This module does not enable openpilot longitudinal control and does not read 0x2bf
for the dashcam decision.
"""

from panda import Panda

from openpilot.selfdrive.car.tesla.values import CANBUS, CAR

# Same bit as panda/board/safety/safety_tesla.h TESLA_FLAG_AP1.
FLAG_TESLA_AP1 = Panda.FLAG_TESLA_AP1


def _has_powertrain_das(fingerprint):
  """True when 0x2bf (DAS_control) is on the auxiliary powertrain panda bus.

  Same membership test the Tesla interface used before the AP1 flag. Chassis
  0x2bf does not count. AP1 is not expected to have this bus.
  """
  bus = CANBUS.autopilot_powertrain
  return (bus in fingerprint.keys()) and (0x2bf in fingerprint[bus].keys())


def flags_for_candidate(candidate, fingerprint):
  """Safety params for the Tesla safety model.

  Identical to the previous interface flags, plus bit 8 when the candidate is
  CAR.TESLA_AP1_MODELS. Raven keeps bit 2 (value 4) and does not get bit 8.
  AP2 gets neither. A 0x2bf powertrain fingerprint still adds longitudinal
  control and a second config with the powertrain bit. That second config
  also gets bit 8 only for the AP1 Model S candidate.
  """
  if FLAG_TESLA_AP1 != 8:
    raise RuntimeError("TESLA_FLAG_AP1 must be 8")

  flags = Panda.FLAG_TESLA_RAVEN if candidate == CAR.TESLA_MODELS_RAVEN else 0
  if candidate == CAR.TESLA_AP1_MODELS:
    flags |= FLAG_TESLA_AP1

  if _has_powertrain_das(fingerprint):
    flags |= Panda.FLAG_TESLA_LONG_CONTROL
    return (flags, flags | Panda.FLAG_TESLA_POWERTRAIN)
  return (flags,)


def dashcam_only_for_candidate(candidate):
  """True unless the candidate is CAR.TESLA_AP1_MODELS.

  AP1 is an explicit user exception for the Mobileye chassis port, not a
  Model 3 change. AP2, Raven, and every other candidate stay dashcam-only.
  This does not enable openpilotLongitudinalControl and does not require 0x2bf.
  """
  return candidate != CAR.TESLA_AP1_MODELS
