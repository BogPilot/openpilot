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
  assert cc._calib_rest is not None
  return cc


def _feed(cc, pairs):
  for raw, gas in pairs:
    cc._update_detection_and_calib(_cs(raw, gas))


def _press(onset=3.0, full=107.0):
  """Onset reading where the car first reports 0.4 %, a rise, then the reading where it first reports 99.6 %."""
  return [(onset, 0.004), (onset + 20.0, 0.2), (onset + 60.0, 0.6), (full, 0.996)]


def _saved_factor():
  return params.get_float(params.PreApParamKeys.PEDAL_CALIB_FACTOR)


def test_capture_state_machine_driver_press_only():
  cc = _controller()
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED, True)
  # foot off: the car reads DI 0 for a whole rest window
  for _ in range(calib.COAST_FRAMES + 2):
    cc._update_detection_and_calib(_cs(0.8, 0.0))
  assert cc._calib_rest is not None and params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED)
  # press: nothing is saved before the car reads full throttle
  _feed(cc, _press()[:3])
  assert params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED), "still measuring until the car reads full throttle"
  assert not calib.is_pedal_calibrated()
  _feed(cc, _press()[3:])
  assert not params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED)
  assert calib.is_pedal_calibrated()
  assert params.get_float(params.PreApParamKeys.PEDAL_CALIB_ZERO) == pytest.approx(3.0)        # the DI-onset reading, not the rest 0.8
  assert _saved_factor() == pytest.approx(100.0 / (107.0 - 3.0), rel=1e-6)
  assert params.get_float(params.PreApParamKeys.PEDAL_CALIB_MIN) == pytest.approx(0.8)          # rest mean, Tinkla TeslaPedalCalibMin


def test_twitch_does_not_calibrate():
  cc = _armed_after_coast()
  _feed(cc, [(7.0, 0.012)] + [(0.8, 0.0)] * calib.PRESS_RELEASE_FRAMES)   # the car saw 1.2 % and went back to 0: ignored
  assert not calib.is_pedal_calibrated() and cc._calib_onset is None
  assert params.get_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED) and not params.get_str(params.PreApParamKeys.PEDAL_CALIB_MESSAGE)


def test_press_without_di_gas_is_ignored_and_small_span_fails_with_a_message():
  cc = _armed_after_coast()
  cc._update_detection_and_calib(_cs(60.0, 0.0))   # interceptor moved but the car did not see gas: not a driver press
  assert cc._calib_onset is None
  _feed(cc, [(1.2, 0.004), (6.0, 0.5), (11.4, 0.996)])   # real press, span 10.2 -> factor 9.8
  assert not calib.is_pedal_calibrated()
  assert params.get_str(params.PreApParamKeys.PEDAL_CALIB_MESSAGE).startswith("Pedal scale 9.8")
  assert calib.pedal_status(detected=True) == calib.STATUS_FAILED


def test_nothing_is_saved_while_the_press_is_still_being_measured_and_a_disarm_or_lost_pedal_saves_nothing():
  cc = _armed_after_coast()
  _feed(cc, _press()[:3] * 10)
  assert not calib.is_pedal_calibrated()
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_ARMED, False)             # Cancel / timeout / screen closed
  _feed(cc, _press())
  assert not calib.is_pedal_calibrated() and cc._calib_onset is None
  cc = _armed_after_coast()
  _feed(cc, _press()[:3])
  cc._update_detection_and_calib(SimpleNamespace(preap_pedal_detected=False, preap_pedal_raw=None, out=SimpleNamespace(), di_gas=0.0))
  _feed(cc, _press()[3:])
  assert not calib.is_pedal_calibrated()
