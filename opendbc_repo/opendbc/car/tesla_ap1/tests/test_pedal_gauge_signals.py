"""Car-state inputs of the onroad 3-bar pedal gauge, through the real DBC packer and CANParser: 0x108 motor torque and
RPM published on AP1 Model S, AP1 Model X and Pre-AP; DI_pedalPos SNA reads as missing; the Pre-AP brake level is binary
by default and follows 0x554 BrakePedalPosition with the iBooster swap toggle (missing / stale / fault -> -1)."""
import math
from types import SimpleNamespace

import pytest

from opendbc.can import CANParser
from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1 import pedal_signals as PS
from opendbc.car.tesla_ap1.brake_level import BRAKE_LEVEL_MISSING
from opendbc.car.tesla_ap1.carstate import CarState as Ap1CarState
from opendbc.car.tesla_ap1.preap import ibooster as IBST, params
from opendbc.car.tesla_ap1.values import CAR, DBC
from opendbc.car.tesla_ap1.tests.test_preap_gas_threshold import CLOCK, StockRig, _ap1_send, _params_dir  # noqa: F401

DBC_AP1 = "tesla_ap1_can"


def ap1_feed(car, frames):
  """frames: list of DI_torque1 value dicts. Returns the CarStates."""
  cp = SimpleNamespace(carFingerprint=car)
  state, parsers = Ap1CarState(cp), Ap1CarState.get_can_parsers(cp)
  packer = CANPacker(DBC[car][Bus.chassis])
  chassis = parsers[Bus.chassis]
  out = []
  for di in frames:
    _ap1_send(chassis, packer, "DI_torque1", di)
    _ap1_send(chassis, packer, "ESP_B", {"ESP_vehicleSpeed": 50.0})
    _ap1_send(chassis, packer, "BrakeMessage", {"driverBrakeStatus": 1})
    _ap1_send(chassis, packer, "EPAS_sysStatus", {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0})
    _ap1_send(chassis, packer, "STW_ANGLHP_STAT", {"StW_AnglHP_Spd": 0.0})
    _ap1_send(chassis, packer, "DI_torque2", {"DI_gear": 4})
    _ap1_send(chassis, packer, "DI_state", {})
    _ap1_send(chassis, packer, "SDM1", {"SDM_bcklDrivStatus": 1})
    out.append(state.update(parsers))
  return out


class Rig(StockRig):
  """Pre-AP stock rig with chosen DI_torque1 values, brake press and optional 0x554 frames."""

  def step(self, di=None, pressed=False, ibst=None):
    self.nanos += 10_000_000
    CLOCK[0] += 0.01
    for n in self.base:
      if n == "DI_torque1":
        self.send(n, **(di or {}))
      elif n == "BrakeMessage":
        self.send(n, driverBrakeStatus=2 if pressed else 1)
      else:
        self.send(n)
    if ibst is not None:
      self.send(IBST.MSG, **ibst)
    return self.cs.update(self.parsers)


@pytest.mark.parametrize("car", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_ap1_s_and_x_publish_motor_torque_and_rpm(car):
  o = ap1_feed(car, [{"DI_torqueMotor": -80.0, "DI_motorRPM": 6000}])[-1]
  assert o.bogpilot.ap1MotorTorqueNm == -80.0
  assert o.bogpilot.ap1MotorRpm == 6000.0


@pytest.mark.parametrize("car", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_ap1_sna_stays_raw(car):
  # SNA is published as decoded (-1024 Nm, -32768 rpm) so the gauge can fail closed; it is never replaced by a guess
  o = ap1_feed(car, [{"DI_torqueMotor": -1024.0, "DI_motorRPM": -32768}])[-1]
  assert (o.bogpilot.ap1MotorTorqueNm, o.bogpilot.ap1MotorRpm) == (-1024.0, -32768.0)


def test_preap_publishes_motor_torque_and_rpm():
  o = Rig().step(di={"DI_torqueMotor": -60.25, "DI_motorRPM": 4500})
  assert o.bogpilot.ap1MotorTorqueNm == -60.25
  assert o.bogpilot.ap1MotorRpm == 4500.0


def test_preap_dbc_has_the_0x108_signals():
  # Pre-AP uses the same chassis DBC; the signals the gauge needs exist there with the AP1 layout
  assert DBC[CAR.TESLA_PREAP_MODELS][Bus.chassis] == DBC_AP1
  cp = CANParser(DBC_AP1, [("DI_torque1", float("nan"))], 0)
  addr, dat, _ = CANPacker(DBC_AP1).make_can_msg("DI_torque1", 0, {"DI_torqueMotor": -100.0, "DI_motorRPM": -1234})
  assert addr == 0x108
  cp.update([(1_000_000, [(addr, dat, 0)])])
  assert (cp.vl["DI_torque1"]["DI_torqueMotor"], cp.vl["DI_torque1"]["DI_motorRPM"]) == (-100.0, -1234.0)


@pytest.mark.parametrize("pct,want", [(0.0, 0.0), (40.0, 0.4), (100.0, 1.0), (102.0, PS.PEDAL_MISSING),
                                      (101.6, PS.PEDAL_MISSING), (-1.0, PS.PEDAL_MISSING), (float("nan"), PS.PEDAL_MISSING),
                                      (None, PS.PEDAL_MISSING), ("x", PS.PEDAL_MISSING)])
def test_pedal_position(pct, want):
  assert PS.pedal_position(pct) == pytest.approx(want)


def test_pedal_sna_is_missing_on_ap1_and_preap():
  o = ap1_feed(CAR.TESLA_AP1_MODELS, [{"DI_pedalPos": 102.0}])[-1]       # raw 255 = SNA
  assert o.deprecated.gas == PS.PEDAL_MISSING and o.gasPressed               # gasPressed unchanged (raw > 0)
  o = Rig().step(di={"DI_pedalPos": 102.0})
  assert o.deprecated.gas == PS.PEDAL_MISSING


def test_preap_brake_binary_by_default():
  assert params.DEFAULTS[params.PreApParamKeys.HAS_IBOOSTER] is False
  r = Rig()
  assert r.cs.has_ibooster is False
  assert IBST.MSG not in r.parsers[Bus.chassis].vl                      # not subscribed with the toggle off
  assert r.step(pressed=False).deprecated.brake == 0.0
  o = r.step(pressed=True)
  assert o.brakePressed and o.deprecated.brake == 1.0
  # a 0x554 frame on the bus changes nothing while the toggle is off
  assert r.step(pressed=False, ibst={"BrakePedalPosition": 20.0, "BrakeOK": 1, "Status": 0}).deprecated.brake == 0.0


def _ibooster_on(tmp):
  (tmp / params.PreApParamKeys.HAS_IBOOSTER).write_text("1")


def test_preap_ibooster_proportional(_params_dir):
  _ibooster_on(_params_dir)
  r = Rig()
  assert r.cs.has_ibooster is True
  assert IBST.MSG in r.parsers[Bus.chassis].vl
  for mm in (0.0, 11.75, 23.5, 47.0, 55.0):   # 12-bit raw tops out at 58.98 mm
    o = r.step(pressed=mm > 0, ibst={"BrakePedalPosition": mm, "BrakeOK": 1, "Status": 0})
    assert o.deprecated.brake == pytest.approx(min(mm / IBST.IBOOSTER_PEDAL_FULL_MM, 1.0), abs=0.001)
  # brakePressed still comes from BrakeMessage / DI_brakePedal, not from the iBooster frame
  o = r.step(pressed=False, ibst={"BrakePedalPosition": 20.0, "BrakeOK": 1, "Status": 0})
  assert not o.brakePressed and o.deprecated.brake > 0


def test_preap_ibooster_fails_closed(_params_dir):
  _ibooster_on(_params_dir)
  r = Rig()
  assert r.step(pressed=True).deprecated.brake == BRAKE_LEVEL_MISSING        # never received
  assert r.step(pressed=True, ibst={"BrakePedalPosition": 20.0, "BrakeOK": 0, "Status": 0}).deprecated.brake == BRAKE_LEVEL_MISSING
  assert r.step(pressed=True, ibst={"BrakePedalPosition": 20.0, "BrakeOK": 1, "Status": 4}).deprecated.brake == BRAKE_LEVEL_MISSING
  assert r.step(pressed=True, ibst={"BrakePedalPosition": 20.0, "BrakeOK": 1, "Status": 0}).deprecated.brake > 0
  for _ in range(int(IBST.IBOOSTER_MAX_AGE_S / 0.01) + 5):                  # frames stop: stale
    o = r.step(pressed=True)
  assert o.deprecated.brake == BRAKE_LEVEL_MISSING


def test_ibooster_level_helper():
  ok = {"BrakePedalPosition": 23.5, "BrakeOK": 1, "Status": 0}
  assert IBST.ibooster_brake_level(ok, True) == pytest.approx(0.5)
  assert IBST.ibooster_brake_level(ok, False) == BRAKE_LEVEL_MISSING
  assert IBST.ibooster_brake_level(None, True) == BRAKE_LEVEL_MISSING
  assert IBST.ibooster_brake_level({**ok, "BrakePedalPosition": float("nan")}, True) == BRAKE_LEVEL_MISSING
  assert IBST.ibooster_brake_level({**ok, "BrakePedalPosition": -5.0}, True) == 0.0
  assert IBST.binary_brake_level(True) == 1.0 and IBST.binary_brake_level(False) == 0.0


def test_ibooster_dbc_matches_the_reference_layout():
  # BogGyver opendbc 9c0b6fe tesla_can.dbc BO_ 1364 ECU_BrakeStatus: 5 bytes, BrakePedalPosition 20|12@1+ (0.015625,-5) mm
  addr, dat, _ = CANPacker(DBC_AP1).make_can_msg(IBST.MSG, 0, {"BrakePedalPosition": 12.5, "BrakeOK": 1, "Status": 0})
  assert addr == IBST.ADDR == 0x554 and len(dat) == 5
  raw = (int.from_bytes(dat, "little") >> 20) & 0xFFF
  assert math.isclose(raw * 0.015625 - 5, 12.5)
  assert (dat[2] & 0x01) == 1                                              # BrakeOK at bit 16
