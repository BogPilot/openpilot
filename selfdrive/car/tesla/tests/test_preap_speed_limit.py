"""Pre-AP dashboardSpeedLimit: map/mpp only (no Mobileye fused)."""
from __future__ import annotations

from pathlib import Path

import pytest

from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.car.tesla.speed_limit import dashboard_speed_limit_ms
from openpilot.selfdrive.car.tesla.values import CAR

ROOT = Path(__file__).resolve().parents[4]
MPH = CV.MPH_TO_MS


def test_dashboard_none_fused_and_absent_msgs_are_zero():
  """Missing UI msgs / None fused must not raise — returns 0.0."""
  assert dashboard_speed_limit_ms(None, None, None, None) == 0.0
  assert dashboard_speed_limit_ms(None, 0, None, 0) == 0.0
  # empty-dict .get paths used by carstate when freq-0 msgs never arrived
  ui_map = {}.get("UI_mapSpeedLimit")
  gps = {}
  assert dashboard_speed_limit_ms(
    None, ui_map, gps.get("UI_mppSpeedLimit"), gps.get("UI_mapSpeedLimitUnits"),
  ) == 0.0


def test_dashboard_map_only_without_fused():
  # UI_mapSpeedLimit enum 7 = LEQ_30 mph; units 0 = MPH
  assert dashboard_speed_limit_ms(None, 7, None, 0) == pytest.approx(30 * MPH)


def test_carstate_subscribes_preap_ui_map_freq0():
  src = (ROOT / "selfdrive/car/tesla/carstate.py").read_text()
  assert "TESLA_PREAP_MODELS" in src
  assert "UI_driverAssistMapData" in src
  assert "UI_gpsVehicleSpeed" in src
  # Pre-AP fused path is explicitly None
  assert "fused = None" in src
  assert "CAR.TESLA_PREAP_MODELS" in src


def test_slc_map_data_has_no_carmodel_gate_excluding_preap():
  """FrogPilot SLC offline Map Data is MapSpeedLimit param — no CarModel gate."""
  slc = (ROOT / "frogpilot/controls/lib/speed_limit_controller.py").read_text()
  assert "MapSpeedLimit" in slc
  assert '"Map Data"' in slc
  # No fingerprint / CarModel exclusion around map data
  assert "TESLA_PREAP" not in slc
  assert "CarModel" not in slc
  vcruise = (ROOT / "frogpilot/controls/lib/frogpilot_vcruise.py").read_text()
  # AP1 guard is AP1-only; Pre-AP still gets update_limits with dashboard + maps
  assert 'car_model", "") or "") == "TESLA_AP1_MODELS"' in vcruise or          '== "TESLA_AP1_MODELS"' in vcruise
