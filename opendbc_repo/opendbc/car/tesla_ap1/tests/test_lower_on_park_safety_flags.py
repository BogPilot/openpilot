"""Lower on Park safety bit: 1024 on AP1 Model S / X only when the setting is on at car start; matches tesla_ap1.h."""
import re
from pathlib import Path

import pytest

from opendbc.car.tesla_ap1 import ride_height as rh
from opendbc.car.tesla_ap1.safety_flags import FLAG_TESLA_AP1_RIDE_HEIGHT, flags_for_candidate, flags_for_preap
from opendbc.car.tesla_ap1.values import CAR, TeslaAp1SafetyFlags

HEADER = Path(__file__).resolve().parents[3] / "safety" / "modes" / "tesla_ap1.h"


def test_bit_matches_the_panda_header_and_ride_height_module():
  m = re.search(r"#define TESLA_FLAG_AP1_RIDE_HEIGHT (\d+)U", HEADER.read_text())
  assert m and int(m.group(1)) == 1024
  assert FLAG_TESLA_AP1_RIDE_HEIGHT == int(TeslaAp1SafetyFlags.AP1_RIDE_HEIGHT) == rh.FLAG_TESLA_AP1_RIDE_HEIGHT == 1024
  others = [int(f) for f in TeslaAp1SafetyFlags if f is not TeslaAp1SafetyFlags.AP1_RIDE_HEIGHT]
  assert all(o & 1024 == 0 for o in others) and 512 & 1024 == 0     # AP2 powertrain bit 512 stays separate


def test_panda_allows_it_in_this_tree():
  assert rh.PANDA_TX_SUPPORTED is True
  assert rh.tx_supported(8 | 1024) and not rh.tx_supported(8)


@pytest.mark.parametrize("kw,base", [({}, 9), ({"standstill": True}, 25)])
def test_model_s(kw, base):
  assert flags_for_candidate(CAR.TESLA_AP1_MODELS, **kw) == (base,)
  assert flags_for_candidate(CAR.TESLA_AP1_MODELS, ride_height=True, **kw) == (base | 1024,)


def test_model_x():
  assert flags_for_candidate(CAR.TESLA_AP1_MODELX) == (8,)
  assert flags_for_candidate(CAR.TESLA_AP1_MODELX, ride_height=True) == (8 | 1024,)
  assert flags_for_candidate(CAR.TESLA_AP1_MODELX, x_long=True, ride_height=True) == (9 | 1024,)


def test_never_on_preap_or_other_cars():
  assert flags_for_candidate(CAR.TESLA_PREAP_MODELS, ride_height=True)[0] & 1024 == 0
  assert flags_for_preap(True, True, True) & 1024 == 0


@pytest.fixture
def _files(tmp_path, monkeypatch):
  from opendbc.car.tesla_ap1 import toggles
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "_ap1_standstill_path", tmp_path / "AP1StandstillEngage")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (tmp_path / "Disable1", tmp_path / "Disable2"))
  monkeypatch.setattr(rh, "_enable_path", tmp_path / "LowerOnPark")
  return tmp_path


def _params(fp):
  from opendbc.car.tesla_ap1.interface import CarInterface
  if fp == CAR.TESLA_AP1_MODELS:
    from opendbc.car.tesla_ap1.tests.test_release_interface import params
    return params()
  from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELX
  return CarInterface.get_params(fp, {0: dict(TINKLA_AP1_MODELX), 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}, [], False, False, False)


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_interface_sets_the_bit_only_while_on(fp, _files):
  off = _params(fp)
  assert not off.dashcamOnly
  rh.set_enabled(True)
  on = _params(fp)
  p_off, p_on = int(off.safetyConfigs[-1].safetyParam), int(on.safetyConfigs[-1].safetyParam)
  assert p_off & 1024 == 0 and p_on == p_off | 1024
  rh.set_enabled(False)
  assert int(_params(fp).safetyConfigs[-1].safetyParam) == p_off


def test_interface_never_sets_it_on_preap(_files):
  from opendbc.car.tesla_ap1.interface import CarInterface
  rh.set_enabled(True)
  cp = CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)
  assert all(int(c.safetyParam) & 1024 == 0 for c in cp.safetyConfigs)
