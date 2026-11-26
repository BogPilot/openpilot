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


# ---- StW_AnglHP_Sens_Stat (PREAP_COLUMN_SENS_STAT_20261120) ----------------------------------------------------------------

from opendbc.car.tesla_ap1.steer_rate import SOURCE_EPAS_ANGLE  # noqa: E402


def _feed_epas(f, n, col_rate, col_angle, stat, epas_rate_dps, start=0, epas_angle0=0.0):
  """100 Hz calls; the EPAS frame (25 Hz) is new every 4th call. Returns the published rates."""
  out = []
  for i in range(start, start + n):
    k = i // 4
    epas_angle = epas_angle0 + epas_rate_dps * 0.04 * k
    out.append(f.update(col_rate, col_angle(i) if callable(col_angle) else col_angle, i % 16, sens_stat=stat,
                        epas_angle=epas_angle, epas_counter=k % 16))
  return out


@pytest.mark.parametrize("stat", [1, 2, 3])
def test_bad_status_ignores_the_column_and_uses_the_epas_angle(stat):
  f = SteerRateFallback()
  out = _feed_epas(f, 200, 300.0, lambda i: 50.0 + i, stat, 15.0)    # column says 300 deg/s and a racing angle: both ignored
  assert f.source == SOURCE_EPAS_ANGLE and not f.column_ok
  assert abs(out[-1] - 15.0) < 0.5
  assert all(abs(x) < 16.0 for x in out)


def test_ok_status_is_unchanged_behaviour():
  for rate in (12.0, SNA):
    a, b = SteerRateFallback(), SteerRateFallback()
    out_a = _feed_epas(a, 200, rate, lambda i: 0.1 * i, 0, 40.0)
    out_b = _feed(b, [rate] * 200, [0.1 * i for i in range(200)], [i % 16 for i in range(200)])
    assert out_a == out_b and a.column_ok


def test_bad_status_and_epas_sna_gives_zero():
  f = SteerRateFallback()
  out = [f.update(200.0, 10.0, i % 16, sens_stat=2, epas_angle=-819.1, epas_counter=(i // 4) % 16) for i in range(50)]
  assert f.source == SOURCE_NONE and all(x == 0.0 for x in out)
  out = [f.update(200.0, 10.0, i % 16, sens_stat=2) for i in range(10)]     # no EPAS angle passed: also zero
  assert all(x == 0.0 for x in out)


def test_stale_epas_frame_gives_zero():
  f = SteerRateFallback()
  _feed_epas(f, 40, 0.0, 0.0, 1, 20.0)
  assert f.source == SOURCE_EPAS_ANGLE
  out = [f.update(0.0, 0.0, i % 16, sens_stat=1, epas_angle=3.2, epas_counter=9) for i in range(40)]   # counter stuck 0.4 s
  assert out[-1] == 0.0 and f.source == SOURCE_NONE


def test_status_flicker_has_no_spike():
  f = SteerRateFallback()
  rnd = random.Random(11)
  out = []
  for i in range(2000):    # wheel still; column status flickers OK / ERR, EPAS angle has 1 LSB noise
    stat = 0 if (i // 37) % 2 == 0 else 2
    out.append(f.update(SNA, 4.0 + round(rnd.gauss(0.0, 0.05), 1), i % 16, sens_stat=stat,
                        epas_angle=4.0 + 0.1 * rnd.choice((0, 0, 1)), epas_counter=(i // 4) % 16))
  assert max(abs(x) for x in out[10:]) < 15.0              # ANGLE_ERROR needs 20 deg/s, RATE 25-35 deg/s


def test_column_angle_sna_with_rate_sna_uses_the_epas_angle():
  f = SteerRateFallback()
  out = _feed_epas(f, 200, SNA, 819.1, 0, -25.0)
  assert f.source == SOURCE_EPAS_ANGLE and abs(out[-1] + 25.0) < 0.5


def _stw_stat(packer, bus, ang, spd, counter, stat):
  addr, dat, _ = packer.make_can_msg("STW_ANGLHP_STAT", bus, {"StW_AnglHP": ang, "StW_AnglHP_Spd": spd, "MC_STW_ANGLHP_STAT": counter,
                                                              "StW_AnglHP_Sens_Stat": stat})
  return addr, dat


def _run_carstate_stat(state, parsers, stat, n=200):
  chassis = parsers[Bus.chassis]
  packer = CANPacker("tesla_ap1_can")
  out = []
  for i in range(n):
    frames = [_stw_stat(packer, chassis.bus, 100.0, 500.0, i % 16, stat) + (chassis.bus,)]   # column: nonsense rate
    if i % 4 == 0:   # EPAS 25 Hz, 10 deg/s
      a2, d2, _ = packer.make_can_msg("EPAS_sysStatus", chassis.bus, {"EPAS_internalSAS": 0.4 * (i // 4),
                                                                      "EPAS_sysStatusCounter": (i // 4) % 16})
      frames.append((a2, d2, chassis.bus))
    chassis.update([((i + 1) * 10_000_000, frames)])
    out.append(state.update(parsers).steeringRateDeg)
  return out, state.steer_rate_source


def test_ap1_and_preap_carstates_gate_on_status(tmp_path, monkeypatch):
  from opendbc.car.tesla_ap1.carstate import CarState
  from opendbc.car.tesla_ap1.preap import params
  from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
  from opendbc.car.tesla_ap1.values import CAR
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  for cls, cp in ((CarState, SimpleNamespace(carFingerprint=CAR.TESLA_AP1_MODELS)),
                  (PreApCarState, SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True))):
    out, src = _run_carstate_stat(cls(cp), cls.get_can_parsers(cp), 2)
    assert src == SOURCE_EPAS_ANGLE and abs(out[-1] + 10.0) < 1.0, (cls, out[-5:])
    out, src = _run_carstate_stat(cls(cp), cls.get_can_parsers(cp), 0)
    assert src == SOURCE_SENSOR and out[-1] == -500.0
