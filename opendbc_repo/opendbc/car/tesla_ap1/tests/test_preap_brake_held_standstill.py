"""Brake held at the second pull: follow NAP. A double pull (< 400 ms) with the brake held at a standstill enters FULL with the
standstill hold (pedal ENABLE=0, raw <= 500, target held at 0) until the accelerator; releasing the brake does not end the hold.
NAP @ e99f4dc75: preap/engagement.py:101-103 (brake drops speed control only on a rising edge), :131-142 (no brake term on the second
pull). Stricter than NAP: brakePressed stays visible to openpilot (NAP preap/carstate.py:134-135 hides it), the hold never sends
ENABLE=1 (NAP preap/carcontroller.py:123-128 holds with ENABLE=1), and the panda still refuses ENABLE=1 under a brake
(tesla_preap.h:254, unchanged). Moving with the brake held is still refused."""
import math
from types import SimpleNamespace as NS

import pytest

from opendbc.car.tesla_ap1.preap import engagement as eng
from opendbc.car.tesla_ap1.preap.engagement import STANDSTILL_SPEED_MS, Mode, PreAPEngagement
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_engagement import step
from opendbc.car.tesla_ap1.tests.test_preap_standstill_hold import RAW_LIMIT_DISABLED, Car

TIP_UP = 4       # STW_ACTN_RQ.SpdCtrlLvr_Stat 4 = accel tip (values.py BUTTONS accelCruise)


def _no_drive(frames):
  assert frames, "pedal frames were sent"
  assert not any(any(e["enabled"]) for e in frames), "no pedal ENABLE=1 while holding"
  assert all(r <= RAW_LIMIT_DISABLED for e in frames for r in e["raw"]), "hold frames stay ENABLE=0 with raw <= 500"


def _brake_held_double_pull(v_kph=0.0):
  c = Car()
  for _ in range(20):
    c.step(brake=True, v_kph=v_kph)
  c.step(stalk=PULL, brake=True, v_kph=v_kph)
  for _ in range(9):
    c.step(brake=True, v_kph=v_kph)
  c.step(stalk=PULL, brake=True, v_kph=v_kph)              # second pull 100 ms after the first, brake still held
  for _ in range(100):
    out = c.step(brake=True, v_kph=v_kph)
  return c, out


def _held_with_brake():
  c, out = _brake_held_double_pull()
  assert c.mode == Mode.FULL and c.rig.cs.preap_standstill_hold and c.op and not out.bogpilot.preapLatOnly
  return c, out


# (1)
def test_brake_held_double_pull_at_standstill_is_full_with_the_hold():
  c, out = _held_with_brake()
  assert out.brakePressed, "brakePressed stays visible to openpilot"
  _no_drive(c.log[30:])


# (2)
def test_hold_survives_brake_release():
  c, _ = _held_with_brake()
  n = len(c.log)
  for _ in range(150):
    out = c.step(brake=False)
  assert not out.brakePressed and c.mode == Mode.FULL and c.rig.cs.preap_standstill_hold and c.op
  _no_drive(c.log[n:])


# (3)
def test_up_tip_while_held_raises_the_set_speed_but_does_not_drive_off():
  from openpilot.selfdrive.car.cruise import VCruiseHelper
  vc = VCruiseHelper(NS(pcmCruise=False))
  c, _ = _held_with_brake()
  for _ in range(20):
    c.step(brake=False)
  vc.v_cruise_kph = 10.0
  n = len(c.log)
  for stalk in (TIP_UP, 0):                                # press then release: openpilot changes the set on the release
    out = c.step(stalk=stalk)
    vc.update_v_cruise(out, enabled=c.op, is_metric=True)
  assert vc.v_cruise_kph == 11.0, "the up tip raised the set speed"
  for _ in range(150):
    out = c.step()
  assert c.mode == Mode.FULL and c.rig.cs.preap_standstill_hold and not out.bogpilot.preapLatOnly
  _no_drive(c.log[n:])


# (4)
def test_gas_press_ends_the_hold_normally():
  c, _ = _held_with_brake()
  for _ in range(20):
    c.step(brake=False)
  for _ in range(10):
    c.step(gas=40.0, v_kph=3.0)
    assert not any(c.log[-1]["enabled"]), "ENABLE=0 while the accelerator is pressed"
  c.step(gas=0.8, v_kph=5.0)                               # released while moving: the hold ends
  assert not c.rig.cs.preap_standstill_hold and not any(c.log[-1]["enabled"])
  for _ in range(60):
    c.step(gas=0.8, v_kph=5.0)
  assert c.mode == Mode.FULL and any(any(e["enabled"]) for e in c.log[-60:]), "then normal FULL control"


# (5)
def test_fresh_brake_press_after_engaging_demotes_to_steering_only():
  c, _ = _held_with_brake()
  for _ in range(20):
    c.step(brake=False)
  n = len(c.log)
  for _ in range(20):
    out = c.step(brake=True)
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly and c.op and out.cruiseState.enabled
  _no_drive(c.log[n:])


# (6)
def test_brake_held_double_pull_while_moving_is_still_refused():
  c, out = _brake_held_double_pull(v_kph=20.0)
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly and not c.rig.cs.preap_standstill_hold
  assert not any(any(e["enabled"]) for e in c.log)


# FSM edges of the same rule
def test_fsm_brake_pressed_on_the_second_pull_itself_is_refused():
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0)
  d = step(e, 200, pull=True, op=True, v_ego=0.0, brake=True)   # a press, not a held brake
  assert d.mode == Mode.LAT_ONLY and not d.standstill_hold


def test_fsm_held_brake_hold_drops_to_steering_only_when_the_car_moves_with_it():
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0, brake=True)
  d = step(e, 200, pull=True, op=True, v_ego=0.0, brake=True)
  assert d.mode == Mode.FULL and d.standstill_hold and d.capture_edge and d.capture_from_stop   # t1401: set on the pull
  d = step(e, 300, op=True, v_ego=STANDSTILL_SPEED_MS, brake=True)
  assert d.mode == Mode.LAT_ONLY and d.lat_only


def test_fsm_unknown_speed_with_the_brake_held_is_refused():
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=None, brake=True)
  assert step(e, 200, pull=True, op=True, v_ego=None, brake=True).mode == Mode.LAT_ONLY


def test_no_toggle_for_the_brake_held_rule():
  assert not [n for n in dir(eng) if n.startswith("PREAP_") and "BRAKE" in n]


# ---- openpilot side: selfdrived/preap_brake.py PreapHeldBrake, the only exemption from the stock brake rule ----
PREAP_CP = NS(carFingerprint="TESLA_PREAP_MODELS")
OTHER_TESLA_CPS = [NS(carFingerprint=f) for f in ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_MODEL_S_RAVEN", "TESLA_MODEL_X")]
FULL = int(Mode.FULL)


def _cs(brake, mode=0, v=0.0, lat_only=False, standstill=False, v_raw=None):
  return NS(brakePressed=brake, standstill=standstill, vEgo=v, vEgoRaw=v if v_raw is None else v_raw,
            bogpilot=NS(preapLatOnly=lat_only, preapFsmMode=mode))


def _stock(cs, prev):
  return bool(cs.brakePressed and (not prev.brakePressed or not cs.standstill))


def _run(cp, frames):
  """Feed (CS) frames to PreapHeldBrake and evaluate selfdrived's brake rule like selfdrived does; returns [(held, disengages)]."""
  from openpilot.selfdrive.selfdrived.preap_brake import PreapHeldBrake, brake_disengages
  hb, prev, out = PreapHeldBrake(cp), _cs(False), []
  for cs in frames:
    held = hb.update(cs)
    out.append((held, brake_disengages(cs, prev, held)))
    prev = cs
  return out


class RigWithSelfdrived(Car):
  """The car-state rig plus selfdrived's PreapHeldBrake and brake rule fed every frame."""
  def __init__(self):
    from openpilot.selfdrive.selfdrived.preap_brake import PreapHeldBrake
    super().__init__()
    self.hb, self.prev, self.sd = PreapHeldBrake(PREAP_CP), None, []

  def step(self, **kw):
    from openpilot.selfdrive.selfdrived.preap_brake import brake_disengages
    out = super().step(**kw)
    held = self.hb.update(out)
    self.sd.append((held, self.prev is not None and brake_disengages(out, self.prev, held), int(out.bogpilot.preapFsmMode)))
    self.prev = out
    return out


def test_held_brake_survives_500_frames_with_enable_0_throughout():
  c = RigWithSelfdrived()
  for _ in range(20):
    c.step(brake=True)
  c.step(stalk=PULL, brake=True)
  for _ in range(9):
    c.step(brake=True)
  c.step(stalk=PULL, brake=True)
  entry = len(c.sd) - 1
  assert c.mode == Mode.FULL and c.rig.cs.preap_standstill_hold
  n = len(c.log)
  for _ in range(500):
    c.step(brake=True)
  held = c.sd[entry:]
  assert len(held) == 501 and all(h and not d and m == FULL for h, d, m in held), "exempt on every frame, never disengaged"
  assert c.mode == Mode.FULL and c.op
  _no_drive(c.log[n:])


def test_release_then_repress_is_not_exempt():
  frames = [_cs(True)] * 5 + [_cs(True, FULL)] * 50 + [_cs(False, FULL)] * 5 + [_cs(True, FULL)] * 20
  r = _run(PREAP_CP, frames)
  assert all(h and not d for h, d in r[5:55])
  assert not any(h for h, _ in r[55:]), "a release ends it for the session"
  assert r[60][1] and all(d for _, d in r[60:]), "the re-press disengages as stock (car side: also steering only on that edge)"
  # integrated: the car side drops speed control on the re-press, and the exemption does not come back
  c = RigWithSelfdrived()
  for _ in range(20):
    c.step(brake=True)
  c.step(stalk=PULL, brake=True)
  for _ in range(9):
    c.step(brake=True)
  c.step(stalk=PULL, brake=True)
  for _ in range(10):
    c.step()
  for _ in range(20):
    out = c.step(brake=True)
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly and not any(h for h, _, _ in c.sd[-30:])


def test_creeping_to_0_1_ms_with_the_brake_held_is_not_exempt():
  frames = [_cs(True)] * 5 + [_cs(True, FULL)] * 20 + [_cs(True, FULL, v=STANDSTILL_SPEED_MS)] + [_cs(True, FULL)] * 10
  r = _run(PREAP_CP, frames)
  assert all(h for h, _ in r[5:25])
  assert all(d and not h for h, d in r[25:]), "motion >= 0.1 m/s disengages as stock, and back at 0 it stays ended"
  # integrated: the car side drops speed control as soon as the car moves with the brake held
  c = RigWithSelfdrived()
  for _ in range(20):
    c.step(brake=True)
  c.step(stalk=PULL, brake=True)
  for _ in range(9):
    c.step(brake=True)
  c.step(stalk=PULL, brake=True)
  vs = []
  for _ in range(30):
    out = c.step(brake=True, v_kph=STANDSTILL_SPEED_MS * 3.6 * 2)
    vs.append(out.vEgo)
  moving = [i for i, v in enumerate(vs) if v >= STANDSTILL_SPEED_MS]
  assert moving and not any(h for h, _, _ in c.sd[-30:][moving[0]:]), "not exempt from the first frame at >= 0.1 m/s on"
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly
  assert not any(any(e["enabled"]) for e in c.log)


def test_fsm_full_entered_on_the_press_frame_is_not_exempt():
  r = _run(PREAP_CP, [_cs(False)] * 5 + [_cs(True, FULL)] * 10)
  assert not any(h for h, _ in r) and r[5][1]


def test_ap1_and_other_tesla_cars_are_never_exempt_and_keep_the_stock_rule():
  import itertools
  grid = [_cs(b, m, v, standstill=st) for b, m, v, st in itertools.product((False, True), (0, FULL), (0.0, 0.05, 1.0), (False, True))]
  for cp in OTHER_TESLA_CPS:
    for prev, cs in itertools.product(grid, grid):
      r = _run(cp, [prev, cs])
      assert not r[0][0] and not r[1][0], cp.carFingerprint
      assert r[1][1] == _stock(cs, prev), (cp.carFingerprint, prev, cs)
  # and a long held-brake FULL-looking sequence on AP1 is still disengaged on every frame, as stock
  r = _run(NS(carFingerprint="TESLA_AP1_MODELS"), [_cs(True)] * 5 + [_cs(True, FULL)] * 100)
  assert all(d and not h for h, d in r[1:])


def test_only_the_pre_ap_car_state_writes_the_fsm_mode():
  import pathlib
  root = pathlib.Path(eng.__file__).parents[2]                    # opendbc/car
  writers = sorted(str(f.relative_to(root)) for f in root.rglob("*.py")
                   if "/tests/" not in str(f) and "preapFsmMode =" in f.read_text(errors="ignore"))
  assert writers == ["tesla_ap1/preap/carstate.py"], writers


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", ["v", "v_raw"])
def test_non_finite_speed_ends_the_exemption_and_disengages_as_stock(bad, field):
  frames = [_cs(True)] * 5 + [_cs(True, FULL)] * 20 + [_cs(True, FULL, **{field: bad})] + [_cs(True, FULL)] * 10
  r = _run(PREAP_CP, frames)
  assert all(h for h, _ in r[5:25])
  assert all(d and not h for h, d in r[25:]), "a non-finite speed ends it for the session and the brake disengages as stock"


def test_raw_speed_crossing_0_1_ends_the_exemption_while_filtered_speed_is_still_below():
  lag = _cs(True, FULL, v=0.05, v_raw=STANDSTILL_SPEED_MS)
  assert lag.vEgo < STANDSTILL_SPEED_MS <= lag.vEgoRaw
  frames = [_cs(True)] * 5 + [_cs(True, FULL)] * 20 + [lag] + [_cs(True, FULL, v=0.05, v_raw=0.0)] * 10
  r = _run(PREAP_CP, frames)
  assert all(h for h, _ in r[5:25])
  assert all(d and not h for h, d in r[25:])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_fsm_non_finite_speed_is_unknown_speed_fail_closed(bad):
  # FULL entered under a held brake at a standstill: a non-finite speed with the brake still held drops to steering only
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0, brake=True)
  assert step(e, 200, pull=True, op=True, v_ego=0.0, brake=True).mode == Mode.FULL
  d = step(e, 300, op=True, v_ego=bad, brake=True)
  assert d.mode == Mode.LAT_ONLY and d.lat_only
  # a brake-held double pull with a non-finite speed is refused, never a hold
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=bad, brake=True)
  d = step(e, 200, pull=True, op=True, v_ego=bad, brake=True)
  assert d.mode == Mode.LAT_ONLY and not d.standstill_hold
  # without the brake a non-finite speed at the second pull is refused too (no hold on an unknown speed)
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=bad)
  d = step(e, 200, pull=True, op=True, v_ego=bad)
  assert d.mode == Mode.LAT_ONLY and not d.standstill_hold


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_fsm_gas_release_at_unknown_speed_keeps_the_hold(bad):
  # engagement.py:238: the hold ends on the accelerator release only at a known speed >= 0.1 m/s; a non-finite speed is unknown
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0, brake=True)
  assert step(e, 200, pull=True, op=True, v_ego=0.0, brake=True).standstill_hold
  step(e, 300, op=True, v_ego=0.0)                                  # brake released: still held
  for t in range(400, 600, 10):
    d = step(e, t, op=True, v_ego=0.0, gas=True)
  assert d.mode == Mode.FULL and d.standstill_hold
  d = step(e, 600, op=True, v_ego=bad, gas=False)                    # accelerator released at an unknown speed
  assert d.mode == Mode.FULL and d.standstill_hold and not d.capture_edge, "the hold is kept"
  for t in range(610, 800, 10):
    d = step(e, t, op=True, v_ego=0.0)
  assert d.mode == Mode.FULL and d.standstill_hold, "still held; only a new press and a release while moving ends it"
  step(e, 800, op=True, v_ego=0.0, gas=True)
  d = step(e, 810, op=True, v_ego=1.0)
  assert not d.standstill_hold and not d.capture_edge   # t1401: the release keeps the set taken on the pull


def test_rig_raw_speed_from_esp_b_ends_the_exemption_before_the_filtered_speed():
  # Real car-state parsing: ESP_B (0x155) ESP_vehicleSpeed -> vEgoRaw, then the speed filter -> vEgo (preap/carstate.py:125-126).
  # A step to 0.5 km/h (0.139 m/s, the panda's moving bound) shows in vEgoRaw at once while vEgo still lags below 0.1 m/s.
  c = RigWithSelfdrived()
  for _ in range(20):
    c.step(brake=True)
  c.step(stalk=PULL, brake=True)
  for _ in range(9):
    c.step(brake=True)
  c.step(stalk=PULL, brake=True)
  for _ in range(20):
    out = c.step(brake=True)
  assert c.sd[-1][0] and out.vEgoRaw == 0.0
  out = c.step(brake=True, v_kph=0.5)
  assert out.vEgoRaw >= STANDSTILL_SPEED_MS > out.vEgo, (out.vEgoRaw, out.vEgo)
  held, disengages, mode = c.sd[-1]
  assert mode == FULL, "the car side still reads the filtered speed as stopped on this frame"
  assert not held and disengages, "the helper ends on vEgoRaw alone and the brake disengages as stock"
  assert not any(any(e["enabled"]) for e in c.log)
