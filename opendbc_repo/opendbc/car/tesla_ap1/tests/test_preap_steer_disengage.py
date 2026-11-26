"""Pre-AP carState.steeringDisengage: raised on the same frame as the panda's hands-on / EPAS refusal drop, with and without the pedal.

steeringDisengage = preap_epas_refusing (hands on level 3, or INHIBITED with error 6..9), the inputs of tesla_preap_epas_blocking in
tesla_preap.h. As in NAP (opendbc preap/carstate.py:60-68 @ cc39c7fa). openpilot turns its rising edge into steerDisengage
(selfdrive/car/car_events.py); the event-level test lives in selfdrive/car/tests/test_preap_steer_disengage.py.
EAC_FAULT stays steerFaultPermanent (steerUnavailable), not steeringDisengage.
"""
import pytest

from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (  # noqa: F401  (autouse fixture)
  PULL, Rig, _inv, _pedal_frame, _ready_rig, _params_dir)
from opendbc.car.tesla_ap1.tests.test_preap_g1_parity import PandaPreapMirror, fresh_pull_parity

EAC_INHIBITED, EAC_AVAILABLE, EAC_ACTIVE, EAC_FAULT = 0, 1, 2, 3


class Drive:
  def __init__(self, pedal: bool):
    if pedal:
      self.rig, _ = _ready_rig(double=False)
    else:
      self.rig = Rig(long=False)                 # stock TACC drives (pcmCruise True): cruiseState follows DI_state
      self.rig.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", "ENABLED")
    self.pedal = pedal
    self.panda = PandaPreapMirror()
    self.n = 0
    self.mirror_mismatch = 0         # ticks where carstate's fresh-pull mirror differs from need_fresh_pull (fresh_pull_parity)
    self.fresh_hold = False
    self._rx = []
    orig = self.rig.packer.make_can_msg

    def capture(name, bus, values):
      addr, dat, b = orig(name, bus, values)
      self._rx.append((addr, bus, bytes(dat)))
      return addr, dat, b
    self.rig.packer.make_can_msg = capture
    self.epas(0, EAC_ACTIVE, 0)

  def epas(self, hands, status, err):
    self.rig.base["EPAS_sysStatus"] = {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0, "EPAS_handsOnLevel": hands,
                                       "EPAS_eacStatus": status, "EPAS_eacErrorCode": err}

  def step(self, stalk=0, op=True):
    self._rx = []
    if self.pedal:
      _pedal_frame(self.rig, self.n)
    out = self.rig.frame(stalk=stalk, op=op)
    self.panda.now_us += 10_000
    for addr, bus, dat in self._rx:
      self.panda.rx(addr, bus, dat)
    ok, self.fresh_hold = fresh_pull_parity(self.rig.cs, self.panda, self.fresh_hold, stalk)
    self.mirror_mismatch += not ok
    self.n += 1
    return out

  def engage(self):
    for _ in range(20):
      self.step(op=False)
    self.step(stalk=PULL, op=False)
    for _ in range(50):
      out = self.step()
    assert self.panda.controls_allowed and not out.steeringDisengage


CAUSES = [("hands", (3, EAC_ACTIVE, 0))] + [(f"refusal{e}", (0, EAC_INHIBITED, e)) for e in (6, 7, 8, 9)]


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "pcmCruise"])
@pytest.mark.parametrize("cause,epas", CAUSES, ids=[c for c, _ in CAUSES])
def test_steering_disengage_rises_on_the_panda_drop_frame(pedal, cause, epas):
  d = Drive(pedal)
  d.engage()
  d.epas(*epas)
  out = d.step()
  assert d.panda.last_drop and not d.panda.controls_allowed, "the panda drops on this frame"
  assert out.steeringDisengage, "openpilot sees it on the same frame"
  assert not out.steerFaultPermanent
  for _ in range(30):
    assert d.step().steeringDisengage, "held while the condition holds (car_events raises only the rising edge)"
  d.epas(0, EAC_ACTIVE, 0)
  assert not d.step().steeringDisengage


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "pcmCruise"])
def test_eac_fault_stays_steer_fault_permanent(pedal):
  d = Drive(pedal)
  d.engage()
  d.epas(0, EAC_FAULT, 0)
  out = d.step()
  assert d.panda.last_drop
  assert out.steerFaultPermanent and not out.steeringDisengage


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "pcmCruise"])
@pytest.mark.parametrize("hands,status,err", [(0, EAC_INHIBITED, 3), (0, EAC_INHIBITED, 4), (2, EAC_ACTIVE, 0), (1, EAC_ACTIVE, 0)])
def test_no_drop_no_disengage(pedal, hands, status, err):
  # HANDS_ON-coded INHIBITED (3), TMP_FAULT-coded INHIBITED (4) and hands below 3 are not a panda drop
  d = Drive(pedal)
  d.engage()
  d.epas(hands, status, err)
  for _ in range(30):
    out = d.step()
    assert not out.steeringDisengage and d.panda.last_drop is False and d.panda.controls_allowed
