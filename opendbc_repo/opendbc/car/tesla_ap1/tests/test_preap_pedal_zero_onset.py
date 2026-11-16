"""Pre-AP Comma Pedal calibration: the zero is the pedal reading where the car first reports throttle (Tinkla parity), never below the
measured rest noise floor, and the feet-off step is judged on medians so a noisy pedal can calibrate.

Why: with the zero at the resting MEAN, gasPressed (pedal_to_di > 2, i.e. reading > zero + 1/factor) sat inside the rest noise and flickered
True with the foot off. Tinkla calibratePedal.py saves the rest mean only as TeslaPedalCalibMin (:436) and the DI-onset value as
TeslaPedalCalibZero (:362-364, :396-399, :444); factor = 100 / (max - zero) (:401). The rest samples below are synthetic, shaped like a noisy
pedal (0x552 raw 433 to 485 with the foot off).
"""
import random
from types import SimpleNamespace

import pytest

from opendbc.car.tesla_ap1.preap import calib, params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.preap.pedal_can import PEDAL_ENABLED_COMMAND_LIMIT, PEDAL_ENABLED_RAW_LIMIT, PedalCommandCounter, create_pedal_command
from opendbc.car.tesla_ap1.preap.pedal_controller import di_to_pedal
from opendbc.car.tesla_ap1.preap.pedal_feedback import PedalFeedback
from opendbc.car.tesla_ap1.preap.vdas_constants import PEDAL_DI_MIN, PEDAL_MAX_VALUES

SCALE, OFFSET = 0.0507968128, -22.85856576     # GAS_SENSOR INTERCEPTOR_GAS (tesla_ap1_can.dbc)


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  yield tmp_path


def dbc(raw):
  return raw * SCALE + OFFSET


def noisy_rest(n=calib.COAST_FRAMES, seed=7):
  """A noisy pedal at rest: raw 433..485 (2.64 DBC units peak to peak), each 50 Hz reading seen twice by the 100 Hz controller."""
  rng = random.Random(seed)
  out = []
  while len(out) < n:
    r = dbc(rng.randint(433, 485))
    out += [r, r]
  return out[:n]


def _controller():
  from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
  from opendbc.car.tesla_ap1.values import CAR, DBC
  CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
  return PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], CP)


def feed(cc, pairs):
  for raw, di in pairs:
    cc._update_detection_and_calib(SimpleNamespace(preap_pedal_detected=True, preap_pedal_raw=raw, di_gas=di))


def armed_after_rest(rest):
  cc = _controller()
  params.set_bool(K.PEDAL_CALIB_ARMED, True)
  feed(cc, [(r, 0.0) for r in rest])
  return cc


def press(onset_raw, full_raw, pre=(), deeper=()):
  """A slow driver press: readings rise with DI 0 (`pre`), the car reports 0.4 % at onset_raw, ..., 99.6 % at full_raw."""
  steps = [(r, 0.0) for r in pre] + [(onset_raw, 0.004)]
  for k in range(1, 20):
    steps.append((onset_raw + (full_raw - onset_raw) * k / 20, 0.004 + 0.99 * k / 20))
  return steps + [(full_raw, 0.996)] + [(r, 1.0) for r in deeper]


# ---- pure math ----
def test_percentile_is_nearest_rank_and_rest_stats():
  assert calib.percentile(range(1, 101), 99) == 99
  assert calib.percentile([5.0], 99) == 5.0
  st = calib.rest_stats([1.0, 2.0, 3.0, 10.0])
  assert st["mean"] == 4.0 and st["median"] == 2.5 and st["p99"] == 10.0 and st["p2p"] == 9.0 and st["n"] == 4


def test_a_noisy_rest_is_steady_but_a_drifting_or_moving_one_is_not():
  rest = noisy_rest()
  assert max(rest) - min(rest) > 1.0          # the old max-min <= COAST_RAW_QUIET (1.0) test could never pass this pedal
  assert calib.coast_steady(rest)
  assert not calib.coast_steady(rest[:-1])    # not a full window yet
  drift = [v + (2.0 if i >= len(rest) // 2 else 0.0) for i, v in enumerate(rest)]
  assert not calib.coast_steady(drift)        # the reading moved by 2 DBC units halfway through: the foot was on the pedal
  moving = list(rest)
  moving[10] = rest[10] + calib.COAST_P2P_MAX + 1.0
  assert not calib.coast_steady(moving)


def test_zero_from_onset_keeps_the_onset_clamps_to_the_floor_and_fails_below_the_rest_mean():
  rest = calib.rest_stats(noisy_rest())
  floor = calib.noise_floor(rest)
  assert floor == pytest.approx(rest["p99"] + calib.NOISE_FLOOR_MARGIN)
  assert calib.zero_from_onset(rest, floor + 3.0) == (floor + 3.0, False, "ok")       # Tinkla parity: the onset reading
  z, clamped, why = calib.zero_from_onset(rest, rest["mean"] + 0.1)                    # car saw gas inside the rest noise
  assert z == pytest.approx(floor) and clamped and why == "ok"
  z, clamped, why = calib.zero_from_onset(rest, rest["mean"] - 0.5)                    # car saw gas below the resting reading
  assert z is None and why == calib.ONSET_BELOW_REST and len(why) < calib.MESSAGE_MAX


def test_compute_calibration_onset_factor_min_and_max():
  rest = calib.rest_stats([0.8] * calib.COAST_FRAMES)
  res = calib.compute_calibration_onset(rest, 4.0, 108.0)
  assert res["ok"] and res["pedal_calib_zero"] == 4.0
  assert res["pedal_calib_factor"] == pytest.approx(100.0 / 104.0)                   # Tinkla :401
  assert res["pedal_calib_min"] == pytest.approx(0.8) and res["pedal_calib_max"] == 108.0
  assert not calib.compute_calibration_onset(rest, 4.0, 9.0)["ok"]                    # span 5: barely moved
  assert not calib.compute_calibration_onset(rest, 0.0, 108.0)["ok"]                  # onset below the rest mean


# ---- the capture, end to end through the controller ----
def test_a_noisy_pedal_passes_step_1_and_the_zero_is_the_onset_reading():
  rest = noisy_rest()
  cc = armed_after_rest(rest)
  assert cc._calib_rest is not None and params.get_str(K.PEDAL_CALIB_STAGE) == calib.STAGE_COAST_OK
  onset = max(rest) + 2.0
  feed(cc, press(onset, onset + 100.0, pre=[max(rest), max(rest) + 1.0]))
  assert calib.is_pedal_calibrated() and not params.get_bool(K.PEDAL_CALIB_ARMED)
  assert params.get_float(K.PEDAL_CALIB_ZERO) == pytest.approx(onset)
  assert params.get_float(K.PEDAL_CALIB_FACTOR) == pytest.approx(1.0)
  assert params.get_float(K.PEDAL_CALIB_MIN) == pytest.approx(sum(rest) / len(rest))
  assert params.get_float(K.PEDAL_CALIB_MAX) == pytest.approx(onset + 100.0)


def test_step_1_only_counts_frames_with_no_throttle_on_the_car():
  cc = _controller()
  params.set_bool(K.PEDAL_CALIB_ARMED, True)
  feed(cc, [(0.8, 0.0)] * (calib.COAST_FRAMES - 1) + [(0.8, 0.004)] + [(0.8, 0.0)] * (calib.COAST_FRAMES - 1))
  assert cc._calib_rest is None                # DI 0.4 % restarted the window
  feed(cc, [(0.8, 0.0)])
  assert cc._calib_rest is not None


def test_onset_below_the_floor_is_clamped_to_the_floor():
  rest = noisy_rest()
  st = calib.rest_stats(rest)
  cc = armed_after_rest(rest)
  feed(cc, press(st["mean"] + 0.2, st["mean"] + 100.0))
  assert calib.is_pedal_calibrated()
  floor = calib.noise_floor(st)
  assert params.get_float(K.PEDAL_CALIB_ZERO) == pytest.approx(floor)
  assert params.get_float(K.PEDAL_CALIB_FACTOR) == pytest.approx(100.0 / (st["mean"] + 100.0 - floor))


def test_onset_below_the_rest_mean_fails_and_keeps_the_old_calibration():
  params.set_float(K.PEDAL_CALIB_ZERO, 5.0)
  params.set_float(K.PEDAL_CALIB_FACTOR, 1.1)
  params.set_bool(K.PEDAL_CALIB_DONE, True)
  cc = armed_after_rest([3.0] * calib.COAST_FRAMES)
  feed(cc, press(2.0, 104.0))
  assert params.get_str(K.PEDAL_CALIB_MESSAGE) == calib.ONSET_BELOW_REST
  assert params.get_float(K.PEDAL_CALIB_ZERO) == 5.0 and params.get_float(K.PEDAL_CALIB_FACTOR) == 1.1
  assert calib.pedal_status(detected=True) == calib.STATUS_FAILED


def test_the_full_reading_is_taken_where_the_car_first_reads_full_throttle_not_deeper():
  cc = armed_after_rest([0.8] * calib.COAST_FRAMES)
  feed(cc, press(4.0, 104.0, deeper=[115.0] * 20))
  assert params.get_float(K.PEDAL_CALIB_FACTOR) == pytest.approx(1.0)        # 100 / (104 - 4); the kickdown past 99.6 % is not used
  assert params.get_float(K.PEDAL_CALIB_MAX) == 104.0


def test_a_twitch_is_ignored_and_the_next_press_is_measured():
  cc = armed_after_rest([0.8] * calib.COAST_FRAMES)
  feed(cc, [(2.0, 0.004), (2.5, 0.012)] + [(0.8, 0.0)] * calib.PRESS_RELEASE_FRAMES)
  assert params.get_bool(K.PEDAL_CALIB_ARMED) and cc._calib_onset is None and not params.get_str(K.PEDAL_CALIB_MESSAGE)
  feed(cc, press(4.0, 104.0))
  assert calib.is_pedal_calibrated() and params.get_float(K.PEDAL_CALIB_ZERO) == 4.0


def test_a_press_let_go_before_full_throttle_fails_with_a_plain_message():
  cc = armed_after_rest([0.8] * calib.COAST_FRAMES)
  feed(cc, press(4.0, 104.0)[:12] + [(0.8, 0.0)] * calib.PRESS_RELEASE_FRAMES)
  assert not calib.is_pedal_calibrated() and not params.get_bool(K.PEDAL_CALIB_ARMED)
  assert params.get_str(K.PEDAL_CALIB_MESSAGE) == calib.PRESS_NOT_FULL
  low = calib.PRESS_NOT_FULL.lower()
  assert "factor" not in low and "di" not in low.split() and calib.PRESS_NOT_FULL.endswith("try again.")


def test_a_press_that_never_reaches_full_throttle_fails_after_the_window():
  cc = armed_after_rest([0.8] * calib.COAST_FRAMES)
  feed(cc, [(50.0, 0.5)] * (calib.PRESS_WINDOW_FRAMES - 1))
  assert params.get_bool(K.PEDAL_CALIB_ARMED)
  feed(cc, [(50.0, 0.5)])
  assert params.get_str(K.PEDAL_CALIB_MESSAGE) == calib.PRESS_NOT_FULL and not calib.is_pedal_calibrated()


def test_a_short_dip_does_not_end_the_press():
  cc = armed_after_rest([0.8] * calib.COAST_FRAMES)
  p = press(4.0, 104.0)
  feed(cc, p[:10] + [(3.0, 0.0)] * (calib.PRESS_RELEASE_FRAMES - 1) + p[10:])
  assert calib.is_pedal_calibrated() and params.get_float(K.PEDAL_CALIB_ZERO) == 4.0


def test_disarm_or_lost_pedal_mid_press_saves_nothing():
  cc = armed_after_rest([0.8] * calib.COAST_FRAMES)
  feed(cc, press(4.0, 104.0)[:10])
  params.set_bool(K.PEDAL_CALIB_ARMED, False)
  feed(cc, press(4.0, 104.0)[10:])
  assert not calib.is_pedal_calibrated() and cc._calib_onset is None and cc._calib_rest is None
  cc = armed_after_rest([0.8] * calib.COAST_FRAMES)
  feed(cc, press(4.0, 104.0)[:10])
  cc._update_detection_and_calib(SimpleNamespace(preap_pedal_detected=False, preap_pedal_raw=None, di_gas=0.0))
  feed(cc, press(4.0, 104.0)[10:])
  assert not calib.is_pedal_calibrated()


# ---- what the driver gets: gasPressed at rest, and the commanded path with the higher zero ----
def _gas_pressed_count(samples):
  pf = PedalFeedback()
  n = 0
  for i, g in enumerate(samples):
    pf.update({"INTERCEPTOR_GAS": g, "INTERCEPTOR_GAS2": g, "STATE": 0, "IDX": i % 16}, i * 10)
    n += int(pf.gas_pressed)
  return n


def test_gas_pressed_never_flickers_at_rest_with_the_new_zero_but_did_with_the_rest_mean():
  rest = noisy_rest()
  later = noisy_rest(n=2000, seed=11)          # the same pedal at rest for 20 s after calibrating
  st = calib.rest_stats(rest)
  params.set_bool(K.PEDAL_CALIB_DONE, True)
  # before: zero = the rest mean (what the old capture saved), factor 0.947
  params.set_float(K.PEDAL_CALIB_ZERO, st["mean"])
  params.set_float(K.PEDAL_CALIB_FACTOR, 0.947)
  assert _gas_pressed_count(later) > 0
  # after: the lowest zero the new rule can save for this rest window is the floor (any onset below it is clamped)
  cc = armed_after_rest(rest)
  feed(cc, press(st["mean"] + 0.1, st["mean"] + 105.6))
  assert calib.is_pedal_calibrated()
  assert params.get_float(K.PEDAL_CALIB_ZERO) == pytest.approx(calib.noise_floor(st))
  assert _gas_pressed_count(later) == 0
  # and a real press still reads as pressed
  assert _gas_pressed_count([calib.noise_floor(st) + 2.0]) == 1


@pytest.mark.parametrize("zero,factor", [(1.8, 0.96), (4.0, 1.0), (10.0, 0.9), (20.0, 1.25), (30.0, 3.0)])
def test_commanded_path_with_a_higher_zero(zero, factor):
  params.set_float(K.PEDAL_CALIB_ZERO, zero)
  params.set_float(K.PEDAL_CALIB_FACTOR, factor)
  params.set_bool(K.PEDAL_CALIB_DONE, True)
  assert calib.is_pedal_calibrated()
  coast, f = calib.current_pedal_transform()
  assert coast == pytest.approx(zero - 1.0 / factor)                  # Tinkla tunes.py:19 PEDAL_ZERO = CalibZero - 1/factor
  assert di_to_pedal(0.0) == pytest.approx(zero - 1.0 / factor) and di_to_pedal(0.0) < zero    # DI 0 asks for less than the onset
  assert di_to_pedal(1.0) == pytest.approx(zero)                      # the onset reading maps to DI 1 %
  # a higher zero only trims the very top of the planner range at low factors (the clamp keeps every frame under the panda cap)
  reach = calib.max_reachable_di(zero, factor)
  assert reach == pytest.approx(min(calib.PEDAL_DI_MAX, 1.0 + factor * (PEDAL_ENABLED_COMMAND_LIMIT - zero)))
  assert reach > 80.0
  c = PedalCommandCounter()
  for di in (PEDAL_DI_MIN, 0.0, 30.0, 60.0, max(PEDAL_MAX_VALUES)):
    frame = create_pedal_command(di_to_pedal(di), 1, c)
    assert ((frame.dat[0] << 8) | frame.dat[1]) <= PEDAL_ENABLED_RAW_LIMIT
