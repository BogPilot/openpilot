"""AP1 Model X defaults (next build), the parts that import radard / the planner (need msgq: native or AGNOS): phantom
brake Option A (camera-only far lead gate) and the radar lead glitch filter run on the X only while X openpilot long is on,
and Curve Speed Control is built for the X with openpilot long. The Model S rows prove the S is unchanged."""
from pathlib import Path
from types import SimpleNamespace as NS

from openpilot.selfdrive.controls.radard import ap1_lead_filter_platform, vision_only_gate_platform

S, X, PREAP = "TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"


def cp(fp, long):
  return NS(carFingerprint=fp, openpilotLongitudinalControl=long, pcmCruise=not long)


def test_lead_filters_x_only_with_op_long():
  assert ap1_lead_filter_platform(X, True) and vision_only_gate_platform(X, True)
  assert not ap1_lead_filter_platform(X, False) and not vision_only_gate_platform(X, False)
  assert not ap1_lead_filter_platform(X) and not vision_only_gate_platform(X)
  for long in (False, True):                                          # S unchanged: always on, with or without long
    assert ap1_lead_filter_platform(S, long) and vision_only_gate_platform(S, long)
    assert not ap1_lead_filter_platform(PREAP, long) and vision_only_gate_platform(PREAP, long)
    for other in ("TESLA_MODEL_3", "TOYOTA_COROLLA", "", None):
      assert not ap1_lead_filter_platform(other, long) and not vision_only_gate_platform(other, long)


def test_radard_main_wires_both_gates_to_op_long():
  src = (Path(__file__).parents[1] / "radard.py").read_text()
  assert "op_long = bool(CP.openpilotLongitudinalControl)" in src
  assert "ap1_lead_filter=ap1_lead_filter_platform(CP.carFingerprint, op_long)" in src
  assert "vision_only_gate=vision_only_gate_platform(CP.carFingerprint, op_long)" in src


def test_ap1_curve_speed_available_on_x_long():
  from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed
  from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import ToggleStore
  x = Ap1CurveSpeed(cp(X, True), 0.05, ToggleStore(True))
  assert x.available and not x.preap and x.brake is not None and x.csc is not None
  off = Ap1CurveSpeed(cp(X, False), 0.05, ToggleStore(True))
  assert not off.available and off.brake is None and off.csc is None
  s = Ap1CurveSpeed(cp(S, True), 0.05, ToggleStore(True))
  assert s.available and not s.preap and s.brake is not None
