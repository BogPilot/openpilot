"""carState.steeringPressed is the EPAS hands-on level >= 1 and nothing else, the same on every legacy Tesla here.

BogPilot 0.9.7 (bogpilot-tesla selfdrive/car/tesla/carstate.py:88-90, hso.py:57-63): steeringPressed is
hands_on_level >= 1 (ap1_driver_input), with no torque threshold and no counter. Tinkla (tesla_unity_dev
selfdrive/car/tesla/carstate.py:224-229) reads the same EPAS_sysStatus.EPAS_handsOnLevel with no torque term;
its TinklaHandsOnLevel 2 is the lateral pause, kept here separately as hso.ap1_steering_pressed (>= 2).
The 2 s recent-press gate for the steering-limit warning reads this flag, so pre-AP, AP1 S and AP1 X must agree.
Real CarState / PreApCarState fed from packed EPAS_sysStatus frames; no behaviour is changed by this file.
"""
import ast
import pathlib
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.hso import AP1_DRIVER_INPUT_LEVEL, AP1_HANDS_ON_LEVEL, ap1_driver_input, ap1_steering_pressed
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import Rig, _params_dir  # noqa: F401  (autouse fixture)
from opendbc.car.tesla_ap1.values import CAR

S, X, P = CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX, CAR.TESLA_PREAP_MODELS
PLATFORMS = [P, S, X]
LEVELS = [0, 1, 2, 3]                      # EPAS_handsOnLevel is 39|2: every value it can carry
EXPECTED = {0: False, 1: True, 2: True, 3: True}
TORQUES = [0.0, 0.9, -1.5, 3.0, -8.0]       # driver torque never sets steeringPressed by itself


def _ap1_pressed(fingerprint, hands, torque=0.0):
  cp = SimpleNamespace(carFingerprint=fingerprint)
  cs = CarState(cp)
  parsers = CarState.get_can_parsers(cp)
  chassis = parsers[Bus.chassis]
  addr, dat, _ = CANPacker("tesla_ap1_can").make_can_msg(
    "EPAS_sysStatus", chassis.bus, {"EPAS_handsOnLevel": hands, "EPAS_torsionBarTorque": -torque})
  chassis.update([(0, [(addr, dat, chassis.bus)])])
  ret = cs.update(parsers)
  assert int(cs.hands_on_level) == hands
  return ret.steeringPressed


def _preap_pressed(hands, torque=0.0):
  rig = Rig()
  rig.base["EPAS_sysStatus"].update(EPAS_handsOnLevel=hands, EPAS_torsionBarTorque=-torque)
  ret = rig.frame()
  assert int(rig.cs.hands_on_level) == hands
  return ret.steeringPressed


def pressed(fingerprint, hands, torque=0.0):
  return _preap_pressed(hands, torque) if fingerprint == P else _ap1_pressed(fingerprint, hands, torque)


def test_thresholds_are_the_reference_values():
  assert AP1_DRIVER_INPUT_LEVEL == 1, "steeringPressed: BogPilot 0.9.7 hands >= 1"
  assert AP1_HANDS_ON_LEVEL == 2, "lateral pause: Tinkla TinklaHandsOnLevel 2, not steeringPressed"
  assert [ap1_driver_input(h) for h in LEVELS] == [EXPECTED[h] for h in LEVELS]
  assert [ap1_steering_pressed(h) for h in LEVELS] == [False, False, True, True]


@pytest.mark.parametrize("fingerprint", PLATFORMS, ids=["preap_s", "ap1_s", "ap1_x"])
@pytest.mark.parametrize("hands", LEVELS)
def test_hands_level_maps_to_steering_pressed(fingerprint, hands):
  assert pressed(fingerprint, hands) is EXPECTED[hands]


@pytest.mark.parametrize("fingerprint", PLATFORMS, ids=["preap_s", "ap1_s", "ap1_x"])
@pytest.mark.parametrize("torque", TORQUES)
def test_torque_alone_never_sets_steering_pressed(fingerprint, torque):
  assert pressed(fingerprint, 0, torque) is False
  assert pressed(fingerprint, 1, torque) is True


def test_preap_equals_ap1_s_and_ap1_x_for_every_hands_level_and_torque():
  for hands in LEVELS:
    for torque in TORQUES:
      got = {fp: pressed(fp, hands, torque) for fp in PLATFORMS}
      assert len(set(got.values())) == 1, (hands, torque, got)
      assert got[P] is EXPECTED[hands]


# ---- guard: no torque-threshold steeringPressed path in the car port -------------------------------

PKG = pathlib.Path(__file__).resolve().parents[1]


def _sources():
  return [p for p in PKG.rglob("*.py") if "tests" not in p.relative_to(PKG).parts]


def test_no_torque_threshold_press_helper_is_used():
  for path in _sources():
    text = path.read_text()
    for name in ("update_steering_pressed", "STEER_THRESHOLD"):
      assert name not in text, f"{path.relative_to(PKG)} uses {name}"


def test_every_steering_pressed_assignment_reads_only_the_hands_level():
  found = []
  for path in _sources():
    for node in ast.walk(ast.parse(path.read_text())):
      if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "steeringPressed" for t in node.targets):
        names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(node.value) if isinstance(n, ast.Attribute)}
        found.append(str(path.relative_to(PKG)))
        assert attrs <= {"hands_on_level"}, (path.name, node.lineno, attrs)
        assert names <= {"self", "ap1_driver_input"}, (path.name, node.lineno, names)
  assert sorted(set(found)) == ["carstate.py", "preap/carstate.py"], found
