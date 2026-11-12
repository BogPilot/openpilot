"""Pre-AP: openpilot disengages on the SAME frame as the panda's hands-on / EPAS refusal drop, with and without the pedal.

Level of this test: the real PreApCarState (from CAN, via the opendbc rig), the real CarEvents (car_events.py, including the tesla_ap1
event rewrite and HSO) and the real selfdrived StateMachine. It is not a full selfdrived process run (no messaging, no pandaStates
service); the "no preapNotArmed" check feeds PreapArmWatch with the panda mirror's controls_allowed, the way selfdrived does.
The panda side is the Python mirror of tesla_preap.h from opendbc's test_preap_g1_parity.py.
"""
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1.hso import ap1_hso_event_names
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401  (autouse fixture)
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import CAUSES, EAC_FAULT, EAC_INHIBITED, Drive
from opendbc.car.tesla_ap1.values import CAR
from openpilot.cereal import log
from openpilot.selfdrive.car.car_events import CarEvents
from openpilot.selfdrive.selfdrived.preap_arm import PreapArmWatch
from openpilot.selfdrive.selfdrived.state import ENABLED_STATES, StateMachine

EventName = log.OnroadEvent.EventName
State = log.SelfdriveState.OpenpilotState
NAMES = {v: k for k, v in EventName.schema.enumerants.items()}
PANDA_MODE = structs.CarParams.SafetyModel.tesla


class Selfdrive:
  def __init__(self, pedal):
    self.d = Drive(pedal)
    self.CP = structs.CarParams.new_message(brand="tesla_ap1", carFingerprint=CAR.TESLA_PREAP_MODELS,
                                            openpilotLongitudinalControl=pedal, pcmCruise=not pedal)
    self.car_events = CarEvents(self.CP)
    self.sm = StateMachine()
    self.arm = PreapArmWatch(SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS))
    self.cs_prev = structs.CarState.new_message()
    self.not_armed_frames = 0

  def step(self, stalk=0):
    enabled = self.sm.state in ENABLED_STATES
    cs = self.d.step(stalk=stalk, op=enabled)
    cs.buttonEnable = self.d.rig.cs.update_button_enable(cs.buttonEvents)   # as CarInterfaceBase.update does
    cc = structs.CarControl.new_message(enabled=enabled, latActive=enabled, longActive=enabled and self.d.pedal)
    names = {NAMES[e] for e in self.car_events.update(cs, self.cs_prev, cc).names}
    self.cs_prev = cs
    self.sm.update(self.car_events_obj(names))
    enabled_after = self.sm.state in ENABLED_STATES
    panda_states = [SimpleNamespace(controlsAllowed=self.d.panda.controls_allowed, safetyModel=PANDA_MODE)]
    if self.arm.update(enabled_after, panda_states):
      self.not_armed_frames += 1
    return names, cs

  @staticmethod
  def car_events_obj(names):
    from openpilot.selfdrive.selfdrived.events import Events
    ev = Events()
    for n in names:
      ev.add(EventName.schema.enumerants[n])
    return ev

  def engage(self):
    self.d.engage()
    self.sm.state = State.enabled
    for _ in range(20):
      names, _ = self.step()
      assert self.sm.state in ENABLED_STATES, names


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "pcmCruise"])
@pytest.mark.parametrize("cause,epas", CAUSES, ids=[c for c, _ in CAUSES])
def test_openpilot_disengages_on_the_panda_drop_frame(pedal, cause, epas):
  s = Selfdrive(pedal)
  s.engage()
  s.d.epas(*epas)
  names, cs = s.step()
  assert s.d.panda.last_drop and not s.d.panda.controls_allowed, "the panda drops on this frame"
  assert "steerDisengage" in names, f"steerDisengage on the same frame, got {sorted(names)}"
  assert s.sm.state == State.disabled, "openpilot is disengaged on the same frame"
  raised = 0
  for _ in range(100):                          # condition still held: no second steerDisengage, and no preapNotArmed
    names, cs = s.step()
    raised += "steerDisengage" in names
  assert raised == 0, "rising edge only"
  assert s.not_armed_frames == 0, "preapNotArmed never fires for this drop"
  assert s.sm.state == State.disabled


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "pcmCruise"])
def test_eac_fault_is_steer_unavailable_not_steer_disengage(pedal):
  s = Selfdrive(pedal)
  s.engage()
  s.d.epas(0, EAC_FAULT, 0)
  names, _ = s.step()
  assert "steerUnavailable" in names and "steerDisengage" not in names
  assert s.sm.state == State.disabled


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "pcmCruise"])
def test_hands_on_coded_inhibited_keeps_openpilot_engaged(pedal):
  s = Selfdrive(pedal)
  s.engage()
  s.d.epas(0, EAC_INHIBITED, 3)
  for _ in range(50):
    names, _ = s.step()
    assert "steerDisengage" not in names
  assert s.sm.state in ENABLED_STATES and s.d.panda.controls_allowed


def test_hso_does_not_rewrite_steer_disengage():
  # hso.py ap1_hso_event_names only rewrites steerTempUnavailable
  assert ap1_hso_event_names(["steerDisengage"]) == ["steerDisengage"]
  assert ap1_hso_event_names(["steerDisengage", "steerTempUnavailable"]) == ["steerDisengage", "steerTempUnavailableSilent"]
