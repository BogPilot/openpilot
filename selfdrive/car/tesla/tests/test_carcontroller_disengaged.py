"""Disengaged Tesla actuator plan.

CarController.update is not constructed here. opendbc/can/packer_pyx.so is
AArch64, and importing CarController also pulls parser_pyx and msgq. update
calls build_actuator_plan and then TeslaCAN. Those two are what this file runs.

Not a product, no warranty, driver remains responsible, comply with local law.
This does not enable lateral or longitudinal control.
"""

import re
from collections import deque
from pathlib import Path

from openpilot.selfdrive.car.tesla.actuator_plan import STEERING_CONTROL_NONE, build_actuator_plan
from openpilot.selfdrive.car.tesla.platform import long_control_allowed
from openpilot.selfdrive.car.tesla.teslacan import TeslaCAN
from openpilot.selfdrive.car.tesla.values import CANBUS, TeslaPlatform

TESLA = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[4]


class _Packer:
  def __init__(self):
    self.calls = []

  def make_can_msg(self, name, bus, values):
    self.calls.append((name, bus, dict(values)))
    return (0, 0, bytes(8), bus)


def _plan(counters=None, **kwargs):
  if counters is None:
    counters = deque([1, 2, 3])
  args = dict(
    frame=0,
    lat_active=False,
    hands_on_fault=False,
    openpilot_longitudinal_control=False,
    enabled=False,
    long_active=False,
    measured_angle_deg=12.5,
    requested_angle_deg=40.0,
    last_angle_deg=1.0,
    v_ego=15.0,
    accel=2.0,
    acc_state=2,
    das_counters=counters,
    pcm_cancel=False,
  )
  args.update(kwargs)
  return build_actuator_plan(**args), counters


def test_disengaged_echoes_angle_and_sends_no_long_command():
  counters = deque([1, 2, 3])
  plan, _ = _plan(counters)

  assert plan.steer is not None
  assert plan.steer.enabled is False
  assert plan.steer.control_type == STEERING_CONTROL_NONE
  # Inactive branch copies the measured angle, not the requested angle.
  assert plan.steer.angle_deg == 12.5
  assert plan.steer.angle_deg != 40.0
  assert plan.steer.counter == 0
  assert plan.apply_angle_last == 12.5
  assert plan.longitudinal == ()
  assert plan.cancel is False
  # Long gate is off, so stock DAS counters stay put.
  assert list(counters) == [1, 2, 3]

  chassis = _Packer()
  powertrain = _Packer()
  TeslaCAN(chassis, powertrain).create_steering_control(plan.steer.angle_deg, plan.steer.enabled, plan.steer.counter)

  assert [name for name, _, _ in chassis.calls] == ["DAS_steeringControl", "DAS_steeringControl"]
  sent = chassis.calls[-1]
  assert sent[1] == CANBUS.chassis
  assert sent[2]["DAS_steeringControlType"] == 0
  assert sent[2]["DAS_steeringHapticRequest"] == 0
  assert sent[2]["DAS_steeringControlCounter"] == 0
  # Angle field is the echoed measurement, negated the way this message is packed.
  # Control type 0 is NONE, so this is not an EPAS move request.
  assert sent[2]["DAS_steeringAngleRequest"] == -12.5
  assert powertrain.calls == []


def test_odd_frame_sends_no_steering_frame():
  plan, counters = _plan(frame=1)
  assert plan.steer is None
  assert plan.longitudinal == ()
  assert plan.cancel is False
  assert plan.apply_angle_last == 1.0
  assert list(counters) == [1, 2, 3]


def test_hands_on_fault_drops_lateral_request():
  plan, _ = _plan(lat_active=True, hands_on_fault=True, requested_angle_deg=30.0, measured_angle_deg=5.0)
  assert plan.steer is not None
  assert plan.steer.enabled is False
  assert plan.steer.angle_deg == 5.0
  assert plan.steer.control_type == STEERING_CONTROL_NONE
  # frame 0 and the fault forces cancel, which is the existing stalk-cancel path.
  assert plan.cancel is True
  assert plan.longitudinal == ()


def test_active_lateral_is_unchanged_when_engaged():
  # Guards the extraction. Not an enablement of driving.
  plan, _ = _plan(lat_active=True, measured_angle_deg=0.0, requested_angle_deg=10.0, last_angle_deg=0.0, v_ego=0.0, accel=0.0)
  assert plan.steer is not None
  assert plan.steer.enabled is True
  assert plan.steer.control_type == 1
  assert plan.steer.angle_deg == 10.0
  assert plan.longitudinal == ()


def test_no_friction_brake_or_ibooster_apply():
  assert long_control_allowed(TeslaPlatform.preap) is False
  packed = set()
  for name in ("carcontroller.py", "teslacan.py", "actuator_plan.py"):
    text = (TESLA / name).read_text()
    assert "iBooster" not in text
    assert "friction" not in text
    packed.update(re.findall(r'make_can_msg\("([^"]+)"', text))
  assert packed == {"DAS_steeringControl", "STW_ACTN_RQ", "DAS_control"}
  header = (ROOT / "panda/board/safety/safety_tesla.h").read_text()
  assert "BrakeMessage" in header
  assert "{0x20a, 0, 8" in header
  assert "{0x1f8, 0, 8" in header
  # Those ids are RX checks, not TX.
  tx = header.split("RxCheck tesla_rx_checks")[0]
  assert "0x20a" not in tx
  assert "0x1f8" not in tx
