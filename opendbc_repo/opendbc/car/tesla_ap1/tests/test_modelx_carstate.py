"""Model X seatbelt is RCM_status. Model S still reads SDM1."""
from types import SimpleNamespace

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.values import CAR

SDM1 = 513
RCM = 529


def _carstate(fingerprint):
  cp = SimpleNamespace(carFingerprint=fingerprint)
  state = CarState(cp)
  parsers = CarState.get_can_parsers(cp)
  return state, parsers


def _send(parser, name, values):
  packer = CANPacker("tesla_ap1_can")
  addr, dat, _bus = packer.make_can_msg(name, parser.bus, values)
  parser.update([(0, [(addr, dat, parser.bus)])])


def test_model_x_seatbelt_from_rcm_and_not_sdm1():
  state, parsers = _carstate(CAR.TESLA_AP1_MODELX)
  chassis = parsers[Bus.chassis]
  assert RCM in chassis.message_states
  assert SDM1 not in chassis.message_states
  assert "DAS_steeringControl" in parsers[Bus.cam].vl
  assert "AutopilotStatus" not in parsers[Bus.cam].vl

  _send(chassis, "RCM_status", {"RCM_buckleDriverStatus": 1})
  assert state.update(parsers).seatbeltUnlatched is False
  _send(chassis, "RCM_status", {"RCM_buckleDriverStatus": 0})
  assert state.update(parsers).seatbeltUnlatched is True


def test_model_s_seatbelt_still_from_sdm1():
  state, parsers = _carstate(CAR.TESLA_AP1_MODELS)
  chassis = parsers[Bus.chassis]
  assert SDM1 in chassis.message_states
  assert RCM not in chassis.message_states
  assert "AutopilotStatus" in parsers[Bus.cam].vl

  _send(chassis, "SDM1", {"SDM_bcklDrivStatus": 1})
  assert state.update(parsers).seatbeltUnlatched is False
  _send(chassis, "SDM1", {"SDM_bcklDrivStatus": 0})
  assert state.update(parsers).seatbeltUnlatched is True
