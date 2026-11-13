"""doorOpen follows CANDefine values built from the real chassis DBC."""
import pytest

from opendbc.can import CANDefine
from opendbc.car import Bus
from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, Rig, _params_dir  # noqa: F401
from opendbc.car.tesla_ap1.values import CAR, DBC, DOORS

DBC_NAME = DBC[CAR.TESLA_PREAP_MODELS][Bus.chassis]


def test_candefine_door_vals_are_uppercased_from_the_dbc():
  # tesla_ap1_can.dbc VAL_ 792 door/BOOT lines use lowercase "open" / "closed" (and "Init").
  # CANDefine uppercases VAL_ strings (opendbc/can/dbc.py:183), so the "OPEN" compare in
  # preap/carstate.py:244 is correct.
  dv = CANDefine(DBC_NAME).dv["GTW_carState"]
  for sig in DOORS:
    assert dv[sig][0] == "CLOSED"
    assert dv[sig][1] == "OPEN"
    assert "open" not in dv[sig].values() and "closed" not in dv[sig].values()


@pytest.mark.parametrize("sig", DOORS)
def test_door_open_true_when_raw_open_and_false_when_closed(sig):
  dv = CANDefine(DBC_NAME).dv["GTW_carState"]
  open_raw = next(k for k, v in dv[sig].items() if v == "OPEN")
  closed_raw = next(k for k, v in dv[sig].items() if v == "CLOSED")
  assert open_raw == 1 and closed_raw == 0

  r = Rig()
  for other in DOORS:
    r.base["GTW_carState"][other] = 0
  r.base["GTW_carState"][sig] = open_raw
  ret = r.frame()
  assert ret.doorOpen is True

  r.base["GTW_carState"][sig] = closed_raw
  ret = r.frame()
  assert ret.doorOpen is False


@pytest.mark.parametrize("sig", DOORS)
def test_pull_with_a_door_open_is_not_a_valid_pull(sig):
  # engagement.py:191 valid_pull = pull_edge and in_d and doors_closed (panda tesla_preap.h:102-113)
  r = Rig()
  for other in DOORS:
    r.base["GTW_carState"][other] = 0
  r.base["GTW_carState"][sig] = 1
  r.frame()
  ret = r.frame(stalk=PULL)
  assert ret.doorOpen is True
  assert r.cs.engagement.last_valid_pull is False
  assert r.cs.engagement.mode == Mode.OFF and not ret.cruiseState.enabled

  r.base["GTW_carState"][sig] = 0
  r.frame()
  ret = r.frame(stalk=PULL)
  assert ret.doorOpen is False
  assert r.cs.engagement.last_valid_pull is True
