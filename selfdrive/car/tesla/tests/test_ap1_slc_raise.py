"""AP1 low-conflict SLC raise helpers and DI_cruiseSet cruise-set source.

Not a product, no warranty, driver remains responsible, comply with local law.
"""

from collections import defaultdict
from types import SimpleNamespace

import pytest

from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.car.tesla.slc_raise import (
  apply_slc_raise_after_min,
  cluster_display_kph,
  cruise_set_mph,
  is_ap1,
  lift_cruise_ms,
  merge_vcruise_with_slc,
)

MPH = CV.MPH_TO_MS
CRUISING = 5.0


def test_is_ap1_fingerprint():
  from openpilot.selfdrive.car.tesla.values import CAR
  assert is_ap1(CAR.TESLA_AP1_MODELS) is True
  assert is_ap1(CAR.TESLA_AP2_MODELS) is False
  assert is_ap1(None) is False
  assert is_ap1("something_else") is False


def test_lift_cruise_raises_into_faster_zone():
  # 30 zone set 36 mph → enter 45 zone with +6 offset → 51 mph
  out = lift_cruise_ms(36 * MPH, 51 * MPH, 45 * MPH, CRUISING)
  assert out == pytest.approx(51 * MPH)


def test_lift_cruise_does_not_raise_when_desired_lower():
  # Lowering is left to the existing min() merge in frogpilot_vcruise
  out = lift_cruise_ms(51 * MPH, 36 * MPH, 30 * MPH, CRUISING)
  assert out == pytest.approx(51 * MPH)


def test_lift_cruise_no_op_when_target_missing():
  assert lift_cruise_ms(36 * MPH, 51 * MPH, 0.0, CRUISING) == pytest.approx(36 * MPH)
  assert lift_cruise_ms(36 * MPH, 51 * MPH, 3.0, CRUISING) == pytest.approx(36 * MPH)


def test_merge_raise_sticks_when_di_at_or_above_cruising():
  """Regression: DI≈11.5 + limit 25 + offset 5 → 30, not collapse to 11.5.

  Pre-fix lift-before-min undid the raise whenever DI_cruiseSet >= CRUISING_SPEED.
  """
  di = 11.5 * MPH
  slc_target = 25 * MPH
  slc_desired = 30 * MPH  # 25 + 5 offset
  # CSC inactive: csc_target mirrors pre-lift DI seed (same as frogpilot_vcruise)
  out = merge_vcruise_with_slc(di, di, slc_desired, slc_target, CRUISING,
                               csc_controlling_speed=False)
  assert out == pytest.approx(30 * MPH)

  # Same for DI just above CRUISING (~11.18 mph) — the log oscillation case
  di_hi = 11.5 * MPH
  assert merge_vcruise_with_slc(di_hi, di_hi, slc_desired, slc_target, CRUISING) == pytest.approx(30 * MPH)

  # DI below CRUISING also raises (was already OK pre-fix)
  di_lo = 10.0 * MPH
  assert merge_vcruise_with_slc(di_lo, di_lo, slc_desired, slc_target, CRUISING) == pytest.approx(30 * MPH)


def test_merge_still_lowers_when_di_above_slc():
  """DI=60 in a 25+5 zone must still min-cap down to 30."""
  di = 60 * MPH
  slc_target = 25 * MPH
  slc_desired = 30 * MPH
  out = merge_vcruise_with_slc(di, di, slc_desired, slc_target, CRUISING)
  assert out == pytest.approx(30 * MPH)


def test_merge_csc_still_caps_after_raise():
  """Active CSC curve target must still cap below the SLC raise."""
  di = 11.5 * MPH
  slc_target = 25 * MPH
  slc_desired = 30 * MPH
  csc = 20 * MPH
  out = merge_vcruise_with_slc(di, csc, slc_desired, slc_target, CRUISING,
                               csc_controlling_speed=True)
  assert out == pytest.approx(20 * MPH)

  # Inactive CSC must NOT cap with the DI seed
  out_off = apply_slc_raise_after_min(11.5 * MPH, slc_desired, slc_target, CRUISING,
                                      False, di)
  assert out_off == pytest.approx(30 * MPH)


def test_cluster_display_only_lifts():
  cluster_kph = 36 * CV.MPH_TO_KPH
  assert cluster_display_kph(cluster_kph, 51 * MPH) == pytest.approx(51 * CV.MPH_TO_KPH)
  # CSC slowdown must not lower the displayed set
  assert cluster_display_kph(cluster_kph, 30 * MPH) == pytest.approx(cluster_kph)


def test_cruise_set_mph_conversion():
  assert cruise_set_mph(None) is None
  assert cruise_set_mph(0.0) is None
  assert cruise_set_mph(51 * MPH) == pytest.approx(51.0, abs=0.05)


def test_carstate_source_uses_di_cruise_set_not_digital():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[1] / "carstate.py").read_text()
  assert 'cruiseState.speed = cp.vl["DI_state"]["DI_cruiseSet"]' in src
  assert 'cruiseState.speed = cp.vl["DI_state"]["DI_digitalSpeed"]' not in src


# Fixture duplicated lightly from test_ap1_speed_limit so this file is standalone.
@pytest.fixture
def carstate_mod(monkeypatch):
  import importlib
  import sys
  import types
  from openpilot.selfdrive.car.tesla.tests.test_ap1_speed_limit import (
    _Base, _Define, _stub_usb1,
  )
  _stub_usb1(monkeypatch)
  if "smbus2" not in sys.modules:
    smbus2 = types.ModuleType("smbus2")
    smbus2.SMBus = type("SMBus", (), {"__init__": lambda self, *a, **k: None})
    monkeypatch.setitem(sys.modules, "smbus2", smbus2)
  interfaces = types.ModuleType("openpilot.selfdrive.car.interfaces")
  interfaces.CarStateBase = _Base
  parser = types.ModuleType("opendbc.can.parser")

  class FakeParser:
    def __init__(self, dbc, messages, bus):
      self.messages = list(messages)
      self.bus = bus

  parser.CANParser = FakeParser
  define = types.ModuleType("opendbc.can.can_define")
  define.CANDefine = _Define
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.car.interfaces", interfaces)
  monkeypatch.setitem(sys.modules, "opendbc.can.parser", parser)
  monkeypatch.setitem(sys.modules, "opendbc.can.can_define", define)
  sys.modules.pop("openpilot.selfdrive.car.tesla.carstate", None)
  mod = importlib.import_module("openpilot.selfdrive.car.tesla.carstate")
  yield mod
  sys.modules.pop("openpilot.selfdrive.car.tesla.carstate", None)


def test_carstate_cruise_speed_tracks_di_cruise_set(carstate_mod):
  from openpilot.selfdrive.car.tesla.values import CAR
  from openpilot.selfdrive.car.tesla.tests.test_ap1_speed_limit import _ap1_cans, _prep_define

  CP = SimpleNamespace(carFingerprint=CAR.TESLA_AP1_MODELS)
  CS = carstate_mod.CarState(CP, None)
  _prep_define(CS)
  CS.can_define.dv["DI_state"]["DI_cruiseState"] = {2: "ENABLED"}

  cp, cp_cam = _ap1_cans(45.0)
  cp.vl["DI_state"]["DI_cruiseState"] = 2
  cp.vl["DI_state"]["DI_speedUnits"] = 0  # MPH
  cp.vl["DI_state"]["DI_cruiseSet"] = 36.0
  cp.vl["DI_state"]["DI_digitalSpeed"] = 41.0

  ret, _fp = CS.update(cp, cp_cam, None)
  assert ret.cruiseState.speed == pytest.approx(36.0 * MPH)
  assert ret.cruiseState.speed != pytest.approx(41.0 * MPH)

  # KPH units path
  CS.can_define.dv["DI_state"]["DI_speedUnits"] = {1: "KPH"}
  cp.vl["DI_state"]["DI_speedUnits"] = 1
  cp.vl["DI_state"]["DI_cruiseSet"] = 60.0  # kph
  cp.vl["DI_state"]["DI_digitalSpeed"] = 70.0
  ret, _fp = CS.update(cp, cp_cam, None)
  assert ret.cruiseState.speed == pytest.approx(60.0 * CV.KPH_TO_MS)
