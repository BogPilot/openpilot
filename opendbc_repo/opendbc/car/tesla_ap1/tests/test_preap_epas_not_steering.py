"""Pre-AP "EPAS Not Steering" warning: carState.bogpilot.preapEpasNotActive -> ap1_events.py preapEpasNotSteering after 2 s."""
import math
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.ap1_events import (Ap1Events, PREAP_EPAS_NOT_STEERING, PREAP_EPAS_NOT_STEERING_FRAMES,
                                              STEER_TEMP_SILENT)


def bp(not_active=True, hands=0, yielding=False, **kw):
  d = dict(ap1DriverYield=yielding, ap1HandsOnLevel=hands, ap1EacInhibited=False, preapEpasNotActive=not_active)
  d.update(kw)
  return SimpleNamespace(**d)


def run(ev, n, enabled=True, lat=True, fault=False, **kw):
  fired = []
  for _ in range(n):
    fired.append(PREAP_EPAS_NOT_STEERING in ev.update([], enabled, lat, bp(**kw), fault))
  return fired


def test_threshold_is_two_seconds():
  assert PREAP_EPAS_NOT_STEERING_FRAMES == 200


def test_fires_after_2s_and_stays():
  ev = Ap1Events()
  fired = run(ev, 400)
  assert not any(fired[:PREAP_EPAS_NOT_STEERING_FRAMES - 1]) and all(fired[PREAP_EPAS_NOT_STEERING_FRAMES - 1:])


def test_clears_on_the_first_active_frame_and_restarts():
  ev = Ap1Events()
  run(ev, 250)
  assert run(ev, 1, not_active=False) == [False]
  fired = run(ev, 199)
  assert not any(fired)


def test_worst_normal_stretch_does_not_fire():
  ev = Ap1Events()
  for _ in range(20):          # 0.52 s not ACTIVE (worst logged stretch), then ACTIVE again, repeated
    assert not any(run(ev, 52)) and not any(run(ev, 5, not_active=False))
  assert not any(run(ev, 199))


@pytest.mark.parametrize("kw", [dict(enabled=False), dict(lat=False), dict(hands=1), dict(hands=3), dict(yielding=True),
                                dict(fault=True), dict(not_active=False)])
def test_never_fires_outside_the_condition(kw):
  ev = Ap1Events()
  assert not any(run(ev, 600, **kw))


def test_driver_input_resets_the_count():
  ev = Ap1Events()
  run(ev, 150)
  run(ev, 1, hands=1)
  assert not any(run(ev, 199))


def test_warning_only_no_other_events():
  ev = Ap1Events()
  out = []
  for _ in range(300):
    out = ev.update([], True, True, bp(), False)
  assert out == [PREAP_EPAS_NOT_STEERING]
  assert STEER_TEMP_SILENT not in out


def test_ap1_never_sets_the_flag(tmp_path):
  from opendbc.car.tesla_ap1.carstate import CarState
  from opendbc.car.tesla_ap1.values import CAR
  cp = SimpleNamespace(carFingerprint=CAR.TESLA_AP1_MODELS)
  st = CarState(cp); parsers = CarState.get_can_parsers(cp)
  chassis = parsers[Bus.chassis]; packer = CANPacker("tesla_ap1_can")
  for i in range(20):
    a, d, _ = packer.make_can_msg("EPAS_sysStatus", chassis.bus, {"EPAS_eacStatus": 0, "EPAS_sysStatusCounter": i % 16})
    chassis.update([((i + 1) * 10_000_000, [(a, d, chassis.bus)])])
    ret = st.update(parsers)
  assert not ret.bogpilot.preapEpasNotActive


@pytest.mark.parametrize("status,expect", [(0, True), (1, True), (2, False), (3, False), (4, True)])
def test_preap_carstate_flag(tmp_path, monkeypatch, status, expect):
  from opendbc.car.tesla_ap1.preap import params
  from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
  from opendbc.car.tesla_ap1.values import CAR
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  cp = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
  st = PreApCarState(cp); parsers = PreApCarState.get_can_parsers(cp)
  chassis = parsers[Bus.chassis]; packer = CANPacker("tesla_ap1_can")
  for i in range(20):
    a, d, _ = packer.make_can_msg("EPAS_sysStatus", chassis.bus, {"EPAS_eacStatus": status, "EPAS_sysStatusCounter": i % 16})
    chassis.update([((i + 1) * 10_000_000, [(a, d, chassis.bus)])])
    ret = st.update(parsers)
  assert bool(ret.bogpilot.preapEpasNotActive) is expect
  assert math.isfinite(ret.steeringRateDeg)
