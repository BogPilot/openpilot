using Cxx = import "/include/c++.capnp";
$Cxx.namespace("cereal");

using Car = import "/car.capnp";

@0xb526ba661d550a59;

# custom.capnp: a home for empty structs reserved for custom forks
# These structs are guaranteed to remain reserved and empty in mainline
# cereal, so use these if you want custom events in your fork.

# BogPilot (sys199): the BogPilot structs below (named FrogPilot* before the rename) are carried verbatim from
# BogPilot/openpilot@367e1fe (FrogPilot 0.9.7), struct IDs included, so 0.9.7-era logs and tools
# decode unchanged. Event ordinals @107-@116 map exactly as in 367e1fe (see log.capnp).
# BogPilotRadarState (FrogPilotRadarState in 367e1fe) took CustomReserved10's ID in 367e1fe, so CustomReserved10 (Event @136)
# gets a fresh ID (capnp id) here; it is still unused.

struct BogPilotCarControl @0x95bd710036ea524c {
  hudControl @0 :HUDControl;

  struct HUDControl {
    audibleAlert @0 :AudibleAlert;

    enum AudibleAlert {
      none @0;

      engage @1;
      disengage @2;
      refuse @3;

      warningSoft @4;
      warningImmediate @5;

      prompt @6;
      promptRepeat @7;
      promptDistracted @8;

      # Random Events
      angry @9;
      continued @10;
      dejaVu @11;
      doc @12;
      fart @13;
      firefox @14;
      goat @15;
      hal9000 @16;
      mail @17;
      nessie @18;
      noice @19;
      startup @20;
      thisIsFine @21;
      uwu @22;
    }
  }
}

struct BogPilotCarEvent @0x81c2f05a394cf4af {
  name @0 :EventName;

  enable @1 :Bool;
  noEntry @2 :Bool;
  warning @3 :Bool;
  userDisable @4 :Bool;
  softDisable @5 :Bool;
  immediateDisable @6 :Bool;
  preEnable @7 :Bool;
  permanent @8 :Bool;
  overrideLateral @10 :Bool;
  overrideLongitudinal @9 :Bool;

  enum EventName @0xaedffd8f31e7b55d {
    blockUser @0;
    customStartupAlert @1;
    forcingStop @2;
    goatSteerSaturated @3;
    greenLight @4;
    holidayActive @5;
    laneChangeBlockedLoud @6;
    leadDeparting @7;
    noLaneAvailable @8;
    openpilotCrashed @9;
    pedalInterceptorNoBrake @10;
    speedLimitChanged @11;
    torqueNNLoad @12;
    trafficModeActive @13;
    trafficModeInactive @14;
    turningLeft @15;
    turningRight @16;

    # Random Events
    accel30 @17;
    accel35 @18;
    accel40 @19;
    dejaVuCurve @20;
    firefoxSteerSaturated @21;
    hal9000 @22;
    openpilotCrashedRandomEvent @23;
    thisIsFineSteerSaturated @24;
    toBeContinued @25;
    vCruise69 @26;
    yourFrogTriedToKillMe @27;
    youveGotMail @28;

    # BogPilot AP1: stalk follow-distance dial applied a new setting.
    ap1FollowDistanceChanged @29;
  }
}

struct BogPilotCarParams @0xf35cc4560bbf6ec2 {
  canUsePedal @0 :Bool;
  canUseSDSU @1 :Bool;
  fpFlags @2 :UInt32;
  isHDA2 @3 :Bool;
  openpilotLongitudinalControlDisabled @4 :Bool;
  safetyConfigs @5 :List(SafetyConfig);

  struct SafetyConfig {
    safetyParam @0 :UInt16;
  }
}

struct BogPilotCarStateMsg @0xda96579883444c35 {
  accelPressed @0 :Bool;
  alwaysOnLateralAllowed @1 :Bool;
  alwaysOnLateralEnabled @2 :Bool;
  brakeLights @3 :Bool;
  dashboardSpeedLimit @4 :Float32;
  decelPressed @5 :Bool;
  distancePressed @6 :Bool;
  distanceLongPressed @7 :Bool;
  distanceVeryLongPressed @8 :Bool;
  ecoGear @9 :Bool;
  forceCoast @10 :Bool;
  isParked @11 :Bool;
  pauseLateral @12 :Bool;
  pauseLongitudinal @13 :Bool;
  sportGear @14 :Bool;
  trafficModeEnabled @15 :Bool;
  # AP1: continuous RWD / pull-toward (SpdCtrlLvr_Stat=2 / resumeCruise) level
  # from carstate.button_states — same path as accel/decelPressed (not buttonEvents).
  resumePressed @16 :Bool;
  # AP1: raw SpdCtrlLvr_Stat (0 IDLE, 2 RWD, 4 UP_2ND, 8 DN_2ND, 16 UP_1ST, 32 DN_1ST).
  # Tip next-5 uses 4/8; ±1 uses 16/32. button_states OR pos1+pos2 so detent is here.
  spdCtrlLvr @17 :UInt8;
  # AP1 regen-aware stop braking inputs (tesla/regen_aware.py).
  # 0x208 GTW_ambientTemperature (C, NaN when absent), 0x108 DI_torqueMotor (Nm), DI_motorRPM.
  ap1AmbientTempC @18 :Float32;
  ap1MotorTorqueNm @19 :Float32;
  ap1MotorRpm @20 :Float32;
  # AP1 DI_torque2 (0x118) DI_brakePedalState: 0 OFF, 1 ON (iBooster applied, driver or OP), 2 INVALID, 3 SNA / stale /
  # not AP1 (default). Read by the onroad decel bar colour ONLY (pedals.py); no controls, planner or safety reader.
  ap1BrakePedalState @21 :UInt8 = 3;
  # Tesla trim detection (opendbc tesla_ap1/trims.py), mirrored from carState.bogpilot: 0x186 front motor (NaN when absent),
  # layout 0 unknown / 1 single / 2 dual, Performance rear 0 unknown / 1 no / 2 yes, rpm per m/s per motor.
  ap1FrontMotorTorqueNm @22 :Float32;
  ap1FrontMotorRpm @23 :Float32;
  ap1DriveLayout @24 :UInt8;
  ap1PerfRear @25 :UInt8;
  ap1RearRpmPerMs @26 :Float32;
  ap1FrontRpmPerMs @27 :Float32;
  ap1RpmPerMsMeasured @28 :Bool;

  struct ButtonEvent {
    enum Type {
      lkas @0;
    }
  }
}

struct BogPilotControlsState @0x80ae746ee2596b11 {
  alertStatus @0 :AlertStatus;
  alertText1 @1 :Text;
  alertText2 @2 :Text;
  alertSize @3 :AlertSize;
  alertBlinkingRate @4 :Float32;
  alertType @5 :Text;
  alertSound @6 :Car.CarControl.HUDControl.AudibleAlert;

  enum AlertSize {
    none @0;    # don't display the alert
    small @1;   # small box
    mid @2;     # mid screen
    full @3;    # full screen
  }

  enum AlertStatus {
    normal @0;       # low priority alert for user's convenience
    userPrompt @1;   # mid priority alert that might require user intervention
    critical @2;     # high priority alert that needs immediate user intervention
    bogpilot @3;    # BogPilot startup alert
  }
}

struct BogPilotDeviceState @0xa5cd762cd951a455 {
  freeSpace @0 :Int16;
  usedSpace @1 :Int16;
}

struct BogPilotModelDataV2 @0xf98d843bfd7004a3 {
  turnDirection @0 :TurnDirection;

  enum TurnDirection {
    none @0;
    turnLeft @1;
    turnRight @2;
  }
}

struct BogPilotNavigation @0xf416ec09499d9d19 {
  approachingIntersection @0 :Bool;
  approachingTurn @1 :Bool;
  navigationSpeedLimit @2 :Float32;
}

struct BogPilotPlan @0xa1680744031fdb2d {
  accelerationJerk @0 :Float32;
  accelerationJerkStock @1 :Float32;
  cscControllingSpeed @2 :Bool;
  cscSpeed @3 :Float32;
  cscTraining @4 :Bool;
  dangerJerk @5 :Float32;
  desiredFollowDistance @6 :Int64;
  experimentalMode @7 :Bool;
  forcingStop @8 :Bool;
  forcingStopLength @9 :Float32;
  bogpilotEvents @10 :List(BogPilotCarEvent);
  increasedStoppedDistance @11 :Float32;
  lateralCheck @12 :Bool;
  laneWidthLeft @13 :Float32;
  laneWidthRight @14 :Float32;
  maxAcceleration @15 :Float32;
  minAcceleration @16 :Float32;
  redLight @17 :Bool;
  roadCurvature @18 :Float32;
  slcMapSpeedLimit @19 :Float32;
  slcMapboxSpeedLimit @20 :Float32;
  slcNextSpeedLimit @21 :Float32;
  slcOverriddenSpeed @22 :Float32;
  slcSpeedLimit @23 :Float32;
  slcSpeedLimitOffset @24 :Float32;
  slcSpeedLimitSource @25 :Text;
  speedJerk @26 :Float32;
  speedJerkStock @27 :Float32;
  speedLimitChanged @28 :Bool;
  tFollow @29 :Float32;
  themeUpdated @30 :Bool;
  togglesUpdated @31 :Bool;
  trackingLead @32 :Bool;
  unconfirmedSlcSpeedLimit @33 :Float32;
  vCruise @34 :Float32;
  weatherDaytime @35 :Bool;
  weatherId @36 :Int16;
  cscActive @37 :Bool;
}

struct BogPilotRadarState @0xcb9fd56c7057593a {
  leadLeft @0 :LeadData;
  leadRight @1 :LeadData;

  struct LeadData {
    dRel @0 :Float32;
    yRel @1 :Float32;
    vRel @2 :Float32;
    aRel @3 :Float32;
    vLead @4 :Float32;
    dPath @6 :Float32;
    vLat @7 :Float32;
    vLeadK @8 :Float32;
    aLeadK @9 :Float32;
    fcw @10 :Bool;
    status @11 :Bool;
    aLeadTau @12 :Float32;
    modelProb @13 :Float32;
    radar @14 :Bool;
    radarTrackId @15 :Int32 = -1;

    aLeadDEPRECATED @5 :Float32;
  }
}

struct CustomReserved7 @0xb86e6369214c01c8 {
}

struct CustomReserved10 @0xc7195fc350bd23ea {
}

struct CustomReserved11 @0xc2243c65e0340384 {
}

struct CustomReserved12 @0x9ccdc8676701b412 {
}

struct CustomReserved13 @0xcd96dafb67a082d0 {
}

struct CustomReserved14 @0xb057204d7deadf3f {
}

struct CustomReserved15 @0xbd443b539493bc68 {
}

struct CustomReserved16 @0xfc6241ed8877b611 {
}

# mapd v2 (pfeiferj/mapd v2.4.0, MIT, cereal/custom/custom.capnp at tag v2.4.0): the three message structs keep the
# CustomReserved17/18/19 ids, so mapd's own schema and ours agree on the wire. Copied verbatim (helper structs and enums
# included); do not edit field numbers.
struct MapdDownloadLocationDetails @0xff889853e7b0987f {
  location @0 :Text;
  totalFiles @1 :UInt32;
  downloadedFiles @2 :UInt32;
}

struct MapdDownloadProgress @0xfaa35dcac85073a2 {
  active @0 :Bool;
  cancelled @1 :Bool;
  totalFiles @2 :UInt32;
  downloadedFiles @3 :UInt32;
  locations @4 :List(Text);
  locationDetails @5 :List(MapdDownloadLocationDetails);
}

struct MapdPathPoint @0xd6f78acca1bc3939 {
  latitude @0 :Float64;
  longitude @1 :Float64;
  curvature @2 :Float32;
  targetVelocity @3 :Float32;
}

struct MapdPosition @0xde9705979aca8339 {
  latitude @0 :Float64;
  longitude @1 :Float64;
}

struct MapdExtendedOut @0xa30662f84033036c {
  downloadProgress @0 :MapdDownloadProgress;
  settings @1 :Text;
  path @2 :List(MapdPathPoint);
  position @3 :MapdPosition;
  loopRateAverage @4 :Float32;
  loopRateMin @5 :Float32;
}

enum MapdInputType {
  download @0;
  reloadSettings @9;
  saveSettings @10;
  loadDefaultSettings @21;
  loadRecommendedSettings @22;
  loadPersistentSettings @26;
  cancelDownload @27;
  setJsonPathFloat @43;
  setJsonPathText @44;
  setJsonPathBool @45;
  acceptSpeedLimit @34;

  # DEPRECATED settings inputs
  setLogLevel @6;
  setLogSource @29;
  setLogJson @28;
  setTargetLateralAccel @1;
  setSpeedLimitOffset @2;
  setSpeedLimitControl @3;
  setMapCurveSpeedControl @4;
  setVisionCurveSpeedControl @5;
  setVisionCurveTargetLatA @7;
  setVisionCurveMinTargetV @8;
  setEnableSpeed @11;
  setVisionCurveUseEnableSpeed @12;
  setMapCurveUseEnableSpeed @13;
  setSpeedLimitUseEnableSpeed @14;
  setHoldLastSeenSpeedLimit @15;
  setTargetSpeedJerk @16;
  setTargetSpeedAccel @17;
  setTargetSpeedTimeOffset @18;
  setDefaultLaneWidth @19;
  setMapCurveTargetLatA @20;
  setSlowDownForNextSpeedLimit @23;
  setSpeedUpForNextSpeedLimit @24;
  setHoldSpeedLimitWhileChangingSetSpeed @25;
  setExternalSpeedLimitControl @30;
  setExternalSpeedLimit @31;
  setSpeedLimitPriority @32;
  setSpeedLimitChangeRequiresAccept @33;
  setPressGasToAcceptSpeedLimit @35;
  setAdjustSetSpeedToAcceptSpeedLimit @36;
  setAcceptSpeedLimitTimeout @37;
  setPressGasToOverrideSpeedLimit @38;
  setConditionalSpeedLimitControl @39;
  setShadowCarState @40;
  setShadowModelV2 @41;
  setShadowGpsLocation @42;
  setShadowGpsLocationExternal @46;
}

enum WaySelectionType {
  current @0;
  predicted @1;
  possible @2;
  extended @3;
  fail @4;
}

enum SpeedLimitOffsetType {
  static @0;
  percent @1;
}

struct MapdIn @0xc86a3d38d13eb3ef {
  type @0 :MapdInputType;
  float @1 :Float32;
  str @2 :Text;
  bool @3 :Bool;
  jsonPath @4 :Text;
}

enum RoadContext {
  freeway @0;
  city @1;
  unknown @2;
}

# WARNING: must be kept in perfect sync (names and values) with the
# HighwayClass enum in cereal/offline/offline.capnp — state.go casts directly
# between the two generated enum types.
# unknown either means the way's highway tag was not one of the listed values
# or the loaded map tiles predate this field.
enum HighwayClass {
  unknown @0;
  motorway @1;
  motorwayLink @2;
  trunk @3;
  trunkLink @4;
  primary @5;
  primaryLink @6;
  secondary @7;
  secondaryLink @8;
  tertiary @9;
  tertiaryLink @10;
  unclassified @11;
  residential @12;
  livingStreet @13;
}

struct MapdOut @0xa4f1eb3323f5f582 {
  wayName @0 :Text;
  wayRef @1 :Text;
  roadName @2 :Text;
  speedLimit @3 :Float32;
  nextSpeedLimit @4 :Float32;
  nextSpeedLimitDistance @5 :Float32;
  hazard @6 :Text;
  nextHazard @7 :Text;
  nextHazardDistance @8 :Float32;
  advisorySpeed @9 :Float32;
  nextAdvisorySpeed @10 :Float32;
  nextAdvisorySpeedDistance @11 :Float32;
  oneWay @12 :Bool;
  lanes @13 :UInt8;
  tileLoaded @14 :Bool;
  speedLimitSuggestedSpeed @15 :Float32;
  suggestedSpeed @16 :Float32;
  estimatedRoadWidth @17 :Float32;
  roadContext @18 :RoadContext;
  distanceFromWayCenter @19 :Float32;
  visionCurveSpeed @20 :Float32;
  mapCurveSpeed @21 :Float32;
  waySelectionType @22 :WaySelectionType;
  speedLimitAccepted @23 :Bool;
  highwayClass @24 :HighwayClass;
  wayId @25 :Int64;
  conditionalSpeedLimit @26 :Text;
  isForward @27 :Bool;
}
