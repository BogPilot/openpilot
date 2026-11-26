"""steerSaturated gate: the same conditions as BogPilot 0.9.7 controlsd, with no openpilot-state gate."""
import inspect

from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD, State, steer_saturated_alert_allowed
from openpilot.selfdrive.selfdrived.state import ACTIVE_STATES

SATURATED_TURN = dict(undershooting=True, turning=True, saturated=True)


def recent_steer_pressed(frame, last_steering_pressed_frame):
  # The 0.9.7 expression, also used verbatim in SelfdriveD.update_events.
  return (frame - last_steering_pressed_frame)*DT_CTRL < 2.0


def test_gate_takes_no_openpilot_state():
  assert list(inspect.signature(steer_saturated_alert_allowed).parameters) == [
    "lac_active", "recent_steer_pressed", "not_car", "undershooting", "turning", "saturated"]


def test_gas_only_override_with_saturation_fires():
  # Accelerator-only override: overriding is an active state, lateral control stays active,
  # and the wheel was not touched in the last 2 s.
  assert State.overriding in ACTIVE_STATES
  assert steer_saturated_alert_allowed(lac_active=True, recent_steer_pressed=False, not_car=False, **SATURATED_TURN)


def test_undershoot_kinematics_fire_without_a_steering_press():
  # desired 1.325 vs actual 0.310 m/s^2 lateral accel (4.3x undershoot), saturated, no steering press.
  undershooting = abs(-1.325) / abs(1e-3 + -0.310) > 1.2
  turning = abs(-1.325) > 1.0
  assert steer_saturated_alert_allowed(lac_active=True, recent_steer_pressed=False, not_car=False,
                                       undershooting=undershooting, turning=turning, saturated=True)


def test_enabled_with_saturation_fires():
  assert State.enabled in ACTIVE_STATES
  assert steer_saturated_alert_allowed(lac_active=True, recent_steer_pressed=False, not_car=False, **SATURATED_TURN)


def test_needs_undershoot_turn_and_saturation():
  for missing in SATURATED_TURN:
    kw = {**SATURATED_TURN, missing: False}
    assert not steer_saturated_alert_allowed(lac_active=True, recent_steer_pressed=False, not_car=False, **kw)


def test_recent_steer_press_window_is_2s_like_097():
  last = 1000
  assert recent_steer_pressed(last, last)
  assert recent_steer_pressed(last + int(2. / DT_CTRL) - 1, last)
  assert not recent_steer_pressed(last + int(2. / DT_CTRL), last)
  assert not steer_saturated_alert_allowed(lac_active=True, recent_steer_pressed=True, not_car=False, **SATURATED_TURN)


def test_update_events_uses_the_097_steer_press_window():
  src = inspect.getsource(SelfdriveD.update_events)
  assert "if CS.steeringPressed:\n      self.last_steering_pressed_frame = self.sm.frame" in src
  assert "recent_steer_pressed = (self.sm.frame - self.last_steering_pressed_frame)*DT_CTRL < 2.0" in src
  call = src[src.index("steer_saturated_alert_allowed("):src.index("EventName.steerSaturated")]
  assert "state" not in call.replace("steer_saturated_alert_allowed", "")


def test_inactive_or_notcar_is_silent():
  for kw in (dict(lac_active=False, not_car=False), dict(lac_active=True, not_car=True)):
    assert not steer_saturated_alert_allowed(recent_steer_pressed=False, **kw, **SATURATED_TURN)
