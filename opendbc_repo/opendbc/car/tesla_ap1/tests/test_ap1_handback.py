"""Smooth hand-back after a driver override, on every legacy Tesla.

The command is released on the first frame of the override (type NONE at the measured wheel, nothing
to fight with). It comes back only after the driver has let go (hands 0, torque and wheel rate low for
the hold) and the EPAS reports a clean state, starts from the measured wheel, and blends to the plan.
"""
import pytest

from opendbc.car.tesla_ap1.epas_gate import EPAS_CLEAN_FRAMES
from opendbc.car.tesla_ap1.hso import AP1_RESUME_HOLD_FRAMES
from opendbc.car.tesla_ap1.tests.test_ap1_override_detector import PLATFORMS, Car, P, S, X  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401


def swerve(car, torque=-5.0, rate=-100.0, frames=40, to=-20.0):
  """The driver pulls the wheel away from the plan: hands flag stays 0."""
  car.torque, car.rate = torque, rate
  out = []
  for i in range(frames):
    car.angle = to * (i + 1) / frames
    out.append(car.step())
  return [x for x in out if x is not None]


def let_go(car, frames):
  car.torque, car.rate, car.hands = 0.0, 0.0, 0
  return [x for x in car.run(frames) if x is not None]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_release_is_immediate_and_nothing_opposes_the_driver(platform):
  car = Car(platform)
  car.planned = 6.0
  car.angle = 6.0
  car.settle(300)
  car.angle = 6.0
  sent = swerve(car)
  first_none = next(i for i, (t, _a) in enumerate(sent) if t == 0)
  assert first_none <= 2
  assert all(t == 0 for t, _a in sent[first_none:])
  # whatever was sent while the wheel moves from +6 toward -20 never pointed against that move
  assert all(a <= 6.0 + 0.2 for _t, a in sent)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_no_resume_while_the_driver_still_leans_on_the_wheel(platform):
  car = Car(platform)
  car.planned = 6.0
  car.settle(300)
  swerve(car)
  car.torque, car.rate = 1.5, 5.0       # hands flag 0, but still pushing
  assert all(t == 0 for t, _a in [x for x in car.run(300) if x is not None])
  assert all(t == 0 for t, _a in let_go(car, AP1_RESUME_HOLD_FRAMES - 4))


@pytest.mark.parametrize("platform", PLATFORMS)
def test_no_resume_while_the_epas_is_inhibited_then_waits_for_it_to_be_clean(platform):
  car = Car(platform)
  car.planned = 6.0
  car.settle(300)
  swerve(car)
  car.status, car.error, car.hands = "EAC_INHIBITED", "EAC_ERROR_HANDS_ON", 3
  car.run(30)
  car.hands = 0
  sent = let_go(car, 200)
  assert all(t == 0 for t, _a in sent), "driver is off the wheel but the EPAS is still INHIBITED"
  car.status, car.error = "EAC_AVAILABLE", "EAC_ERROR_HANDS_ON"          # latched code 3 at AVAILABLE
  early = let_go(car, EPAS_CLEAN_FRAMES - 6)
  assert all(t == 0 for t, _a in early)
  late = let_go(car, 80)
  assert late[-1][0] == 1


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("v_ego", [4.0, 15.0])
def test_resume_starts_at_the_wheel_and_blends_without_steps(platform, v_ego):
  car = Car(platform)
  car.v_ego = v_ego
  car.planned = 10.0
  car.settle(400)
  car.angle = 10.0
  car.settle(100)
  swerve(car, to=0.0)
  car.angle = 0.0
  sent = let_go(car, AP1_RESUME_HOLD_FRAMES + 150)
  angles = [a for t, a in sent if t == 1]
  assert angles, "lateral came back"
  assert abs(angles[0] - 0.0) < 1.0, f"first angle after the hand-back is at the wheel, got {angles[0]}"
  steps = [abs(b - a) for a, b in zip(angles, angles[1:])]
  assert max(steps) < 1.5, f"largest step between ANGLE frames {max(steps):.2f} deg"
  car.angle = angles[-1]
  assert angles[-1] > 6.0, "blended all the way to the plan"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_driver_can_grab_again_during_the_blend(platform):
  car = Car(platform)
  car.planned = 10.0
  car.settle(400)
  swerve(car, to=0.0)
  car.angle = 0.0
  let_go(car, AP1_RESUME_HOLD_FRAMES + 20)
  car.torque = 4.0
  sent = [x for x in car.run(10) if x is not None]
  assert any(t == 0 for t, _a in sent) and sent[-1][0] == 0
