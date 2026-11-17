"""Drive - Reverse - Drive: from FULL, Reverse ends the engagement (openpilot off, no pedal ENABLE), coming back to Drive does not
re-engage by itself, and a fresh double pull in Drive is FULL again (steering and pedal). Real CarState + CarController."""
import functools

import pytest

from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, Rig, _inv, _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_full_demote import Car, _double_pull


def _gear(c, g, v_kph):
  c.rig.base["DI_torque2"]["DI_gear"] = _inv("DI_torque2", "DI_gear", g)
  c.rig.frame = functools.partial(Rig.frame, c.rig, v_kph=v_kph)


def _pedal_on(c, n):
  before = c.enabled_frames
  for _ in range(n):
    out = c.step()
  return c.enabled_frames - before, out


@pytest.mark.parametrize("cycles", [1, 3])
def test_drive_reverse_drive_reengages_on_a_fresh_double_pull(cycles):
  c = Car(pedal=True)
  _gear(c, "DI_GEAR_D", 20.0)
  out = _double_pull(c)
  assert c.mode == Mode.FULL and out.cruiseState.enabled
  for _ in range(cycles):
    _gear(c, "DI_GEAR_D", 0.0)
    _pedal_on(c, 20)
    _gear(c, "DI_GEAR_R", 0.0)
    enabled, out = _pedal_on(c, 30)
    assert not out.cruiseState.enabled and c.mode != Mode.FULL      # Reverse ends it
    assert not c.op
    n_r, _ = _pedal_on(c, 20)
    assert n_r == 0                                                # no pedal ENABLE in Reverse
    _gear(c, "DI_GEAR_D", 0.0)
    n_d, out = _pedal_on(c, 100)
    assert n_d == 0 and not out.cruiseState.enabled and not c.op   # back in Drive: nothing by itself
    _gear(c, "DI_GEAR_D", 20.0)
    out = _double_pull(c)
    assert c.mode == Mode.FULL and out.cruiseState.enabled and not out.bogpilot.preapLatOnly and c.op
    n_full, out = _pedal_on(c, 50)
    assert n_full > 0                                              # the pedal drives again


def test_single_pull_after_reverse_is_steering_only():
  c = Car(pedal=True)
  _gear(c, "DI_GEAR_D", 20.0)
  _double_pull(c)
  _gear(c, "DI_GEAR_R", 0.0)
  _pedal_on(c, 40)
  _gear(c, "DI_GEAR_D", 20.0)
  _pedal_on(c, 40)
  c.step(stalk=PULL)
  n, out = _pedal_on(c, 60)
  assert out.cruiseState.enabled and out.bogpilot.preapLatOnly and n == 0
