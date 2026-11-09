"""Reverse driver-camera controller: enable gating, 0.5 s hold, entry/exit, repeat, stale gear, offroad.

Also replays gear timelines (including flapping) through read_gear + controller together, and asserts the
main.py safety contract that stock visual alerts stay drawn over the reverse cabin view.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opendbc.car.structs import car
from openpilot.selfdrive.ui.bogpilot import reverse_camera as rc

R, D = car.CarState.GearShifter.reverse, car.CarState.GearShifter.drive
N = car.CarState.GearShifter.neutral
P = car.CarState.GearShifter.park


class Clock:
  def __init__(self, t: float = 100.0):
    self.t = t

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


class _SM:
  def __init__(self, gear, alive=True, valid=True, recv=10.0):
    self.alive = {"carState": alive}
    self.valid = {"carState": valid}
    self.recv_time = {"carState": recv}
    self._cs = SimpleNamespace(gearShifter=gear)

  def __getitem__(self, k):
    return self._cs


def sm(gear, alive=True, valid=True, recv=10.0):
  return _SM(gear, alive, valid, recv)


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
  src = Path(__import__("openpilot.common.bogpilot_ap1_profile", fromlist=["x"]).__file__).read_text()
  assert '"DriverCamera": "1"' in src


def test_main_py_keeps_stock_alert_overlay_after_reverse_view():
  """Safety: reverse cabin video must never hide stock visual alerts (audio is soundd, untouched)."""
  source = (Path(__file__).parents[1] / "layouts/main.py").read_text()
  camera = source.index("self._reverse_view.render(self._rect)")
  overlay = source.index("self._layouts[MainState.ONROAD].alert_renderer.render(self._rect)")
  assert camera < overlay < source.index("return", overlay)
  # Toggle-off / stock path: reverse early-return must be gated on _reverse_active only
  assert "if self._reverse_active:" in source
  assert "ReverseCameraController" in source
  assert "enabled_from" in source


def test_reverse_view_does_not_write_driver_view_param_or_steal_manual_preview():
  """Reverse view must not poke IsDriverViewEnabled (manual offroad preview lifecycle stays stock)."""
  src = (Path(__file__).parents[1] / "onroad/reverse_camera_view.py").read_text()
  # Docstring may mention the param by name; body must not write it.
  body = src.split('"""', 2)[-1] if src.lstrip().startswith('"""') else src
  assert "IsDriverViewEnabled" not in body
  assert "params.put" not in body
  assert "VISION_STREAM_CABIN" in src
  assert "_handle_mouse_release" in src


# ---- Gear timeline replay (read_gear + controller), including flapping ----

def replay_gear_timeline(events, *, started=True, enabled=True, t0=1000.0):
  """Replay [(dt, gear, alive, valid), ...] from t0.

  Each event advances the monotonic clock by dt, sets carState recv_time to the new clock
  (fresh), and returns the sequence of controller active booleans.
  """
  clock = Clock(t0)
  ctl = rc.ReverseCameraController(clock=clock)
  out = []
  for dt, gear, alive, valid in events:
    clock.t += dt
    # Message arrives "now" when alive/valid; a dead/stale sample keeps an old recv_time.
    recv = clock.t if (alive and valid) else (clock.t - 5.0)
    in_reverse, fresh = rc.read_gear(sm(gear, alive=alive, valid=valid, recv=recv), clock.t)
    out.append(ctl.update(started=started, enabled=enabled, in_reverse=in_reverse, carstate_fresh=fresh))
  return out


def test_timeline_sustained_reverse_shows_after_hold():
  # 0.0 enter R, then 0.2 / 0.2 / 0.2 => show on the sample that crosses 0.5 s
  got = replay_gear_timeline([
    (0.0, R, True, True),
    (0.2, R, True, True),
    (0.2, R, True, True),
    (0.2, R, True, True),
  ])
  assert got == [False, False, False, True]


def test_timeline_leave_reverse_drops_immediately_then_rearms():
  got = replay_gear_timeline([
    (0.0, R, True, True),
    (0.6, R, True, True),   # show
    (0.05, D, True, True),  # leave -> drop
    (0.05, R, True, True),  # re-enter, timer reset
    (0.3, R, True, True),
    (0.25, R, True, True),  # crosses fresh 0.5 s
  ])
  assert got == [False, True, False, False, False, True]


def test_timeline_flapping_gear_never_shows():
  """Rapid R/D/R/D/... blips under the hold must never activate the reverse view."""
  events = []
  # 40 flaps of 0.15 s reverse / 0.15 s drive (~6 s wall, never 0.5 s continuous R)
  for _ in range(40):
    events.append((0.15, R, True, True))
    events.append((0.15, D, True, True))
  got = replay_gear_timeline(events)
  assert got == [False] * len(events)


def test_timeline_flapping_then_sustained_shows():
  """After flaps, a clean 0.5 s reverse hold must still arm and show."""
  events = []
  for _ in range(8):
    events.append((0.1, R, True, True))
    events.append((0.1, D, True, True))
  events += [
    (0.0, R, True, True),
    (0.25, R, True, True),
    (0.25, R, True, True),  # = 0.5 s continuous -> show
  ]
  got = replay_gear_timeline(events)
  assert all(v is False for v in got[:-1])
  assert got[-1] is True


def test_timeline_flapping_across_park_neutral_drive():
  """Non-reverse gears (P/N/D) interleaved with short R pulses keep the view off."""
  seq = [(0.1, R, True, True), (0.1, P, True, True),
         (0.1, R, True, True), (0.1, N, True, True),
         (0.1, R, True, True), (0.1, D, True, True)] * 5
  got = replay_gear_timeline(seq)
  assert got == [False] * len(seq)


def test_timeline_stale_carstate_mid_reverse_drops_and_requires_rehold():
  got = replay_gear_timeline([
    (0.0, R, True, True),
    (0.6, R, True, True),     # show
    (0.05, R, False, True),   # !alive => not fresh => drop + reset
    (0.05, R, True, True),    # back alive, need fresh hold
    (0.3, R, True, True),
    (0.25, R, True, True),
  ])
  assert got == [False, True, False, False, False, True]


def test_timeline_invalid_carstate_counts_as_not_reverse_fresh():
  got = replay_gear_timeline([
    (0.0, R, True, True),
    (0.4, R, True, True),
    (0.05, R, True, False),  # invalid mid-hold resets timer
    (0.4, R, True, True),
    (0.2, R, True, True),    # still under fresh 0.5 after reset
    (0.35, R, True, True),   # crosses
  ])
  assert got[0] is False and got[1] is False and got[2] is False
  assert got[3] is False and got[4] is False and got[5] is True


def test_timeline_toggle_off_is_stock_even_in_sustained_reverse():
  """DriverCamera / QOL off => stock onroad (controller never activates)."""
  events = [(0.0, R, True, True), (0.3, R, True, True), (0.3, R, True, True), (0.3, R, True, True)]
  assert replay_gear_timeline(events, enabled=False) == [False] * 4
  assert replay_gear_timeline(events, started=False) == [False] * 4


def test_timeline_exact_hold_boundary():
  """Active becomes True only once elapsed >= HOLD_S (0.5)."""
  assert rc.HOLD_S == 0.5
  # just under
  under = replay_gear_timeline([(0.0, R, True, True), (0.499, R, True, True)])
  assert under == [False, False]
  # exact boundary
  exact = replay_gear_timeline([(0.0, R, True, True), (0.5, R, True, True)])
  assert exact == [False, True]
