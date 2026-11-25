"""AP1 Model X with openpilot longitudinal gets the Model S planner and stalk behaviour: throttle cut filter, set-speed
reaction shaping, stalk follow distance, personality sync, Stalk Controls and Human-Like Lane Changes on by default.
A Model X with openpilot longitudinal off keeps none of them. Standstill and steer delay are not part of this."""
from types import SimpleNamespace

import pytest

from opendbc.car.tesla_ap1 import phase3_stalk_controls as SC
from opendbc.car.tesla_ap1.throttle_gate import Ap1ThrottleCap, ap1_throttle_gate_for
from openpilot.selfdrive.controls.lib import phase3_lanechange as L
from openpilot.selfdrive.controls.lib.ap1_planning import Ap1Planning

S, X, P = "TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"


def cp(fp, long=True, radar=True):
  return SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=long, dashcamOnly=False, passive=False,
                         radarUnavailable=not radar, brand="tesla_ap1")


@pytest.mark.parametrize("fp,long,want", [(S, True, True), (S, False, True), (X, True, True), (X, False, False),
                                          (P, True, False), ("TESLA_MODEL_3", True, False)])
def test_throttle_gate(fp, long, want):
  gate = ap1_throttle_gate_for(fp, long)
  assert isinstance(gate, Ap1ThrottleCap) if want else gate is None


def test_throttle_gate_old_call_shape_unchanged():
  assert isinstance(ap1_throttle_gate_for(S), Ap1ThrottleCap)
  assert ap1_throttle_gate_for(X) is None


@pytest.mark.parametrize("fp,long,active,follow", [(S, True, True, True), (X, True, True, True), (X, False, False, False),
                                                   (P, True, False, True), (S, False, False, False)])
def test_planning_flags(fp, long, active, follow):
  plan = Ap1Planning(cp(fp, long), 0.05)
  assert bool(plan.active) is active
  assert bool(plan.stalk_follow_active) is follow


@pytest.mark.parametrize("fp,long,want", [(S, True, True), (S, False, True), (X, True, True), (X, False, False),
                                          (P, True, False), (None, True, False)])
def test_stalk_controls_supported(fp, long, want):
  assert SC.supported(None if fp is None else cp(fp, long)) is want
  assert SC.experimental_supported(None if fp is None else cp(fp, long)) is (want and long)


def test_stalk_controls_dashcam_x_unsupported():
  c = cp(X, True)
  c.dashcamOnly = True
  assert SC.supported(c) is False


@pytest.mark.parametrize("fp,long,want", [(S, True, True), (X, True, True), (X, False, True), (P, True, False)])
def test_human_lane_changes_default_rule(fp, long, want):
  assert L.human_lane_changes_default_on(cp(fp, long, radar=fp != P)) is want


def test_carstate_uses_shared_stalk_follow_rule():
  from opendbc.car.tesla_ap1 import carstate
  src = open(carstate.__file__).read()
  assert "stalk_follow_s = follow_seconds(self.stalk_follow) if stalk_follow_on else 0.0" in src
  assert "fp_ret.ap1StalkFollowS = float(stalk_follow_s) if stalk_follow_on else 0.0" in src
  assert "stalk_follow_on = stalk_follow_car(self.CP)" in src


def test_card_personality_sync_includes_x_with_long():
  from openpilot.selfdrive.car import card
  src = open(card.__file__).read()
  assert '(self.CP.carFingerprint == "TESLA_AP1_MODELX" and self.CP.openpilotLongitudinalControl)' in src


def test_planner_passes_op_long_to_throttle_gate():
  from openpilot.selfdrive.controls.lib import longitudinal_planner
  src = open(longitudinal_planner.__file__).read()
  assert 'ap1_throttle_gate_for(CP.carFingerprint, bool(getattr(CP, "openpilotLongitudinalControl", False)))' in src


def test_wheel_controls_note_for_x():
  from openpilot.selfdrive.ui.bogpilot import menu_locks as ML
  assert ML.page_note(cp(X, True), "stalk_controls") is None
  assert ML.page_note(cp(X, False), "stalk_controls") is ML.MODEL_X_WHEEL
  assert ML.page_note(cp(S, True), "stalk_controls") is None
