"""AP1 hands-on pause matches Tinkla HSO, not a FrogPilot cancel.

Not a product, no warranty, driver remains responsible, comply with local law.
This does not make the car safe to drive. Continuous EPAS error code 6 still
blocks path lateral.
"""

from collections import deque
from pathlib import Path

from openpilot.selfdrive.car.tesla.actuator_plan import (
  ACC_ON,
  STEERING_CONTROL_ANGLE,
  STEERING_CONTROL_NONE,
  build_actuator_plan,
)
from openpilot.selfdrive.car.tesla.hso import (
  AP1_HANDS_ON_LEVEL,
  ap1_hso_event_names,
  ap1_lat_active,
  ap1_steering_pressed,
)

ROOT = Path(__file__).resolve().parents[4]


def _plan(**kwargs):
  args = dict(
    frame=0,
    lat_active=False,
    hands_on_fault=False,
    openpilot_longitudinal_control=True,
    enabled=True,
    long_active=True,
    measured_angle_deg=8.0,
    requested_angle_deg=30.0,
    last_angle_deg=8.0,
    v_ego=15.0,
    accel=0.2,
    acc_state=ACC_ON,
    das_counters=deque([3]),
    pcm_cancel=False,
    chassis_das_only=True,
  )
  args.update(kwargs)
  return build_actuator_plan(**args)


def test_hands_threshold_is_tinkla_level_2():
  assert AP1_HANDS_ON_LEVEL == 2
  assert ap1_steering_pressed(0) is False
  assert ap1_steering_pressed(1) is False
  assert ap1_steering_pressed(2) is True
  assert ap1_steering_pressed(3) is True
  # Path lateral pauses at the threshold even if controlsd still says lat active.
  assert ap1_lat_active(True, 2) is False
  assert ap1_lat_active(True, 1) is True
  assert ap1_lat_active(False, 0) is False


def test_hands_pause_sends_measured_none_and_keeps_long():
  plan = _plan(lat_active=False)
  assert plan.cancel is False
  assert len(plan.longitudinal) == 1
  assert plan.steer is not None
  assert plan.steer.enabled is False
  assert plan.steer.control_type == STEERING_CONTROL_NONE
  assert plan.steer.angle_deg == 8.0
  assert plan.apply_angle_last == 8.0


def test_hands_drop_resumes_path_angle_without_cancel():
  # v_ego 0 keeps the rate step large enough that the request is not clipped.
  plan = _plan(lat_active=True, requested_angle_deg=10.0, measured_angle_deg=0.0,
               last_angle_deg=0.0, v_ego=0.0, accel=0.0)
  assert plan.cancel is False
  assert len(plan.longitudinal) == 1
  assert plan.steer is not None
  assert plan.steer.enabled is True
  assert plan.steer.control_type == STEERING_CONTROL_ANGLE
  assert plan.steer.angle_deg == 10.0


def test_code_6_keeps_measured_none_not_the_plan():
  # lat_active is already false because code 6 is steerFaultTemporary.
  plan = _plan(lat_active=False, requested_angle_deg=25.0, measured_angle_deg=4.0)
  assert plan.cancel is False
  assert plan.steer is not None
  assert plan.steer.control_type == STEERING_CONTROL_NONE
  assert plan.steer.angle_deg == 4.0
  assert plan.steer.angle_deg != 25.0


def test_disengaged_ap1_still_sends_no_steering_frame():
  plan = _plan(enabled=False, long_active=False, lat_active=False)
  assert plan.steer is None
  assert plan.longitudinal == ()
  assert plan.cancel is False


def test_non_ap1_lat_inactive_still_sends_no_steering_frame():
  plan = _plan(chassis_das_only=False, enabled=True, lat_active=False)
  assert plan.steer is None
  assert plan.cancel is False


def test_temp_steer_event_is_silent_and_fault_is_not():
  assert ap1_hso_event_names(["steerTempUnavailable", "pcmEnable"]) == [
    "steerTempUnavailableSilent",
    "pcmEnable",
  ]
  assert ap1_hso_event_names(["steerTempUnavailable", "steerTempUnavailableSilent"]) == [
    "steerTempUnavailableSilent",
  ]
  assert ap1_hso_event_names(["steerUnavailable"]) == ["steerUnavailable"]
  assert "steerTempUnavailable" not in ap1_hso_event_names(["steerTempUnavailable"])


def test_wiring_keeps_model3_cancel_and_ap1_pause():
  carstate = (ROOT / "selfdrive/car/tesla/carstate.py").read_text()
  assert "ap1_steering_pressed(self.hands_on_level)" in carstate
  assert "self.hands_on_level > 0" in carstate
  controller = (ROOT / "selfdrive/car/tesla/carcontroller.py").read_text()
  assert "hands_on_fault = (not ap1)" in controller
  assert "ap1_lat_active(CC.latActive, CS.hands_on_level)" in controller
  controlsd = (ROOT / "selfdrive/controls/controlsd.py").read_text()
  assert 'self.CP.carFingerprint == "TESLA_AP1_MODELS" and CS.steeringPressed' in controlsd
  assert "not ap1_hands_pause" in controlsd
  interface = (ROOT / "selfdrive/car/tesla/interface.py").read_text()
  assert "ap1_hso_event_names" in interface
  assert "CAR.TESLA_AP1_MODELS" in interface
  # Hold clear and stalk follow stay wired.
  assert "ap1_should_send_hold_clear" in controller
  card = (ROOT / "frogpilot/controls/frogpilot_card.py").read_text()
  assert "TeslaStalkFollow" not in card
