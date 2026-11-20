"""StW_AnglHP_Spd SNA guard (tesla_ap1/steer_rate.py) and its use in the AP1 and Pre-AP car states."""
import math
import random
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.override import DriverOverrideDetector, SIGNAL_NONE, SIGNAL_RATE, SIGNAL_ANGLE_ERROR
from opendbc.car.tesla_ap1.steer_rate import (SOURCE_ANGLE_DIFF, SOURCE_NONE, SOURCE_SENSOR, SteerRateFallback)

SNA = 4095.5


def _feed(f, rates, angles, counters=None):
  out = []
  for i, (r, a) in enumerate(zip(rates, angles)):
    out.append(f.update(r, a, None if counters is None else counters[i]))
  return out


def test_valid_rate_passes_through_unchanged():
  f = SteerRateFallback()
  assert f.update(12.5, 3.0, 0) == 12.5 and f.update(-80.0, 2.2, 1) == -80.0
  assert f.source == SOURCE_SENSOR and not f.sna


def test_sna_rate_uses_the_angle_difference():
  f = SteerRateFallback()
  out = _feed(f, [SNA] * 100, [0.1 * i for i in range(100)], [i % 16 for i in range(100)])   # 10 deg/s
  assert f.source == SOURCE_ANGLE_DIFF and f.sna
  assert abs(out[-1] - 10.0) < 0.3
  out = _feed(f, [-SNA] * 100, [10.0 - 0.3 * i for i in range(100)], [(100 + i) % 16 for i in range(100)])   # -30 deg/s, either sign of SNA
  assert abs(out[-1] + 30.0) < 0.5


def test_non_finite_rate_is_treated_as_sna():
  f = SteerRateFallback()
  _feed(f, [float("nan")] * 20, [0.0] * 20)
  assert f.source == SOURCE_ANGLE_DIFF and f.update(float("inf"), 0.0) == pytest.approx(0.0)


def test_transition_valid_to_sna_is_continuous():
  f = SteerRateFallback()
  angles = [0.25 * i for i in range(200)]   # 25 deg/s throughout
  out = _feed(f, [25.0] * 100 + [SNA] * 100, angles, [i % 16 for i in range(200)])
  assert out[99] == 25.0
  assert all(abs(x - 25.0) < 1.0 for x in out[100:])


def test_transition_sna_to_valid_is_immediate():
  f = SteerRateFallback()
  _feed(f, [SNA] * 50, [0.0] * 50, [i % 16 for i in range(50)])
  assert f.update(-42.0, 0.0, 50 % 16) == -42.0 and f.source == SOURCE_SENSOR


def test_angle_sna_too_gives_zero_and_no_spike_on_return():
  f = SteerRateFallback()
  _feed(f, [SNA] * 20, [5.0] * 20, [i % 16 for i in range(20)])
  assert f.update(SNA, 819.1, 4) == 0.0 and f.source == SOURCE_NONE
  out = _feed(f, [SNA] * 10, [-200.0] * 10, [(5 + i) % 16 for i in range(10)])   # the angle comes back far away
  assert all(abs(x) < 1e-9 for x in out)


def test_repeated_counter_holds_and_skipped_frames_scale_dt():
  f = SteerRateFallback()
  _feed(f, [SNA] * 60, [0.2 * i for i in range(60)], [i % 16 for i in range(60)])   # 20 deg/s
  r = f.rate
  assert f.update(SNA, 0.2 * 59, 59 % 16) == r                  # same frame again (no new 0x00E this loop)
  f2 = SteerRateFallback()
  cs = [(2 * i) % 16 for i in range(80)]                         # every other frame missing: 0.4 deg per 20 ms = 20 deg/s
  out = _feed(f2, [SNA] * 80, [0.4 * i for i in range(80)], cs)
  assert abs(out[-1] - 20.0) < 0.5


def test_quantization_and_noise_stay_below_override_rates():
  rnd = random.Random(7)
  f = SteerRateFallback()
  toggle = _feed(f, [SNA] * 500, [0.1 * (i % 2) for i in range(500)], [i % 16 for i in range(500)])   # 1 LSB flicker
  assert max(abs(x) for x in toggle[10:]) < 2.0
  f = SteerRateFallback()
  noisy = _feed(f, [SNA] * 3000, [round(rnd.gauss(0.0, 0.1), 1) for _ in range(3000)], [i % 16 for i in range(3000)])
  assert max(abs(x) for x in noisy[10:]) < 15.0                 # ANGLE_ERROR needs 20 deg/s, RATE 25-35 deg/s


def test_detector_not_twitchy_on_sna_and_still_detects_a_real_override():
  f = SteerRateFallback(); d = DriverOverrideDetector()
  rnd = random.Random(3)
  sigs = []
  for i in range(300):   # wheel still with sensor noise, 1.2 Nm, command 5 deg off (EPAS lagging in a curve)
    a = 2.0 + round(rnd.gauss(0.0, 0.05), 1)
    sigs.append(d.update(True, 0, 1.2, f.update(-SNA, a, i % 16), a, command_deg=7.0))
  assert all(s == SIGNAL_NONE for s in sigs)
  for i in range(50):
    d.update(True, 0, 0.2, f.update(-SNA, 2.0, (300 + i) % 16), 2.0, command_deg=2.0)
  assert d.quiet
  fired = set()
  for i in range(30):    # driver turns the wheel away from the command at 60 deg/s with 1.5 Nm
    a = 2.0 - 0.6 * i
    fired.add(d.update(True, 0, 1.5, f.update(-SNA, a, (350 + i) % 16), a, command_deg=2.0))
  assert fired & {SIGNAL_RATE, SIGNAL_ANGLE_ERROR}


def _stw(packer, bus, ang, spd, counter):
  addr, dat, _ = packer.make_can_msg("STW_ANGLHP_STAT", bus, {"StW_AnglHP": ang, "StW_AnglHP_Spd": spd, "MC_STW_ANGLHP_STAT": counter})
  return addr, dat


def _run_carstate(state, parsers, spd, n=60):
  chassis = parsers[Bus.chassis]
  packer = CANPacker("tesla_ap1_can")
  out = []
  for i in range(n):
    addr, dat = _stw(packer, chassis.bus, 0.1 * i, spd, i % 16)
    a2, d2, _ = packer.make_can_msg("EPAS_sysStatus", chassis.bus, {"EPAS_internalSAS": 0.1 * i})
    chassis.update([((i + 1) * 10_000_000, [(addr, dat, chassis.bus), (a2, d2, chassis.bus)])])
    out.append(state.update(parsers).steeringRateDeg)
  return out


def test_ap1_carstate_uses_the_guard():
  from opendbc.car.tesla_ap1.carstate import CarState
  from opendbc.car.tesla_ap1.values import CAR
  for spd, expect in ((SNA, -10.0), (12.0, -12.0)):
    cp = SimpleNamespace(carFingerprint=CAR.TESLA_AP1_MODELS)
    out = _run_carstate(CarState(cp), CarState.get_can_parsers(cp), spd)
    assert all(math.isfinite(x) and abs(x) < 100 for x in out)
    assert abs(out[-1] - expect) < 0.5


def test_preap_carstate_uses_the_guard(tmp_path, monkeypatch):
  from opendbc.car.tesla_ap1.preap import params
  from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
  from opendbc.car.tesla_ap1.values import CAR
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  for spd, expect in ((SNA, -10.0), (12.0, -12.0)):
    cp = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
    out = _run_carstate(PreApCarState(cp), PreApCarState.get_can_parsers(cp), spd)
    assert all(math.isfinite(x) and abs(x) < 100 for x in out)
    assert abs(out[-1] - expect) < 0.5
