"""Comma Pedal 0x551 packing, calibration validation and the driver-press capture state machine."""
from types import SimpleNamespace

import pytest

from opendbc.car.tesla_ap1.preap import calib, params
from opendbc.car.tesla_ap1.preap.pedal_can import GAS_COMMAND_ID, PedalCommandCounter, create_pedal_command
from opendbc.car.tesla_ap1.tests.ap1_harness import decode


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  yield tmp_path


def test_pedal_command_checksum_enable_and_dbc_roundtrip():
  c = PedalCommandCounter()
  f = create_pedal_command(20.0, 1, c, pedal_can_bus=2)
  assert f.address == GAS_COMMAND_ID and f.src == 2 and len(f.dat) == 6
  assert f.dat[4] & 0x80
  assert f.dat[5] == (0x51 + 0x05 + sum(f.dat[:5])) & 0xFF
  name, v = decode(GAS_COMMAND_ID, f.dat)
  assert name == "GAS_COMMAND" and v["ENABLE"] == 1
  assert abs(v["GAS_COMMAND"] - 20.0) < 0.1 and abs(v["GAS_COMMAND2"] - 20.0) < 0.2
  off = create_pedal_command(5.0, 0, c)
  assert off.dat[:4] == bytes(4) and not off.dat[4] & 0x80


def test_pedal_counter_is_consecutive_mod_16():
  c = PedalCommandCounter()
  idx = [create_pedal_command(1.0, 1, c).dat[4] & 0x0F for _ in range(20)]
  assert idx == [i % 16 for i in range(20)]


def test_known_bad_ready_is_rejected():
  # raw 0.762 -> 6.451 (span 5.69, factor 17.6) used to be written as Ready
  res = calib.compute_calibration(0.762, 6.451)
  assert not res["ok"] and "barely moved" in res["reason"]
  assert not calib.apply_calibration_result(res)
  assert not calib.is_pedal_calibrated()


def test_real_full_press_is_accepted_and_ready():
  res = calib.compute_calibration(0.8, 107.0)
  assert res["ok"] and 0.9 < res["pedal_calib_factor"] < 1.0
  assert calib.apply_calibration_result(res)
  assert calib.is_pedal_calibrated()
  assert calib.pedal_status(detected=True) == calib.STATUS_READY
  assert calib.pedal_status(detected=False) == calib.STATUS_NOT_DETECTED


def test_insane_factor_rejected():
  assert not calib.compute_calibration(0.0, 20.0)["ok"] or calib.compute_calibration(0.0, 20.0)["pedal_calib_factor"] <= calib.FACTOR_MAX
  res = calib.compute_calibration(0.0, 10.5)
  assert not res["ok"]          # factor 9.5


def test_done_flag_with_default_values_is_not_calibrated():
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_DONE, True)
  assert not calib.is_pedal_calibrated()


def test_long_allowed_needs_user_pedal_and_calibration():
  assert not calib.pedal_long_allowed(user_wants_long=False, detected=True, calibrated=True)
  assert not calib.pedal_long_allowed(user_wants_long=True, detected=False, calibrated=True)
  assert not calib.pedal_long_allowed(user_wants_long=True, detected=True, calibrated=False)
  assert calib.pedal_long_allowed(user_wants_long=True, detected=True, calibrated=True)


def _controller():
  from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
  from opendbc.car.tesla_ap1.values import CAR, DBC
  from opendbc.car import Bus
  CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
  return PreApCarController({Bus.chassis: "tesla_ap1_can", Bus.pt: "tesla_powertrain"} | {k: v for k, v in DBC[CP.carFingerprint].items() if k == Bus.chassis}, CP)


def _cs(raw, gas):
  return SimpleNamespace(preap_pedal_detected=True, preap_pedal_raw=raw, out=SimpleNamespace(), di_gas=gas)


def _armed_after_coast(coast=0.8):
  cc = _controller()
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED, True)
  for _ in range(calib.COAST_FRAMES + 2):
    cc._update_detection_and_calib(_cs(coast, 0.0))
  assert cc._calib_coast is not None
  return cc


def _press(cc, levels, gas=0.9):
  for raw in levels:
    cc._update_detection_and_calib(_cs(raw, gas))


def _release(cc, coast=0.8):
  for _ in range(calib.PRESS_RELEASE_FRAMES):
    cc._update_detection_and_calib(_cs(coast, 0.0))


def _saved_factor():
  return params.get_float(params.PreApParamKeys.PEDAL_CALIB_FACTOR)


def test_capture_state_machine_driver_press_only():
  cc = _controller()
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED, True)
  # foot off: quiet interceptor and DI gas ~0 for COAST_FRAMES
  for _ in range(calib.COAST_FRAMES + 2):
    cc._update_detection_and_calib(_cs(0.8, 0.0))
  assert cc._calib_coast is not None and params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED)
  # press: interceptor rises together with DI gas; it is measured until the driver lets go
  for _ in range(30):
    cc._update_detection_and_calib(_cs(107.0, 0.9))
  assert params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED), "still measuring while the foot is down"
  assert not calib.is_pedal_calibrated()
  _release(cc)
  assert not params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED)
  assert calib.is_pedal_calibrated()


def test_twitch_does_not_calibrate_and_noisy_coast_never_starts():
  cc = _controller()
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED, True)
  for i in range(calib.COAST_FRAMES * 3):          # noisy interceptor: span > COAST_RAW_QUIET, never "coast"
    cc._update_detection_and_calib(_cs(0.0 + (i % 2) * 5.0, 0.0))
  assert cc._calib_coast is None
  cc = _controller()
  for _ in range(calib.COAST_FRAMES + 2):
    cc._update_detection_and_calib(_cs(0.8, 0.0))
  cc._update_detection_and_calib(_cs(7.0, 0.9))    # 5-count twitch (< PRESS_RAW_DELTA): ignored
  assert not calib.is_pedal_calibrated() and cc._calib_press is None


def test_press_without_di_gas_is_ignored_and_small_span_fails_with_a_message():
  cc = _controller()
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED, True)
  for _ in range(calib.COAST_FRAMES + 2):
    cc._update_detection_and_calib(_cs(0.8, 0.0))
  cc._update_detection_and_calib(_cs(60.0, 0.0))   # interceptor moved but the car did not see gas: not a driver press
  assert cc._calib_press is None
  _press(cc, [11.0] * 12, gas=0.2)                 # real press, span 10.2 -> factor 9.8
  _release(cc)                                     # ... rejected once the driver lets go, message surfaces
  assert not calib.is_pedal_calibrated()
  assert params.get_str(params.PreApParamKeys.PEDAL_CALIB_MESSAGE)
  assert calib.pedal_status(detected=True) == calib.STATUS_FAILED


# ---- the saved value is the DEEPEST held point of the press, not the first sample over the threshold ----
def test_a_slow_press_saves_the_deepest_point_not_the_first_sample_over_the_threshold():
  cc = _armed_after_coast()
  ramp = [12.0, 20.0, 35.0, 55.0, 80.0, 100.0, 107.0]
  _press(cc, [r for r in ramp for _ in range(3)] + [107.0] * 20)
  _release(cc)
  assert calib.is_pedal_calibrated()
  assert _saved_factor() == pytest.approx(100.0 / (107.0 - 0.8), rel=1e-6)     # the old first-sample capture would have used 12.0 (scale 8.9)
  assert params.get_float(params.PreApParamKeys.PEDAL_CALIB_MAX) == pytest.approx(107.0)


def test_the_deepest_point_is_used_even_when_the_driver_eases_off_before_letting_go():
  cc = _armed_after_coast()
  _press(cc, [60.0] * 10 + [110.0] * 12 + [90.0] * 15 + [40.0] * 5)
  _release(cc)
  assert _saved_factor() == pytest.approx(100.0 / (110.0 - 0.8), rel=1e-6)


@pytest.mark.parametrize("spike_len", [1, 2, 3, 7])
def test_a_noise_spike_shorter_than_the_hold_is_rejected(spike_len):
  assert spike_len < calib.PRESS_HOLD_SAMPLES
  cc = _armed_after_coast()
  _press(cc, [100.0] * 15 + [180.0] * spike_len + [100.0] * 15)
  _release(cc)
  assert _saved_factor() == pytest.approx(100.0 / (100.0 - 0.8), rel=1e-6)     # the spike is ignored


def test_a_reading_held_for_the_hold_count_is_the_deepest_point():
  cc = _armed_after_coast()
  _press(cc, [100.0] * 15 + [115.0] * calib.PRESS_HOLD_SAMPLES + [100.0] * 15)
  _release(cc)
  assert _saved_factor() == pytest.approx(100.0 / (115.0 - 0.8), rel=1e-6)


def test_a_press_too_short_to_measure_fails_with_a_plain_message_and_changes_nothing():
  cc = _armed_after_coast()
  _press(cc, [107.0] * (calib.PRESS_HOLD_SAMPLES - 1))
  _release(cc)
  assert not calib.is_pedal_calibrated() and not params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED)
  assert params.get_str(params.PreApParamKeys.PEDAL_CALIB_MESSAGE) == calib.PRESS_TOO_SHORT
  assert "too short" in calib.PRESS_TOO_SHORT and "factor" not in calib.PRESS_TOO_SHORT.lower()
  assert calib.pedal_status(detected=True) == calib.STATUS_FAILED


def test_the_capture_ends_after_the_window_if_the_foot_stays_down():
  cc = _armed_after_coast()
  _press(cc, [107.0] * (calib.PRESS_WINDOW_FRAMES - 1))
  assert params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED)
  _press(cc, [107.0])
  assert not params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED) and calib.is_pedal_calibrated()
  assert _saved_factor() == pytest.approx(100.0 / (107.0 - 0.8), rel=1e-6)


def test_nothing_is_saved_while_the_press_is_still_being_measured_and_a_disarm_or_lost_pedal_saves_nothing():
  cc = _armed_after_coast()
  _press(cc, [107.0] * 40)
  assert not calib.is_pedal_calibrated()
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED, False)             # Cancel / timeout / screen closed
  _press(cc, [107.0] * 5)
  _release(cc)
  assert not calib.is_pedal_calibrated() and cc._calib_press_samples is None
  cc = _armed_after_coast()
  _press(cc, [107.0] * 40)
  cc._update_detection_and_calib(SimpleNamespace(preap_pedal_detected=False, preap_pedal_raw=None, out=SimpleNamespace(), di_gas=0.0))
  _release(cc)
  assert not calib.is_pedal_calibrated()


def test_a_brief_dip_does_not_end_the_press_but_a_real_release_does():
  cc = _armed_after_coast()
  _press(cc, [107.0] * 10)
  for _ in range(calib.PRESS_RELEASE_FRAMES - 1):
    cc._update_detection_and_calib(_cs(0.8, 0.0))
  _press(cc, [120.0] * 12)                                                    # back on the pedal before the release count was reached
  assert params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED)
  _release(cc)
  assert _saved_factor() == pytest.approx(100.0 / (120.0 - 0.8), rel=1e-6)
