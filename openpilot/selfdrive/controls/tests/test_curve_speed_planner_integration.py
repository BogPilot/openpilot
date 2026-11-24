"""Curve speed planner inside the real LongitudinalPlanner (native capnp + MPC): Eco vs Eco+, map-only curves, action
delay wiring, exit without a hold. Synthetic closed loop, not a log replay and not a drive."""
import pytest

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib import ap1_curve_speed as ACS
from openpilot.selfdrive.controls.lib.curve_speed_planner import A_MIN, RELEASE_JERK
from openpilot.selfdrive.controls.lib.phase3_long_accel import PROFILE_ACK, ADVANCED_ACK
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, ap1_cp, drive, msgs, planner, road
from openpilot.selfdrive.controls.tests.test_phase3_long_accel import Store

K, START, LENGTH = 0.02, 300.0, 150.0
LAT = 2.0
V_CURVE = (LAT / K) ** 0.5


def profiled(decel):
  p = planner()
  p.long_accel.store = Store(**{PROFILE_ACK: 1, 'LongitudinalTune': 1, 'AccelerationProfile': 0,
                               'DecelerationProfile': decel, 'HumanAcceleration': 0})
  return p


@pytest.mark.parametrize("decel", [0, 1, 2])
def test_curve_braking_identical_under_every_deceleration_profile(decel):
  ref, log = [], []
  drive(profiled(1), 25.0, 30.0, road(START, K, LENGTH), 40.0, log=ref)
  drive(profiled(decel), 25.0, 30.0, road(START, K, LENGTH), 40.0, log=log)
  # the curve request is the same on every frame; the car reaches the curve speed by the curve
  assert [r[4] for r in log] == pytest.approx([r[4] for r in ref], abs=1e-9)
  assert min(r[4] for r in log) >= A_MIN - 1e-9 and min(r[4] for r in log) < -0.5
  v_entry = next(v for s, v, *_ in log if s >= START)
  assert v_entry <= V_CURVE + 0.5


def test_eco_plus_floor_applies_to_cruise_only_not_curves():
  """Set speed dropped far below the speed (no curve): Eco+ floors the cruise candidate at ACCEL_MIN/4, Eco at /2."""
  mins = {}
  for decel in (1, 2):
    p = profiled(decel)
    out = []
    for _ in range(200):
      p.update(SM(msgs(25.0, 10.0)))
      out.append(float(p.output_a_target))
    mins[decel] = min(out)
  assert mins[2] == pytest.approx(-0.875, abs=1e-3)
  assert mins[1] < -0.875 - 0.2


def test_tesla_smoothing_is_profile_independent():
  """Ap1AccelSmoother / Ap1JerkLimit are built from the platform alone; nothing in them reads a profile."""
  import inspect
  from opendbc.car.tesla_ap1 import carcontroller, long_smooth
  src = inspect.getsource(long_smooth) + inspect.getsource(carcontroller)
  assert "DecelerationProfile" not in src and "AccelerationProfile" not in src


def test_map_only_curve_brakes_in_the_planner(monkeypatch):
  p = planner()
  cs = p.curve_speed
  state = {"s": 0.0}
  monkeypatch.setattr(cs, "_map_on", lambda: True)
  monkeypatch.setattr(cs, "_map_curve_speed", lambda: 12.0 if 0.0 <= 450.0 - state["s"] <= 380.0 else 0.0)
  v, s, a = 25.0, 0.0, 0.0
  rows = []
  for _ in range(int(30 / DT_MDL)):
    state["s"] = s
    p.update(SM(msgs(v, 30.0, s, road(), a_ego=a)))   # vision: straight road
    a = float(p.output_a_target)
    v = max(0.0, v + a * DT_MDL)
    s += v * DT_MDL
    rows.append((s, v, cs.a_curve, cs.controlling, cs.map_cap))
  assert any(r[4] > 0 for r in rows) and any(r[3] for r in rows)
  assert min(r[2] for r in rows) < -0.3
  assert next(v for s, v, *_ in rows if s >= 445.0) <= 12.0 + 1.0


def test_action_delay_comes_from_the_planner(monkeypatch):
  seen = []
  p = planner()
  real = p.curve_speed.planner.update

  def spy(v_ego, dt, a_lat, action_delay=0.35, **kw):
    seen.append(action_delay)
    return real(v_ego, dt, a_lat, action_delay, **kw)
  monkeypatch.setattr(p.curve_speed.planner, "update", spy)
  p.update(SM(msgs(20.0, 30.0, 0.0, road(100.0, K, 50.0))))
  assert seen[-1] == pytest.approx(0.35)                      # AP1 CarParams
  p.long_accel.store = Store(**{ADVANCED_ACK: 1, 'AdvancedLongitudinalTune': 1, 'LongitudinalActuatorDelay': 0.6})
  p.update(SM(msgs(20.0, 30.0, 0.0, road(100.0, K, 50.0))))
  assert seen[-1] == pytest.approx(0.6)                       # the Actuator Delay override


def test_cruise_speed_not_lowered_and_exit_has_no_hold():
  log = []
  drive(planner(), 25.0, 30.0, road(START, K, LENGTH), 45.0, log=log)
  end = START + LENGTH
  # the curve candidate is back to 0 within the release ramp after the curve ends, then cruise accelerates again
  rows_after = [r for r in log if r[0] >= end]
  t_release = next(i for i, r in enumerate(rows_after) if r[4] == 0.0) * DT_MDL
  assert t_release <= abs(A_MIN) / RELEASE_JERK + 0.1
  t_accel = next(i for i, r in enumerate(rows_after) if r[2] > 0.05) * DT_MDL
  assert t_accel < 2.0
  # display set speed follows the curve speed while controlling and returns to the set speed after
  assert min(r[3] for r in log) <= V_CURVE + 0.5
  assert rows_after[int(2.0 / DT_MDL)][3] == pytest.approx(30.0)


def test_no_hold_constant_removed():
  assert not hasattr(ACS, "CSC_HOLD_S")
  assert not hasattr(ACS.Ap1CurveSpeed(ap1_cp(), DT_MDL, store=None), "_hold_s")


def test_cruise_cap_eases_accel_off_and_never_touches_braking():
  from openpilot.selfdrive.controls.lib.curve_speed_planner import ONSET_JERK
  cs = planner().curve_speed
  cs._dt_s = DT_MDL
  assert cs.cap_cruise_accel(1.0) == 1.0                      # no curve: untouched
  cs.cruise_ceiling = 0.1                                     # a curve node comes into view
  out = [cs.cap_cruise_accel(1.0) for _ in range(40)]
  steps = [a - b for a, b in zip([1.0] + out[:-1], out, strict=True)]
  assert all(s <= ONSET_JERK * DT_MDL + 1e-9 for s in steps)  # eased off, never stepped down
  assert out[-1] == pytest.approx(0.1) and all(o >= 0.1 - 1e-9 for o in out)
  assert cs.cap_cruise_accel(0.05) == 0.05                    # below the ceiling: untouched
  cs.cruise_ceiling = 0.0
  assert cs.cap_cruise_accel(-0.8) == -0.8                    # braking never touched


def test_cruise_rise_limit_unit():
  cs = planner().curve_speed
  cs._dt_s = DT_MDL
  cs.curve_ahead = True                                       # a curve slower than the set speed is in the envelope
  assert cs.cap_cruise_accel(2.0, 0.4) == pytest.approx(0.4 + RELEASE_JERK * DT_MDL)
  assert cs.cap_cruise_accel(-0.5, 0.4) == -0.5                                   # braking never touched
  assert cs.cap_cruise_accel(2.0, -0.6) == pytest.approx(RELEASE_JERK * DT_MDL)   # from braking: rises from 0
  cs.curve_ahead = False
  cs.cap_cruise_accel(2.0, 0.4)                               # curve left the envelope: keeps ramping until caught up
  assert cs._rising
  assert cs.cap_cruise_accel(0.3, 0.4) == 0.3 and not cs._rising
  assert cs.cap_cruise_accel(2.0, 0.3) == 2.0                 # caught up: no limit any more


def test_candidate_switch_in_a_curve_ramps_instead_of_stepping():
  """In a curve below its curve speed, Experimental mode (e2e asking a gentle 0.4 m/s^2) turns off while the cruise
  candidate sits at its accel limit. The plan ramps at CurveReleaseJerk instead of stepping to the cruise accel, and
  keeps ramping on the straight after the curve (no hold)."""
  k, v, v_set = 0.006, 11.7, 25.0          # curve speed sqrt(2 / 0.006) = 18.3 m/s, well above the car
  p = planner()
  outs = []
  for i in range(int(3.0 / DT_MDL)):
    p.update(SM(msgs(v, v_set, 20.0 * i * DT_MDL, road(0.0, k, 1e9), experimental=True, e2e_accel=0.3)))
  prev = float(p.output_a_target)
  assert prev == pytest.approx(0.3, abs=0.1)
  assert p.curve_speed.curve_ahead
  for i in range(int(2.0 / DT_MDL)):
    p.update(SM(msgs(v, v_set, 100.0 + 20.0 * i * DT_MDL, road(0.0, k, 1e9))))
    out = float(p.output_a_target)
    assert out - prev <= RELEASE_JERK * DT_MDL + 1e-6
    outs.append(out)
    prev = out
  for i in range(int(3.0 / DT_MDL)):
    p.update(SM(msgs(v, v_set, 300.0 + 20.0 * i * DT_MDL, road(0.0, 0.0, 1e9))))
    out = float(p.output_a_target)
    assert out - prev <= max(RELEASE_JERK, 1.6) * DT_MDL + 1e-6   # no step once the curve clears either
    outs.append(out)
    prev = out
  assert outs[-1] > outs[int(2.0 / DT_MDL) - 1] + 0.3              # still accelerating out of the curve: not held
