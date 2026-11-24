"""CSC platform and Pre-AP gate (csc_platform.py): AP1, or Pre-AP with openpilot long and a calibrated, live pedal,
controlling only in FULL. Pure logic, no planner or native libraries."""
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from openpilot.selfdrive.controls.lib import csc_platform as P
from openpilot.selfdrive.controls.lib.curve_speed_planner import CurveSpeedPlanner, curve_speed_planner_for

FULL, LAT_ONLY, LAT_PENDING, LOCKOUT, OFF = 4, 3, 2, 1, 0


def cp(fp, long=True, pcm=None):
  return SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=long, pcmCruise=(not long) if pcm is None else pcm)


def cs(mode=FULL, detected=True, calibrated=True, unavailable=False, not_responding=False):
  c = structs.CarState.new_message()
  c.bogpilot.preapFsmMode = mode
  c.bogpilot.preapPedalDetected = detected
  c.bogpilot.preapPedalCalibrated = calibrated
  c.bogpilot.preapPedalUnavailable = unavailable
  c.bogpilot.preapPedalNotResponding = not_responding
  return c


def test_available_ap1_op_long_only():
  assert P.csc_supported(cp("TESLA_AP1_MODELS"))
  assert not P.csc_supported(cp("TESLA_AP1_MODELS", long=False))


def test_available_preap_pedal_op_long():
  assert P.csc_supported(cp("TESLA_PREAP_MODELS"), pedal_ok=True)


def test_unavailable_preap_no_pedal(monkeypatch):
  assert not P.csc_supported(cp("TESLA_PREAP_MODELS"), pedal_ok=False)
  monkeypatch.setattr(P, "stored_pedal_ok", lambda: False)      # stored: not detected or not calibrated
  assert not P.csc_supported(cp("TESLA_PREAP_MODELS"))
  monkeypatch.setattr(P, "stored_pedal_ok", lambda: True)
  assert P.csc_supported(cp("TESLA_PREAP_MODELS"))


def test_stored_pedal_read_failure_is_no_pedal(monkeypatch):
  import opendbc.car.tesla_ap1.preap.calib as calib
  def boom(**_):
    raise OSError("params unreadable")
  monkeypatch.setattr(calib, "pedal_long_allowed", boom)
  assert P.stored_pedal_ok() is False


def test_unavailable_preap_long_off():
  assert not P.csc_supported(cp("TESLA_PREAP_MODELS", long=False), pedal_ok=True)
  assert not P.csc_supported(cp("TESLA_PREAP_MODELS", long=True, pcm=True), pedal_ok=True)   # stock cruise owns speed
  assert not P.csc_supported(SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True), pedal_ok=True)


def test_available_ap1_model_x_op_long_only():
  assert P.csc_supported(cp("TESLA_AP1_MODELX"))
  assert not P.csc_supported(cp("TESLA_AP1_MODELX", long=False))      # stock cruise: never
  assert P.csc_row_visible(cp("TESLA_AP1_MODELX")) and not P.csc_row_visible(cp("TESLA_AP1_MODELX", long=False))
  assert isinstance(curve_speed_planner_for(cp("TESLA_AP1_MODELX")), CurveSpeedPlanner)
  assert curve_speed_planner_for(cp("TESLA_AP1_MODELX", long=False)) is None
  assert P.csc_gate(P.is_preap(cp("TESLA_AP1_MODELX")), SimpleNamespace()) == (True, True)   # AP1 gate, no Pre-AP pedal rules


@pytest.mark.parametrize("fp", ["TESLA_MODEL_3", "HONDA_CIVIC", ""])
def test_unavailable_other_cars(fp):
  assert not P.csc_supported(cp(fp), pedal_ok=True)
  assert not P.csc_supported(None, pedal_ok=True)


def test_gate_ap1_ignores_preap_fields():
  assert P.csc_gate(False, cs(mode=OFF, detected=False, calibrated=False)) == (True, True)
  assert P.csc_gate(False, SimpleNamespace()) == (True, True)


def test_gate_preap_no_pedal_or_uncalibrated_is_inactive():
  assert P.csc_gate(True, cs(detected=False)) == (False, False)
  assert P.csc_gate(True, cs(calibrated=False)) == (False, False)
  assert P.csc_gate(True, cs(unavailable=True)) == (False, False)
  assert P.csc_gate(True, cs(not_responding=True)) == (False, False)
  assert P.csc_gate(True, SimpleNamespace()) == (False, False)          # missing fields fail closed


@pytest.mark.parametrize("mode", [OFF, LOCKOUT, LAT_PENDING, LAT_ONLY])
def test_gate_preap_steering_only_never_controls(mode):
  assert P.csc_gate(True, cs(mode=mode)) == (True, False)


def test_gate_preap_full_controls():
  assert P.csc_gate(True, cs(mode=FULL)) == (True, True)
  assert P.preap_full(SimpleNamespace(bogpilot=SimpleNamespace(preapFsmMode="x"))) is False


def test_curve_brake_factory_preap_pedal():
  assert isinstance(curve_speed_planner_for(cp("TESLA_PREAP_MODELS"), pedal_ok=True), CurveSpeedPlanner)
  assert curve_speed_planner_for(cp("TESLA_PREAP_MODELS"), pedal_ok=False) is None
  assert curve_speed_planner_for(cp("TESLA_PREAP_MODELS", long=False), pedal_ok=True) is None
  assert isinstance(curve_speed_planner_for(cp("TESLA_AP1_MODELS")), CurveSpeedPlanner)


def test_csc_toggle_row_preap_pedal_only(monkeypatch):
  assert P.csc_row_visible(cp("TESLA_AP1_MODELS"))
  assert not P.csc_row_visible(cp("TESLA_AP1_MODELS", long=False))
  assert P.csc_row_visible(cp("TESLA_PREAP_MODELS"), pedal_ok=True)
  assert not P.csc_row_visible(cp("TESLA_PREAP_MODELS"), pedal_ok=False)
  monkeypatch.setattr(P, "stored_pedal_ok", lambda: False)        # offroad, not calibrated yet: hidden
  assert not P.csc_row_visible(cp("TESLA_PREAP_MODELS"))
  assert not P.csc_row_visible(cp("TESLA_PREAP_MODELS", long=False), pedal_ok=True)
  assert not P.csc_row_visible(None)


def test_toggle_reused_default_on_at_level_1():
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  assert BOGPILOT_PARAMS["CurveSpeedController"][2:4] == ("1", 1)
  assert BOGPILOT_PARAMS["ShowCSCStatus"][2:4] == ("1", 2)
