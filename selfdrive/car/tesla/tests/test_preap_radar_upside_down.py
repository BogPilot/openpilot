"""Pre-AP radar upside-down mount invert tests."""
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


def _fake_rcp(lat_dist=1.5, lat_speed=0.4):
  rcp = MagicMock()
  rcp.can_valid = True
  rcp.vl = {
    "TeslaRadarSguInfo": {"RADC_HWFail": 0, "RADC_SGUFail": 0, "RADC_SensorDirty": 0},
  }
  for i in range(32):
    tracked = 1 if i == 0 else 0
    rcp.vl[f"RadarPoint{i}_A"] = {
      "Index": 0, "Tracked": tracked, "LongDist": 10.0, "LatDist": lat_dist,
      "LongSpeed": 0.0, "LongAccel": 0.0, "ProbExist": 1, "Meas": 1,
    }
    rcp.vl[f"RadarPoint{i}_B"] = {"Index2": 0, "LatSpeed": lat_speed}
  rcp.update_strings = MagicMock(return_value={878})
  return rcp


def _make(rcp):
  radar = ri.RadarInterface.__new__(ri.RadarInterface)
  radar.CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS)
  radar.rcp = rcp
  radar.updated_messages = set()
  radar.track_id = 0
  radar.pts = {}
  radar.num_points = 32
  radar.trigger_msg = 878
  radar._preap_radar_offset_m = 0.0
  radar._preap_radar_upside_down = False
  return radar


def test_default_no_invert(tmp_params):
  radar = _make(_fake_rcp(1.5, 0.4))
  ret = radar.update([])
  pt = ret.points[0]
  assert pt.yRel == pytest.approx(1.5)
  assert pt.yvRel == pytest.approx(0.4)


def test_upside_down_inverts_lat(tmp_params):
  params.set_bool(params.PreApParamKeys.RADAR_UPSIDE_DOWN, True)
  radar = _make(_fake_rcp(1.5, 0.4))
  ret = radar.update([])
  pt = ret.points[0]
  assert pt.yRel == pytest.approx(-1.5)
  assert pt.yvRel == pytest.approx(-0.4)


def test_upside_down_applies_offset_before_invert(tmp_params):
  params.set_bool(params.PreApParamKeys.RADAR_UPSIDE_DOWN, True)
  radar = _make(_fake_rcp(1.0, 0.2))
  # offset is re-read live; set param
  params.set_float(params.PreApParamKeys.RADAR_OFFSET, 0.5)
  ret = radar.update([])
  pt = ret.points[0]
  # -(1.0 + 0.5) = -1.5
  assert pt.yRel == pytest.approx(-1.5)
  assert pt.yvRel == pytest.approx(-0.2)
