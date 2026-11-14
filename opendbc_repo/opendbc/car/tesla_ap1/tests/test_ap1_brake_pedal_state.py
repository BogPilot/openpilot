"""DI_brakePedalState (DI_torque2 0x118, stock tesla_ap1_can.dbc) published on AP1 as carState.bogpilot.ap1BrakePedalState
for the onroad decel bar colour only: fresh values pass through, stale / junk read SNA (3), Pre-AP keeps the default."""
import os
import re
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1 import brake_level as BL
from opendbc.car.tesla_ap1.carstate import CarState as Ap1CarState
from opendbc.car.tesla_ap1.values import CAR, DBC
from opendbc.car.tesla_ap1.tests.test_preap_gas_threshold import StockRig, _params_dir  # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
DBC_FILE = os.path.join(HERE, "..", "..", "..", "dbc", "tesla_ap1_can.dbc")


def feed(car, states, gap_s=0.01):
  """One DI_torque2 per step with this DI_brakePedalState (None = frame not sent this step)."""
  cp = SimpleNamespace(carFingerprint=car)
  state, parsers = Ap1CarState(cp), Ap1CarState.get_can_parsers(cp)
  packer = CANPacker(DBC[car][Bus.chassis])
  chassis = parsers[Bus.chassis]
  base = {"ESP_B": {"ESP_vehicleSpeed": 50.0}, "BrakeMessage": {"driverBrakeStatus": 1},
          "EPAS_sysStatus": {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0}, "STW_ANGLHP_STAT": {"StW_AnglHP_Spd": 0.0},
          "DI_state": {}, "SDM1": {"SDM_bcklDrivStatus": 1}, "DI_torque1": {}}
  out, t = [], 1_000_000_000
  for st in states:
    t += int(gap_s * 1e9)
    msgs = [packer.make_can_msg(n, chassis.bus, v)[:2] for n, v in base.items()]
    if st is not None:
      msgs.append(packer.make_can_msg("DI_torque2", chassis.bus, {"DI_gear": 4, "DI_brakePedalState": st})[:2])
    chassis.update([(t, [(a, d, chassis.bus) for a, d in msgs])])
    out.append(state.update(parsers))
  return out


def test_signal_is_in_the_stock_dbc():
  txt = open(DBC_FILE).read()
  assert re.search(r"BO_ 280 DI_torque2: 6 DI", txt)
  assert re.search(r"SG_ DI_brakePedalState : 36\|2@1\+ \(1,0\)", txt)
  assert 'VAL_ 280 DI_brakePedalState 3 "SNA" 2 "INVALID" 1 "ON" 0 "OFF" ;' in txt
  assert (BL.DI_BRAKE_STATE_ON, BL.DI_BRAKE_STATE_SNA) == (1, 3)


def test_helper():
  assert [BL.brake_pedal_state(v, True) for v in (0, 1, 2, 3)] == [0, 1, 2, 3]
  assert BL.brake_pedal_state(1, False) == 3
  for junk in (None, "x", float("nan"), 4, -1, 1.5):
    assert BL.brake_pedal_state(junk, True) == 3


@pytest.mark.parametrize("car", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
class TestAp1:
  def test_published(self, car):
    outs = feed(car, [0, 1, 1, 0, 2, 3])
    assert [o.bogpilot.ap1BrakePedalState for o in outs] == [0, 1, 1, 0, 2, 3]
    assert not any(o.brakePressed for o in outs)          # brakePressed still comes from BrakeMessage only

  def test_stale_is_sna(self, car):
    outs = feed(car, [1] + [None] * 30)
    assert outs[0].bogpilot.ap1BrakePedalState == 1
    assert outs[10].bogpilot.ap1BrakePedalState == 1       # 0.1 s: fresh
    assert outs[-1].bogpilot.ap1BrakePedalState == 3       # 0.3 s: stale -> SNA


def test_preap_default_is_sna():
  rig = StockRig()
  for _ in range(3):
    out, _ = rig.frame(0)
  assert out.bogpilot.ap1BrakePedalState == 3
