"""Reverse driver-camera controller: enable gating, 0.5 s hold, entry/exit, repeat, stale gear, offroad."""
from types import SimpleNamespace

import pytest

from opendbc.car.structs import car
from openpilot.selfdrive.ui.bogpilot import reverse_camera as rc

R, D = car.CarState.GearShifter.reverse, car.CarState.GearShifter.drive


class Clock:
  def __init__(self):
    self.t = 100.0

  def __call__(self):
    return self.t


@pytest.fixture
def ctl():
  c = Clock()
  return rc.ReverseCameraController(clock=c), c


def step(ctl, dt, **kw):
  c, clock = ctl
  clock.t += dt
  args = dict(started=True, enabled=True, in_reverse=True, carstate_fresh=True) | kw
  return c.update(**args)


def test_disabled_never_shows(ctl):
  assert not any(step(ctl, 0.2, enabled=False) for _ in range(20))


def test_hold_debounce_then_show(ctl):
  assert step(ctl, 0.0) is False
  assert step(ctl, 0.3) is False
  assert step(ctl, 0.25) is True


def test_exit_reverse_returns_immediately_and_rearms(ctl):
  step(ctl, 0.0)
  assert step(ctl, 0.6)
  assert step(ctl, 0.05, in_reverse=False) is False
  assert step(ctl, 0.05) is False           # repeated reverse needs a fresh 0.5 s hold
  assert step(ctl, 0.3) is False
  assert step(ctl, 0.3) is True


def test_brief_reverse_blips_never_show(ctl):
  for _ in range(10):
    assert step(ctl, 0.2) is False
    assert step(ctl, 0.2, in_reverse=False) is False


@pytest.mark.parametrize("kw", [dict(started=False), dict(carstate_fresh=False), dict(enabled=False)])
def test_offroad_stale_or_toggle_off_drop_view_and_reset(ctl, kw):
  step(ctl, 0.0)
  assert step(ctl, 0.6)
  assert step(ctl, 0.01, **kw) is False
  assert step(ctl, 0.01) is False


def test_enabled_requires_qol_parent_and_driver_camera():
  def store(v):
    return SimpleNamespace(get_bool=lambda k: v.get(k, False))
  assert rc.enabled_from(store({"QOLVisuals": True, "DriverCamera": True}))
  assert not rc.enabled_from(store({"QOLVisuals": False, "DriverCamera": True}))
  assert not rc.enabled_from(store({"QOLVisuals": True}))
  assert not rc.enabled_from(SimpleNamespace(get_bool=lambda k: 1 / 0))


def sm(gear, alive=True, valid=True, recv=10.0):
  return _SM(gear, alive, valid, recv)


class _SM:
  def __init__(self, gear, alive, valid, recv):
    self.alive, self.valid, self.recv_time = {"carState": alive}, {"carState": valid}, {"carState": recv}
    self._cs = SimpleNamespace(gearShifter=gear)

  def __getitem__(self, k):
    return self._cs


def test_read_gear_freshness():
  assert rc.read_gear(sm(R), 10.2) == (True, True)
  assert rc.read_gear(sm(D), 10.2) == (False, True)
  assert rc.read_gear(sm(R), 11.0) == (True, False)       # stale
  assert rc.read_gear(sm(R, alive=False), 10.1)[1] is False
  assert rc.read_gear(sm(R, valid=False), 10.1)[1] is False
  assert rc.read_gear(None) == (False, False)


def test_registered_param_and_ap1_profile_value():
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  from openpilot.common.params import Params
  assert BOGPILOT_PARAMS["DriverCamera"][:3] == ("PERSISTENT", "BOOL", "0")
  assert BOGPILOT_PARAMS["QOLVisuals"][:3] == ("PERSISTENT", "BOOL", "1")
  Params().check_key("DriverCamera")
  src = __import__("pathlib").Path(__import__("openpilot.common.bogpilot_ap1_profile", fromlist=["x"]).__file__).read_text()
  assert '"DriverCamera": "1"' in src
