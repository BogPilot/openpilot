"""Pre-AP Pedal Emergency Disable and Reset Hardware Settings: the parameter logic (preap/hw_tools.py). Credit: NAP nap-dev
_on_emergency_disable / _on_reset_defaults (MIT). Temp params dir only."""
import pytest

from opendbc.car.tesla_ap1.preap import calib, hw_tools, params
from opendbc.car.tesla_ap1.preap.params import DEFAULTS, PreApParamKeys as K


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path / "params_bogpilot")
  yield tmp_path / "params_bogpilot"


def calibrated():
  calib.apply_calibration_result({"ok": 1.0, "pedal_calib_zero": 12.0, "pedal_calib_factor": 1.5, "pedal_calib_min": -3.0,
                                  "pedal_calib_max": 99.6})
  assert calib.is_pedal_calibrated()


def test_emergency_clears_the_done_flag_and_stops_pedal_long():
  calibrated()
  assert calib.pedal_long_allowed(user_wants_long=True, detected=True)
  hw_tools.clear_pedal_calibration()
  assert not calib.is_pedal_calibrated()
  assert not calib.pedal_long_allowed(user_wants_long=True, detected=True)        # the live stop


def test_emergency_keeps_the_saved_values_like_nap_and_cancels_a_running_calibration():
  calibrated()
  params.set_bool(K.PEDAL_CALIB_ARMED, True)
  params.set_str(K.PEDAL_CALIB_MESSAGE, "x")
  calib.set_stage(calib.STAGE_COAST_OK)
  hw_tools.clear_pedal_calibration()
  assert params.get_float(K.PEDAL_CALIB_ZERO) == 12.0 and params.get_float(K.PEDAL_CALIB_FACTOR) == 1.5
  assert not params.get_bool(K.PEDAL_CALIB_ARMED) and params.get_str(K.PEDAL_CALIB_MESSAGE) == ""
  assert params.get_str(K.PEDAL_CALIB_STAGE) == calib.STAGE_IDLE


def test_emergency_is_idempotent_and_works_with_nothing_saved():
  hw_tools.clear_pedal_calibration()
  hw_tools.clear_pedal_calibration()
  assert not calib.is_pedal_calibrated()


def test_reset_table_is_pedal_radar_offset_and_saved_stalk_detection_only():
  table = hw_tools.hw_reset_defaults()
  assert set(table) == {K.PEDAL_CALIB_DONE, K.PEDAL_CALIB_MIN, K.PEDAL_CALIB_MAX, K.PEDAL_CALIB_FACTOR, K.PEDAL_CALIB_ZERO,
                        K.PEDAL_CAN_BUS, K.RADAR_ENABLED, K.RADAR_BEHIND_NOSECONE, K.RADAR_DONOR_VIN, K.RADAR_DONOR_TYPE,
                        K.RADAR_EPAS_TYPE, K.RADAR_IGNORE_HW_FAIL, K.RADAR_FLIP, K.RADAR_OFFSET,
                        K.STALK_RETROFIT_DETECTED}
  assert next(iter(table)) == K.PEDAL_CALIB_DONE                      # the live stop is written first
  assert all(table[k] == DEFAULTS[k] for k in table)
  assert table[K.RADAR_OFFSET] == 0.0 and table[K.RADAR_DONOR_VIN] == "" and table[K.PEDAL_CAN_BUS] == 2


@pytest.mark.parametrize("key", [K.DOUBLE_PULL, K.AUTO_SPEED, K.HAS_IBOOSTER, K.OVERRIDE_SENSITIVITY, K.PANDA_FIRMWARE,
                                 K.PEDAL_DETECTED, K.PEDAL_SEEN_TS, K.PEDAL_CALIB_ARMED, K.RADAR_READ_VIN, "DisableOpenpilotLongitudinal"])
def test_reset_never_lists_other_settings(key):
  assert key not in hw_tools.HW_RESET_KEYS and key not in hw_tools.hw_reset_defaults()


def test_reset_writes_defaults_and_leaves_everything_else_alone():
  calibrated()
  params.set_int(K.PEDAL_CAN_BUS, 0)
  params.set_bool(K.RADAR_ENABLED, True)
  params.set_bool(K.RADAR_FLIP, True)
  params.set_float(K.RADAR_OFFSET, 0.4)
  params.set_int(K.RADAR_DONOR_TYPE, 2)
  params.set_int(K.RADAR_EPAS_TYPE, 4)
  params.set_str(K.RADAR_DONOR_VIN, "DONORVINTESTVALUE")   # any non-empty stand-in
  params.set_bool(K.RADAR_IGNORE_HW_FAIL, True)
  params.set_bool(K.AUTO_SPEED, True)
  params.set_bool(K.HAS_IBOOSTER, True)
  params.set_bool(K.DOUBLE_PULL, False)
  params.set_int(K.OVERRIDE_SENSITIVITY, 5)
  params.set_bool(K.PEDAL_CALIB_ARMED, True)
  written = hw_tools.reset_hw_settings()
  assert written == list(hw_tools.HW_RESET_KEYS)
  assert not calib.is_pedal_calibrated() and params.get_float(K.PEDAL_CALIB_ZERO) == DEFAULTS[K.PEDAL_CALIB_ZERO]
  assert params.get_float(K.PEDAL_CALIB_FACTOR) == 1.0 and params.get_int(K.PEDAL_CAN_BUS) == 2
  assert not params.get_bool(K.RADAR_ENABLED) and not params.get_bool(K.RADAR_FLIP) and params.radar_offset_m() == 0.0
  assert params.radar_donor_type() == 0 and params.radar_epas_type() == 0 and params.get_str(K.RADAR_DONOR_VIN) == ""
  assert not params.get_bool(K.RADAR_IGNORE_HW_FAIL) and not params.get_bool(K.PEDAL_CALIB_ARMED)
  # untouched
  assert params.get_bool(K.AUTO_SPEED) and params.get_bool(K.HAS_IBOOSTER) and not params.get_bool(K.DOUBLE_PULL)
  assert params.get_int(K.OVERRIDE_SENSITIVITY) == 5


def test_writer_refuses_a_key_outside_the_table():
  for key in (K.AUTO_SPEED, K.DOUBLE_PULL, "SomethingElse"):
    with pytest.raises(KeyError):
      hw_tools.write_default(key, True)
  assert params.get_bool(K.AUTO_SPEED) is False


def test_reset_stops_at_a_failing_writer_and_reports_it():
  seen = []

  def write(key, value):
    seen.append(key)
    if len(seen) == 3:
      raise OSError("disk")
  with pytest.raises(OSError):
    hw_tools.reset_hw_settings(write)
  assert seen == list(hw_tools.HW_RESET_KEYS)[:3]


def test_reset_is_idempotent():
  hw_tools.reset_hw_settings()
  before = {k: params.get_str(k) for k in hw_tools.HW_RESET_KEYS}
  hw_tools.reset_hw_settings()
  assert {k: params.get_str(k) for k in hw_tools.HW_RESET_KEYS} == before
