"""Pre-AP brake press keeps steering and cuts only the pedal: car side, end to end.

The panda half is opendbc/safety/tests/test_tesla_preap_brake_steer.py; the selfdrived half is selfdrive/selfdrived/tests/test_preap_brake.py.
Here selfdrived is modelled the way the real one now behaves: it disengages on a brake press unless carState.bogpilot.preapLatOnly says the
press only drops longitudinal.
"""
from opendbc.car import structs
from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (  # noqa: F401  (autouse fixture)
  CAR, DBC, PULL, Rig, _act, _params_dir, _pedal_frame, _ready_rig,
)


class Drive:
  """Frame loop: stalk -> CarState -> modelled selfdrived/controlsd -> CarController. Records what went on the wire."""

  def __init__(self):
    self.rig, self.ctl = _ready_rig(double=False)
    self.n = 0
    self.op = False
    self.log = []                      # per frame: dict(op, long_active, lat_only, pedal_enabled, steer_enabled, brake, enabled_cruise)

  def step(self, pull=False, brake=False, gas=False):
    rig = self.rig
    _pedal_frame(rig, self.n, raw=40.0 if gas else 0.8)
    out = rig.frame(stalk=PULL if pull else 0, op=self.op, brake=brake)
    rig.cs.out = out
    enable_req = rig.cs.update_button_enable(out.buttonEvents)
    brake_edge = brake and not self.log_brake_prev
    # selfdrived: stock disengage on a brake press, except when the car side says it only drops longitudinal
    brake_disengages = bool(out.brakePressed and not out.bogpilot.preapLatOnly and (brake_edge or out.vEgo > 0.5))
    self.op = bool((self.op and out.cruiseState.enabled and not brake_disengages) or (enable_req and out.cruiseState.available))
    self.log_brake_prev = brake
    long_active = self.op and not out.bogpilot.preapLatOnly
    cc = structs.CarControl.new_message(enabled=self.op, latActive=self.op, longActive=long_active, actuators=_act(0.3)).as_reader()
    _, sends = self.ctl.update(cc, rig.cs, rig.nanos)
    ped = steer = False
    for sd in sends:
      addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
      ped |= bool(addr == 0x551 and dat[4] & 0x80)
      steer |= bool(addr == 0x488 and (dat[2] >> 6) == 1)
    self.log.append(dict(op=self.op, long_active=long_active, lat_only=bool(out.bogpilot.preapLatOnly), pedal=ped, steer=steer, brake=brake,
                         cruise=bool(out.cruiseState.enabled)))
    self.n += 1

  log_brake_prev = False

  def run(self, frames, **kw):
    for _ in range(frames):
      self.step(**kw)
    return self.log[-frames:]


def _engaged():
  d = Drive()
  d.run(20)
  d.step(pull=True)
  d.run(250)
  assert d.log[-1]["op"] and d.log[-1]["long_active"] and any(f["pedal"] for f in d.log[-50:]), "engaged with the pedal driving"
  return d


def test_brake_press_keeps_openpilot_engaged_steering_on_and_cuts_the_pedal():
  d = _engaged()
  held = d.run(60, brake=True)
  assert all(f["op"] and f["cruise"] and f["lat_only"] for f in held), "openpilot stays enabled, lateral only"
  assert all(not f["long_active"] for f in held)
  assert not any(f["pedal"] for f in held[3:]), "no enabled pedal frame while the brake is pressed (a frame or two of lag at the edge is fine)"
  assert sum(f["steer"] for f in held) >= 25, "steering frames (0x488 ANGLE) keep going at 50 Hz"


def test_after_the_brake_is_released_steering_continues_and_the_pedal_stays_off_until_a_pull():
  d = _engaged()
  d.run(30, brake=True)
  free = d.run(150)
  assert all(f["op"] and f["lat_only"] for f in free)
  assert not any(f["pedal"] for f in free), "no pedal until the driver pulls again"
  assert sum(f["steer"] for f in free) >= 70
  d.step(pull=True)
  back = d.run(250)
  assert back[-1]["op"] and back[-1]["long_active"] and not back[-1]["lat_only"]
  assert any(f["pedal"] for f in back), "a pull with the brake free brings the pedal back"


def test_a_pull_with_the_foot_still_on_the_brake_does_not_bring_the_pedal_back():
  d = _engaged()
  d.run(30, brake=True)
  d.step(pull=True, brake=True)
  held = d.run(100, brake=True)
  assert all(f["op"] and f["lat_only"] and not f["pedal"] for f in held)


def test_gas_press_while_lateral_only_changes_nothing_on_the_car_side():
  # the panda no longer drops the steering latch on a gas edge, so openpilot must not either: still enabled, still lat_only, still steering
  d = _engaged()
  d.run(30, brake=True)
  d.run(20)
  for _ in range(5):
    gas = d.run(10, gas=True)
    assert all(f["op"] and f["lat_only"] for f in gas)
    assert sum(f["steer"] for f in gas) >= 4, "steering frames keep going while the driver is on the accelerator"
    assert not any(f["pedal"] for f in gas), "the pedal stays off"
    free = d.run(10)
    assert all(f["op"] and f["lat_only"] for f in free)


def test_cancel_still_ends_everything():
  d = _engaged()
  d.run(30, brake=True)
  d.rig.frame(stalk=1)                 # cancel (stalk away); the FSM resets and openpilot follows it down
  d.op = False
  out = d.rig.frame(stalk=0)
  assert not out.cruiseState.enabled and not out.bogpilot.preapLatOnly
