"""CarState.deprecated.gas carries DI_pedalPos / 100 (0..1) for the onroad pedal bars, through the real DBC packer and
CANParser on AP1 Model S, AP1 Model X and Pre-AP. gasPressed thresholds are unchanged (test_preap_gas_threshold)."""
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.carstate import CarState as Ap1CarState
from opendbc.car.tesla_ap1.values import CAR, DBC
from opendbc.car.tesla_ap1.tests.test_preap_gas_threshold import (StockRig, _ap1_send, _params_dir,  # noqa: F401
                                                                   pack_di_pedal_raw)


def ap1_feed(car, raws):
  cp = SimpleNamespace(carFingerprint=car)
  state, parsers = Ap1CarState(cp), Ap1CarState.get_can_parsers(cp)
  packer = CANPacker(DBC[car][Bus.chassis])
  chassis = parsers[Bus.chassis]
  out = []
  for raw in raws:
    addr, dat = pack_di_pedal_raw(packer, raw)
    chassis.update([(0, [(addr, dat, chassis.bus)])])
    _ap1_send(chassis, packer, "ESP_B", {"ESP_vehicleSpeed": 50.0})
    _ap1_send(chassis, packer, "BrakeMessage", {"driverBrakeStatus": 1})
    _ap1_send(chassis, packer, "EPAS_sysStatus", {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0})
    _ap1_send(chassis, packer, "STW_ANGLHP_STAT", {"StW_AnglHP_Spd": 0.0})
    _ap1_send(chassis, packer, "DI_torque2", {"DI_gear": 4})
    _ap1_send(chassis, packer, "DI_state", {})
    _ap1_send(chassis, packer, "SDM1", {"SDM_bcklDrivStatus": 1})
    out.append(state.update(parsers))
  return out


@pytest.mark.parametrize("car", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_ap1_publishes_pedal_pos(car):
  outs = ap1_feed(car, [0, 100, 250])            # raw * 0.4 % -> 0 %, 40 %, 100 %
  assert [round(o.deprecated.gas, 4) for o in outs] == [0.0, 0.4, 1.0]
  assert [o.gasPressed for o in outs] == [False, True, True]


def test_preap_publishes_pedal_pos():
  rig = StockRig()
  got = []
  for raw in (0, 5, 100, 250):
    out, _ = rig.frame(raw)
    got.append((round(out.deprecated.gas, 4), out.gasPressed))
  assert got == [(0.0, False), (0.02, False), (0.4, True), (1.0, True)]
