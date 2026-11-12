"""Pre-AP: a takeover (hands on at level 3) or an EPAS refusal disengages, and re-engaging needs a new stalk pull (G1).

Real PreApCarState (from CAN) plus the real PreApCarController, one pull to engage, 100 Hz. The panda behaviour is modelled by
`panda_rejects` (the same condition as tesla_preap.h tesla_preap_epas_blocking: hands at level 3 or the EPAS INHIBITED with error
6..9). With G1 the panda also drops controls_allowed and the cruise latch on those inputs (as NAP and BogPilot na-preap do), so the
car state resets the engagement on the same inputs (preap_steer_drop). Every case asserts the host never sends ANGLE the panda
would reject. A torque-only takeover (hands flag below 3) still pauses and resumes by itself: the panda does not drop on it.
Replay shows what the code sends, not what the car does. Bit-level parity with the panda lives in test_preap_g1_parity.py.
"""
import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1.hso import AP1_RESUME_HOLD_FRAMES
from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
from opendbc.car.tesla_ap1.epas_gate import EPAS_CLEAN_FRAMES
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (  # noqa: F401  (autouse fixture)
  CANCEL, PULL, Rig, _act, _inv, _pedal_frame, _ready_rig, _params_dir)
from opendbc.car.tesla_ap1.values import CAR, DBC


def panda_rejects(hands, status, err):
  return hands >= 3 or (status == "EAC_INHIBITED" and 6 <= err <= 9)


class Takeover:
  def __init__(self, planned=0.3):
    self.rig, self.ctl = _ready_rig(double=False)
    self.planned = planned
    self.n = 0
    self.op = False
    self.hands = 0
    self.status = "EAC_AVAILABLE"
    self.err = 0
    self.torque = 0.0
    self.rate = 0.0
    self.wheel = 0.0
    self.sent = []          # (control type, angle) of every 0x488
    self.out = None
    self.panda_violations = 0

  def set_epas(self):
    self.rig.base["EPAS_sysStatus"].update(
      EPAS_handsOnLevel=self.hands, EPAS_eacStatus=_inv("EPAS_sysStatus", "EPAS_eacStatus", self.status),
      EPAS_eacErrorCode=self.err, EPAS_torsionBarTorque=-self.torque, EPAS_internalSAS=-self.wheel)
    self.rig.base["STW_ANGLHP_STAT"]["StW_AnglHP_Spd"] = -self.rate

  def step(self, n=1, stalk=0):
    out = []
    for _ in range(n):
      self.set_epas()
      _pedal_frame(self.rig, self.n)
      self.out = self.rig.frame(stalk=stalk, op=self.op)
      self.rig.cs.out = self.out
      enable_req = self.rig.cs.update_button_enable(self.out.buttonEvents)
      self.op = bool(self.op and self.out.cruiseState.enabled) or bool(enable_req and self.out.cruiseState.available)
      cc = structs.CarControl.new_message(enabled=self.op, latActive=self.op, longActive=self.op, actuators=_act(self.planned)).as_reader()
      _, sends = self.ctl.update(cc, self.rig.cs, self.rig.nanos)
      self.n += 1
      for sd in sends:
        addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
        if addr == 0x488:
          typ = dat[2] >> 6
          ang = -(((dat[0] & 0x7F) << 8 | dat[1]) - 16384) * 0.1
          out.append((typ, ang))
          if typ == 1 and panda_rejects(self.hands, self.status, self.err):
            self.panda_violations += 1
      self.sent.extend(out[-1:] if out else [])
    return out

  def engage(self):
    self.wheel = self.planned
    self.step(20)
    self.step(1, stalk=PULL)
    self.step(300)
    assert self.op and self.out.cruiseState.enabled
    assert self.step(10)[-1][0] == 1, "steering is on"


def angle_frames(sent):
  return [s for s in sent if s[0] == 1]


def test_hands_on_takeover_disengages_and_stops_steering():
  t = Takeover()
  t.engage()
  t.hands = 3
  sent = t.step(200)
  assert t.rig.cs.preap_panda_drop, "hands on at level 3 is a panda drop (G1)"
  assert not t.out.cruiseState.enabled and not t.op, "openpilot disengages with the panda"
  assert all(s[0] == 0 for s in sent[3:]), "NONE while the driver is on the wheel"
  assert t.panda_violations == 0


def test_still_hands_on_never_resumes():
  t = Takeover()
  t.engage()
  t.hands = 3
  t.step(50)
  t.hands = 2                                  # the EPAS only reports 0, 1 and 3, but a level 2 would still hold it
  assert angle_frames(t.step(500)) == []
  t.hands = 1                                  # light touch reported as 1: hands-on is over, but the detector must be quiet
  t.torque = 1.5
  assert angle_frames(t.step(500)) == [], "torque on the wheel keeps the pause"
  assert t.panda_violations == 0


def test_after_the_driver_lets_go_a_new_pull_is_needed_and_steering_starts_from_the_wheel():
  t = Takeover(planned=8.0)
  t.engage()
  t.hands = 3
  t.wheel = 25.0                               # the driver turned the wheel away from the plan
  t.step(100)
  t.hands, t.torque, t.rate = 0, 0.0, 0.0
  assert angle_frames(t.step(AP1_RESUME_HOLD_FRAMES * 3)) == [], "no resume on its own (G1)"
  assert not t.out.cruiseState.enabled and not t.op and not t.rig.cs.preap_panda_drop
  t.step(1, stalk=PULL)
  sent = t.step(AP1_RESUME_HOLD_FRAMES * 3)
  assert t.op and t.out.cruiseState.enabled, "a new pull re-engages"
  angles = [a for typ, a in sent if typ == 1]
  assert angles, "steering is back after the new pull"
  assert abs(angles[0] - 25.0) < 2.0, "the first ANGLE starts from the measured wheel"
  assert t.panda_violations == 0


def test_a_torque_takeover_with_the_hands_flag_at_zero_also_resumes():
  t = Takeover()
  t.engage()
  t.torque, t.rate = -4.0, -60.0
  sent = t.step(20)
  assert any(s[0] == 0 for s in sent)
  t.torque, t.rate = 0.0, 0.0
  sent = t.step(AP1_RESUME_HOLD_FRAMES * 3)
  assert sent[-1][0] == 1 and t.out.cruiseState.enabled


@pytest.mark.parametrize("err", [6, 7, 8, 9])
def test_refusing_epas_disengages_and_a_new_pull_resumes_after_the_clean_frames(err):
  t = Takeover()
  t.engage()
  t.status, t.err = "EAC_INHIBITED", err
  sent = t.step(100)
  assert t.rig.cs.preap_panda_drop and not t.out.cruiseState.enabled and not t.op, "an EPAS refusal disengages (G1)"
  assert angle_frames(sent[2:]) == []
  t.status, t.err = "EAC_ACTIVE", 0
  assert angle_frames(t.step(300)) == [], "no resume on its own"
  t.step(1, stalk=PULL)
  sent = t.step(EPAS_CLEAN_FRAMES + AP1_RESUME_HOLD_FRAMES * 3)
  assert t.op and sent[-1][0] == 1
  assert t.panda_violations == 0


def test_a_pull_into_a_refusing_epas_does_not_engage():
  t = Takeover()
  t.rig.base["EPAS_sysStatus"]["EPAS_eacStatus"] = _inv("EPAS_sysStatus", "EPAS_eacStatus", "EAC_AVAILABLE")
  t.wheel = t.planned
  t.step(20)
  t.status, t.err = "EAC_INHIBITED", 7
  t.step(1, stalk=PULL)
  sent = t.step(200)
  assert angle_frames(sent) == [], "never ANGLE into a refusing EPAS"
  assert not t.op and not t.out.cruiseState.enabled, "the panda would drop it on the next EPAS frame, so openpilot does not engage"
  t.status, t.err = "EAC_AVAILABLE", 0
  assert angle_frames(t.step(200)) == [], "the refused pull is gone, it does not engage later"
  t.step(1, stalk=PULL)
  sent = t.step(200)
  assert t.op and sent[-1][0] == 1
  assert t.panda_violations == 0


def test_eac_fault_disengages_and_needs_a_new_pull():
  t = Takeover()
  t.engage()
  t.status = "EAC_FAULT"
  t.step(5)
  assert t.rig.cs.preap_panda_drop and not t.out.cruiseState.enabled and not t.op
  t.status = "EAC_AVAILABLE"
  assert angle_frames(t.step(300)) == []
  t.step(1, stalk=PULL)
  t.step(100)
  assert t.op and t.out.cruiseState.enabled


def test_stalk_cancel_disengages_even_during_a_torque_takeover():
  t = Takeover()
  t.engage()
  t.torque, t.rate = -4.0, -60.0               # torque takeover with the hands flag below 3: a pause, not a panda drop
  t.step(50)
  assert t.op and not t.rig.cs.preap_panda_drop
  t.step(1, stalk=CANCEL)
  t.step(5)
  assert not t.out.cruiseState.enabled and not t.op
  t.torque, t.rate = 0.0, 0.0
  assert angle_frames(t.step(400)) == [], "a cancelled takeover does not come back"


def test_leaving_drive_still_resets():
  t = Takeover()
  t.engage()
  t.rig.base["DI_torque2"]["DI_gear"] = _inv("DI_torque2", "DI_gear", "DI_GEAR_N")
  t.step(5)
  assert not t.out.cruiseState.enabled
