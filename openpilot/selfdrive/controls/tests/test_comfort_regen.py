"""Comfort regen v2 (RegenComfortBrake): the add-only comfort layer after the stock plan. Pure Python, no MPC."""
import math
import random
from types import SimpleNamespace as NS

import pytest

import openpilot.selfdrive.controls.lib.comfort_regen as cr
from openpilot.selfdrive.controls.lib.comfort_regen import ComfortRegen, settle_decel, comfort_regen_enabled

DT = 0.05
TF = 1.75


def lead(d, v, radar=True, present=True, tid=7):
  return NS(dRel=d, vLead=v, radar=radar, present=present, radarTrackId=tid)


def step(c, stock, v, ld, engaged=True, gas=False, standstill=False, tf=TF):
  return c.update(stock, engaged=engaged, gas_pressed=gas, standstill=standstill, v_ego=v, lead=ld, t_follow=tf)


def test_stop_distance_matches_mpc():
  src = open(cr.__file__.replace("comfort_regen.py", "longitudinal_mpc_lib/long_mpc.py")).read()
  assert "STOP_DISTANCE = 6.0" in src and cr.STOP_DISTANCE == 6.0


def test_settle_decel_formula():
  # 300 ft (91.4 m) to a lead 10 mph (4.47 m/s) slower at 45 mph: settle at stock gap TF*v_lead + 6
  v, vl, d = 20.12, 20.12 - 4.47, 91.44
  want = 4.47 ** 2 / (2 * (d - (TF * vl + 6.0)))
  assert settle_decel(v, vl, d, TF) == pytest.approx(want)
  assert settle_decel(v, v + 1, d, TF) == 0.0                    # opening: nothing
  assert settle_decel(v, vl, TF * vl + 5.0, TF) == math.inf      # already inside the stock gap: no room


def test_gentle_request_for_far_slower_radar_lead_and_jerk_limited_onset():
  c = ComfortRegen(enabled=True, dt=DT)
  v, vl, d = 20.12, 15.65, 91.44
  outs = [step(c, 0.0, v, lead(d, vl)) for _ in range(60)]
  a_req = settle_decel(v, vl, d, TF)
  assert 0.05 < a_req < 0.9
  assert min(outs) == pytest.approx(-a_req * cr.MARGIN, abs=1e-6)
  steps = [outs[0] - 0.0] + [b - a for a, b in zip(outs, outs[1:], strict=False)]
  assert min(steps) >= -cr.JERK_ON * DT - 1e-9                   # onset never faster than JERK_ON


def test_camera_only_or_absent_lead_does_nothing():
  c = ComfortRegen(enabled=True, dt=DT)
  for _ in range(40):
    assert step(c, 0.3, 20.0, lead(90, 15, radar=False)) == 0.3
    assert step(c, 0.3, 20.0, None) == 0.3
    assert step(c, 0.3, 20.0, lead(90, 15, present=False)) == 0.3


def test_not_closing_or_lead_faster_does_nothing():
  c = ComfortRegen(enabled=True, dt=DT)
  for _ in range(40):
    assert step(c, 0.2, 20.0, lead(60, 19.8)) == 0.2     # 0.2 m/s closing, below CLOSING_MIN
    assert step(c, 0.2, 20.0, lead(60, 22.0)) == 0.2


def test_hands_off_to_stock_when_more_than_gentle_is_needed():
  c = ComfortRegen(enabled=True, dt=DT)
  # stopped car 120 ft at 45 mph needs ~4 m/s^2: far beyond gentle, layer must not act
  for _ in range(40):
    assert step(c, -0.5, 20.12, lead(36.6, 0.0)) == -0.5


def test_releases_when_lead_accelerates_and_never_jumps():
  c = ComfortRegen(enabled=True, dt=DT)
  v, d, vl = 20.0, 90.0, 15.0
  for _ in range(60):
    step(c, 0.0, v, lead(d, vl))
  assert c.request is not None and c.request < -0.2
  prev = c.request
  outs = []
  for i in range(200):
    vl = min(25.0, vl + 2.0 * DT)        # lead pulls away at 2 m/s^2
    o = step(c, 0.0, v, lead(d, vl))
    outs.append(o)
    assert o - prev <= cr.JERK_OFF * DT + 1e-9     # release is jerk limited
    prev = o
  assert outs[-1] == 0.0 and c.request is None


def test_brake_tap_is_filtered():
  # A 1.5 s lead brake tap at -3 m/s^2: the 1 s filter keeps the comfort request gentle and bounded
  c = ComfortRegen(enabled=True, dt=DT)
  v, d, vl = 17.9, 50.0, 14.3
  outs = []
  for i in range(200):
    t = i * DT
    if 1.0 <= t < 2.5:
      vl -= 3.0 * DT
    d += (vl - v) * DT
    outs.append(step(c, 0.0, v, lead(d, vl)))
  assert min(outs) >= -cr.A_GENTLE_ON - 1e-9


def test_inactive_when_disengaged_gas_or_standstill_and_resets():
  for kw in ({"engaged": False}, {"gas": True}, {"standstill": True}):
    c = ComfortRegen(enabled=True, dt=DT)
    for _ in range(40):
      step(c, 0.0, 20.0, lead(90, 15))
    assert c.request is not None
    assert step(c, 0.4, 20.0, lead(90, 15), **kw) == 0.4
    assert c.request is None


def test_disabled_is_identity():
  c = ComfortRegen(enabled=False, dt=DT)
  for s in (-3.0, -0.2, 0.0, 1.5):
    assert step(c, s, 20.0, lead(90, 15)) == s


def test_never_more_than_gentle_and_never_above_stock_fuzz():
  rng = random.Random(7)
  c = ComfortRegen(enabled=True, dt=DT)
  for _ in range(20000):
    stock = rng.uniform(-3.5, 2.0)
    v = rng.uniform(0.0, 35.0)
    ld = lead(rng.uniform(1, 200), rng.uniform(0, 35), radar=rng.random() < 0.8, tid=rng.choice([1, 1, 1, 2]))
    out = step(c, stock, v, ld, engaged=rng.random() < 0.97, gas=rng.random() < 0.02)
    assert out <= stock + 1e-12
    # the layer can only pull the output below stock down to -A_GENTLE_ON (it never adds a hard stop)
    assert out >= min(stock, -cr.A_GENTLE_ON) - 1e-9


def test_strong_stock_braking_is_passed_through_immediately():
  c = ComfortRegen(enabled=True, dt=DT)
  for _ in range(60):
    step(c, 0.0, 20.0, lead(90, 15))
  assert step(c, -3.5, 20.0, lead(90, 15)) == -3.5   # stock bypasses the comfort jerk limit


def test_setting_mapping(monkeypatch):
  import opendbc.car.tesla_ap1.regen_brake as rb
  monkeypatch.setattr(rb, "_read_regen_comfort_file", lambda: "")
  assert comfort_regen_enabled(NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True))
  assert comfort_regen_enabled(NS(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True))
  assert not comfort_regen_enabled(NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=False))
  assert not comfort_regen_enabled(NS(carFingerprint="TESLA_MODEL_3", openpilotLongitudinalControl=True))
  assert comfort_regen_enabled(NS(carFingerprint="TESLA_AP1_MODELX", openpilotLongitudinalControl=True))
  assert not comfort_regen_enabled(NS(carFingerprint="TESLA_AP1_MODELX", openpilotLongitudinalControl=False))
  monkeypatch.setattr(rb, "_read_regen_comfort_file", lambda: "0")
  assert not comfort_regen_enabled(NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True))
  # v1 gap widening is retired in both states
  for txt in ("", "0", "1"):
    assert rb.ap1_comfort_brake("TESLA_AP1_MODELS", stored=txt) == rb.STOCK_COMFORT_BRAKE == 2.5
