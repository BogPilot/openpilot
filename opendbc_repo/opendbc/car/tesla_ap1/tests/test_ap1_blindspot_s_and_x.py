"""Blind spot from stock 0x399 (AutopilotStatus, bus 2) on the AP1 Model S and the AP1 Model X.

Both cars read DAS_blindSpotRearLeft / DAS_blindSpotRearRight through the same fail-closed Ap1Blindspot
(blindspot.py): clear only on a recent checksum-OK NO_WARNING, occupied on WARNING_LEVEL_1/2, SNA,
a bad checksum dropout or a stale frame. Synthetic CAN bytes only.
"""
from types import SimpleNamespace

import pytest

from opendbc.car import Bus, DT_CTRL
from opendbc.car.tesla_ap1.blindspot import BSM_HOLD_S, BSM_STALE_S
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.cluster import AUTOPILOT_STATUS, CHECKSUM_SIGNALS, SIGNALS, pack, tesla_checksum
from opendbc.car.tesla_ap1.values import CAR

CK = CHECKSUM_SIGNALS[AUTOPILOT_STATUS]
CARS = (CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX)


def frame_399(left=0, right=0, good_checksum=True):
  vals = {"DAS_blindSpotRearLeft": left, "DAS_blindSpotRearRight": right}
  body = pack(AUTOPILOT_STATUS, SIGNALS[AUTOPILOT_STATUS], vals).to_bytes(8, "little")
  ck = tesla_checksum(AUTOPILOT_STATUS, body)
  vals[CK] = ck if good_checksum else (ck + 1) & 0xFF
  return pack(AUTOPILOT_STATUS, SIGNALS[AUTOPILOT_STATUS], vals).to_bytes(8, "little")


class Car:
  def __init__(self, fingerprint):
    self.CP = SimpleNamespace(carFingerprint=fingerprint)
    self.state = CarState(self.CP)
    self.parsers = CarState.get_can_parsers(self.CP)
    self.t = 1_000_000_000

  def step_ret(self, dat=None, steps=1):
    ret = None
    for i in range(steps):
      self.t += 10_000_000
      msgs = [(AUTOPILOT_STATUS, dat, 2)] if (dat is not None and i == 0) else []
      for p in self.parsers.values():
        p.update([(self.t, msgs)])
      ret = self.state.update(self.parsers)
    return ret

  def step(self, dat=None, steps=1):
    ret = self.step_ret(dat, steps)
    return bool(ret.leftBlindspot), bool(ret.rightBlindspot)


@pytest.mark.parametrize("fp", CARS)
def test_cam_parser_subscribes_autopilot_status(fp):
  car = Car(fp)
  assert "AutopilotStatus" in car.parsers[Bus.cam].vl


@pytest.mark.parametrize("fp", CARS)
def test_clear(fp):
  assert Car(fp).step(frame_399(0, 0)) == (False, False)


@pytest.mark.parametrize("fp", CARS)
@pytest.mark.parametrize("left,right,expected", [(1, 0, (True, False)), (0, 2, (False, True)), (2, 1, (True, True))])
def test_warning_levels(fp, left, right, expected):
  assert Car(fp).step(frame_399(left, right)) == expected


@pytest.mark.parametrize("fp", CARS)
def test_sna_is_occupied(fp):
  assert Car(fp).step(frame_399(3, 3)) == (True, True)


@pytest.mark.parametrize("fp", CARS)
def test_warning_held_then_cleared_by_new_clear_frame(fp):
  car = Car(fp)
  assert car.step(frame_399(1, 0)) == (True, False)
  # 0x399 comes about every 0.45 s: a clear frame inside the hold clears that side at once.
  assert car.step(frame_399(0, 0)) == (False, False)
  car2 = Car(fp)
  car2.step(frame_399(1, 0))
  assert car2.step(steps=int(0.5 / DT_CTRL)) == (True, False)    # no new frame: held
  assert car2.step(frame_399(0, 0)) == (False, False)


@pytest.mark.parametrize("fp", CARS)
def test_stale_is_occupied(fp):
  car = Car(fp)
  assert car.step(frame_399(0, 0)) == (False, False)
  assert car.step(steps=int(BSM_STALE_S / DT_CTRL) - 5) == (False, False)
  assert car.step(steps=10) == (True, True)   # past BSM_STALE_S with no frame: unknown -> occupied
  assert car.step(frame_399(0, 0)) == (False, False)  # a fresh clear frame recovers


@pytest.mark.parametrize("fp", CARS)
def test_bad_checksum_frame_not_trusted(fp):
  car = Car(fp)
  car.step(frame_399(0, 0))
  # A bad-checksum WARNING frame is skipped (no refresh), so the clear stays until it goes stale.
  assert car.step(frame_399(1, 1, good_checksum=False)) == (False, False)
  assert car.state.ap1_bsm.bad_checksum == 1
  assert car.step(steps=int(BSM_STALE_S / DT_CTRL) + 5) == (True, True)


def test_hold_constant_unchanged():
  assert BSM_HOLD_S == 1.0 and BSM_STALE_S == 1.5


# Startup presence check: no blind spot source until a checksum-OK 0x399 frame is seen on bus 2 after start.

@pytest.mark.parametrize("fp", CARS)
def test_never_seen_is_waiting_not_occupied(fp):
  car = Car(fp)
  ret = car.step_ret(steps=int(5.0 / DT_CTRL))          # 5 s, no 0x399 at all
  assert (ret.leftBlindspot, ret.rightBlindspot) == (False, False)
  assert ret.bogpilot.bsmWaiting is True
  assert car.state.ap1_bsm.waiting


@pytest.mark.parametrize("fp", CARS)
def test_bad_checksum_frames_do_not_count_as_seen(fp):
  car = Car(fp)
  ret = car.step_ret(frame_399(1, 1, good_checksum=False))
  assert (ret.leftBlindspot, ret.rightBlindspot) == (False, False)
  assert ret.bogpilot.bsmWaiting is True


@pytest.mark.parametrize("fp", CARS)
def test_seen_then_lost_is_occupied(fp):
  car = Car(fp)
  ret = car.step_ret(frame_399(0, 0))
  assert (ret.leftBlindspot, ret.rightBlindspot) == (False, False)
  assert ret.bogpilot.bsmWaiting is False
  ret = car.step_ret(steps=int(BSM_STALE_S / DT_CTRL) + 5)   # source lost mid-drive
  assert (ret.leftBlindspot, ret.rightBlindspot) == (True, True)
  assert ret.bogpilot.bsmWaiting is False                     # never goes back to waiting
  ret = car.step_ret(steps=int(10.0 / DT_CTRL))
  assert (ret.leftBlindspot, ret.rightBlindspot) == (True, True)


@pytest.mark.parametrize("fp", CARS)
def test_normal_after_first_frame(fp):
  car = Car(fp)
  car.step(steps=50)                                           # a short wait before the first frame
  ret = car.step_ret(frame_399(1, 0))
  assert (ret.leftBlindspot, ret.rightBlindspot) == (True, False)
  assert ret.bogpilot.bsmWaiting is False
  assert car.step(frame_399(0, 2)) == (False, True)
  assert car.step(frame_399(0, 0)) == (False, False)


def test_waiting_unit():
  from opendbc.car.tesla_ap1.blindspot import Ap1Blindspot
  bsm = Ap1Blindspot()
  assert bsm.waiting and bsm.update([], 0.01) == (False, False)
  assert bsm.left and bsm.right                                # raw properties stay fail-closed


def test_preap_never_waiting():
  from opendbc.car.tesla_ap1.preap.carstate import PreApCarState  # noqa: F401  (Pre-AP has no 0x399 source)
  from opendbc.car import structs
  assert structs.CarState().bogpilot.bsmWaiting is False
