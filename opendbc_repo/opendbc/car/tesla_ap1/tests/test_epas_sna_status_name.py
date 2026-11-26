"""EPAS status 4 is named "SNA" in the DBC (VAL_ 880 EPAS_eacStatus), not "EAC_SNA".

The refusal gate used to list "EAC_SNA", so an EPAS reporting SNA with error IDLE did not block. These tests decode a real
0x370 frame through both car states, so a rename in the DBC or in the gate tuple fails here.
"""
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.can import CANDefine
from opendbc.car.tesla_ap1.actuator_plan import build_actuator_plan
from opendbc.car.tesla_ap1.epas_gate import EAC_BLOCKING_STATUS, EpasGate, epas_not_ready
from opendbc.car.tesla_ap1.tests.test_ap1_epas_yield import _plan
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401  (autouse fixture)

DBC = "tesla_ap1_can"
IDLE = "EAC_ERROR_IDLE"


def _status_names():
  return dict(CANDefine(DBC).dv["EPAS_sysStatus"]["EPAS_eacStatus"])


def test_dbc_names_status_4_sna_and_the_gate_tuple_uses_dbc_names():
  names = _status_names()
  assert names[4] == "SNA"
  assert "EAC_SNA" not in EAC_BLOCKING_STATUS and "SNA" in EAC_BLOCKING_STATUS
  assert set(EAC_BLOCKING_STATUS) <= set(names.values()), "every gate status name must exist in the DBC"
  assert {names[0], names[3], names[4]} == set(EAC_BLOCKING_STATUS)


def test_sna_status_with_error_idle_is_not_ready_and_blocks_first_frame():
  assert epas_not_ready("SNA", IDLE)
  for arm in (False, True):
    g = EpasGate(arm_on_active=arm)
    if arm:
      assert g.update(True, "EAC_ACTIVE", IDLE) is False
    assert g.update(True, "SNA", IDLE) is True, "SNA with a clean error code must block (was passing before the fix)"


@pytest.mark.parametrize("err", ["EAC_ERROR_HANDS_ON", "EAC_ERROR_HIGH_ANGLE_REQ"])
def test_sna_status_blocks_even_with_the_two_latched_ok_errors(err):
  assert epas_not_ready("SNA", err)


def test_the_old_fake_name_never_matches_a_decoded_status():
  assert "EAC_SNA" not in _status_names().values()


def test_planner_blocks_ap1_when_decoded_status_is_sna():
  sna = _status_names()[4]
  for lat in (True, False):
    p = _plan(eac_status=sna, epas_error=IDLE, lat_active=lat)
    assert not p.steer.enabled and p.steer.control_type == 0 and p.steer.angle_deg == 5.0


def _frames(status, n=20):
  packer = CANPacker(DBC)
  for i in range(n):
    yield packer.make_can_msg("EPAS_sysStatus", 0, {"EPAS_eacStatus": status, "EPAS_eacErrorCode": 0, "EPAS_sysStatusCounter": i % 16})


def _drive(st, parsers, status):
  chassis = parsers[Bus.chassis]
  ret = None
  for i, (a, d, b) in enumerate(_frames(status)):
    chassis.update([((i + 1) * 10_000_000, [(a, d, chassis.bus)])])
    ret = st.update(parsers)
  return ret


def test_ap1_carstate_decodes_sna_and_the_controller_gate_blocks_it():
  from opendbc.car.tesla_ap1.carstate import CarState
  from opendbc.car.tesla_ap1.values import CAR
  cp = SimpleNamespace(carFingerprint=CAR.TESLA_AP1_MODELS)
  st = CarState(cp)
  _drive(st, CarState.get_can_parsers(cp), 4)
  assert st.eac_status == "SNA"
  g = EpasGate()
  assert g.update(True, st.eac_status, st.steer_warning, bool(st.eac_fault)) is True
  assert st.steer_warning == IDLE, "the frame carries error IDLE, so only the status can block"


def test_preap_carstate_decodes_sna_and_the_armed_gate_blocks_it(monkeypatch, tmp_path):
  from opendbc.car.tesla_ap1.preap import params
  from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
  from opendbc.car.tesla_ap1.values import CAR
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  cp = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
  st = PreApCarState(cp)
  parsers = PreApCarState.get_can_parsers(cp)
  _drive(st, parsers, 4)
  assert st.eac_status == "SNA"
  g = EpasGate(arm_on_active=True)   # Pre-AP builds the gate armed-on-active
  assert g.update(True, "EAC_ACTIVE", IDLE) is False
  assert g.update(True, st.eac_status, st.steer_warning, bool(st.eac_fault)) is True


def test_controllers_treat_sna_as_blocked():
  from opendbc.car.tesla_ap1.carcontroller import EAC_BLOCKING_STATUS as cc_tuple
  from opendbc.car.tesla_ap1.actuator_plan import EAC_BLOCKING_STATUS as plan_tuple
  assert cc_tuple is EAC_BLOCKING_STATUS and plan_tuple is EAC_BLOCKING_STATUS and "SNA" in cc_tuple
