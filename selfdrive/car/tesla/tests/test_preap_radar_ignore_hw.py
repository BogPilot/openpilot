"""Pre-AP radar health: SGUFail ignored; HWFail gated by TeslaRadarIgnoreHwFail.

Matches NAP opendbc/car/tesla/radar_interface.py TestBoschHealth:
  RADC_SGUFail alone -> no fault
  RADC_HWFail -> fault unless ignore param
  RADC_SensorDirty -> no hard fault on Pre-AP (NAP uses temp-unavailable; we lack that enum)

Credit: NotAutopilot. BogPilot product name. No real VINs.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openpilot.selfdrive.car.tesla import radar_interface as ri
from openpilot.selfdrive.car.tesla.preap import params
from openpilot.selfdrive.car.tesla.values import CAR


@pytest.fixture()
def tmp_params(monkeypatch):
  d = Path(tempfile.mkdtemp())
  monkeypatch.setattr(params, "_params_dir", d)
  return d


def _fake_rcp(hw=0, sgu=0, dirty=0):
  rcp = MagicMock()
  rcp.can_valid = True
  rcp.vl = {
    "TeslaRadarSguInfo": {
      "RADC_HWFail": hw,
      "RADC_SGUFail": sgu,
      "RADC_SensorDirty": dirty,
    },
  }
  # unused point tables — update returns before parsing if we short-circuit carefully
  for i in range(32):
    rcp.vl[f"RadarPoint{i}_A"] = {"Index": 0, "Tracked": 0, "LongDist": 0, "LatDist": 0,
                                   "LongSpeed": 0, "LongAccel": 0, "ProbExist": 0, "Meas": 0}
    rcp.vl[f"RadarPoint{i}_B"] = {"Index2": 0, "LatSpeed": 0}
  rcp.update_strings = MagicMock(return_value={878})
  return rcp


def _make_preap_radar(rcp):
  radar = ri.RadarInterface.__new__(ri.RadarInterface)
  radar.CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS)
  radar.rcp = rcp
  radar.updated_messages = set()
  radar.track_id = 0
  radar.pts = {}
  radar.num_points = 32
  radar.trigger_msg = 878
  radar._preap_radar_offset_m = 0.0
  return radar


def test_sgufail_alone_does_not_fault_preap(tmp_params):
  radar = _make_preap_radar(_fake_rcp(hw=0, sgu=1, dirty=0))
  ret = radar.update([])
  assert ret is not None
  assert "fault" not in ret.errors


def test_hwfail_faults_when_ignore_off(tmp_params):
  assert params.get_bool(params.PreApParamKeys.RADAR_IGNORE_HW_FAIL, False) is False
  radar = _make_preap_radar(_fake_rcp(hw=1, sgu=0, dirty=0))
  ret = radar.update([])
  assert "fault" in ret.errors


def test_hwfail_ignored_when_param_on(tmp_params):
  params.set_bool(params.PreApParamKeys.RADAR_IGNORE_HW_FAIL, True)
  radar = _make_preap_radar(_fake_rcp(hw=1, sgu=1, dirty=0))
  ret = radar.update([])
  assert "fault" not in ret.errors


def test_sensor_dirty_does_not_hard_fault_preap(tmp_params):
  radar = _make_preap_radar(_fake_rcp(hw=0, sgu=0, dirty=1))
  ret = radar.update([])
  assert "fault" not in ret.errors


def test_ignore_param_live_each_update(tmp_params):
  radar = _make_preap_radar(_fake_rcp(hw=1, sgu=0, dirty=0))
  assert "fault" in radar.update([]).errors
  params.set_bool(params.PreApParamKeys.RADAR_IGNORE_HW_FAIL, True)
  assert "fault" not in radar.update([]).errors
