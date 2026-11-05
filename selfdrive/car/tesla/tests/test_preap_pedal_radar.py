"""Pre-AP pedal calib gating + Bosch radar defaults (host suite).

Credit: NotAutopilot nap_conf calib math. BogPilot product name.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openpilot.selfdrive.car.tesla.preap import calib, params, radar_tx, status, menu_copy
from openpilot.selfdrive.car.tesla.preap.accel_to_pedal import accel_to_pedal_command
from openpilot.selfdrive.car.tesla.safety_flags import flags_for_preap
from panda import Panda


@pytest.fixture()
def tmp_params(monkeypatch):
  d = Path(tempfile.mkdtemp())
  monkeypatch.setattr(params, "_params_dir", d)
  return d


def test_calib_compute_and_gate(tmp_params):
  r = calib.compute_calibration(10.0, 60.0)
  assert r["ok"] == 1.0
  assert abs(r["pedal_calib_factor"] - (100.0 / 50.0)) < 1e-9
  assert not calib.is_pedal_calibrated()
  assert calib.pedal_status(detected=False) == calib.STATUS_NOT_DETECTED
  assert calib.pedal_status(detected=True, calibrated=False) == calib.STATUS_NEEDS_CALIBRATION
  assert not calib.pedal_long_allowed(user_wants_long=True, detected=True, calibrated=False)
  assert not calib.pedal_long_allowed(user_wants_long=True, detected=False, calibrated=True)
  assert not calib.pedal_long_allowed(user_wants_long=False, detected=True, calibrated=True)

  assert calib.apply_calibration_result(r)
  assert calib.is_pedal_calibrated()
  assert calib.pedal_status(detected=True) == calib.STATUS_READY
  assert calib.pedal_long_allowed(user_wants_long=True, detected=True, calibrated=True)
  assert status.status_label(calib.STATUS_READY) == "Ready"


def test_calib_reject_zero_span(tmp_params):
  r = calib.compute_calibration(5.0, 5.0)
  assert r["ok"] == 0.0
  assert not calib.apply_calibration_result(r)
  assert not calib.is_pedal_calibrated()


def test_done_flag_alone_not_calibrated(tmp_params):
  params.set_bool(params.PreApParamKeys.PEDAL_CALIB_DONE, True)
  # defaults still zero/1.0 → not calibrated
  assert not calib.is_pedal_calibrated()


def test_accel_command_disabled_and_identity(tmp_params):
  cmd, en = accel_to_pedal_command(0.5, False)
  assert en == 0 and cmd == 0.0
  cmd, en = accel_to_pedal_command(0.0, True)
  assert en == 1
  assert abs(cmd - 15.0) < 1e-6


def test_radar_default_off_and_flags(tmp_params):
  assert params.get_bool(params.PreApParamKeys.RADAR_ENABLED, False) is False
  assert flags_for_preap(enable_pedal=True) == Panda.FLAG_TESLA_PREAP_ENABLE_PEDAL
  assert flags_for_preap(enable_pedal=True, radar=False) == Panda.FLAG_TESLA_PREAP_ENABLE_PEDAL
  with_radar = flags_for_preap(enable_pedal=True, radar=True, radar_behind_nosecone=True)
  assert with_radar & Panda.FLAG_TESLA_PREAP_RADAR_EMULATION
  assert with_radar & Panda.FLAG_TESLA_PREAP_RADAR_BEHIND_NOSECONE


def test_radar_tx_dummy_vin_only_when_enabled():
  assert radar_tx.radar_tx_frames(enabled=False) == []
  frames = radar_tx.radar_tx_frames(enabled=True, bus=1)
  assert len(frames) >= 1
  assert all(len(f) == 4 and isinstance(f[1], int) for f in frames)  # sendcan 4-tuple
  addr, _, dat, bus = frames[0]
  assert addr == radar_tx.ADDR_VIN_VIP
  assert bus == 1
  assert b"DUMMY" in radar_tx.DUMMY_VIN.encode()
  with pytest.raises(ValueError):
    radar_tx.pack_dummy_vin("REALLOOKINGVIN0001")  # no DUMMY/TEST marker — refuse


def test_menu_copy_has_preap_strings():
  assert menu_copy.DISABLE_LONG_TITLE_PREAP == "Disable Pedal Longitudinal"
  assert "Comma Pedal longitudinal" in menu_copy.DISABLE_LONG_DESC_PREAP
  assert "steering only" in menu_copy.DISABLE_LONG_DESC_PREAP
  assert "Not detected" in menu_copy.PEDAL_STATUS_DESC
  assert "Park" in menu_copy.PEDAL_CALIBRATE_DESC
  assert "Bus 2 is the usual install" in menu_copy.PEDAL_CAN_BUS_DESC
  assert "wired there" in menu_copy.PEDAL_CAN_BUS_DESC
  assert "Off by default" in menu_copy.RADAR_ENABLED_DESC
  assert "wake the radar" in menu_copy.RADAR_ENABLED_DESC
  assert "nosecone" in menu_copy.RADAR_NOSECONE_DESC.lower()
  assert "inches" in menu_copy.RADAR_OFFSET_DESC
  assert "meters" in menu_copy.RADAR_OFFSET_DESC


def test_safety_preap_h_radar_whitelist_and_ap1_untouched():
  root = Path(__file__).resolve().parents[4]
  preap = (root / "panda/board/safety/safety_tesla_preap.h").read_text()
  assert "PREAP_FLAG_RADAR_EMULATION" in preap
  assert "0x560" in preap
  assert "TESLA_PREAP_TX_MSGS_WITH_RADAR" in preap
  assert "preap_radar_emulation" in preap
  ap1 = (root / "panda/board/safety/safety_tesla.h").read_text()
  assert "0x551" not in ap1
  assert "TESLA_PREAP" not in ap1


def test_vehicle_settings_preap_copy_and_ap1_unchanged():
  root = Path(__file__).resolve().parents[4]
  vs = (root / "frogpilot/ui/qt/offroad/vehicle_settings.cc").read_text()
  assert "Disable Pedal Longitudinal" in vs
  assert "Comma Pedal longitudinal (Pre-AP)" in vs
  assert "Bus 2 is the usual install" in vs
  assert "wake the radar" in vs
  assert "TeslaPreAPToggles" in vs
  assert "isTeslaPreAP" in vs
  # AP1 panel copy still present unchanged
  assert "Tesla Model S and X with Autopilot 1" in vs
  assert "Dash Cluster Integration" in vs


def test_radar_ignore_hw_fail_default_off(tmp_params):
  # NAP NAPRadarIgnoreHwFail defaults False
  assert params.DEFAULTS[params.PreApParamKeys.RADAR_IGNORE_HW_FAIL] is False
  assert params.get_bool(params.PreApParamKeys.RADAR_IGNORE_HW_FAIL, False) is False
  params.set_bool(params.PreApParamKeys.RADAR_IGNORE_HW_FAIL, True)
  assert params.get_bool(params.PreApParamKeys.RADAR_IGNORE_HW_FAIL, False) is True


def test_menu_copy_ignore_hw_fail_strings():
  assert menu_copy.RADAR_IGNORE_HW_FAIL_TITLE == "Ignore Radar Hardware Errors"
  assert "Off by default" in menu_copy.RADAR_IGNORE_HW_FAIL_DESC
  assert "NAPRadarIgnoreHwFail" in menu_copy.RADAR_IGNORE_HW_FAIL_DESC
  assert "SGUFail" in menu_copy.RADAR_IGNORE_HW_FAIL_DESC
  assert "no reboot" in menu_copy.RADAR_IGNORE_HW_FAIL_DESC.lower()


def test_vehicle_settings_ignore_hw_fail_toggle():
  root = Path(__file__).resolve().parents[4]
  vs = (root / "frogpilot/ui/qt/offroad/vehicle_settings.cc").read_text()
  assert "TeslaRadarIgnoreHwFail" in vs
  assert "Ignore Radar Hardware Errors" in vs
  assert "NAPRadarIgnoreHwFail" in vs
  vh = (root / "frogpilot/ui/qt/offroad/vehicle_settings.h").read_text()
  assert "TeslaRadarIgnoreHwFail" in vh
