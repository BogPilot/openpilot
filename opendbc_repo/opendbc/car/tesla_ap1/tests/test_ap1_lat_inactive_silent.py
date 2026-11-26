"""No active steering frame once latActive is false, and a fresh engagement after it, on every legacy Tesla.

In a logged override event openpilot kept sending 27 ANGLE frames after controlsd dropped latActive: the
AP1 hold-measured branch only looked at `enabled` and the EPAS status. It now needs latActive.
"""
import pytest

from opendbc.car.tesla_ap1.tests.test_ap1_epas_yield import _plan
from opendbc.car.tesla_ap1.tests.test_ap1_override_detector import PLATFORMS, Car, P, S, X  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401

EPAS_STATES = [("EAC_ACTIVE", "EAC_ERROR_IDLE", 0),
               ("EAC_AVAILABLE", "EAC_ERROR_IDLE", 0),
               ("EAC_AVAILABLE", "EAC_ERROR_HANDS_ON", 0),
               ("EAC_AVAILABLE", "EAC_ERROR_HIGH_ANGLE_REQ", 0),
               ("EAC_INHIBITED", "EAC_ERROR_HIGH_ANGLE_RATE_SAFETY", 0),   # the logged case
               ("EAC_INHIBITED", "EAC_ERROR_HANDS_ON", 3),                 # the other drive
               ("EAC_INHIBITED", "EAC_ERROR_HIGH_ANGLE_REQ", 0),
               ("EAC_FAULT", "EAC_ERROR_IDLE", 0)]


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("status,err,hands", EPAS_STATES)
def test_no_angle_frame_after_lat_active_goes_false(platform, status, err, hands):
  car = Car(platform)
  car.planned = 4.0
  car.angle = 4.0
  car.settle(300)
  car.lat = False                      # controlsd drops latActive; enabled stays true
  car.status, car.error, car.hands = status, err, hands
  sent = [x for x in car.run(300) if x is not None]
  assert sent, "NONE frames keep the 0x488 stream"
  assert all(t == 0 for t, _a in sent), sent[:5]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_lat_active_false_from_the_start_never_sends_angle(platform):
  car = Car(platform)
  car.lat = False
  car.status, car.error = "EAC_AVAILABLE", "EAC_ERROR_IDLE"
  assert all(t == 0 for t, _a in [x for x in car.run(300) if x is not None])


@pytest.mark.parametrize("platform", PLATFORMS)
def test_fresh_lat_active_starts_from_the_measured_wheel(platform):
  car = Car(platform)
  car.planned = 10.0
  car.angle = 0.0
  car.lat = False
  car.status, car.error = "EAC_AVAILABLE", "EAC_ERROR_IDLE"
  car.run(100)
  car.lat = True
  sent = [x for x in car.run(40) if x is not None]
  first = next((a for t, a in sent if t == 1), None)
  assert first is not None and abs(first - 0.0) < 1.5, f"first ANGLE after a fresh latActive is near the wheel, got {first}"
  car.status = "EAC_ACTIVE"
  sent = [x for x in car.run(300) if x is not None]
  assert sent[-1][0] == 1 and sent[-1][1] > 3.0, "then it follows the plan"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_lat_active_drop_and_return_restarts_the_soft_start(platform):
  car = Car(platform)
  car.planned = 10.0
  car.settle(400)
  car.angle = 10.0
  car.settle(100)
  car.lat = False
  car.angle = 2.0
  car.run(50)
  car.lat = True
  sent = [x for x in car.run(10) if x is not None]
  angles = [a for t, a in sent if t == 1]
  assert angles and all(abs(a - 2.0) < 2.5 for a in angles), "steps from the wheel, not back to the old 10 deg target"


def test_planner_hold_needs_lat_session_when_it_is_given():
  held = _plan(lat_active=False, eac_status="EAC_AVAILABLE", lat_session=False)
  assert not held.steer.enabled
  held = _plan(lat_active=False, eac_status="EAC_AVAILABLE", lat_session=True, last_angle_deg=5.0)
  assert held.steer.enabled and held.steer.angle_deg == 5.0, "latActive with an AVAILABLE EPAS: the measured hold, as before"
  legacy = _plan(lat_active=False, eac_status="EAC_AVAILABLE")
  assert legacy.steer.enabled, "callers that do not pass lat_session keep the old rule"
