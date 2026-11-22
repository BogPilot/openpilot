"""Model X detection on the fingerprint window of a real Model X drive (addresses and lengths only)."""
import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.modelx_fingerprint import (
  S_ONLY,
  ap1_sx_ambiguous,
  detect_ap1_candidate,
  match_ap1_modelx,
  s_contradicts_x,
  x_evidence,
)
from opendbc.car.tesla_ap1.modelx_fingerprint_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.modelx_observed_data import MODELX_EPS_FW, OBSERVED_AP1_MODELX_BUS0
from opendbc.car.tesla_ap1.tests.modelx_drive_fp_data import BUS0, BUS1, BUS2, RARE_BUS0
from opendbc.car.tesla_ap1.values import CAR

Ecu = structs.CarParams.Ecu


def _fp(extra_bus0=None):
  bus0 = dict(BUS0)
  bus0.update(extra_bus0 or {})
  return {0: bus0, 1: dict(BUS1), 2: dict(BUS2)}


def _eps_fw():
  fw = MODELX_EPS_FW + b"\x00" * 7
  return [structs.CarParams.CarFw(ecu=Ecu.eps, fwVersion=fw, address=0x730, subAddress=0, bus=0)]


@pytest.mark.parametrize("car_fw", [None, [], "eps"])
def test_drive_window_detects_model_x(car_fw):
  fw = _eps_fw() if car_fw == "eps" else car_fw
  fp = _fp()
  assert x_evidence(fp)
  assert match_ap1_modelx(fp, fw)
  assert not ap1_sx_ambiguous(fp, fw)
  assert detect_ap1_candidate(fp, fw) == CAR.TESLA_AP1_MODELX
  assert not s_contradicts_x(fp)


@pytest.mark.parametrize("addr", sorted(RARE_BUS0))
def test_rare_real_x_frame_in_window_still_detects(addr):
  fp = _fp({addr: RARE_BUS0[addr]})
  assert detect_ap1_candidate(fp, _eps_fw()) == CAR.TESLA_AP1_MODELX
  assert detect_ap1_candidate(fp, None) == CAR.TESLA_AP1_MODELX


def test_all_rare_frames_together_still_detect():
  assert detect_ap1_candidate(_fp(RARE_BUS0), None) == CAR.TESLA_AP1_MODELX


def test_rare_frames_are_known_model_x_lengths():
  # Tinkla's Model X dict already carries these four at 8 bytes, so no table change is needed for them.
  for addr, length in RARE_BUS0.items():
    assert TINKLA_AP1_MODELX.get(addr) == length or OBSERVED_AP1_MODELX_BUS0.get(addr) == length, hex(addr)


def test_window_bus0_is_covered_by_observed_table():
  # The earlier real-X capture alone covers this drive's whole window (Tinkla's dict alone does not:
  # 0x20B, 0x20D and 0x294 have other lengths there, and 0x21A, 0x268, 0x310, 0x352 are missing).
  for addr, length in BUS0.items():
    if addr < 0x800:
      assert OBSERVED_AP1_MODELX_BUS0.get(addr) == length, hex(addr)


def test_tinkla_dict_alone_would_not_match_this_car():
  mismatched = {a for a, l in BUS0.items() if a < 0x800 and TINKLA_AP1_MODELX.get(a) != l}
  assert mismatched == {0x20B, 0x20D, 0x294, 0x21A, 0x268, 0x310, 0x352}


@pytest.mark.parametrize("addr", sorted(S_ONLY))
def test_model_s_marker_still_blocks_detection(addr):
  fp = _fp({addr: S_ONLY[addr]})
  assert detect_ap1_candidate(fp, _eps_fw()) is None
  assert s_contradicts_x(fp)


def test_unknown_bus0_frame_still_blocks_detection():
  assert detect_ap1_candidate(_fp({0x7FE: 8}), None) is None


def test_wrong_length_still_blocks_detection():
  assert detect_ap1_candidate(_fp({0x2F8: 2}), None) is None


def test_drive_window_params_lateral_only_not_dashcam(tmp_path, monkeypatch):
  # X long defaults on for a detected AP1 Model X; this checks the user's Off (stock TACC, steering only)
  from opendbc.car.tesla_ap1 import toggles
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  (tmp_path / "AP1XOpenpilotLong").write_text("0")
  cp = CarInterface.get_params(CAR.TESLA_AP1_MODELX, _fp(), _eps_fw(), False, False, False)
  assert cp.dashcamOnly is False
  assert cp.openpilotLongitudinalControl is False
  assert cp.safetyConfigs[0].safetyParam == 8
