import copy
from collections import deque

from opendbc.car import Bus, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car import DT_CTRL
from opendbc.car.tesla_ap1.blindspot import Ap1Blindspot, frames_from_vl_all
from opendbc.car.tesla_ap1.brake_level import BRAKE_LEVEL_MAX_AGE_S, DI_BRAKE_STATE_MAX_AGE_S, brake_level, brake_pedal_state
from opendbc.car.tesla_ap1.cluster import CLUSTER_ADDRS, COUNTER_SIGNALS, MSG_NAMES
from opendbc.car.tesla_ap1.hso import ap1_driver_input
from opendbc.car.tesla_ap1.op_long_set_speed import OpLongSetSpeed
from opendbc.car.tesla_ap1.pedal_signals import pedal_position
from opendbc.car.tesla_ap1.cruise_set import cruise_set_scale, cruise_set_scale_fix_enabled
from opendbc.car.tesla_ap1.stalk_follow import dtr_sample, follow_seconds, parse_stalk_raw
from opendbc.car.tesla_ap1.phase3_stalk_controls import StalkControls
from opendbc.car.tesla_ap1.speed_limit import LIMIT_MAX_AGE_S, dashboard_speed_limit_ms, frame_fresh
from opendbc.car.tesla_ap1.steer_fault import steer_fault_temporary
from opendbc.car.tesla_ap1.steer_rate import SteerRateFallback
from opendbc.car.tesla_ap1 import ride_height, trims
from opendbc.car.tesla_ap1.values import CAR, DBC, CANBUS, GEAR_MAP, DOORS, BUTTONS, is_ap1_family
from opendbc.car.interfaces import CarStateBase
from opendbc.can import CANDefine, CANParser

# Minimum published stalk level width in 100 Hz frames: 6 x 10 ms > one 50 ms planner tick (DT_MDL) plus jitter.
# A press shorter than this is stretched to it; a longer press is published exactly as long as it is held.
STALK_LEVEL_HOLD_FRAMES = 6

# 0.9.7 frequency 0 (never marks the message missing) is NaN in the 0.11 parser.
OPTIONAL = float('nan')
# 0x186 (100 Hz on the logs) counts as present when seen within this; 0x398 is slow (about 1 Hz), so a longer window.
FRONT_MOTOR_MAX_AGE_S = 0.2
CAR_CONFIG_MAX_AGE_S = 5.0


def _saved_detection():
  try:
    return trims.read_detected()
  except Exception:
    return None


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.steer_rate = SteerRateFallback(DT_CTRL)   # StW_AnglHP_Spd SNA guard
    self.steer_rate_source = 0
    self.button_states = {button.event_type: False for button in BUTTONS}
    # Published stalk levels (bogpilot.accelPressed / decelPressed / resumePressed) stay high at least
    # STALK_LEVEL_HOLD_FRAMES from the press, so the 20 Hz planner (DT_MDL 50 ms) cannot miss a short tap or pull,
    # and drop at the release of a longer press (no tail, so the planner's hold time is the driver's). buttonEvents
    # are untouched.
    self.stalk_level_hold = {}
    self.stalk_level_prev = {}
    self.can_define = CANDefine(DBC[CP.carFingerprint][Bus.chassis])

    # Needed by carcontroller
    self.msg_stw_actn_req = None
    self.hands_on_level = 0
    self.steer_warning = None
    self.eac_status = None
    self.eac_fault = False
    self.acc_state = 0
    self.das_control_counters = deque(maxlen=32)
    # DTR_Dist_Rq decision. Python only; cereal was not extended.
    self.spd_ctrl_lvr = 0
    self.stalk_follow = None
    # Experimental-only holds; normal buttonEvents and PCM engagement stay fixed.
    self.stalk_pull_toggle = False
    self.stalk_fwd_toggle = False
    self.stalk_controls = StalkControls()
    self.stalk_controls_allowed = False  # card supplies live onroad/experimental eligibility
    # AP1 only. {addr: decoded values} for stock cluster frames (bus 2) that
    # arrived this step. Read by CarController for the cluster frames.
    self.cluster_stock = {}
    # AP1 only. Stock DAS_steeringControlCounter values (bus 2) received this
    # step, oldest first. CarController follows them (steer_counter.py).
    self.stock_steer_counters = []
    # AP1 only. Last EPB_epasEACAllow seen. None until the first 0x214 frame
    # (vl defaults to 0 before that, which would read as revoked).
    self.epb_eac_allow = None
    self.epb_eac_revoked = False
    # AP1 only. Control steps since the last 0x214 sample (None = never seen). The code 4 recovery needs a recent one.
    self.epb_eac_allow_age = None
    # AP1 only. Stock 0x399 blind-spot fields with a per-side hold (blindspot.py).
    self.ap1_bsm = Ap1Blindspot()
    self.stock_ap_active = False
    # AP1 only. Last UI_baseMapSpeedLimitMPS (0x238 mux 3, m/s) and the parser time it was seen (0 = never this
    # drive). The dashboard limit guard reads it as unknown when 0 or older than LIMIT_MAX_AGE_S (speed_limit.py).
    self.base_map_ms = 0.0
    self.base_map_nanos = 0
    # AP1 only. The dashboard limit published last step, held when the guard ignores a map-only rise.
    self.dash_hold_ms = 0.0
    # AP1 openpilot long only: openpilot's own cruise set speed (op_long_set_speed.py).
    op_long = bool(getattr(CP, "openpilotLongitudinalControl", False)) and is_ap1_family(CP.carFingerprint)
    self.op_long_set = OpLongSetSpeed() if op_long else None
    # Speed-limit offset for the engage set (limit_ms -> offset_ms). The card supplies it from params
    # (phase3_speed_control.EngageLimitOffset); None = no offset (tests, replay).
    self.op_long_offset = None
    # Standstill tap-from-0 speed (kph). The card supplies it from params (EngageTapFromZero); None = 15 mph default.
    self.op_long_tap_from_zero = None
    # DI_cruiseSet DBC factor 0.5 halves the AP1 value (cruise_set.py, BogPilot x2 fix). Default ON, read once.
    self.cruise_set_scale = cruise_set_scale(cruise_set_scale_fix_enabled())
    # Trim detection (trims.py): motor layout from 0x186 / GTW_fourWheelDrive, Performance rear from the rpm ratio, and the
    # live rpm per m/s of each motor. Seeded from the last drive's saved detection (read once here, at car start).
    self.drive_detect = trims.DriveDetector(CP.carFingerprint, DT_CTRL, front_possible=True, seed=_saved_detection())
    # Lower on Park (ride_height.py), AP1 Model S / X: the screen's 0x308 frames received this step (raw bytes, oldest first),
    # the newest one and its age, and the 0x398 air suspension flag (None until a fresh 0x398).
    self.ride_height_frames = []
    self.ride_height_last = None
    self.ride_height_age_s = float("inf")
    self.air_suspension = None

  def update(self, can_parsers) -> structs.CarState:
    cp = can_parsers[Bus.chassis]
    cp_cam = can_parsers[Bus.cam]
    ret = structs.CarState()
    fp_ret = ret.bogpilot

    # Vehicle speed
    ret.vEgoRaw = cp.vl["ESP_B"]["ESP_vehicleSpeed"] * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.standstill = (ret.vEgo < 0.1)

    # Gas pedal
    gas = cp.vl["DI_torque1"]["DI_pedalPos"] / 100.0
    ret.gasPressed = gas > 0
    # Pedal position 0..1 for the onroad pedal gauge, in the deprecated CarState.gas slot (no schema change; see DIVERGENCES).
    # DI_pedalPos SNA (VAL_ 255, decoded 102 %) or out of range is published as -1 (missing), never as a full bar.
    ret.deprecated.gas = pedal_position(cp.vl["DI_torque1"]["DI_pedalPos"])

    # Brake pedal
    ret.brakePressed = bool(cp.vl["BrakeMessage"]["driverBrakeStatus"] != 1)
    # Brake level 0..1 for the onroad decel bar (0x39D rod stroke, BogPilot divergence from drive logs), in the deprecated
    # CarState.brake slot (no schema change); BRAKE_LEVEL_MISSING (-1) when missing, stale or bad checksum. Display only.
    booster = cp.vl["BrakeBoosterStroke"]
    ret.deprecated.brake = brake_level(booster["brakeRodStroke"], booster["brakeBoosterCounter"],
                                       booster["brakeBoosterChecksum"],
                                       frame_fresh(cp, "BrakeBoosterStroke", BRAKE_LEVEL_MAX_AGE_S))

    # Steering wheel
    epas_status = cp.vl["EPAS_sysStatus"]

    self.hands_on_level = epas_status["EPAS_handsOnLevel"]
    self.steer_warning = self.can_define.dv["EPAS_sysStatus"]["EPAS_eacErrorCode"].get(int(epas_status["EPAS_eacErrorCode"]), None)
    steer_status = self.can_define.dv["EPAS_sysStatus"]["EPAS_eacStatus"].get(int(epas_status["EPAS_eacStatus"]), None)
    self.eac_status = steer_status

    ret.steeringAngleDeg = -epas_status["EPAS_internalSAS"]
    # From the steering-column angle sensor (0x00E), not the EPAS, and at a different rate. StW_AnglHP_Spd is SNA on some sensors;
    # tesla_ap1/steer_rate.py then uses the StW_AnglHP difference so the override detector never sees SNA as a wheel rate. A column
    # frame whose StW_AnglHP_Sens_Stat is not OK (INI / ERR / SNA) is not used at all: the rate then comes from the EPAS angle.
    stw = cp.vl["STW_ANGLHP_STAT"]
    ret.steeringRateDeg = self.steer_rate.update(-stw["StW_AnglHP_Spd"], -stw["StW_AnglHP"], stw["MC_STW_ANGLHP_STAT"],
                                                 sens_stat=stw["StW_AnglHP_Sens_Stat"], epas_angle=-epas_status["EPAS_internalSAS"],
                                                 epas_counter=epas_status["EPAS_sysStatusCounter"])
    self.steer_rate_source = self.steer_rate.source
    ret.steeringTorque = -epas_status["EPAS_torsionBarTorque"]
    # Any non-zero hands level is driver input (override, grey border), as in
    # frog_ap1. AP1 EPAS reports 0, 1, 3. The AP1 lateral pause stays at
    # TinklaHandsOnLevel 2 in CarController (hso.ap1_steering_pressed).
    # Structural AP1 (Model S and Model X): hands override and EAC fault handling.
    ap1 = is_ap1_family(self.CP.carFingerprint)
    # Model S only. Cluster, stalk follow and standstill stay off on Model X (the regen inputs below are read on both).
    ap1_s = self.CP.carFingerprint == CAR.TESLA_AP1_MODELS
    if ap1:
      ret.steeringPressed = ap1_driver_input(self.hands_on_level)
    else:
      ret.steeringPressed = (self.hands_on_level > 0)
    self.eac_fault = steer_status == "EAC_FAULT"
    ret.steerFaultPermanent = self.eac_fault
    if ap1:
      # EPB_epasEACAllow 0: the EPB revoked EAC. EPAS stays INHIBITED until a
      # car power cycle (the comma reboot does not clear it). Report it as a
      # permanent steer fault ("LKAS Fault: Restart the Car") instead of only
      # the silent steer-unavailable warning.
      epb = cp.vl_all.get("EPB_epasControl", {}).get("EPB_epasEACAllow", [])
      if len(epb):
        self.epb_eac_allow = int(epb[-1])
        self.epb_eac_allow_age = 0
      elif self.epb_eac_allow_age is not None:
        self.epb_eac_allow_age += 1
      self.epb_eac_revoked = self.epb_eac_allow == 0
      ret.steerFaultPermanent = ret.steerFaultPermanent or self.epb_eac_revoked
    # AP1: idle, code 6, and latched HANDS_ON (3) are not temporary faults.
    # Both codes stay set after hands return below 2, so they must not keep
    # latActive false. The hands pause is hands_on_level >= 2, not this flag.
    # Other non-idle names still warn. Model 3/Y still faults on code 6 and
    # still does not fault on HANDS_ON.
    ret.steerFaultTemporary = steer_fault_temporary(self.steer_warning, ap1)

    # Cruise state
    cruise_state = self.can_define.dv["DI_state"]["DI_cruiseState"].get(int(cp.vl["DI_state"]["DI_cruiseState"]), None)
    speed_units = self.can_define.dv["DI_state"]["DI_speedUnits"].get(int(cp.vl["DI_state"]["DI_speedUnits"]), None)

    acc_enabled = (cruise_state in ("ENABLED", "STANDSTILL", "OVERRIDE", "PRE_FAULT", "PRE_CANCEL"))

    ret.cruiseState.enabled = acc_enabled
    # Tinkla-aligned: cruise set is DI_cruiseSet (ACC set), not DI_digitalSpeed
    # (≈ ego). With pcmCruise, VCruiseHelper copies this into controlsState.vCruise
    # so openpilot's set tracks the stalk set. Display/ego stay on ESP vEgo.
    if speed_units == "KPH":
      ret.cruiseState.speed = cp.vl["DI_state"]["DI_cruiseSet"] * self.cruise_set_scale * CV.KPH_TO_MS
    elif speed_units == "MPH":
      ret.cruiseState.speed = cp.vl["DI_state"]["DI_cruiseSet"] * self.cruise_set_scale * CV.MPH_TO_MS
    # openpilot long (AP1 S and X): cruiseState.speed is replaced below, after dashboardSpeedLimit and the
    # stalk buttons are read (op_long_set_speed.py). Openpilot long off (stock AP) keeps DI_cruiseSet above.
    ret.cruiseState.available = ((cruise_state == "STANDBY") or ret.cruiseState.enabled)
    ret.cruiseState.standstill = False # This needs to be false, since we can resume from stop without sending anything special

    # Gear
    ret.gearShifter = GEAR_MAP[self.can_define.dv["DI_torque2"]["DI_gear"].get(int(cp.vl["DI_torque2"]["DI_gear"]), "DI_GEAR_INVALID")]

    # Buttons
    buttonEvents = []
    for button in BUTTONS:
      state = (cp.vl[button.can_addr][button.can_msg] in button.values)
      if self.button_states[button.event_type] != state:
        event = structs.CarState.ButtonEvent(type=button.event_type, pressed=state)
        buttonEvents.append(event)
      self.button_states[button.event_type] = state
    ret.buttonEvents = buttonEvents

    # Doors
    ret.doorOpen = any((self.can_define.dv["GTW_carState"][door].get(int(cp.vl["GTW_carState"][door]), "OPEN") == "OPEN") for door in DOORS)

    # Blinkers
    ret.leftBlinker = (cp.vl["GTW_carState"]["BC_indicatorLStatus"] == 1)
    ret.rightBlinker = (cp.vl["GTW_carState"]["BC_indicatorRStatus"] == 1)

    # Seatbelt. Model X reads RCM_status (0x211); Model S keeps SDM1.
    if self.CP.carFingerprint == CAR.TESLA_AP1_MODELX:
      ret.seatbeltUnlatched = cp.vl["RCM_status"]["RCM_buckleDriverStatus"] != 1
    else:
      ret.seatbeltUnlatched = (cp.vl["SDM1"]["SDM_bcklDrivStatus"] != 1)

    # Blindspot. Model S only: stock DAS_blindSpotRearLeft/Right from 0x399 on
    # cp_cam. Fail-closed: WARNING/SNA/garbage/stale/bad-checksum dropout =>
    # Blindspot True (OCCUPIED). Only recent checksum-OK NO_WARNING clears.
    # Held BSM_HOLD_S; stale after BSM_STALE_S. Other Teslas: no BSM.
    if ap1_s:
      ret.leftBlindspot, ret.rightBlindspot = self.ap1_bsm.update(frames_from_vl_all(cp_cam), DT_CTRL)

    # AEB
    ret.stockAeb = (cp_cam.vl["DAS_control"]["DAS_aebEvent"] == 1)

    # AP1 tip detent: raw SpdCtrlLvr_Stat (UP_2ND=4 / DN_2ND=8 vs 1ST).
    try:
      self.spd_ctrl_lvr = int(cp.vl["STW_ACTN_RQ"].get("SpdCtrlLvr_Stat") or 0)
    except Exception:
      self.spd_ctrl_lvr = 0

    # Stalk follow detent. STW_ACTN_RQ is already subscribed. No cereal field.
    # A zero timestamp is the parser default, not ACC_DIST_1.
    stw = cp.vl.get("STW_ACTN_RQ")
    ts_map = getattr(cp, "ts_nanos", {}).get("STW_ACTN_RQ", {})
    if not isinstance(stw, dict) or not isinstance(ts_map, dict):
      raw = None
    else:
      raw = dtr_sample(stw.get("DTR_Dist_Rq"), ts_map.get("DTR_Dist_Rq", 0))
    # No debounce: fast intentional spins apply at once (user request, 10/13).
    self.stalk_follow = parse_stalk_raw(raw, self.stalk_follow)
    # 0.11.2 has no cruiseState.speedOffset. AP1 publishes the stalk follow
    # seconds in bogpilot.ap1StalkFollowS so the openpilot planner can set tFollow.
    # 0 means no ready detent. 255 holds the last seconds via parse_stalk_raw.
    # Model S only. Stalk follow is not published for Model X.
    stalk_follow_s = follow_seconds(self.stalk_follow) if self.CP.carFingerprint == CAR.TESLA_AP1_MODELS else 0.0

    # Experimental holds never modify the buttonEvents above or stock PCM state.
    prev = getattr(self, "out", None)
    was_engaged = bool(prev.cruiseState.enabled) if prev is not None else False
    sample_ns = ts_map.get("SpdCtrlLvr_Stat", 0) if isinstance(ts_map, dict) else 0
    self.stalk_pull_toggle, self.stalk_fwd_toggle = self.stalk_controls.update(
      self.spd_ctrl_lvr, was_engaged, sample_ns,
      bool(cp.can_valid and cp_cam.can_valid), self.stalk_controls_allowed, self.CP)
    if not self.stalk_controls.settings.twist_follow:
      stalk_follow_s = 0.0  # planner falls back to normal profile; no speed/engage changes

    # Messages needed by carcontroller
    self.msg_stw_actn_req = copy.copy(cp.vl["STW_ACTN_RQ"])
    self.acc_state = cp_cam.vl["DAS_control"]["DAS_accState"]
    self.das_control_counters.extend(cp_cam.vl_all["DAS_control"]["DAS_controlCounter"])
    # Model S only. Cluster substitution is not used on Model X.
    self.cluster_stock = self.new_cluster_frames(cp_cam) if ap1_s else {}
    # Structural AP1: stock 0x488 counters for the steer handover.
    if ap1:
      steer_ctrs = cp_cam.vl_all.get("DAS_steeringControl", {}).get("DAS_steeringControlCounter", [])
      self.stock_steer_counters = [int(c) for c in steer_ctrs]

    # Model S: Mobileye fused (stock 0x399 on cp_cam / bus 2) then GTW UI map/mpp
    # into BogPilot dashboardSpeedLimit (m/s). Cluster TX is on bus 0 and
    # never reaches cp_cam. Freq-0 UI msgs on chassis; missing → 0.
    # Model S: stock Autopilot active (stock 0x399 on bus 2, state 3/4/5). Gates the
    # standstill-experiment standby DAS_control (Tinkla: not while stock AP).
    if ap1_s:
      st = cp_cam.vl.get("AutopilotStatus", {}).get("autopilotStatus", 0)
      self.stock_ap_active = 3 <= int(st or 0) <= 5
    # AP1 S and X: Mobileye fused (optional on X) then GTW UI map/mpp into dashboardSpeedLimit.
    # Cluster substitution, BSM, and regen inputs stay Model S only.
    if ap1:
      fused = cp_cam.vl.get("AutopilotStatus", {}).get("DAS_fusedSpeedLimit")
      ui_map = cp.vl.get("UI_driverAssistMapData", {}).get("UI_mapSpeedLimit")
      gps = cp.vl.get("UI_gpsVehicleSpeed", {})
      # Base-map guard inputs (speed_limit.py). The camera-only limit shares the fused frame; stale = no camera
      # limit. The base map is only passed once the car has sent it this drive: a car that never sends 0x238 mux 3
      # keeps the previous result instead of having every map-only limit ignored.
      guard = self.base_map_guard_args(cp, cp_cam)
      fp_ret.dashboardSpeedLimit = dashboard_speed_limit_ms(
        fused, ui_map, gps.get("UI_mppSpeedLimit"), gps.get("UI_mapSpeedLimitUnits"), **guard,
      )
      self.dash_hold_ms = fp_ret.dashboardSpeedLimit
      # Engage set: only fresh frames (optional messages keep their last value; stale = unknown).
      fresh_gps = frame_fresh(cp, "UI_gpsVehicleSpeed")
      engage_limit_ms = dashboard_speed_limit_ms(
        fused if frame_fresh(cp_cam, "AutopilotStatus") else None,
        ui_map if frame_fresh(cp, "UI_driverAssistMapData") else None,
        gps.get("UI_mppSpeedLimit") if fresh_gps else None,
        gps.get("UI_mapSpeedLimitUnits") if fresh_gps else None,
        **guard,
      )
      if not fresh_gps:
        # Units (UI_mapSpeedLimitUnits, 0x2F8) unknown or stale -> no limit-based engage set; a fused
        # AutopilotStatus value could be a kph sign read as mph (units_are_metric falls back to MPH).
        # Model S and Model X. Falls through to vEgo / tap / NO_ENTRY.
        engage_limit_ms = 0.0
    else:
      engage_limit_ms = 0.0

    if self.op_long_set is not None:
      # openpilot long: openpilot's own set, never DI_cruiseSet (it follows ego speed and is 0 at every stop;
      # VCruiseHelper reads 0 as unset). Tinkla carstate.py:312-313 / ACC_module.py:154-158 @501c7de for the
      # latch; BogPilot 0.9.7 SLC limit + offset for the engage set. 0 while not engaged (no DI seed).
      ButtonType = structs.CarState.ButtonEvent.Type
      tap = any(be.pressed and be.type in (ButtonType.accelCruise, ButtonType.decelCruise) for be in ret.buttonEvents)
      # Pull toward the driver: resumeCruise = SpdCtrlLvr_Stat 2 (values.py BUTTONS). Only a pull engages at limit+offset.
      pull = any(be.pressed and be.type == ButtonType.resumeCruise for be in ret.buttonEvents)
      tap_zero = self.op_long_tap_from_zero() if self.op_long_tap_from_zero is not None else None
      ret.cruiseState.speed = self.op_long_set.update(cruise_state, ret.vEgoRaw, ret.standstill,
                                                      limit_ms=engage_limit_ms,
                                                      offset_fn=self.op_long_offset, tap=tap,
                                                      tap_from_zero_kph=tap_zero, pull=pull,
                                                      is_metric=(speed_units == "KPH"))
      fp_ret.ap1SpeedLimitUnknown = self.op_long_set.speed_limit_unknown

    # 0x108 motor torque (Nm) and RPM, raw decoded values (SNA stays -1024 Nm / -32768 rpm). Published for Model S and
    # Model X: the onroad pedal gauge's regen bar reads them on every legacy platform. The regen-aware stop shaping
    # (regen_aware.py via ap1_planning) runs on the Model S and the Model X with openpilot longitudinal; it is gated on the
    # fingerprint, not on these fields.
    fp_ret.ap1MotorTorqueNm = float(cp.vl["DI_torque1"]["DI_torqueMotor"])
    fp_ret.ap1MotorRpm = float(cp.vl["DI_torque1"]["DI_motorRPM"])
    self._update_drive_detect(cp, ret.vEgoRaw, fp_ret)
    if ap1:
      self._update_ride_height(cp)
    if ap1_s or self.CP.carFingerprint == CAR.TESLA_AP1_MODELX:
      # Model S and Model X. Regen-aware stop braking inputs (regen_aware.py): ambient temperature. The Model X sends
      # 0x208 as a 4-byte frame (the DBC says 8); GTW_ambientTemperature is byte 1, so it decodes the same.
      amb = cp.vl.get("GTW_ESP1", {})
      amb_seen = getattr(cp, "ts_nanos", {}).get("GTW_ESP1", {}).get("GTW_ambientTemperature", 0)
      fp_ret.ap1AmbientTempC = float(amb["GTW_ambientTemperature"]) if amb_seen else float("nan")

    # AP1 state for openpilot-side events and BogPilot planners (0.9.7 read
    # these off CarState/CarController directly; 0.11 goes through carState).
    fp_ret.spdCtrlLvr = max(0, min(255, int(self.spd_ctrl_lvr)))
    if ap1:
      # DI_brakePedalState (DI_torque2, stock DBC): iBooster applied, driver or OP. For the onroad decel bar colour ONLY
      # (BogPilot divergence); nothing in controls, the planner or safety reads it. SNA (3) when stale. Pre-AP keeps 3.
      fp_ret.ap1BrakePedalState = brake_pedal_state(cp.vl["DI_torque2"]["DI_brakePedalState"],
                                                    frame_fresh(cp, "DI_torque2", DI_BRAKE_STATE_MAX_AGE_S))
      # Continuous UP/DN/RWD levels (button_states, not 10 ms buttonEvents) for the SLC software set and
      # confirmation (0.9.7 bogpilot_card._apply_ap1_stalk_levels). accelPressed is UP only, RWD is resumePressed.
      # Each level is at least STALK_LEVEL_HOLD_FRAMES wide (>= one planner tick) and ends at the release of a longer
      # press; a cancel (FWD) drops them all.
      ButtonType = structs.CarState.ButtonEvent.Type
      levels = self._held_stalk_levels(ButtonType)
      fp_ret.accelPressed = levels[ButtonType.accelCruise]
      fp_ret.decelPressed = levels[ButtonType.decelCruise]
      fp_ret.resumePressed = levels[ButtonType.resumeCruise]
    fp_ret.ap1HandsOnLevel = max(0, min(255, int(self.hands_on_level or 0)))
    fp_ret.ap1EacInhibited = self.eac_status == "EAC_INHIBITED"
    fp_ret.ap1StalkPullToggle = self.stalk_pull_toggle
    fp_ret.ap1StalkFwdToggle = self.stalk_fwd_toggle
    fp_ret.ap1StockApActive = bool(self.stock_ap_active)
    # Model S only. Stalk follow seconds stay 0 on Model X.
    fp_ret.ap1StalkFollowS = float(stalk_follow_s) if ap1_s else 0.0

    return ret

  def _update_drive_detect(self, cp, v_ego_raw, fp_ret) -> None:
    """0x186 front motor (NaN unless a fresh frame), the drive layout / Performance rear and the rpm per m/s of each motor.
    Display and comfort layers only (pedal gauge, regen-aware stop shaper); nothing in CarParams, the panda or safety."""
    front_seen = frame_fresh(cp, "DI_torque1Front", FRONT_MOTOR_MAX_AGE_S)
    front = cp.vl.get("DI_torque1Front", {}) if front_seen else {}
    front_tq = float(front["DI_torqueMotorFront"]) if front_seen else float("nan")
    front_rpm = float(front["DI_motorRPMFront"]) if front_seen else float("nan")
    fwd = None
    if frame_fresh(cp, "GTW_carConfig", CAR_CONFIG_MAX_AGE_S):
      try:
        fwd = int(cp.vl["GTW_carConfig"]["GTW_fourWheelDrive"])
      except (KeyError, TypeError, ValueError):
        fwd = None
    det = self.drive_detect
    det.update(v_ego_raw, fp_ret.ap1MotorRpm, front_rpm, front_seen, fwd)
    fp_ret.ap1FrontMotorTorqueNm = front_tq
    fp_ret.ap1FrontMotorRpm = front_rpm
    fp_ret.ap1DriveLayout = int(det.layout)
    fp_ret.ap1PerfRear = int(det.perf)
    fp_ret.ap1RearRpmPerMs = float(det.rear_k)
    fp_ret.ap1FrontRpmPerMs = float(det.front_k)
    fp_ret.ap1RpmPerMsMeasured = bool(det.measured)

  def _update_ride_height(self, cp) -> None:
    """0x308 frames from the touchscreen (rebuilt byte for byte) and the 0x398 air suspension flag. Lower on Park only."""
    rows = cp.vl_all.get("UI_rideHeightRequest", {})
    cols = [rows.get(f"UI_rideHeightByte{i}", []) for i in range(8)]
    n = min((len(c) for c in cols), default=0)
    self.ride_height_frames = [bytes(int(cols[i][k]) & 0xFF for i in range(8)) for k in range(n)]
    if n:
      self.ride_height_last = self.ride_height_frames[-1]
    ts = getattr(cp, "ts_nanos", {}).get("UI_rideHeightRequest")
    last = max(ts.values()) if ts else 0
    now = getattr(cp, "_last_update_nanos", 0) or 0
    self.ride_height_age_s = (now - last) * 1e-9 if (last > 0 and self.ride_height_last is not None) else float("inf")
    if frame_fresh(cp, "GTW_carConfig", CAR_CONFIG_MAX_AGE_S):
      air = ride_height.air_suspension_from_car_config(cp.vl["GTW_carConfig"]["GTW_airSuspensionInstalled"])
      if air is not None and air != self.air_suspension:
        self.air_suspension = air
        ride_height.write_air_suspension_detected(air)   # only on a change; the Vehicle Controls row reads it

  def _held_stalk_levels(self, ButtonType) -> dict:
    """Continuous UP/DN/RWD levels from button_states, each at least STALK_LEVEL_HOLD_FRAMES wide from the press.

    The minimum width counts from the press edge, not from the release: a press longer than it ends at its release,
    so the planner's measured hold (Ap1RaiseHoldoff TIP_HOLD_S) and the shown set follow the stalk with no 50 ms tail.
    """
    cancel = bool(self.button_states.get(ButtonType.cancel, False))
    out = {}
    for bt in (ButtonType.accelCruise, ButtonType.decelCruise, ButtonType.resumeCruise):
      pressed = bool(self.button_states.get(bt, False))
      if pressed and not self.stalk_level_prev.get(bt, False):
        left = STALK_LEVEL_HOLD_FRAMES   # press edge: this frame starts the minimum width
      else:
        left = max(int(self.stalk_level_hold.get(bt, 0)) - 1, 0)
      self.stalk_level_prev[bt] = pressed
      if cancel:
        left = 0
        pressed = False
      self.stalk_level_hold[bt] = left
      out[bt] = pressed or left > 0
    return out

  def base_map_guard_args(self, cp, cp_cam):
    """Optional dashboard_speed_limit_ms args for the base-map guard. {} until a 0x238 mux 3 frame is seen.

    The parser decodes every signal of a multiplexed frame, so UI_baseMapSpeedLimitMPS is only taken from frames
    whose UI_roadSign is 3 (vl_all keeps one entry per frame in order).
    """
    sign = cp.vl_all.get("UI_driverAssistRoadSign", {})
    for mux, value in zip(sign.get("UI_roadSign", []), sign.get("UI_baseMapSpeedLimitMPS", []), strict=False):
      if int(mux) == 3:
        self.base_map_ms = float(value)
        self.base_map_nanos = int(getattr(cp, "_last_update_nanos", 0) or 0)
    if self.base_map_nanos <= 0:
      return {}
    now = int(getattr(cp, "_last_update_nanos", 0) or 0)
    fresh = (now - self.base_map_nanos) <= LIMIT_MAX_AGE_S * 1e9
    vision = cp_cam.vl.get("AutopilotStatus", {}).get("DAS_visionOnlySpeedLimit")
    return {
      "vision_phys": vision if frame_fresh(cp_cam, "AutopilotStatus") else None,
      "base_map_ms": self.base_map_ms if fresh else None,
      "hold_ms": self.dash_hold_ms,
    }

  @staticmethod
  def new_cluster_frames(cp_cam):
    """Stock AutopilotStatus / DAS_status2 / DAS_lanes received this step.

    A frame counts as new when its counter signal has a value in vl_all for
    this update. vl holds the newest decoded values of that frame.
    """
    out = {}
    for addr in CLUSTER_ADDRS:
      name = MSG_NAMES[addr]
      if len(cp_cam.vl_all[name].get(COUNTER_SIGNALS[addr], [])):
        out[addr] = dict(cp_cam.vl[name])
    return out

  @staticmethod
  def get_can_parsers(CP):
    messages = [
      # sig_address, frequency
      ("ESP_B", 50),
      ("DI_torque1", 100),
      ("DI_torque2", 100),
      ("STW_ANGLHP_STAT", 100),
      ("EPAS_sysStatus", 25),
      ("DI_state", 10),
      ("STW_ACTN_RQ", 10),
      ("GTW_carState", 10),
      ("BrakeMessage", 50),
      # 0x39D brake level for the onroad decel bar (display only). Frequency 0 so a car without it does not trip canValid.
      ("BrakeBoosterStroke", OPTIONAL),
      # Trim detection (trims.py, display and comfort only): 0x186 front drive inverter (dual-motor cars only) and 0x398
      # GTW_carConfig. Frequency 0: a single-motor car (no 0x186) or a missing 0x398 never trips canValid.
      ("DI_torque1Front", OPTIONAL),
      ("GTW_carConfig", OPTIONAL),
    ]
    if is_ap1_family(CP.carFingerprint):
      # Lower on Park (ride_height.py): the touchscreen's ride height request 0x308. Frequency 0 (no canValid effect).
      messages.append(("UI_rideHeightRequest", OPTIONAL))

    # Model X seatbelt is RCM_status (0x211). SDM1 stays in this slot for Model S.
    if CP.carFingerprint == CAR.TESLA_AP1_MODELX:
      messages.append(("RCM_status", 10))
    else:
      messages.append(("SDM1", 10))

    if CP.carFingerprint == CAR.TESLA_AP1_MODELS:
      # GTW map / mpp speed limits for dashboardSpeedLimit. Frequency 0 so a
      # car without them does not trip canValid (same pattern as cluster RX).
      messages.append(("UI_driverAssistMapData", OPTIONAL))
      messages.append(("UI_gpsVehicleSpeed", OPTIONAL))
      # GTW base-map limit (0x238 mux 3) for the dashboard limit guard. Frequency 0, same reason.
      messages.append(("UI_driverAssistRoadSign", OPTIONAL))
      # EPB EAC allow (0x214) for the EPB revoke fault. Frequency 0, same reason.
      messages.append(("EPB_epasControl", OPTIONAL))
      # 0x208 outside air temperature for regen_aware.py. Frequency 0 (no canValid effect).
      messages.append(("GTW_ESP1", OPTIONAL))
    elif CP.carFingerprint == CAR.TESLA_AP1_MODELX:
      # Model X dashboard SLC uses the same GTW map / mpp frames as Model S.
      # Frequency 0 so missing frames do not trip canValid.
      messages.append(("UI_driverAssistMapData", OPTIONAL))
      messages.append(("UI_gpsVehicleSpeed", OPTIONAL))
      messages.append(("UI_driverAssistRoadSign", OPTIONAL))
      messages.append(("EPB_epasControl", OPTIONAL))
      # 0x208 outside air temperature for regen_aware.py (cold regen ceiling). Frequency 0 (no canValid effect).
      messages.append(("GTW_ESP1", OPTIONAL))

    cam_messages = [
      # sig_address, frequency
      ("DAS_control", 40),
    ]

    if CP.carFingerprint == CAR.TESLA_AP1_MODELS:
      # Stock cluster frames for the AP1 cluster substitution. Frequency 0:
      # the parser never marks them missing or timed out, so they cannot
      # change canValid. A car without them just gets no cluster frames.
      for addr in CLUSTER_ADDRS:
        cam_messages.append((MSG_NAMES[addr], OPTIONAL))
      # Stock 0x488 counter for handover continuity (steer_counter.py).
      # Frequency 0: missing stock frames fall back to the old cadence.
      cam_messages.append(("DAS_steeringControl", OPTIONAL))
    elif CP.carFingerprint == CAR.TESLA_AP1_MODELX:
      # Model X follows the stock 0x488 counter. Cluster substitution stays Model S only,
      # but AutopilotStatus is subscribed so DAS_fusedSpeedLimit can fill Dashboard when present.
      cam_messages.append(("AutopilotStatus", OPTIONAL))
      cam_messages.append(("DAS_steeringControl", OPTIONAL))

    return {
      Bus.chassis: CANParser(DBC[CP.carFingerprint][Bus.chassis], messages, CANBUS.chassis),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.chassis], cam_messages, CANBUS.autopilot_chassis),
    }
