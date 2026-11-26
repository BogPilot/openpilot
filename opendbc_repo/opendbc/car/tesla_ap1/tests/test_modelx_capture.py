"""Model X AP1 tests built from a real Model X capture (addresses, lengths and rates only; no VIN)."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus, structs
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.modelx_fingerprint import (
  ap1_sx_ambiguous,
  detect_ap1_candidate,
  fw_says_x,
  match_ap1_modelx,
  s_contradicts_x,
  s_evidence,
  x_evidence,
)
from opendbc.car.tesla_ap1.modelx_fingerprint_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.radar_interface import get_radar_can_parser
from opendbc.car.tesla_ap1.safety_flags import flags_for_candidate
from opendbc.car.tesla_ap1.tests.modelx_capture_data import (
  BUS0_HZ,
  BUS1_RADAR,
  BUS2,
  BUS2_HZ,
  DI_CRUISE_STATE_SEEN,
  MODELX_EPS_FW,
  OBSERVED_AP1_MODELX_BUS0,
  RCM_DRIVER_BUCKLE_SEEN,
  SENT_ON_BUS0,
)
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELS_VARIANTS
from opendbc.car.tesla_ap1.values import CAR, DBC

X = CAR.TESLA_AP1_MODELX
S = CAR.TESLA_AP1_MODELS
Ecu = structs.CarParams.Ecu
SAFETY_HEADER = Path(__file__).parents[3] / "safety" / "modes" / "tesla_ap1.h"


def _fp():
  return {0: dict(OBSERVED_AP1_MODELX_BUS0), 2: dict(BUS2)}


def _eps(version=MODELX_EPS_FW + b"\x00" * 10, address=0x730, ecu=Ecu.eps):
  return structs.CarParams.CarFw(ecu=ecu, address=address, fwVersion=version, bus=0)


def test_real_lengths_differ_from_tinkla_on_seven_frames():
  diff = {a for a, n in OBSERVED_AP1_MODELX_BUS0.items() if TINKLA_AP1_MODELX.get(a) != n}
  assert diff == {0x20B, 0x20D, 0x21A, 0x268, 0x294, 0x310, 0x352}
  # Tinkla's table alone would reject this car: the old rule needed every bus-0 frame to match it.
  assert not all(TINKLA_AP1_MODELX.get(a) == n for a, n in OBSERVED_AP1_MODELX_BUS0.items())


def test_real_model_x_detects_as_x_without_firmware():
  fp = _fp()
  assert x_evidence(fp)
  assert s_evidence(fp) == frozenset()
  assert match_ap1_modelx(fp) is True
  assert detect_ap1_candidate(fp) == X
  assert s_contradicts_x(fp) is False


def test_real_model_x_still_rejects_unknown_extras_and_s_markers():
  extra = _fp()
  extra[0][0x123] = 8
  assert detect_ap1_candidate(extra) is None
  assert ap1_sx_ambiguous(extra) is True
  s_marked = _fp()
  s_marked[0][0x201] = 5
  assert detect_ap1_candidate(s_marked) is None
  # A wrong length on a frame that is in the observed table is not accepted either.
  wrong_len = _fp()
  wrong_len[0][0x20B] = 7
  assert TINKLA_AP1_MODELX[0x20B] == 7
  assert detect_ap1_candidate(wrong_len) == X  # Tinkla's own length for that frame stays valid
  wrong_len[0][0x20B] = 4
  assert detect_ap1_candidate(wrong_len) is None


def test_eps_firmware_marker():
  assert fw_says_x([_eps()]) is True
  assert fw_says_x([_eps(MODELX_EPS_FW)]) is True
  assert fw_says_x([_eps(b"1016704-00-HAA" + b"\x00" * 10)]) is False
  assert fw_says_x([_eps(address=0x731)]) is False
  assert fw_says_x([_eps(ecu=Ecu.abs)]) is False
  for bad in (None, [], [None], "foo", 3, [object()]):
    assert fw_says_x(bad) is False


def test_firmware_keeps_a_partial_capture_from_becoming_model_s():
  # Chassis and Mobileye signature only: no X marker frame seen yet.
  partial = {0: {0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8}, 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}
  assert x_evidence(partial) == frozenset()
  assert detect_ap1_candidate(partial) == S
  assert detect_ap1_candidate(partial, [_eps(b"1016704-00-HAA")]) == S
  assert detect_ap1_candidate(partial, [_eps()]) == X


def test_firmware_never_overrides_model_s_evidence():
  conflict = {0: {0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8, 0x201: 5}, 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}
  assert detect_ap1_candidate(conflict) == S
  assert detect_ap1_candidate(conflict, [_eps()]) is None
  assert ap1_sx_ambiguous(conflict, [_eps()]) is True
  # Chassis signature is still required with the firmware.
  assert detect_ap1_candidate({0: {0x2F1: 8}}, [_eps()]) is None
  assert detect_ap1_candidate({}, [_eps()]) is None


def test_model_s_captures_do_not_move():
  for variant in TINKLA_AP1_MODELS_VARIANTS:
    fp = {0: dict(variant), 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}
    assert detect_ap1_candidate(fp) == S
    assert detect_ap1_candidate(fp, []) == S


@pytest.fixture
def x_long(tmp_path, monkeypatch):
  """Disable openpilot Longitudinal Control in a temp file (default off, so openpilot long is on; write "1" for stock TACC)."""
  from opendbc.car.tesla_ap1 import toggles
  path = tmp_path / "DisableOpenpilotLongitudinal"
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (path, tmp_path / "Disable2"))
  return path


def test_params_from_real_capture_default_to_openpilot_long(x_long):
  cp = CarInterface.get_params(X, _fp(), [_eps()], False, False, False)
  assert cp.openpilotLongitudinalControl is True and cp.safetyConfigs[0].safetyParam & (8 | 1) == 8 | 1   # AP1 + LONG_CONTROL
  assert cp.safetyConfigs[0].safetyParam in (8 | 1, 8 | 1 | 16)   # + standstill (16) unless AP1StandstillEngage is off
  assert cp.dashcamOnly is False


def test_params_from_real_capture_are_lateral_only(x_long):
  x_long.write_text("1")                                  # Disable on: stock TACC, steering only
  cp = CarInterface.get_params(X, _fp(), [_eps()], False, False, False)
  assert cp.brand == "tesla_ap1"
  assert cp.dashcamOnly is False
  assert cp.steerControlType == structs.CarParams.SteerControlType.angle
  assert str(cp.safetyConfigs[0].safetyModel) == "tesla"
  assert cp.safetyConfigs[0].safetyParam == 8
  assert cp.openpilotLongitudinalControl is False
  assert flags_for_candidate(X, _fp()) == (8,)


# 0x208 GTW_ESP1 is 4 bytes on the X (8 in the DBC). Only GTW_ambientTemperature (byte 1) is read.
SHORT_LIVE_FRAMES_OK = {0x208: 4}


def _parser_messages(parser):
  return {addr: state for addr, state in parser.message_states.items()}


def test_carstate_messages_exist_at_the_live_length_and_rate():
  cp = SimpleNamespace(carFingerprint=X)
  parsers = CarState.get_can_parsers(cp)
  for bus, live, hz in ((Bus.chassis, OBSERVED_AP1_MODELX_BUS0, BUS0_HZ), (Bus.cam, BUS2, BUS2_HZ)):
    for addr, state in _parser_messages(parsers[bus]).items():
      assert addr in live, (state.name, hex(addr))
      if addr in SHORT_LIVE_FRAMES_OK:
        # The X sends this frame shorter than the DBC; every signal we read must sit inside the live bytes.
        assert live[addr] == SHORT_LIVE_FRAMES_OK[addr] < state.size, (state.name, hex(addr), live[addr], state.size)
        assert all(max(sig.start_bit, sig.msb) // 8 < live[addr] for sig in state.signals), (state.name, hex(addr))
        continue
      assert live[addr] == state.size, (state.name, hex(addr), live[addr], state.size)
      if state.frequency > 0 and addr in hz:
        assert hz[addr] >= min(state.frequency, 25), (state.name, hex(addr), hz[addr], state.frequency)


def test_model_x_has_no_sdm1_frame_and_reads_rcm():
  assert 0x201 not in OBSERVED_AP1_MODELX_BUS0
  assert OBSERVED_AP1_MODELX_BUS0[0x211] == 8


def _carstate():
  cp = SimpleNamespace(carFingerprint=X)
  return CarState(cp), CarState.get_can_parsers(cp)


def _send(parser, name, values):
  packer = CANPacker("tesla_ap1_can")
  addr, dat, _bus = packer.make_can_msg(name, parser.bus, values)
  parser.update([(0, [(addr, dat, parser.bus)])])


def test_seatbelt_values_seen_on_the_real_car():
  assert RCM_DRIVER_BUCKLE_SEEN == (1, 3)
  state, parsers = _carstate()
  chassis = parsers[Bus.chassis]
  _send(chassis, "RCM_status", {"RCM_buckleDriverStatus": 1})
  assert state.update(parsers).seatbeltUnlatched is False
  # 3 is the "signal not available" value the car shows early in a drive. It fails closed, as in stock openpilot.
  _send(chassis, "RCM_status", {"RCM_buckleDriverStatus": 3})
  assert state.update(parsers).seatbeltUnlatched is True


def test_stock_cruise_states_seen_on_the_real_car_do_not_engage():
  assert DI_CRUISE_STATE_SEEN == (0, 1)
  state, parsers = _carstate()
  chassis = parsers[Bus.chassis]
  names = state.can_define.dv["DI_state"]["DI_cruiseState"]
  assert [names[v] for v in DI_CRUISE_STATE_SEEN] == ["OFF", "STANDBY"]
  for value, available in ((0, False), (1, True)):
    _send(chassis, "DI_state", {"DI_cruiseState": value, "DI_speedUnits": 1})
    out = state.update(parsers)
    assert out.cruiseState.enabled is False
    assert out.cruiseState.available is available


def _header_table(pattern):
  return [tuple(int(g, 0) for g in m.groups()) for m in re.finditer(pattern, SAFETY_HEADER.read_text())]


def test_panda_ap1_rx_checks_match_the_real_car():
  rx = _header_table(r"\{\.msg = \{\{(0x[0-9a-f]+), (\d), (\d+), (\d+)U")
  assert len(rx) == 7
  live = {0: (OBSERVED_AP1_MODELX_BUS0, BUS0_HZ), 2: (BUS2, BUS2_HZ)}
  for addr, bus, length, hz in rx:
    frames, rates = live[bus]
    assert frames.get(addr) == length, hex(addr)
    assert rates[addr] >= hz, (hex(addr), rates[addr], hz)


def test_panda_ap1_tx_lengths_match_what_the_real_car_carries():
  tx = {addr: (bus, length) for addr, bus, length in _header_table(r"\{(0x[0-9a-f]+), (\d), (\d+), \.check_relay")}
  for addr, (length, _hz) in SENT_ON_BUS0.items():
    assert tx[addr] == (0, length)
  for addr in (0x45, 0x488, 0x2B9):
    assert OBSERVED_AP1_MODELX_BUS0[addr] == tx.get(addr, (0, OBSERVED_AP1_MODELX_BUS0[addr]))[1]


def test_radar_bus_matches_the_bosch_radar_parser():
  cp = SimpleNamespace(carFingerprint=X, radarUnavailable=False)
  parser = get_radar_can_parser(cp)
  assert parser is not None
  short = []
  for addr, state in parser.message_states.items():
    assert addr in BUS1_RADAR, (state.name, hex(addr))
    if BUS1_RADAR[addr] != state.size:
      short.append((state.name, BUS1_RADAR[addr], state.size))
  # The radar status frame is 6 bytes on this car and 8 in the DBC; every signal in it fits in 6 bytes.
  assert short == [("TeslaRadarSguInfo", 6, 8)]
  packer = CANPacker(DBC[X][Bus.radar])
  addr, dat, _ = packer.make_can_msg("TeslaRadarSguInfo", 1, {"RADC_HWFail": 1})
  parser.update([(1_000_000_000, [(addr, dat[:6], 1)])])
  assert parser.vl["TeslaRadarSguInfo"]["RADC_HWFail"] == 1


def _get_car(monkeypatch, fingerprints, car_fw):
  from opendbc.car import car_helpers
  monkeypatch.setattr(car_helpers, "fingerprint", lambda *a, **k: (None, fingerprints, "0" * 17, car_fw, structs.CarParams.FingerprintSource.can, True))
  return car_helpers.get_car(lambda: [], lambda msgs: None, lambda x: None, False, False)


def test_get_car_selects_model_x_from_the_real_capture(monkeypatch, x_long):
  x_long.write_text("1")
  car = _get_car(monkeypatch, _fp(), [_eps()])
  assert car.CP.carFingerprint == X
  assert car.CP.openpilotLongitudinalControl is False
  assert car.CP.dashcamOnly is False


def test_get_car_uses_firmware_when_markers_are_missing(monkeypatch):
  partial = {0: {0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8}, 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}
  assert _get_car(monkeypatch, partial, []).CP.carFingerprint == S
  assert _get_car(monkeypatch, partial, [_eps()]).CP.carFingerprint == X
