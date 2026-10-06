from dataclasses import dataclass, field
from enum import Enum, IntFlag
from opendbc.car import ACCELERATION_DUE_TO_GRAVITY, Bus, CarSpecs, DbcDict, PlatformConfig, Platforms
from opendbc.car.lateral import AngleSteeringLimits, ISO_LATERAL_ACCEL
from opendbc.car.structs import CarParams, CarState
from opendbc.car.docs_definitions import CarDocs, CarFootnote, CarHarness, CarParts, Column, SupportType
from opendbc.car.fw_query_definitions import FwQueryConfig, Request, StdQueries

Ecu = CarParams.Ecu


class Footnote(Enum):
  HW_TYPE = CarFootnote(
    "Some 2023 model years have HW4. To check which hardware type your vehicle has, look for " +
    "<b>Autopilot computer</b> under <b>Software -> Additional Vehicle Information</b> on your vehicle's touchscreen. </br></br>" +
    "See <a href=\"https://www.notateslaapp.com/news/2173/how-to-check-if-your-tesla-has-hardware-4-ai4-or-hardware-3\">this page</a> for more information.",
    Column.MODEL)

  SETUP = CarFootnote(
    "See more setup details for <a href=\"https://github.com/commaai/openpilot/wiki/tesla\" target=\"_blank\">Tesla</a>.",
    Column.MAKE, setup_note=True)


@dataclass
class TeslaCarDocsHW3(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.tesla_a]))
  footnotes: list[Enum] = field(default_factory=lambda: [Footnote.HW_TYPE, Footnote.SETUP])


@dataclass
class TeslaCarDocsHW4(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.tesla_b]))
  footnotes: list[Enum] = field(default_factory=lambda: [Footnote.HW_TYPE, Footnote.SETUP])


@dataclass
class TeslaPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.party: 'tesla_model3_party'})


class CAR(Platforms):
  TESLA_MODEL_3 = TeslaPlatformConfig(
    [
      # TODO: do we support 2017? It's HW3
      TeslaCarDocsHW3("Tesla Model 3 (with HW3) 2019-23"),
      TeslaCarDocsHW4("Tesla Model 3 (with HW4) 2024-26"),
    ],
    CarSpecs(mass=1899., wheelbase=2.875, steerRatio=12.0),
  )
  TESLA_MODEL_Y = TeslaPlatformConfig(
    [
      TeslaCarDocsHW3("Tesla Model Y (with HW3) 2020-23"),
      TeslaCarDocsHW4("Tesla Model Y (with HW4) 2024-25"),
     ],
    CarSpecs(mass=2072., wheelbase=2.890, steerRatio=12.0),
  )
  TESLA_MODEL_X = TeslaPlatformConfig(
    [TeslaCarDocsHW4("Tesla Model X (with HW4) 2024")],
    CarSpecs(mass=2495., wheelbase=2.960, steerRatio=12.0),
  )
  TESLA_MODEL_S_PREAP = TeslaPlatformConfig(
    [CarDocs("Tesla Model S (Pre-AP) 2012-14", "All", support_type=SupportType.COMMUNITY, support_link="#community")],
    CarSpecs(mass=2100., wheelbase=2.960, steerRatio=15.0),
    {
      Bus.party: 'tesla_can',
      Bus.pt: 'tesla_can',
      Bus.chassis: 'tesla_can',
      Bus.radar: 'tesla_radar_bosch_generated',
    },
  )
  # BogStar: AP1 (Mobileye / HW1) Model S runs the BogPilot AP1 port (ap1_*.py, safety tesla_ap1.h).
  # Platform name kept from StarPilot so saved car selections still resolve.
  TESLA_MODEL_S_HW1 = TeslaPlatformConfig(
    [CarDocs("Tesla AP1 Model S (with HW1) 2014-16", "All", support_type=SupportType.COMMUNITY, support_link="#community")],
    CarSpecs(mass=2100., wheelbase=2.960, steerRatio=15.0),
    {
      Bus.chassis: 'tesla_can',
      Bus.party: 'tesla_can',
      Bus.pt: 'tesla_can',
      Bus.radar: 'tesla_radar_bosch_generated',
    },
  )


FW_QUERY_CONFIG = FwQueryConfig(
  requests=[
    Request(
      [StdQueries.TESTER_PRESENT_REQUEST, StdQueries.SUPPLIER_SOFTWARE_VERSION_REQUEST],
      [StdQueries.TESTER_PRESENT_RESPONSE, StdQueries.SUPPLIER_SOFTWARE_VERSION_RESPONSE],
      bus=0,
    ),
    # AP1 Model S: brake booster 0x64d -> 0x65d and Bosch radar 0x671 -> 0x681 answer UDS F181 on the
    # chassis bus (same request as BogPilot's AP1 port; seen on AP1 rlogs).
    Request(
      [StdQueries.TESTER_PRESENT_REQUEST, StdQueries.UDS_VERSION_REQUEST],
      [StdQueries.TESTER_PRESENT_RESPONSE, StdQueries.UDS_VERSION_RESPONSE],
      whitelist_ecus=[Ecu.electricBrakeBooster, Ecu.fwdRadar],
      rx_offset=0x10,
      bus=0,
    ),
    # AP1 Model S EPAS 0x730 -> 0x738 answers UDS F188 (manufacturer ECU software number) on AP1 rlogs.
    Request(
      [StdQueries.TESTER_PRESENT_REQUEST, StdQueries.MANUFACTURER_SOFTWARE_VERSION_REQUEST],
      [StdQueries.TESTER_PRESENT_RESPONSE, StdQueries.MANUFACTURER_SOFTWARE_VERSION_RESPONSE],
      whitelist_ecus=[Ecu.eps],
      rx_offset=0x08,
      bus=0,
    ),
  ],
  # The radar answer is AP1-car specific; an HW1 car whose radar does not answer still matches on the EPAS.
  non_essential_ecus={Ecu.fwdRadar: [CAR.TESLA_MODEL_S_HW1]},
)


class CANBUS:
  party = 0
  radar = 1
  vehicle = radar
  autopilot_party = 2
  # AP1 Model S aliases. Same numbers as party / autopilot_party.
  chassis = 0
  autopilot_chassis = 2


GEAR_MAP = {
  "DI_GEAR_INVALID": CarState.GearShifter.unknown,
  "DI_GEAR_P": CarState.GearShifter.park,
  "DI_GEAR_R": CarState.GearShifter.reverse,
  "DI_GEAR_N": CarState.GearShifter.neutral,
  "DI_GEAR_D": CarState.GearShifter.drive,
  "DI_GEAR_SNA": CarState.GearShifter.unknown,
}


# Add extra tolerance for average banked road since safety doesn't have the roll
AVERAGE_ROAD_ROLL = 0.06  # ~3.4 degrees, 6% superelevation. higher actual roll lowers lateral acceleration


class CarControllerParams:
  # AP1 Model S: Tinkla earlytesla-panda TESLA_LOOKUP_ANGLE_RATE_UP / _DOWN.
  # Used by ap1_carcontroller. Model 3/Y still uses ANGLE_LIMITS below.
  AP1_ANGLE_LIMITS = AngleSteeringLimits(
    819.2,  # deg, EPAS_internalSAS range
    ([2., 7., 17.], [8., 4., 2.5]),
    ([2., 7., 17.], [9., 5., 4.5]),
  )
  AP1_STEER_STEP = 2  # 50 Hz
  AP1_ACCEL_TO_SPEED_MULTIPLIER = 3
  AP1_JERK_LIMIT_MAX = 8
  AP1_JERK_LIMIT_MIN = -8

  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    # EPAS faults above this angle
    360,  # deg
    # Tesla uses a vehicle model instead, check carcontroller.py for details
    ([], []),
    ([], []),

    # Vehicle model angle limits
    # Add extra tolerance for average banked road since safety doesn't have the roll
    MAX_LATERAL_ACCEL=ISO_LATERAL_ACCEL + (ACCELERATION_DUE_TO_GRAVITY * AVERAGE_ROAD_ROLL),  # ~3.6 m/s^2
    MAX_LATERAL_JERK=3.0 + (ACCELERATION_DUE_TO_GRAVITY * AVERAGE_ROAD_ROLL),  # ~3.6 m/s^3

    # limit angle rate to both prevent a fault and for low speed comfort (~12 mph rate down to 0 mph)
    MAX_ANGLE_RATE=5,  # deg/20ms frame, EPS faults at 12 at a standstill
  )

  STEER_STEP = 2  # Angle command is sent at 50 Hz
  ACCEL_MAX = 2.0    # m/s^2
  ACCEL_MIN = -3.48  # m/s^2
  JERK_LIMIT_MAX = 4.9  # m/s^3, ACC faults at 5.0
  JERK_LIMIT_MIN = -4.9  # m/s^3, ACC faults at 5.0
  JERK_RAMP_RATE = JERK_LIMIT_MAX * 0.002


class TeslaSafetyFlags(IntFlag):
  LONG_CONTROL = 1
  FLAG_EXTERNAL_PANDA = 4
  FLAG_HW1 = 8
  COOP_STEERING = 256


class TeslaAp1SafetyFlags(IntFlag):
  """AP1 Model S safety param (opendbc/safety/modes/tesla_ap1.h).

  Numbering is BogGyver/Tinkla's (BogGyver/panda board/safety/safety_tesla.h, FLAG_TESLA_*):
    POWERTRAIN = 1, LONG_CONTROL = 2, RADAR_BEHIND_NOSECONE = 4, HAS_IC_INTEGRATION = 8,
    HAS_AP = 16, NEED_RADAR_EMULATION = 32, ENABLE_HAO = 64, HAS_IBOOSTER = 128.
  This port implements only HAS_AP (selects the AP1 safety) and LONG_CONTROL (chassis 0x2b9).
  The other BogGyver/Tinkla bits are not implemented and are never set. In particular bit 8 is
  StarPilot's TeslaSafetyFlags.FLAG_HW1 (routes to tesla_legacy.h) and must stay clear for AP1.
  """
  LONG_CONTROL = 2
  HAS_AP = 16


class TeslaFlags(IntFlag):
  LONG_CONTROL = 1
  AP1 = 0x100


class CruiseButtons:
  IDLE = 0
  CANCEL = 1
  MAIN = 2
  RES_ACCEL_2ND = 4
  DECEL_2ND = 8
  SET_ACCEL = 16
  RES_ACCEL = 16
  DECEL_SET = 32

  @classmethod
  def is_accel(cls, btn: int) -> bool:
    return btn in (cls.RES_ACCEL, cls.RES_ACCEL_2ND)

  @classmethod
  def is_decel(cls, btn: int) -> bool:
    return btn in (cls.DECEL_SET, cls.DECEL_2ND)


DBC = CAR.create_dbc_map()

# StarPilot's legacy HW1 stack (tesla_legacy.h / update_legacy) is kept in the tree but no platform
# routes to it on BogStar: the HW1 Model S uses the AP1 port (AP1_CARS).
LEGACY_CARS: tuple = ()
AP1_CARS = (CAR.TESLA_MODEL_S_HW1,)

STEER_THRESHOLD = 1
STEER_DISENGAGE_THRESHOLD = 5.0
