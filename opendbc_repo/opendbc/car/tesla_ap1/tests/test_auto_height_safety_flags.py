"""Auto Height Drive safety bit: 2048 on AP1 Model S / X, set with 1024 while Auto Height is on at car start; matches tesla_ap1.h."""
import re
from pathlib import Path

import pytest

from opendbc.car.tesla_ap1 import ride_height as rh
from opendbc.car.tesla_ap1.safety_flags import FLAG_TESLA_AP1_RIDE_HEIGHT_DRIVE, flags_for_candidate, flags_for_preap
from opendbc.car.tesla_ap1.values import CAR, TeslaAp1SafetyFlags

HEADER = Path(__file__).resolve().parents[3] / "safety" / "modes" / "tesla_ap1.h"


def test_bit_matches_the_panda_header_and_ride_height_module():
  m = re.search(r"#define TESLA_FLAG_AP1_RIDE_HEIGHT_DRIVE (\d+)U", HEADER.read_text())
  assert m and int(m.group(1)) == 2048
  assert (FLAG_TESLA_AP1_RIDE_HEIGHT_DRIVE == int(TeslaAp1SafetyFlags.AP1_RIDE_HEIGHT_DRIVE)
          == rh.FLAG_TESLA_AP1_RIDE_HEIGHT_DRIVE == 2048)
  others = [int(f) for f in TeslaAp1SafetyFlags if f is not TeslaAp1SafetyFlags.AP1_RIDE_HEIGHT_DRIVE]
  assert all(o & 2048 == 0 for o in others) and 512 & 2048 == 0
  assert 2048 < (1 << 16)                                             # fits the uint16 safety param


def test_panda_allows_it_in_this_tree():
  assert rh.PANDA_DRIVE_TX_SUPPORTED is True
  assert rh.drive_tx_supported(8 | 2048) and not rh.drive_tx_supported(8 | 1024)


@pytest.mark.parametrize("kw,base", [({}, 9), ({"standstill": True}, 25), ({"ride_height": True}, 9 | 1024)])
def test_model_s(kw, base):
  assert flags_for_candidate(CAR.TESLA_AP1_MODELS, **kw) == (base,)
  assert flags_for_candidate(CAR.TESLA_AP1_MODELS, ride_height_drive=True, **kw) == (base | 2048,)


def test_model_x():
  assert flags_for_candidate(CAR.TESLA_AP1_MODELX) == (8,)
  assert flags_for_candidate(CAR.TESLA_AP1_MODELX, ride_height_drive=True) == (8 | 2048,)
  assert flags_for_candidate(CAR.TESLA_AP1_MODELX, x_long=True, ride_height=True, ride_height_drive=True) == (9 | 1024 | 2048,)


def test_never_on_preap_or_other_cars():
  assert flags_for_candidate(CAR.TESLA_PREAP_MODELS, ride_height_drive=True)[0] & 2048 == 0
  assert flags_for_preap(True, True, True) & 2048 == 0


# Auto Height on also sets the Very Low bit 4096, on the Model X only.
VL = {CAR.TESLA_AP1_MODELS: 0, CAR.TESLA_AP1_MODELX: 4096}

@pytest.fixture
def _files(tmp_path, monkeypatch):
  from opendbc.car.tesla_ap1 import toggles
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "_ap1_standstill_path", tmp_path / "AP1StandstillEngage")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (tmp_path / "Disable1", tmp_path / "Disable2"))
  monkeypatch.setattr(rh, "_enable_path", tmp_path / "AutoHeight")
  monkeypatch.setattr(rh, "_drive_height_path", tmp_path / "AutoHeightDrive")
  return tmp_path


def _params(fp):
  from opendbc.car.tesla_ap1.interface import CarInterface
  if fp == CAR.TESLA_AP1_MODELS:
    from opendbc.car.tesla_ap1.tests.test_release_interface import params
    return params()
  from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELX
  return CarInterface.get_params(fp, {0: dict(TINKLA_AP1_MODELX), 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}, [], False, False, False)


def test_panda_header_allows_levels_1_to_4():
  src = HEADER.read_text()
  assert "bool level_ok = ((msg->data[0] >= 0x41U) && (msg->data[0] <= 0x44U)) ||" in src
  assert "(tesla_ap1_ride_height_very_low && (msg->data[0] == 0x47U));" in src
  assert re.search(r"#define TESLA_FLAG_AP1_RIDE_HEIGHT_VERY_LOW (\d+)U", src).group(1) == "4096"
  assert rh.PANDA_PARK_LEVELS == (1, 2, 3, 4) and rh.park_choices() == rh.CHOICES and rh.drive_choices() == rh.CHOICES
  assert rh.park_choices(model_x=True) == rh.X_CHOICES and rh.drive_choices(model_x=True) == rh.X_CHOICES


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_interface_sets_both_bits_only_while_auto_height_is_on(fp, _files):
  p_off = int(_params(fp).safetyConfigs[-1].safetyParam)
  assert p_off & (1024 | 2048) == 0
  for value in rh.HEIGHTS:                                            # the Drive height never decides the bit
    rh.set_drive_height(value)
    assert int(_params(fp).safetyConfigs[-1].safetyParam) == p_off
  rh.set_enabled(True)
  for value in rh.HEIGHTS:
    rh.set_drive_height(value)
    assert int(_params(fp).safetyConfigs[-1].safetyParam) == p_off | 1024 | VL[fp] | 2048
  rh.set_enabled(False)
  assert int(_params(fp).safetyConfigs[-1].safetyParam) == p_off


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_saved_lower_on_park_gets_drive_only_after_a_drive_height_is_picked(fp, _files):
  p_off = int(_params(fp).safetyConfigs[-1].safetyParam)
  (_files / "LowerOnPark").write_text("1")
  assert int(_params(fp).safetyConfigs[-1].safetyParam) == p_off | 1024 | VL[fp]           # Drive starts at None: unchanged behavior
  rh.set_drive_height("medium")
  assert int(_params(fp).safetyConfigs[-1].safetyParam) == p_off | 1024 | VL[fp] | 2048
  rh.set_drive_height("none")
  assert int(_params(fp).safetyConfigs[-1].safetyParam) == p_off | 1024 | VL[fp]


def test_interface_never_sets_it_on_preap(_files):
  from opendbc.car.tesla_ap1.interface import CarInterface
  rh.set_enabled(True)
  rh.set_drive_height("very_high")
  cp = CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)
  assert all(int(c.safetyParam) & (1024 | 2048) == 0 for c in cp.safetyConfigs)
