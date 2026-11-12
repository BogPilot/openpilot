"""Pre-AP stock cruise: no pcmEnable while the panda waits for a fresh stalk pull.

carstate.preap_fresh_pull_pending mirrors tesla_preap_need_fresh_pull (tesla_preap.h): set by every EPAS drop, cleared by a pull in D
with the doors closed unless the pull was held through the drop. With stock cruise (pcmCruise True) it is reported as blockPcmEnable,
which stops only the pcmEnable rising edge (selfdrive/car/car_events.py). cruiseState.enabled still follows DI_cruiseState, so the gate
can never keep openpilot engaged or delay a disengage. The pedal mode never sets blockPcmEnable; AP1 uses a different CarState.
Event-level tests: selfdrive/car/tests/test_preap_reengage.py.
"""
import inspect

import pytest

import opendbc.car.tesla_ap1.carstate as ap1_carstate
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import CANCEL, PULL, _inv, _params_dir  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import EAC_ACTIVE, EAC_FAULT, EAC_INHIBITED, Drive

DROPS = [("hands", (3, EAC_ACTIVE, 0)), ("refusal6", (0, EAC_INHIBITED, 6)), ("refusal9", (0, EAC_INHIBITED, 9)),
         ("fault", (0, EAC_FAULT, 0))]


def tacc(d, on):
  d.rig.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", "ENABLED" if on else "STANDBY")


def step(d, stalk=0):
  out = d.step(stalk=stalk, op=False)
  cs = d.rig.cs
  assert cs.preap_fresh_pull_pending == d.panda.need_fresh_pull, (d.n, cs.preap_fresh_pull_pending, d.panda.need_fresh_pull)
  return out


def drop_held_release(d, epas):
  step(d, stalk=PULL)
  d.epas(*epas)
  for _ in range(5):
    step(d, stalk=PULL)                                                  # pull held through the drop: both pending
  d.epas(0, EAC_ACTIVE, 0)
  for _ in range(5):
    step(d, stalk=PULL)
  assert d.panda.need_fresh_pull and d.rig.cs.preap_fresh_pull_pending
  for _ in range(3):
    step(d)                                                              # release


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "pcmCruise"])
@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_mirror_sets_and_clears_on_the_panda_edges(pedal, cause, epas):
  d = Drive(pedal)
  for _ in range(5):
    step(d)
  assert not d.rig.cs.preap_fresh_pull_pending and not d.panda.need_fresh_pull, "both start clear (tesla_preap_init_config)"
  drop_held_release(d, epas)
  step(d, stalk=PULL)
  assert not d.rig.cs.preap_fresh_pull_pending and not d.panda.need_fresh_pull, "the fresh pull clears both on the same tick"
  assert d.mirror_mismatch == 0


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "pcmCruise"])
def test_pull_out_of_drive_or_with_a_door_open_clears_neither(pedal):
  d = Drive(pedal)
  drop_held_release(d, (3, EAC_ACTIVE, 0))
  d.rig.base["DI_torque2"]["DI_gear"] = _inv("DI_torque2", "DI_gear", "DI_GEAR_N")
  d.panda.gear_d = False                       # the mirror holds gear and doors; tesla_preap.h reads them from 0x118 / 0x318
  step(d, stalk=PULL)
  step(d)
  assert d.rig.cs.preap_fresh_pull_pending and d.panda.need_fresh_pull
  d.rig.base["DI_torque2"]["DI_gear"] = _inv("DI_torque2", "DI_gear", "DI_GEAR_D")
  d.panda.gear_d = True
  d.rig.base["GTW_carState"]["DOOR_STATE_FL"] = _inv("GTW_carState", "DOOR_STATE_FL", "OPEN")
  d.panda.doors_open = True
  step(d, stalk=PULL)
  step(d)
  assert d.rig.cs.preap_fresh_pull_pending and d.panda.need_fresh_pull
  d.rig.base["GTW_carState"]["DOOR_STATE_FL"] = _inv("GTW_carState", "DOOR_STATE_FL", "CLOSED")
  d.panda.doors_open = False
  step(d, stalk=PULL)
  assert not d.rig.cs.preap_fresh_pull_pending and not d.panda.need_fresh_pull


@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_stock_cruise_block_pcm_enable_is_the_mirror_and_cruise_state_still_follows_di(cause, epas):
  d = Drive(pedal=False)
  seen = []
  for i in range(40):
    if i == 10:
      d.epas(*epas)
    if i == 12:
      d.epas(0, EAC_ACTIVE, 0)
    if i in (20, 30):
      tacc(d, i == 30)                         # off at 20, on at 30 with no pull: stays blocked
    out = step(d)
    seen.append(out.blockPcmEnable)
    assert out.blockPcmEnable == d.rig.cs.preap_fresh_pull_pending
    di_on = d.rig.base["DI_state"]["DI_cruiseState"] == _inv("DI_state", "DI_cruiseState", "ENABLED")
    assert out.cruiseState.enabled == di_on, "the gate never touches cruiseState.enabled"
  assert not any(seen[:10]) and all(seen[10:])
  out = step(d, stalk=PULL)
  assert not out.blockPcmEnable and not d.panda.need_fresh_pull, "the fresh pull clears the block on the tick the panda re-arms"


def test_stock_cruise_cancel_while_pending_drops_cruise_state_on_that_tick():
  d = Drive(pedal=False)
  d.epas(3, EAC_ACTIVE, 0)
  step(d)
  d.epas(0, EAC_ACTIVE, 0)
  out = step(d)
  assert out.blockPcmEnable and out.cruiseState.enabled, "TACC still on: cruiseState stays as the car reports it"
  tacc(d, False)
  out = step(d, stalk=CANCEL)
  assert not out.cruiseState.enabled, "the disengage edge is not held back by the pending pull"


@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_pedal_mode_never_sets_block_pcm_enable(cause, epas):
  d = Drive(pedal=True)
  d.engage()
  drop_held_release(d, epas)
  for _ in range(20):
    assert not step(d).blockPcmEnable
  assert d.rig.cs.preap_fresh_pull_pending, "the mirror still runs; only its use is stock cruise"
  out = step(d, stalk=PULL)
  assert not out.blockPcmEnable and not d.rig.cs.preap_fresh_pull_pending


def test_ap1_car_state_has_no_fresh_pull_gate():
  src = inspect.getsource(ap1_carstate)
  assert "blockPcmEnable" not in src and "fresh_pull" not in src
  from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
  assert not issubclass(ap1_carstate.CarState, PreApCarState)
