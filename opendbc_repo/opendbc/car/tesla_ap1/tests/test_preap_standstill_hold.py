"""Q1 option (b) with the panda unchanged: FULL from a standstill holds at 0 (pedal ENABLE=0, raw <= 500, no drive-off) until the
driver presses the accelerator; the first ENABLE=1 goes out one update after the accelerator is released (the panda refuses ENABLE
while gas_pressed_prev, get_longitudinal_allowed). Never ENABLE=1 while braking. NAP: preap/engagement.py:142,243-246 and
preap/carcontroller.py:97-100,123-128 @ e99f4dc75 (NAP holds with ENABLE=1 at zero torque; this is stricter)."""
from types import SimpleNamespace

from opendbc.car import structs
from opendbc.car.tesla_ap1.preap.carstate import PANDA_GAS_PRESSED_DBC
from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.preap.long_controller import PreAPLongController
from opendbc.car.tesla_ap1.preap.pedal_can import PedalCommandCounter
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, _act, _inv, _params_dir, _pedal_frame, _ready_rig, params  # noqa: F401

RAW_LIMIT_DISABLED = 500      # tesla_preap.h:249,256: an ENABLE=0 frame must stay <= 500 raw


class Car:
  def __init__(self):
    self.rig, self.ctl = _ready_rig(double=False)
    self.op, self.n, self.log = False, 0, []

  def step(self, stalk=0, brake=False, v_kph=0.0, gas=0.8):
    _pedal_frame(self.rig, self.n, raw=gas)
    out = self.rig.frame(stalk=stalk, op=self.op, brake=brake, v_kph=v_kph)
    self.rig.cs.out = out
    req = self.rig.cs.update_button_enable(out.buttonEvents)
    self.op = bool(self.op and out.cruiseState.enabled) or bool(req and out.cruiseState.available)
    cc = structs.CarControl.new_message(enabled=self.op, latActive=self.op, longActive=self.op and not out.bogpilot.preapLatOnly,
                                        actuators=_act(0.5)).as_reader()
    _, sends = self.ctl.update(cc, self.rig.cs, self.rig.nanos)
    frames = [(sd.address if hasattr(sd, "address") else sd[0], bytes(sd.dat if hasattr(sd, "dat") else sd[1])) for sd in sends]
    pedal = [d for a, d in frames if a == 0x551]
    self.log.append(dict(n=self.n, gas=gas, brake=brake, enabled=[bool(d[4] & 0x80) for d in pedal],
                         raw=[(d[0] << 8) | d[1] for d in pedal]))
    self.n += 1
    return out

  @property
  def mode(self):
    return Mode(self.rig.cs.preap_fsm_mode)


def _held():
  c = Car()
  for _ in range(20):
    c.step()
  c.step(stalk=PULL)
  for _ in range(9):
    c.step()
  c.step(stalk=PULL)
  for _ in range(100):
    out = c.step()
  assert c.mode == Mode.FULL and c.rig.cs.preap_standstill_hold and c.op and not out.bogpilot.preapLatOnly
  return c


def test_standstill_full_holds_at_zero_with_no_lead_and_never_enables():
  c = _held()
  held = c.log[30:]
  assert held and not any(any(e["enabled"]) for e in held), "no pedal ENABLE=1 while holding"
  assert all(r <= RAW_LIMIT_DISABLED for e in held for r in e["raw"]), "(a) hold frames are ENABLE=0 with raw <= 500"


def test_gas_press_releases_the_hold_and_enable_waits_one_update_after_release():
  c = _held()
  for _ in range(10):
    c.step(gas=40.0, v_kph=3.0)                       # driver on the accelerator
    assert not any(c.log[-1]["enabled"]), "(b) ENABLE=0 while gasPressed"
  c.step(gas=0.8, v_kph=5.0)                           # released on this update, moving: the hold ends and the set is captured
  assert not c.rig.cs.preap_standstill_hold and not any(c.log[-1]["enabled"]), "(b) not on the update the accelerator is released"
  for _ in range(60):
    c.step(gas=0.8, v_kph=5.0)
  assert c.mode == Mode.FULL and any(any(e["enabled"]) for e in c.log[-60:]), "then normal FULL control"


def test_released_while_still_stopped_keeps_holding():
  c = _held()
  for _ in range(5):
    c.step(gas=40.0, v_kph=0.0)
  for _ in range(30):
    c.step(gas=0.8, v_kph=0.0)
  assert c.rig.cs.preap_standstill_hold and c.mode == Mode.FULL and not any(any(e["enabled"]) for e in c.log[-35:])


def test_panda_only_gas_also_blocks_enable():
  lc = PreAPLongController(PedalCommandCounter(), lambda: 2)
  cs = SimpleNamespace(preap_fsm_mode=int(Mode.FULL), real_brake_pressed=False, out=SimpleNamespace(gasPressed=False),
                       preap_panda_gas_pressed=True, preap_gas_clear_updates=5, preap_standstill_hold=False)
  sends = []
  lc._append_pedal_command(sends, cs, 0.4, 1)
  assert not sends[0].dat[4] & 0x80 and getattr(cs, "preap_pedal_guard_blocks", 0) == 0
  assert 650 * 0.0507968128 - 22.85856576 == PANDA_GAS_PRESSED_DBC


def test_a_never_enable_while_braking():
  c = _held()
  c.step(gas=40.0, v_kph=3.0)
  for _ in range(5):
    c.step(v_kph=10.0)
  for _ in range(5):
    c.step(v_kph=10.0, brake=True)
    assert not any(c.log[-1]["enabled"])


def test_c_pulls_out_of_drive_or_with_a_door_open_do_not_pair():
  c = Car()
  for _ in range(5):
    c.step()
  c.rig.base["DI_torque2"] = {"DI_gear": 3}            # DI_torque2.DI_gear 3 = DI_GEAR_N (tesla_ap1_can.dbc:177,768)
  c.step(stalk=PULL)
  c.rig.base["DI_torque2"] = {"DI_gear": 4}            # DI_GEAR_D
  for _ in range(3):
    c.step()
  c.step(stalk=PULL, v_kph=20.0)
  for _ in range(60):
    out = c.step(v_kph=20.0)
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly, "the pull in N did not count as the first of a pair"
  # door open: GTW_carState.DOOR_STATE_FL (tesla_ap1_can.dbc:228,232). A pull with the door open is ignored, so a closed-door pull
  # 100 ms later is only a first pull.
  c = Car()
  for _ in range(5):
    c.step(v_kph=20.0)
  c.rig.base["GTW_carState"] = {"DOOR_STATE_FL": _inv("GTW_carState", "DOOR_STATE_FL", "OPEN")}
  out = c.step(stalk=PULL, v_kph=20.0)
  assert c.mode == Mode.OFF and not out.cruiseState.enabled
  c.rig.base["GTW_carState"] = {"DOOR_STATE_FL": _inv("GTW_carState", "DOOR_STATE_FL", "CLOSED")}
  for _ in range(9):
    c.step(v_kph=20.0)
  c.step(stalk=PULL, v_kph=20.0)
  assert c.mode == Mode.LAT_PENDING


def test_d_no_alert_text_implies_a_brake_hold():
  import pathlib
  import re
  root = pathlib.Path(__file__).resolve().parents[5]
  ev = (root / "openpilot/selfdrive/selfdrived/events.py")
  if not ev.exists():
    return
  src = ev.read_text()
  found = 0
  for name in ("preapSteerOnly", "preapSpeedBlocked", "preapCruiseNotArmed", "preapNotArmed"):
    m = re.search(r"EventName\." + name + r": \{(.*?)\n  \},", src, re.S)
    if m:
      found += 1
      assert not re.search(r"\bhold|\bholding|brake hold|auto.?hold|\bbrak(e|ing)\b", m.group(1), re.I), name
  assert found == 4


def test_e_fresh_brake_at_a_stop_after_engaging_leaves_full():
  c = _held()
  out = c.step(brake=True)                             # safety.h:354-355 drops controls_allowed on this rising edge
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly and out.cruiseState.enabled
  for _ in range(50):
    out = c.step()
  assert c.mode == Mode.LAT_ONLY and not any(any(e["enabled"]) for e in c.log[-50:]), "never back to FULL without a new double pull"
