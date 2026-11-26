"""carstate mirror of the panda steer-through-brake latch (tesla_preap.h:74-120): preapSteerLatch = armed && brake_seen, checked against
the Python panda model (PandaPreapMirror) on every tick. Also the new preapFsmMode / preapSpeedBlocked fields."""
import pytest

from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import CANCEL, PULL, _params_dir  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import EAC_ACTIVE, Drive


def _armed_braked(pedal):
  d = Drive(pedal=pedal)
  d.step(op=False)
  d.step(stalk=PULL, op=False)
  for _ in range(3):
    out = d.step()
  assert not out.bogpilot.preapSteerLatch
  out = _brake(d)
  assert out.bogpilot.preapSteerLatch
  return d


def _brake(d, on=True):
  d.rig.base["BrakeMessage"] = {"driverBrakeStatus": 2 if on else 1}
  return d.step()


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "nopedal"])
def test_pull_then_brake_sets_the_latch_and_it_survives_the_release(pedal):
  d = _armed_braked(pedal)
  out = _brake(d, on=False)
  assert out.bogpilot.preapSteerLatch


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "nopedal"])
def test_a_new_pull_clears_brake_seen(pedal):
  d = _armed_braked(pedal)
  _brake(d, on=False)
  out = d.step(stalk=PULL)
  assert not out.bogpilot.preapSteerLatch


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "nopedal"])
def test_epas_drop_clears_the_latch(pedal):
  d = _armed_braked(pedal)
  d.epas(3, EAC_ACTIVE, 0)
  out = d.step()
  assert not out.bogpilot.preapSteerLatch


def test_cancel_inside_the_echo_window_keeps_it_after_clears_it():
  d = _armed_braked(False)
  d.rig.base["BrakeMessage"] = {"driverBrakeStatus": 1}
  for _ in range(70):
    d.step()
  out = d.step(stalk=CANCEL)
  assert not out.bogpilot.preapSteerLatch


def test_fsm_mode_field_follows_the_fsm():
  d = Drive(pedal=True)
  out = d.step(op=False)
  assert out.bogpilot.preapFsmMode == int(Mode.OFF)
  out = d.step(stalk=PULL, op=False)
  assert out.bogpilot.preapFsmMode == int(Mode.LAT_PENDING)
