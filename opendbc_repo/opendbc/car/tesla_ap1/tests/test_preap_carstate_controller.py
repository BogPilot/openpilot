"""Pre-AP CarState (stalk pull -> engagement -> cruiseState / preapLatOnly) and CarController (0x488 + 0x214, pedal gating)."""
from types import SimpleNamespace

import pytest

from opendbc.can import CANDefine
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, structs
from opendbc.car.tesla_ap1.preap import calib, params
from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
from opendbc.car.tesla_ap1.tests.ap1_harness import decode
from opendbc.car.tesla_ap1.values import CAR, DBC

PULL, CANCEL = 2, 1
DBC_NAME = DBC[CAR.TESLA_PREAP_MODELS][Bus.chassis]


AOL = [True]       # most tests here exercise the pull logic as if Always On Lateral were available; the inert tests flip this off
CLOCK = [1000.0]   # fake time.monotonic seconds; Rig.frame advances it 10 ms per frame


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  CLOCK[0] = 1000.0
  AOL[0] = True
  monkeypatch.setattr(params, "aol_available", lambda: AOL[0])
  monkeypatch.setattr("opendbc.car.tesla_ap1.preap.carstate.time.monotonic", lambda: CLOCK[0])
  yield tmp_path


def _inv(msg, sig, name):
  dv = CANDefine(DBC_NAME).dv[msg][sig]
  return next(k for k, v in dv.items() if v == name)


class Rig:
  def __init__(self, long=True):
    self.CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=long)
    self.cs = PreApCarState(self.CP)
    self.parsers = PreApCarState.get_can_parsers(self.CP)
    self.packer = CANPacker(DBC_NAME)
    self.nanos = 0
    self.base = {
      "DI_torque2": {"DI_gear": _inv("DI_torque2", "DI_gear", "DI_GEAR_D")},
      "BrakeMessage": {"driverBrakeStatus": 1},
      "SDM1": {"SDM_bcklDrivStatus": 1},
      "DI_state": {"DI_cruiseState": _inv("DI_state", "DI_cruiseState", "STANDBY"), "DI_speedUnits": _inv("DI_state", "DI_speedUnits", "MPH")},
      "EPAS_sysStatus": {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0, "EPAS_eacStatus": _inv("EPAS_sysStatus", "EPAS_eacStatus", "EAC_AVAILABLE") if "EAC_AVAILABLE" in CANDefine(DBC_NAME).dv["EPAS_sysStatus"]["EPAS_eacStatus"].values() else 0},
      "ESP_B": {}, "DI_torque1": {}, "STW_ANGLHP_STAT": {"StW_AnglHP_Spd": 0.0}, "GTW_carState": {}, "STW_ACTN_RQ": {},
    }
    self.base["GTW_carState"] = {d: _inv("GTW_carState", d, "CLOSED") for d in ("DOOR_STATE_FL",) if "CLOSED" in CANDefine(DBC_NAME).dv["GTW_carState"][d].values()}

  def send(self, name, **values):
    v = dict(self.base.get(name, {}))
    v.update(values)
    addr, dat, bus = self.packer.make_can_msg(name, 0, v)
    pn = self.parsers[Bus.chassis]
    pn.update([(self.nanos, [(addr, dat, 0)])])

  def wait(self, ms):
    CLOCK[0] += ms / 1000.0

  def frame(self, stalk=0, op=False, brake=False, v_kph=50.0, **extra):
    self.nanos += 10_000_000
    CLOCK[0] += 0.01
    for n in self.base:
      if n == "STW_ACTN_RQ":
        self.send(n, SpdCtrlLvr_Stat=stalk)
      elif n == "BrakeMessage" and brake:
        self.send(n, driverBrakeStatus=2)
      elif n == "ESP_B":
        self.send(n, ESP_vehicleSpeed=v_kph)
      else:
        self.send(n)
    self.cs.op_enabled = op
    return self.cs.update(self.parsers)


def test_parsers_have_no_autopilot_messages():
  r = Rig()
  assert "GAS_SENSOR" in (r.parsers[Bus.cam].vl if params and r.cs.pedal_bus == 2 else r.parsers[Bus.chassis].vl)
  assert "DAS_control" not in r.parsers[Bus.cam].vl and "AutopilotStatus" not in r.parsers[Bus.cam].vl


def test_shipped_aol_gate_is_closed(monkeypatch):
  import importlib
  real = importlib.import_module("opendbc.car.tesla_ap1.preap.params")
  monkeypatch.undo()                                   # the real, unpatched gate
  real.register_aol_provider(None)
  assert real.aol_available() is False                 # no provider registered (this build)
  assert real.double_pull_enabled() is False


def test_aol_gate_follows_only_a_provider_that_answers_exactly_true(monkeypatch):
  import importlib
  real = importlib.import_module("opendbc.car.tesla_ap1.preap.params")
  monkeypatch.undo()
  try:
    for answer, want in ((True, True), (False, False), (None, False), (1, False), ("yes", False)):
      real.register_aol_provider(lambda a=answer: a)
      assert real.aol_available() is want, answer
    def boom():
      raise RuntimeError("policy crashed")
    real.register_aol_provider(boom)
    assert real.aol_available() is False               # a crashing policy is closed, not open
  finally:
    real.register_aol_provider(None)


def test_saved_double_pull_is_kept_but_inert_without_aol():
  # Branch default is ON, so a fresh install has it saved ON. With AOL unavailable the first pull still engages steering AND pedal long.
  assert params.get_bool(params.PreApParamKeys.DOUBLE_PULL) is True
  AOL[0] = False
  assert params.double_pull_enabled() is False
  r = Rig()
  r.frame()
  out = r.frame(stalk=PULL)
  assert out.cruiseState.enabled and not out.bogpilot.preapLatOnly
  assert params.get_bool(params.PreApParamKeys.DOUBLE_PULL) is True          # the saved choice is never rewritten
  AOL[0] = True
  assert params.double_pull_enabled() is True


def test_single_pull_sets_cruise_enabled_and_enable_request():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, False)
  r = Rig()
  out = r.frame(stalk=0)
  assert not out.cruiseState.enabled
  out = r.frame(stalk=PULL)
  assert out.cruiseState.enabled and not out.bogpilot.preapLatOnly
  assert r.cs.update_button_enable(out.buttonEvents) is True
  out = r.frame(stalk=0, op=True)
  assert out.cruiseState.enabled and r.cs.update_button_enable(out.buttonEvents) is False


def test_double_pull_first_pull_is_an_aol_lateral_intent_and_second_engages():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, True)
  r = Rig()
  r.frame()
  out = r.frame(stalk=PULL)
  assert out.bogpilot.preapAolLat and not out.cruiseState.enabled and not out.bogpilot.preapLatOnly
  assert r.cs.update_button_enable(out.buttonEvents) is False      # openpilot is NOT asked to engage
  out = r.frame(stalk=0)
  assert out.bogpilot.preapAolLat and not out.cruiseState.enabled
  r.wait(50)
  out = r.frame(stalk=PULL)
  assert out.cruiseState.enabled and not out.bogpilot.preapAolLat and not out.bogpilot.preapLatOnly
  assert r.cs.update_button_enable(out.buttonEvents) is True


def test_double_pull_second_pull_after_the_400ms_window_stays_an_aol_intent():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, True)
  r = Rig()
  r.frame(); r.frame(stalk=PULL); r.frame()
  r.wait(450)
  r.frame()
  out = r.frame(stalk=PULL)
  assert out.bogpilot.preapAolLat and not out.cruiseState.enabled


def test_double_pull_intent_is_dropped_when_aol_goes_away_and_is_not_promoted():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, True)
  r = Rig()
  r.frame(); out = r.frame(stalk=PULL)
  assert out.bogpilot.preapAolLat
  AOL[0] = False
  out = r.frame()
  assert not out.bogpilot.preapAolLat and not out.cruiseState.enabled


def test_aol_lat_flag_is_false_in_single_pull_mode():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, False)
  r = Rig()
  r.frame(); out = r.frame(stalk=PULL)
  assert out.cruiseState.enabled and not out.bogpilot.preapAolLat


def test_cancel_stalk_disengages():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, False)
  r = Rig()
  r.frame(); r.frame(stalk=PULL); r.frame(op=True)
  r.wait(700)                                  # past the 600 ms own-spoof echo window
  out = r.frame(stalk=CANCEL, op=True)
  assert not out.cruiseState.enabled


def test_cancel_within_600ms_of_a_stalk_press_while_enabled_is_swallowed_as_an_echo():
  # Documents the ported echo rule (cruise.is_preap_cancel_echo). Listed in the port notes.
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, False)
  r = Rig()
  r.frame(); r.frame(stalk=PULL); r.frame(op=True)
  r.wait(200)
  out = r.frame(stalk=CANCEL, op=True)
  assert out.cruiseState.enabled


def test_brake_and_non_drive_gear_clear_long_wanted():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, False)
  r = Rig()
  r.frame(); r.frame(stalk=PULL); r.frame(op=True)
  out = r.frame(op=True, brake=True)
  assert out.brakePressed and out.cruiseState.enabled and out.bogpilot.preapLatOnly
  r.base["DI_torque2"]["DI_gear"] = _inv("DI_torque2", "DI_gear", "DI_GEAR_P")
  out = r.frame(op=True)
  assert not out.cruiseState.enabled


def test_steer_fault_temporary_never_set_and_stock_aeb_false():
  r = Rig()
  out = r.frame()
  assert out.steerFaultTemporary is False and out.stockAeb is False


def test_no_pedal_mode_follows_stock_tacc():
  r = Rig(long=False)
  r.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", "ENABLED")
  assert r.frame().cruiseState.enabled
  out = r.frame(stalk=PULL)           # a pull must not invent an engagement in stock-TACC mode
  assert r.cs.update_button_enable(out.buttonEvents) is False


def test_available_needs_pedal_detected_and_calibrated():
  r = Rig()
  assert not r.frame().cruiseState.available
  calib.apply_calibration_result(calib.compute_calibration(0.8, 107.0))
  assert not r.frame().cruiseState.available          # calibrated but pedal not detected
  r.cs.preap_pedal_detected = True
  r.cs.pedal_timeout = False
  out = r.frame()
  assert out.bogpilot.preapPedalCalibrated


def _cc(enabled=False, lat=False, long_active=False, angle=0.0):
  act = structs.CarControl.Actuators.new_message(steeringAngleDeg=angle)
  return structs.CarControl.new_message(enabled=enabled, latActive=lat, longActive=long_active, actuators=act).as_reader()


def _controller(long=True):
  CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=long)
  return PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], CP)


def _frames(sends):
  return {(f.address if hasattr(f, "address") else f[0]): f for f in sends}


def test_controller_sends_488_and_214_with_eacallow_and_idle_holds_angle():
  ctl = _controller(long=False)
  cs = SimpleNamespace(hands_on_level=0, out=SimpleNamespace(vEgo=10.0, steeringAngleDeg=12.5), di_gas=0.0,
                       preap_pedal_detected=False, preap_pedal_raw=None, preap_cc_cancel_needed=False)
  _, sends = ctl.update(_cc(), cs, 0)
  by = {}
  for s in sends:
    addr, dat = (s.address, s.dat) if hasattr(s, "address") else (s[0], s[1])
    by[addr] = dat
  assert 0x488 in by and 0x214 in by
  name, v = decode(0x214, by[0x214])
  assert name == "EPB_epasControl" and v["EPB_epasEACAllow"] == 1
  name, v = decode(0x488, by[0x488])
  # raw EPAS sign is the inverse of steeringAngleDeg
  assert abs(v["DAS_steeringAngleRequest"] + 12.5) < 0.2 and v["DAS_steeringControlType"] == 0


def test_controller_pedal_command_only_when_allowed_and_long_active():
  ctl = _controller(long=True)
  cs = SimpleNamespace(hands_on_level=0, out=SimpleNamespace(vEgo=10.0, steeringAngleDeg=0.0), di_gas=0.0,
                       preap_pedal_detected=True, preap_pedal_raw=0.8, preap_cc_cancel_needed=False)
  # lateral-only: no enabled pedal frame, ever
  for i in range(50):
    _, sends = ctl.update(_cc(enabled=True, lat=True, long_active=False), cs, i * 10_000_000)
    for s in sends:
      addr, dat = (s.address, s.dat) if hasattr(s, "address") else (s[0], s[1])
      if addr == 0x551:
        assert not dat[4] & 0x80


def _act(accel):
  return structs.CarControl.Actuators.new_message(accel=accel)


# ---- end to end: stalk -> CarState -> (controlsd-style CC) -> CarController -> 0x551 ----
def _pedal_frame(rig, idx, raw=0.8, state=0):
  addr, dat, _ = rig.packer.make_can_msg("GAS_SENSOR", 2, {"INTERCEPTOR_GAS": raw, "INTERCEPTOR_GAS2": raw * 2, "STATE": state, "IDX": idx % 16})
  rig.parsers[Bus.cam].update([(rig.nanos, [(addr, dat, 2)])])


def _drive(rig, ctl, stalk_at, frames, *, pulls=(), idx0=0):
  """Run `frames` 10 ms steps. `pulls` = frame numbers with the stalk pulled. Returns (enabled pedal frames, outs)."""
  enabled, outs, op_enabled = 0, [], False
  for n in range(frames):
    _pedal_frame(rig, idx0 + n)
    out = rig.frame(stalk=PULL if n in pulls else 0, op=op_enabled)
    rig.cs.out = out
    # what controlsd does: enabled follows buttonEnable / cruiseState, longActive = enabled and not the lat-only override event
    enable_req = rig.cs.update_button_enable(out.buttonEvents)
    op_enabled = bool(op_enabled and out.cruiseState.enabled) or bool(enable_req and out.cruiseState.available)
    long_active = op_enabled and not out.bogpilot.preapLatOnly
    # the AOL core (a stand-in here; the real one is the AOL lane's): latActive without enabled while preapAolLat is True
    lat_active = op_enabled or bool(out.bogpilot.preapAolLat)
    cc = structs.CarControl.new_message(enabled=op_enabled, latActive=lat_active, longActive=long_active, actuators=_act(0.3)).as_reader()
    _, sends = ctl.update(cc, rig.cs, rig.nanos)
    for sd in sends:
      addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
      if addr == 0x551 and dat[4] & 0x80:
        enabled += 1
      if addr == 0x488 and (dat[2] >> 6) == 1:
        rig.lat_frames = getattr(rig, "lat_frames", 0) + 1
    outs.append((op_enabled, long_active, out))
  return enabled, outs


def _ready_rig(double):
  calib.apply_calibration_result(calib.compute_calibration(0.8, 107.0))
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, double)
  rig = Rig()
  return rig, PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP)


def test_e2e_single_pull_drives_the_pedal():
  rig, ctl = _ready_rig(double=False)
  enabled, outs = _drive(rig, ctl, 0, 300, pulls={20})
  assert outs[-1][0] and outs[-1][1], "engaged with long active"
  assert enabled > 20


def test_e2e_double_pull_first_pull_steers_via_aol_and_never_drives_the_pedal_second_pull_does():
  rig, ctl = _ready_rig(double=True)
  enabled, outs = _drive(rig, ctl, 0, 300, pulls={20})
  assert not outs[-1][0] and not outs[-1][1], "openpilot not engaged: AOL lateral only"
  assert outs[-1][2].bogpilot.preapAolLat
  assert enabled == 0
  assert getattr(rig, "lat_frames", 0) > 50, "steering is active (0x488 control type ANGLE) from the AOL latActive"
  rig, ctl = _ready_rig(double=True)
  enabled, outs = _drive(rig, ctl, 0, 300, pulls={20, 45})        # 250 ms apart
  assert outs[-1][0] and outs[-1][1]
  assert enabled > 20


def test_e2e_double_pull_without_the_aol_consumer_never_steers_or_drives():
  # AOL provider says yes but nothing acts on preapAolLat (e.g. a half-wired AOL lane): the first pull must do nothing dangerous
  rig, ctl = _ready_rig(double=True)
  enabled, outs = 0, []
  for n in range(120):
    _pedal_frame(rig, n)
    out = rig.frame(stalk=PULL if n == 20 else 0, op=False)
    rig.cs.out = out
    cc = structs.CarControl.new_message(enabled=False, latActive=False, longActive=False, actuators=_act(0.3)).as_reader()
    _, sends = ctl.update(cc, rig.cs, rig.nanos)
    for sd in sends:
      addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
      assert not (addr == 0x551 and dat[4] & 0x80)
      assert not (addr == 0x488 and (dat[2] >> 6) == 1)


def test_e2e_uncalibrated_or_no_pedal_never_drives():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, False)
  rig = Rig(); ctl = PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP)
  assert not calib.is_pedal_calibrated()
  enabled, outs = _drive(rig, ctl, 0, 200, pulls={20})
  assert enabled == 0
  assert not outs[-1][0], "not available (uncalibrated): the pull must not engage"


# ---- regression: a spoofed STW_ACTN_RQ must never change the wiper stalk position (WprSw6Posn) or other live stalk fields ----
def ctl_crc(rig, dat):
  return PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP).tesla_can.crc(dat[:7])


def _spoof(wiper, cancel=True, **extra):
  """Live frame -> CarState copy -> TeslaCAN.create_action_request, exactly as StockCCSpoofer does."""
  from opendbc.car.tesla_ap1.preap.stock_cc_spoofer import StockCCSpoofer
  rig = Rig()
  live = {"WprSw6Posn": wiper, "SpdCtrlLvr_Stat": 2, "WprWashSw_Psd": 1, "WprWash_R_Sw_Posn_V2": 2, "HiBmLvr_Stat": 1,
          "TurnIndLvr_Stat": 2, "StW_Sw05_Psd": 1, "HrnSw_Psd": 1, "DTR_Dist_Rq": 120, "MC_STW_ACTN_RQ": 9}
  live.update(extra)
  rig.base["STW_ACTN_RQ"] = live
  rig.frame()
  ctl = PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP)
  rig.cs.preap_cc_cancel_needed = True
  sent = []
  for frame in range(0, 40):
    sent += ctl.stock_cc.update(rig.cs, frame, ctl.tesla_can, 0)
  assert sent, "the spoofer must send one cancel"
  return rig, sent, StockCCSpoofer


@pytest.mark.parametrize("wiper", range(8))
def test_wiper_position_survives_the_cancel_spoof(wiper):
  rig, sent, _ = _spoof(wiper)
  for f in sent:
    addr, dat = (f.address, f.dat) if hasattr(f, "address") else (f[0], f[1])
    assert addr == 0x45
    name, v = decode(0x45, dat)
    assert name == "STW_ACTN_RQ"
    assert v["WprSw6Posn"] == wiper                           # the one field under test
    assert v["SpdCtrlLvr_Stat"] == 1                          # it is a cancel
    # everything else the driver was doing is carried over, not zeroed
    assert (v["WprWashSw_Psd"], v["WprWash_R_Sw_Posn_V2"], v["HiBmLvr_Stat"], v["TurnIndLvr_Stat"]) == (1, 2, 1, 2)
    assert (v["StW_Sw05_Psd"], v["HrnSw_Psd"], v["DTR_Dist_Rq"]) == (1, 1, 120)
    assert v["MC_STW_ACTN_RQ"] == 10                           # live counter + 1
    assert dat[7] == ctl_crc(rig, dat)                         # CRC is valid for the modified frame


@pytest.mark.parametrize("wiper", range(8))
@pytest.mark.parametrize("cancel", [True, False])
def test_create_action_request_preserves_wiper_for_any_frame(wiper, cancel):
  rig = Rig()
  rig.base["STW_ACTN_RQ"] = {"WprSw6Posn": wiper}
  rig.frame()
  ctl = PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP)
  msg = ctl.tesla_can.create_action_request(rig.cs.msg_stw_actn_req, cancel, 0, 3)
  addr, dat = (msg.address, msg.dat) if hasattr(msg, "address") else (msg[0], msg[1])
  _, v = decode(addr, dat)
  assert v["WprSw6Posn"] == wiper


def test_spoof_crc_matches_the_frame_it_protects():
  rig = Rig()
  rig.base["STW_ACTN_RQ"] = {"WprSw6Posn": 5, "MC_STW_ACTN_RQ": 3}
  rig.frame()
  ctl = PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP)
  msg = ctl.tesla_can.create_action_request(rig.cs.msg_stw_actn_req, True, 0, 4)
  dat = msg.dat if hasattr(msg, "dat") else msg[1]
  assert dat[7] == ctl.tesla_can.crc(dat[:7])


def test_e2e_double_pull_saved_on_without_aol_still_drives_the_pedal_on_one_pull():
  rig, ctl = _ready_rig(double=True)
  AOL[0] = False
  enabled, outs = _drive(rig, ctl, 0, 300, pulls={20})
  assert outs[-1][0] and outs[-1][1], "single pull: steering and long together"
  assert enabled > 20
