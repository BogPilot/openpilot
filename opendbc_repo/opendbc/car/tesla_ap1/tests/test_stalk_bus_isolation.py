"""R8 (beta stalk bookmark): 0x45 STW_ACTN_RQ bus isolation for the parser that feeds carState.bogpilot.spdCtrlLvr.

spdCtrlLvr is read from can_parsers[Bus.chassis].vl["STW_ACTN_RQ"]["SpdCtrlLvr_Stat"] (tesla_ap1/carstate.py:171,
preap/carstate.py:166-167). That parser is bound to CANBUS.chassis = 0 and skips any other src (opendbc/can/parser.py
`if src != self.bus`). Our own TX comes back as bus + 0x80 (src 128 / 130). So a FWD frame on bus 2, src 128 or src 130
must never move the value; only src 0 does. Test only; no car code is changed.
"""
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
from opendbc.car.tesla_ap1.values import CAR, DBC

FWD = 1


def _parsers(fp):
  cp = SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=False)
  cls = PreApCarState if fp == CAR.TESLA_PREAP_MODELS else CarState
  return cls.get_can_parsers(cp)


def _stalk(fp, value, src):
  packer = CANPacker(DBC[fp][Bus.chassis])
  addr, dat, _ = packer.make_can_msg("STW_ACTN_RQ", 0, {"SpdCtrlLvr_Stat": value})
  return addr, dat, src


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX, CAR.TESLA_PREAP_MODELS])
@pytest.mark.parametrize("src", [1, 2, 4, 128, 130, 132])
def test_fwd_on_other_src_never_reaches_spdctrllvr(fp, src):
  cp = _parsers(fp)[Bus.chassis]
  assert cp.bus == 0
  t = 1_000_000_000
  cp.update([(t, [_stalk(fp, 0, 0)])])
  for i in range(1, 6):
    cp.update([(t + i * 100_000_000, [_stalk(fp, FWD, src)])])
    assert int(cp.vl["STW_ACTN_RQ"]["SpdCtrlLvr_Stat"]) == 0


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX, CAR.TESLA_PREAP_MODELS])
def test_fwd_on_src0_advances(fp):
  cp = _parsers(fp)[Bus.chassis]
  cp.update([(1_000_000_000, [_stalk(fp, FWD, 0)])])
  assert int(cp.vl["STW_ACTN_RQ"]["SpdCtrlLvr_Stat"]) == FWD


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_PREAP_MODELS])
def test_echo_in_same_packet_as_idle_src0_keeps_idle(fp):
  # src-0 IDLE and our src-128 FWD echo in one packet (the pre-AP shape): the parser keeps IDLE
  cp = _parsers(fp)[Bus.chassis]
  cp.update([(1_000_000_000, [_stalk(fp, 0, 0), _stalk(fp, FWD, 128)])])
  assert int(cp.vl["STW_ACTN_RQ"]["SpdCtrlLvr_Stat"]) == 0
