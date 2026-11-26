"""One pedal limit for the calibration check and the 0x551 encoder, pinned to the panda's cap.

The panda drops an enabled 0x551 frame whose raw command is above `max_enabled_raw_gas_cmd` in tesla_preap.h. Previously the
calibration accepted pedal scales 0.4 to 3.0, and below about 0.85 a normal full pedal command went over that cap and was dropped.
The encoder now clamps to the shared limit and the accepted window is a fixed 0.82 to 3.0: a low scale only
loses some top-end acceleration (calib.max_reachable_di), it can no longer overrun the panda cap. The bounds will be revisited after
the first 0.11.2 calibration and first-drive rlogs.
"""
import re
from pathlib import Path

import pytest

from opendbc.car.tesla_ap1.preap import calib, params
from opendbc.car.tesla_ap1.preap.pedal_can import (
  PANDA_MAX_ENABLED_RAW_GAS_CMD, PEDAL_ENABLED_COMMAND_LIMIT, PEDAL_ENABLED_RAW_LIMIT, PEDAL_RAW_MARGIN,
  PedalCommandCounter, create_pedal_command,
)
from opendbc.car.tesla_ap1.preap.pedal_controller import di_to_pedal
from opendbc.car.tesla_ap1.preap.vdas_constants import PEDAL_DI_MIN, PEDAL_MAX_VALUES

PANDA_HEADER = Path(__file__).resolve().parents[3] / "safety" / "modes" / "tesla_preap.h"


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  yield tmp_path


def _raw_of(frame) -> int:
  return (frame.dat[0] << 8) | frame.dat[1]


def test_python_limit_is_the_panda_cap_in_tesla_preap_h():
  m = re.search(r"max_enabled_raw_gas_cmd\s*=\s*(\d+)\s*;", PANDA_HEADER.read_text())
  assert m, "max_enabled_raw_gas_cmd not found in tesla_preap.h"
  assert int(m.group(1)) == PANDA_MAX_ENABLED_RAW_GAS_CMD
  assert PEDAL_ENABLED_RAW_LIMIT == PANDA_MAX_ENABLED_RAW_GAS_CMD - PEDAL_RAW_MARGIN < PANDA_MAX_ENABLED_RAW_GAS_CMD


def test_window_constants():
  assert calib.FACTOR_MIN == 0.82
  assert calib.FACTOR_MAX == 3.0
  assert calib.PEDAL_DI_MAX == max(PEDAL_MAX_VALUES) == 90.0
  assert PEDAL_ENABLED_COMMAND_LIMIT == pytest.approx(101.5936, abs=1e-3)


def test_the_window_is_fixed_and_reachable_di_comes_from_the_shared_limit_not_a_second_number():
  # one limit: the top-end that a low scale loses is computed from PEDAL_ENABLED_COMMAND_LIMIT, and the encoder clamps to the same value
  for zero, scale in ((0.0, 0.82), (0.8, 0.82), (5.0, 0.9), (0.8, 0.9416)):
    di = calib.max_reachable_di(zero, scale)
    cmd = zero - 1.0 / scale + di / scale
    assert cmd <= PEDAL_ENABLED_COMMAND_LIMIT + 1e-9
    if di < calib.PEDAL_DI_MAX:
      assert cmd == pytest.approx(PEDAL_ENABLED_COMMAND_LIMIT)


def test_how_much_top_end_a_082_pedal_loses():
  # planner positions up to PEDAL_DI_MAX (90) are sent; at scale 0.82 the command reaches the shared limit at about 84 percent
  assert calib.max_reachable_di(0.0, 0.82) == pytest.approx(84.31, abs=0.01)
  assert calib.max_reachable_di(0.8, 0.82) == pytest.approx(83.65, abs=0.01)
  assert calib.PEDAL_DI_MAX - calib.max_reachable_di(0.8, 0.82) == pytest.approx(6.35, abs=0.01)
  # a normal pedal (0.94) and anything above it loses nothing
  assert calib.max_reachable_di(0.8, 0.9416) == calib.PEDAL_DI_MAX
  assert calib.max_reachable_di(0.8, 0.89) == pytest.approx(90.0, abs=0.5)
  # above the reachable DI every planner request sends the same, clamped, command (a flat top, not an overrun)
  c = PedalCommandCounter()
  zero, scale = calib.coast_pedal_zero(0.8, 0.82), 0.82
  raws = [_raw_of(create_pedal_command(calib.transform_di_to_pedal(di, zero, scale), 1, c)) for di in (84.0, 86.0, 88.0, 90.0)]
  assert max(raws) == PEDAL_ENABLED_RAW_LIMIT or max(raws) == PEDAL_ENABLED_RAW_LIMIT - 1
  assert raws[1] == raws[2] == raws[3]


@pytest.mark.parametrize("zero", [0.0, 0.8, 2.0, 5.0, 10.0, 20.0, 40.0])
def test_no_accepted_scale_can_push_a_full_pedal_command_over_the_cap(zero):
  # sweep every scale in 0.001 steps across the old and new windows: every accepted scale, every planner position, every frame built
  # is at or under the shared limit (the encoder clamp), so a frame is never one the panda would drop
  f = 0.30
  accepted = []
  c = PedalCommandCounter()
  while f <= 3.2:
    if calib.calibration_in_window(zero, f):
      accepted.append(f)
      for di in (PEDAL_DI_MIN, 20.0, 60.0, 84.0, 89.9, calib.PEDAL_DI_MAX):
        cmd = calib.transform_di_to_pedal(di, calib.coast_pedal_zero(zero, f), f)
        assert _raw_of(create_pedal_command(cmd, 1, c)) <= PEDAL_ENABLED_RAW_LIMIT < PANDA_MAX_ENABLED_RAW_GAS_CMD, (zero, f, di)
    f = round(f + 0.001, 3)
  assert accepted and min(accepted) == pytest.approx(0.82) and max(accepted) == pytest.approx(3.0), zero


@pytest.mark.parametrize("scale", [0.4, 0.6, 0.8, 0.81, 0.8199, 3.0001, 3.5])
def test_scales_outside_the_fixed_window_are_rejected(scale):
  res, why = calib.validate_calibration(0.8, 0.8 + 100.0 / scale)
  assert res is None and why.startswith("Pedal scale ") and "(0.82 to 3.00)" in why


@pytest.mark.parametrize("scale", [0.8201, 0.82, 0.85, 0.87, 0.89, 0.94, 1.0, 1.5, 2.0, 2.5, 3.0])
def test_normal_scales_still_calibrate(scale):
  res, why = calib.validate_calibration(0.8, 0.8 + 100.0 / scale) if scale != 0.82 else calib.validate_calibration(0.8, 0.8 + 100.0 / 0.82001)
  assert res is not None and why == "ok"
  assert res["pedal_calib_factor"] == pytest.approx(scale, abs=1e-4)


def test_the_measured_real_press_is_unchanged():
  # raw 0.8 -> 107.0 (scale 0.9416) was accepted before and still is
  res = calib.compute_calibration(0.8, 107.0)
  assert res["ok"] and 0.94 < res["pedal_calib_factor"] < 0.95
  assert calib.worst_case_raw_gas_cmd(0.8, res["pedal_calib_factor"]) < PEDAL_ENABLED_RAW_LIMIT


@pytest.mark.parametrize("scale", [0.8201, 0.85, 0.9416, 1.0, 1.7, 3.0])
def test_end_to_end_saved_scale_to_frame_never_exceeds_the_panda_cap(scale):
  res = calib.compute_calibration(0.8, 0.8 + 100.0 / scale)
  assert calib.apply_calibration_result(res) and calib.is_pedal_calibrated()
  c = PedalCommandCounter()
  for di in (PEDAL_DI_MIN, 0.0, 30.0, 60.0, 89.9, max(PEDAL_MAX_VALUES)):
    frame = create_pedal_command(di_to_pedal(di), 1, c)
    assert _raw_of(frame) <= PANDA_MAX_ENABLED_RAW_GAS_CMD
    assert _raw_of(frame) <= PEDAL_ENABLED_RAW_LIMIT


def test_the_encoder_never_builds_a_frame_the_panda_would_drop():
  c = PedalCommandCounter()
  for cmd in (50.0, 101.0, 104.0, 120.0, 250.0, 1e6):
    frame = create_pedal_command(cmd, 1, c)
    assert _raw_of(frame) <= PEDAL_ENABLED_RAW_LIMIT
    assert (frame.dat[2] << 8 | frame.dat[3]) <= PEDAL_ENABLED_RAW_LIMIT // 2 + 1   # the second copy follows the same clamp
  # a command inside the limit is not changed
  assert abs(_raw_of(create_pedal_command(20.0, 1, c)) - (20.0 + 22.85856576) / 0.050796813) < 2
  # disabled frames are untouched (the panda's own 500 cap applies to them)
  assert create_pedal_command(250.0, 0, c).dat[:4] == bytes(4)


def test_saved_scale_outside_the_window_needs_recalibration_and_is_left_alone():
  K = params.PreApParamKeys
  params.set_float(K.PEDAL_CALIB_ZERO, 0.8)
  params.set_float(K.PEDAL_CALIB_FACTOR, 0.60)
  params.set_bool(K.PEDAL_CALIB_DONE, True)
  assert calib.saved_calibration_out_of_range()
  assert not calib.is_pedal_calibrated()
  assert not calib.pedal_long_allowed(user_wants_long=True, detected=True)
  assert calib.pedal_status(detected=True) == calib.STATUS_NEEDS_CALIBRATION
  # never rewritten, never cleared
  assert params.get_float(K.PEDAL_CALIB_FACTOR) == 0.60 and params.get_float(K.PEDAL_CALIB_ZERO) == 0.8
  assert params.get_bool(K.PEDAL_CALIB_DONE) is True
  # a saved in-window scale is fine (0.85 was out under the earlier formula floor and is in under the fixed 0.82), and "done with
  # defaults" is not an out-of-range save
  for ok in (0.94, 0.85, 0.83):
    params.set_float(K.PEDAL_CALIB_FACTOR, ok)
    assert calib.is_pedal_calibrated() and not calib.saved_calibration_out_of_range(), ok
  params.set_float(K.PEDAL_CALIB_FACTOR, 0.81)
  assert not calib.is_pedal_calibrated() and calib.saved_calibration_out_of_range()


def test_not_done_is_not_reported_as_out_of_range():
  assert not calib.saved_calibration_out_of_range()


def test_failure_reasons_use_plain_driver_words():
  cases = [
    calib.validate_calibration(0.8, 140.0)[1],      # scale below the floor
    calib.validate_calibration(0.8, 3.0)[1],        # barely moved
    calib.validate_calibration(0.8, 11.0)[1],       # scale far too high (9.8)
    calib.validate_calibration(200.0, 300.0)[1],    # idle reading too high
  ]
  for why in cases:
    low = why.lower()
    assert why != "ok" and len(why) < 150
    assert "factor" not in low and " gas" not in low and "span" not in low and "interceptor" not in low
    assert why.endswith("try again.")
  assert cases[0] == "Pedal scale 0.718 is out of range (0.82 to 3.00). Check the Comma Pedal wiring and try again."
  assert cases[2].startswith("Pedal scale 9.") and "(0.82 to 3.00)" in cases[2]
  assert cases[3] == "The pedal idle reading is too high. Check the Comma Pedal wiring and try again."


@pytest.mark.parametrize("onset", [1.1, 4.0, 12.0])
@pytest.mark.parametrize("scale", [0.8201, 0.9416, 1.7, 3.0])
def test_a_di_onset_calibration_never_exceeds_the_panda_cap_end_to_end(onset, scale):
  # the zero is now the DI-onset reading (higher than the old rest zero); the frames still never pass the shared limit
  rest = calib.rest_stats([0.8] * calib.COAST_FRAMES)
  res = calib.compute_calibration_onset(rest, onset, onset + 100.0 / scale)
  assert calib.apply_calibration_result(res) and calib.is_pedal_calibrated()
  assert params.get_float(params.PreApParamKeys.PEDAL_CALIB_ZERO) == pytest.approx(onset)
  c = PedalCommandCounter()
  for di in (PEDAL_DI_MIN, 0.0, 30.0, 60.0, 89.9, max(PEDAL_MAX_VALUES)):
    frame = create_pedal_command(di_to_pedal(di), 1, c)
    assert _raw_of(frame) <= PEDAL_ENABLED_RAW_LIMIT < PANDA_MAX_ENABLED_RAW_GAS_CMD


def test_failure_reason_survives_the_ui_message_limit():
  worst = calib.validate_calibration(0.8, 0.8 + 100.0 / 0.4)[1]
  assert len(worst) < calib.MESSAGE_MAX
