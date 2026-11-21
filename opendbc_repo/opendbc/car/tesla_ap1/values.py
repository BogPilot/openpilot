"""Tesla Autopilot 1 (HW1, Mobileye) Model S and Model X.

Legacy chassis-bus port (BogPilot). Separate brand from opendbc.car.tesla so
the Model 3/Y port stays untouched. Panda safety: SafetyModel.tesla with the AP1 flag.
Model X is lateral-only. AP2 is not a platform in this tree.
"""
from collections import namedtuple
from dataclasses import dataclass, field
from enum import IntFlag, StrEnum

from opendbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms
from opendbc.car.docs_definitions import CarDocs, SupportType
from opendbc.car.fw_query_definitions import FwQueryConfig
from opendbc.car.structs import CarParams, CarState
from opendbc.car.tesla.values import TeslaSafetyFlags

Ecu = CarParams.Ecu
ButtonType = CarState.ButtonEvent.Type

Button = namedtuple('Button', ['event_type', 'can_addr', 'can_msg', 'values'])

# 0.9.7 style angle rate limit table: (speed_bp, angle_v), deg per 50 Hz frame.
AngleRateLimit = namedtuple('AngleRateLimit', ['speed_bp', 'angle_v'])


@dataclass
class TeslaAp1PlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.chassis: 'tesla_ap1_can', Bus.pt: 'tesla_powertrain',
                                                     Bus.radar: 'tesla_radar_bosch_generated'})


class CAR(Platforms):
  TESLA_AP1_MODELS = TeslaAp1PlatformConfig(
    [CarDocs("Tesla Model S (Autopilot 1) 2014-16", "Autopilot", support_type=SupportType.COMMUNITY, support_link="#community")],
    CarSpecs(wheelbase=2.959, steerRatio=15.0),
  )
  # Pre-AP Model S (no Autopilot ECU, no Mobileye). Same chassis DBC and steering envelope as the AP1 Model S.
  # Selected by CarModel / ForceFingerprint, or by detect_preap_candidate (Comma Pedal + no Mobileye on bus 2).
  # Lateral through the Pre-AP safety flag; longitudinal only through the Comma Pedal (see preap/).
  TESLA_PREAP_MODELS = TeslaAp1PlatformConfig(
    [CarDocs("Tesla Model S (Pre-Autopilot) 2012-14", "Pre-Autopilot", support_type=SupportType.COMMUNITY, support_link="#community")],
    CarSpecs(wheelbase=2.959, steerRatio=15.0),
  )
  # Real Model X specs: wheelbase 2.965 m (the Model S is 2.959). steerRatio 15 is the Model S value, kept until a real X drive
  # gives a measured one. Curb mass for AP1-era 75D/90D is 2400 kg per Tesla's published Model X specifications (75D 2387 kg),
  # plus the standard openpilot cargo allowance (136 kg) = 2536 kg. CarSpecs in 0.11.2 has no mass field and the vehicle model
  # works per unit mass, so nothing reads the mass: it is recorded here only. Tinkla's 2560 + 136 kg is a TODO value, not used.
  # centerToFront is 0.5 * wheelbase via the CarSpecs default centerToFrontRatio.
  TESLA_AP1_MODELX = TeslaAp1PlatformConfig(
    [CarDocs("Tesla Model X (Autopilot 1) 2016", "Autopilot", support_type=SupportType.COMMUNITY, support_link="#community")],
    CarSpecs(wheelbase=2.965, steerRatio=15.0),
  )


class TeslaPlatform(StrEnum):
  """Early-Tesla platforms. Recognition only; actuation is a later layer."""
  preap = "preap"
  ap1_s = "ap1_s"
  ap1_x = "ap1_x"
  ap2 = "ap2"


# AP1 is selected by its chassis CAN signature (match_ap1_chassis), not FW.
# No AP1-specific UDS requests: the upstream tesla queries already log these
# ECUs, and duplicate requests would only lengthen fingerprinting for all cars.
FW_QUERY_CONFIG = FwQueryConfig(
  requests=[],
  fw_version_regex=rb'.*',
)


class CANBUS:
  # Lateral harness
  chassis = 0
  radar = 1
  autopilot_chassis = 2

  # Longitudinal harness (second panda; not used by AP1)
  powertrain = 4
  private = 5
  autopilot_powertrain = 6


GEAR_MAP = {
  "DI_GEAR_INVALID": CarState.GearShifter.unknown,
  "DI_GEAR_P": CarState.GearShifter.park,
  "DI_GEAR_R": CarState.GearShifter.reverse,
  "DI_GEAR_N": CarState.GearShifter.neutral,
  "DI_GEAR_D": CarState.GearShifter.drive,
  "DI_GEAR_SNA": CarState.GearShifter.unknown,
}

DOORS = ["DOOR_STATE_FL", "DOOR_STATE_FR", "DOOR_STATE_RL", "DOOR_STATE_RR", "DOOR_STATE_FrontTrunk", "BOOT_STATE"]

# Make sure the message and addr is also in the CAN parser!
BUTTONS = [
  Button(ButtonType.leftBlinker, "STW_ACTN_RQ", "TurnIndLvr_Stat", [1]),
  Button(ButtonType.rightBlinker, "STW_ACTN_RQ", "TurnIndLvr_Stat", [2]),
  Button(ButtonType.accelCruise, "STW_ACTN_RQ", "SpdCtrlLvr_Stat", [4, 16]),
  Button(ButtonType.decelCruise, "STW_ACTN_RQ", "SpdCtrlLvr_Stat", [8, 32]),
  Button(ButtonType.cancel, "STW_ACTN_RQ", "SpdCtrlLvr_Stat", [1]),
  Button(ButtonType.resumeCruise, "STW_ACTN_RQ", "SpdCtrlLvr_Stat", [2]),
]


class CarControllerParams:
  ANGLE_RATE_LIMIT_UP = AngleRateLimit(speed_bp=[0., 5., 15.], angle_v=[10., 1.6, .3])
  ANGLE_RATE_LIMIT_DOWN = AngleRateLimit(speed_bp=[0., 5., 15.], angle_v=[10., 7.0, 0.8])
  JERK_LIMIT_MAX = 8
  JERK_LIMIT_MIN = -8
  ACCEL_TO_SPEED_MULTIPLIER = 3

  def __init__(self, CP):
    pass


class TeslaAp1SafetyFlags(IntFlag):
  # opendbc/safety/modes/tesla_ap1.h
  LONG_CONTROL = TeslaSafetyFlags.LONG_CONTROL.value
  AP1 = 8
  STANDSTILL = 16
  # Pre-AP (opendbc/safety/modes/tesla_preap.h). PREAP selects the Pre-AP hooks; they never run with AP1 (8) set.
  PREAP = 32
  PREAP_PEDAL = 64
  # Bosch radar GTW on Pre-AP only. Matches NAP TeslaSafetyFlags on SafetyModel.tesla
  # (opendbc cc39c7fa values.py FLAG_RADAR_BEHIND_NOSECONE / FLAG_RADAR_EMULATION).
  PREAP_RADAR_BEHIND_NOSECONE = 128
  PREAP_RADAR_EMULATION = 256


# Chassis-only recognition is insufficient: Pre-AP shares these messages.
# Require stock Mobileye traffic on bus 2 as well. This fallback is considered
# only after upstream selection failed and cannot replace a stock Model 3/Y match.
AP1_CHASSIS_SIGNATURE = {0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8}


class ForcedFingerprint(dict):
  """Live CAN fingerprint of a car whose model was fixed by the user (CarModel with ForceFingerprint, or FINGERPRINT).
  A fixed model is taken as given and never re-checked against the live bus, as in 0.9.7."""


def match_ap1_chassis(fingerprint) -> bool:
  """AP1 chassis AND stock Mobileye bus-2 signature (0x2B9, 0x488). Pre-AP chassis alone is insufficient.
  0x399 (about 2 Hz) is not required: it can arrive after the fingerprint window closes."""
  bus0 = fingerprint.get(CANBUS.chassis, {}) if isinstance(fingerprint, dict) else {}
  camera = fingerprint.get(CANBUS.autopilot_chassis, {}) if isinstance(fingerprint, dict) else {}
  mobileye = {0x2B9: 8, 0x488: 4}
  return (all(bus0.get(addr) == length for addr, length in AP1_CHASSIS_SIGNATURE.items()) and
          all(camera.get(addr) == length for addr, length in mobileye.items()))


def is_preap(candidate) -> bool:
  """True for the Pre-AP Model S platform. Accepts a CAR member or its name."""
  if candidate is None or isinstance(candidate, bool):
    return False
  try:
    return str(candidate) == str(CAR.TESLA_PREAP_MODELS)
  except Exception:
    return False


_AP1_FAMILY = frozenset((str(CAR.TESLA_AP1_MODELS), str(CAR.TESLA_AP1_MODELX)))


def is_ap1_family(candidate) -> bool:
  """True for Model S AP1 and Model X AP1. Accepts a CAR member or its name."""
  if candidate is None or isinstance(candidate, bool):
    return False
  try:
    return str(candidate) in _AP1_FAMILY
  except Exception:
    return False


# AP1 Bosch radarTracks publish at the radar's own cycle, measured 7.4-12.6 Hz
# depending on track count (about 12 Hz below 10 tracks, 7.4-7.8 Hz at 28-30
# tracks). The slowest 20-sample FrequencyTracker average measured on 14 days of
# AP1 drives was 6.996 Hz, about 0.31 Hz above 6.69 Hz. FrequencyTracker stays
# valid while either its 200-sample or its 20-sample average is in range, and the
# higher of the two, at its worst while engaged, leaves about 1.25 Hz. The stock
# FrequencyTracker floor is 8.0 Hz (0.8 x half of the 20 Hz service). radard
# applies this lower-only override on AP1 Model S and Model X.
AP1_RADARTRACKS_MIN_FREQ_HZ = 6.69


DBC = CAR.create_dbc_map()
