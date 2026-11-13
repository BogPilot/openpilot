"""Latched EAC_ERROR_TMP_FAULT (4) recovery on AP1 (epas_gate.EpasTmpFaultRecovery).

A one-off code 4 used to end lateral for the rest of the drive: code 4 is a temporary fault, so latActive stayed
false, no ANGLE frame was ever sent again and the EPAS kept the code latched. The recovery sends a short ANGLE
request at the measured wheel while engaged with an AVAILABLE EPAS, bounded in length, count and spacing.
"""
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1 import epas_gate
from opendbc.car.tesla_ap1.actuator_plan import build_actuator_plan
from opendbc.car.tesla_ap1.epas_gate import (ERR4_EPB_FRESH_FRAMES, ERR4_MAX_PROBES, ERR4_PROBE_FRAMES, ERR4_SETTLE_FRAMES,
                                            ERR4_WAIT_FRAMES, MIN_ERR4_PROBE_SPEED, EpasTmpFaultRecovery)
from opendbc.car.tesla_ap1.steer_fault import AP1_RECOVERABLE_TMP_FAULT, steer_fault_temporary
from opendbc.car.tesla_ap1.tests import ap1_epas_tmp_fault_window as W
from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401  (autouse fixture)
from opendbc.car.tesla_ap1.values import CAR, CarControllerParams

S, X = CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX
AV, ACT, INH = "EAC_AVAILABLE", "EAC_ACTIVE", "EAC_INHIBITED"
E4, IDLE = "EAC_ERROR_TMP_FAULT", "EAC_ERROR_IDLE"
STATUS = {0: INH, 1: AV, 2: ACT, 3: "EAC_FAULT", 4: "EAC_SNA"}
ERROR = {0: IDLE, 3: "EAC_ERROR_HANDS_ON", 4: E4, 6: "EAC_ERROR_HIGH_ANGLE_REQ"}


def run(rec, n, engaged=True, lat=False, status=AV, err=E4, hands=0, epb=1, fault=False, yield_=False, v=10.0):
  return [rec.update(engaged, lat, status, err, hands, epb, fault, yield_, v_ego=v) for _ in range(n)]


def started(rec, **kw):
  """Run the settle; the request starts on its last frame."""
  out = run(rec, ERR4_SETTLE_FRAMES, **kw)
  assert out == [False] * (ERR4_SETTLE_FRAMES - 1) + [True], "no request before the settle"
  return rec


# ---- state machine ---------------------------------------------------------------------------------

def test_code4_stays_a_temporary_fault_so_lateral_is_not_resumed_blindly():
  assert AP1_RECOVERABLE_TMP_FAULT == E4
  assert steer_fault_temporary(E4, ap1=True) and steer_fault_temporary(E4, ap1=False)


def test_three_bounded_requests_per_engagement_then_none():
  rec = EpasTmpFaultRecovery()
  out = run(rec, 3 * (ERR4_PROBE_FRAMES + ERR4_WAIT_FRAMES) + 1000)
  on = np.flatnonzero(out)
  runs = np.split(on, np.flatnonzero(np.diff(on) > 1) + 1)
  assert len(runs) == ERR4_MAX_PROBES == 3, "the cap of 3 per engagement"
  assert runs[0][0] == ERR4_SETTLE_FRAMES - 1, "first request only after the settle"
  assert all(len(r) <= ERR4_PROBE_FRAMES <= 30 for r in runs), "<= 0.3 s each at 100 Hz"
  gaps = [b[0] - a[-1] - 1 for a, b in zip(runs, runs[1:])]
  assert all(g >= ERR4_WAIT_FRAMES >= 200 for g in gaps), "2 s spacing between requests"
  assert all(abs(g - (ERR4_WAIT_FRAMES + ERR4_SETTLE_FRAMES)) <= 1 for g in gaps), ("2 s wait, then the settle again", gaps)
  assert rec.state == epas_gate.R_DONE and rec.last_result == "timeout"


def test_a_new_engagement_resets_the_count():
  rec = EpasTmpFaultRecovery()
  run(rec, 3 * (ERR4_PROBE_FRAMES + ERR4_WAIT_FRAMES) + 10)
  assert not any(run(rec, 500))
  run(rec, 1, engaged=False)
  started(rec)
  assert rec.probes == 1
  assert run(rec, 1, engaged=False) == [False] and rec.last_result == "abort:disengaged" and rec.probes == 0


@pytest.mark.parametrize("kw,reason", [(dict(status=INH), "status"), (dict(status="EAC_FAULT"), "eac_fault"),
                                       (dict(status="EAC_SNA"), "status"), (dict(fault=True), "eac_fault"),
                                       (dict(epb=0), "epb_allow"), (dict(epb=2), "epb_allow"),
                                       (dict(hands=2), "hands"), (dict(hands=3), "hands"), (dict(yield_=True), "override"),
                                       (dict(err="EAC_ERROR_HANDS_ON"), "error_code"),
                                       (dict(err="EAC_ERROR_HIGH_ANGLE_RATE_SAFETY"), "error_code"),
                                       (dict(err="EAR_ERROR_MAX_STEER_DELTA"), "error_code")])
def test_any_abort_condition_ends_the_request_on_that_frame_and_never_starts_one(kw, reason):
  rec = EpasTmpFaultRecovery()
  assert not any(run(rec, 50, **kw)), "never starts"
  rec = started(EpasTmpFaultRecovery())
  assert run(rec, 5) == [True] * 5
  assert run(rec, 1, **kw) == [False] and rec.last_result == "abort:" + reason and rec.state == epas_gate.R_WAIT


def test_settle_restarts_on_any_frame_that_is_not_available_code4():
  rec = EpasTmpFaultRecovery()
  assert not any(run(rec, ERR4_SETTLE_FRAMES - 1))
  assert run(rec, 1, status=INH) == [False], "one INHIBITED sample restarts the settle"
  started(rec)


def test_0x214_missing_or_stale_means_no_request_as_before():
  """The panda allows code 4 only with a recent EPB allow of 1, so a missing or stale 0x214 (None) gets no request:
  the car behaves as before this recovery. A seen 0 blocks too."""
  rec = EpasTmpFaultRecovery()
  assert not any(run(rec, 1000, epb=None)), "no 0x214: never a request"
  assert EpasTmpFaultRecovery.abort_reason(AV, E4, 0, None, False, False, 10.0) == "epb_allow"
  assert EpasTmpFaultRecovery.abort_reason(AV, E4, 0, 0, False, False, 10.0) == "epb_allow"
  assert EpasTmpFaultRecovery.abort_reason(AV, E4, 0, 1, False, False, 10.0) is None
  rec = started(EpasTmpFaultRecovery())
  assert run(rec, 1, epb=None) == [False] and rec.last_result == "abort:epb_allow", "0x214 goes stale mid-request"


def _cs(v=10.0, epb=1, epb_age=0, status=AV, err=E4):
  o = SimpleNamespace(steeringAngleDeg=4.0, steeringTorque=0.0, steeringRateDeg=0.0, vEgo=v, gasPressed=False,
                      standstill=v < 0.01, gearShifter=structs.CarState.GearShifter.drive)
  return SimpleNamespace(out=o, steer_warning=err, hands_on_level=0, eac_fault=False, eac_status=status, epb_eac_allow=epb,
                         epb_eac_allow_age=epb_age, acc_state=4, das_control_counters=deque(), msg_stw_actn_req={},
                         cluster_stock={}, stock_steer_counters=[], stock_ap_active=False)


def _drive_controller(frames, **cs_kw):
  """CarController on an engaged AP1 S with latActive off; returns the frames with a tmp-fault request."""
  ctl = make_controller(S)
  on = []
  for t in range(frames):
    CC = structs.CarControl()
    CC.enabled = True
    CC.latActive = False
    ctl.update(CC.as_reader(), _cs(**cs_kw), t * 10_000_000)
    on.append(ctl.ap1_tmp_fault.active)
  return on


def test_controller_uses_the_epb_age_from_carstate():
  assert any(_drive_controller(ERR4_SETTLE_FRAMES + 5, epb_age=ERR4_EPB_FRESH_FRAMES)), "a 0x214 sample within 200 ms"
  assert not any(_drive_controller(ERR4_SETTLE_FRAMES + 5, epb_age=ERR4_EPB_FRESH_FRAMES + 1)), "stale 0x214"
  assert not any(_drive_controller(ERR4_SETTLE_FRAMES + 5, epb_age=None)), "0x214 never seen"


# ---- speed gate -----------------------------------------------------------------------------------

def test_min_probe_speed_is_about_5_mph():
  assert MIN_ERR4_PROBE_SPEED == 2.2


def test_no_request_during_a_creep_from_a_stop():
  """Replay case: engaged, AVAILABLE + code 4, EPB allow 1, creeping at 0.24 m/s. No request (it used to start one)."""
  rec = EpasTmpFaultRecovery()
  assert not any(run(rec, 1000, v=0.24))
  assert EpasTmpFaultRecovery.abort_reason(AV, E4, 0, 1, False, False, 0.24) == "speed"
  assert not any(_drive_controller(ERR4_SETTLE_FRAMES + 50, v=0.24)), "same through the CarController"


@pytest.mark.parametrize("v", [0.0, -0.01, MIN_ERR4_PROBE_SPEED - 0.01, float("nan"), None])
def test_no_request_at_a_standstill_or_below_the_speed_gate(v):
  rec = EpasTmpFaultRecovery()
  assert not any(run(rec, 1000, v=v))


def test_speed_gate_lets_a_request_start_at_the_threshold():
  started(EpasTmpFaultRecovery(), v=MIN_ERR4_PROBE_SPEED)


def test_running_request_ends_the_moment_speed_drops_below_the_gate():
  rec = started(EpasTmpFaultRecovery())
  assert run(rec, 3) == [True] * 3
  assert run(rec, 1, v=MIN_ERR4_PROBE_SPEED - 0.1) == [False], "ends on that frame"
  assert rec.last_result == "abort:speed" and rec.probes == 1
  on = _drive_controller(ERR4_SETTLE_FRAMES + 3)
  assert on[-1], "controller request running at 10 m/s"


def test_starts_only_on_available_code4_while_latactive_is_off_and_engaged():
  assert not any(run(EpasTmpFaultRecovery(), 50, status=ACT))
  assert not any(run(EpasTmpFaultRecovery(), 50, err=IDLE))
  assert not any(run(EpasTmpFaultRecovery(), 50, lat=True))
  assert not any(run(EpasTmpFaultRecovery(), 50, engaged=False))


def test_a_clear_holds_until_latactive_returns_then_frees_the_slot():
  rec = started(EpasTmpFaultRecovery())
  assert run(rec, 2) == [True] * 2
  assert run(rec, 4, status=ACT, err=IDLE) == [True] * 4, "EPAS took the request; keep the measured hold"
  assert run(rec, 1, status=ACT, err=IDLE, lat=True) == [False] and rec.last_result == "cleared"
  assert rec.state == epas_gate.R_IDLE and rec.probes == 1
  assert not any(run(rec, 50, status=ACT, err=IDLE, lat=True))
  started(rec)
  assert rec.probes == 2, "a later code 4 in the same engagement gets the next request after the settle"


def test_a_clear_without_latactive_still_ends_at_the_window():
  rec = started(EpasTmpFaultRecovery())
  out = run(rec, 100, status=ACT, err=IDLE)
  assert sum(out) <= ERR4_PROBE_FRAMES and rec.last_result == "cleared"


# ---- planner ---------------------------------------------------------------------------------------

def _plan(**kw):
  args = dict(frame=0, lat_active=False, hands_on_fault=False, openpilot_longitudinal_control=False, enabled=True, long_active=False,
              measured_angle_deg=5.0, requested_angle_deg=-12.0, last_angle_deg=5.0, v_ego=8.0, accel=0.0, acc_state=4,
              das_counters=deque(), pcm_cancel=False, chassis_das_only=True, epas_error=E4, eac_status=AV, lat_session=False)
  args.update(kw)
  return build_actuator_plan(args.pop("frame"), args.pop("lat_active"), args.pop("hands_on_fault"), args.pop("openpilot_longitudinal_control"),
                             args.pop("enabled"), args.pop("long_active"), args.pop("measured_angle_deg"), args.pop("requested_angle_deg"),
                             args.pop("last_angle_deg"), args.pop("v_ego"), args.pop("accel"), args.pop("acc_state"),
                             args.pop("das_counters"), args.pop("pcm_cancel"), **args)


def test_plan_request_is_angle_at_the_measured_wheel_never_the_planner_angle():
  assert not _plan().steer.enabled, "build6c behaviour without the request: NONE"
  p = _plan(tmp_fault_probe=True)
  assert p.steer.enabled and p.steer.control_type == 1 and p.steer.angle_deg == 5.0


@pytest.mark.parametrize("kw", [dict(hands_on_level=2), dict(eac_fault=True), dict(eac_status=INH), dict(epas_yield=True),
                                dict(driver_yield=True), dict(enabled=False), dict(chassis_das_only=False)])
def test_plan_request_loses_to_every_existing_block(kw):
  p = _plan(tmp_fault_probe=True, **kw)
  assert p.steer is None or not p.steer.enabled, kw


# ---- replay of the recorded window -------------------------------------------------------------------

def _expand(col):
  return [v for n, v in col for _ in range(n)]


def _window():
  cols = {k: _expand(getattr(W, k.upper())) for k in ("enabled", "lat_active", "planned_deg", "v_ego", "gas", "epb_allow",
                                                       "eac_status", "eac_error", "hands", "wheel_deg")}
  assert all(len(v) == W.FRAMES for v in cols.values())
  return [dict(zip(cols, r)) for r in zip(*cols.values())]


def _replay(platform, disable_recovery=False, monkeypatch=None):
  ctl = make_controller(long=False, fingerprint=platform)
  if disable_recovery:
    monkeypatch.setattr(ctl.ap1_tmp_fault, "update", lambda *a, **k: False)
  out = []
  for t, r in enumerate(_window()):
    o = SimpleNamespace(steeringAngleDeg=r["wheel_deg"], steeringTorque=0.0, steeringRateDeg=0.0, vEgo=r["v_ego"],
                        gasPressed=bool(r["gas"]), standstill=False, gearShifter=structs.CarState.GearShifter.drive)
    cs = SimpleNamespace(out=o, steer_warning=ERROR[r["eac_error"]], hands_on_level=r["hands"], eac_fault=False,
                         eac_status=STATUS[r["eac_status"]], epb_eac_allow=r["epb_allow"], epb_eac_allow_age=0, acc_state=4,
                         das_control_counters=deque(), msg_stw_actn_req={}, cluster_stock={},
                         stock_steer_counters=[(t // 2) % 16] if t % 2 == 0 else [], stock_ap_active=False)
    CC = structs.CarControl()
    CC.enabled = bool(r["enabled"])
    CC.latActive = bool(r["lat_active"])
    CC.actuators.steeringAngleDeg = r["planned_deg"]
    _o, can = ctl.update(CC.as_reader(), cs, t * 10_000_000)
    for f in can:
      addr, dat = (f.address, f.dat) if hasattr(f, "address") else (f[0], f[1])
      if addr == 0x488:
        out.append((t, dat[2] >> 6, -(((dat[0] & 0x7F) << 8 | dat[1]) - 16384) * 0.1, r))
  return out


FAULT_ROW = 112   # first row with code 4


@pytest.mark.parametrize("platform", [S, X])
def test_replay_without_the_recovery_never_requests_again(platform, monkeypatch):
  sent = _replay(platform, disable_recovery=True, monkeypatch=monkeypatch)
  assert any(ty == 1 for t, ty, _a, _r in sent if t < FAULT_ROW), "the engage soft-start before the fault"
  assert not any(ty == 1 for t, ty, _a, _r in sent if t > FAULT_ROW + 1), "the lockout: no ANGLE for the rest of the window"


@pytest.mark.parametrize("platform", [S, X])
def test_replay_re_requests_lateral_within_bounds_and_limits(platform):
  sent = _replay(platform)
  angle = [(t, a, r) for t, ty, a, r in sent if ty == 1 and t > FAULT_ROW + 1]
  assert angle, "lateral is requested again after the code 4"
  rows = sorted({t for t, _a, _r in angle})
  runs = np.split(np.array(rows), np.flatnonzero(np.diff(rows) > 2) + 1)
  # Two engagements in the window; the EPAS in the log never answered, so every request times out.
  assert 2 <= len(runs) <= 2 * ERR4_MAX_PROBES, [(r[0], r[-1]) for r in runs]
  assert all(r[-1] - r[0] < ERR4_PROBE_FRAMES for r in runs), "each request <= 0.3 s"
  assert all(len(r) <= ERR4_PROBE_FRAMES // 2 for r in runs), "<= 15 ANGLE frames each on the 50 Hz stock phase"
  for t, a, r in angle:
    assert r["enabled"] and STATUS[r["eac_status"]] in (AV, ACT) and r["hands"] < 2 and r["epb_allow"] == 1, (t, r)
    assert ERROR[r["eac_error"]] in (E4, IDLE)
    assert abs(a - r["wheel_deg"]) <= 0.3, "measured wheel (0.1 deg CAN resolution plus one rate step)"
  # Every ANGLE frame in the window stays inside the existing rate limit and the +/- 20 deg clip.
  prev = None
  for t, ty, a, r in sent:
    if ty == 1:
      assert abs(a - r["wheel_deg"]) <= 20 + 0.1
      if prev is not None and prev[0] == t - 2:
        lim = max(np.interp(r["v_ego"], CarControllerParams.ANGLE_RATE_LIMIT_UP.speed_bp, CarControllerParams.ANGLE_RATE_LIMIT_UP.angle_v),
                  np.interp(r["v_ego"], CarControllerParams.ANGLE_RATE_LIMIT_DOWN.speed_bp, CarControllerParams.ANGLE_RATE_LIMIT_DOWN.angle_v))
        assert abs(a - prev[1]) <= lim + 0.1 + 1e-6, (t, a, prev)
    prev = (t, a)
  # No ANGLE while disengaged, and no planner angle while latActive is off.
  assert not any(ty == 1 and not r["enabled"] for t, ty, a, r in sent)


def test_replay_closed_loop_clear_hands_back_through_the_soft_start():
  """Same controller; the EPAS clears on the first request (as codes 3/6 do on this car), then latActive returns."""
  ctl = make_controller(long=False, fingerprint=S)
  types = []
  status, err, lat = AV, E4, False
  t_clear, first_lat = 10_000, None
  for t in range(400):
    o = SimpleNamespace(steeringAngleDeg=4.0, steeringTorque=0.0, steeringRateDeg=0.0, vEgo=8.0, gasPressed=False,
                        standstill=False, gearShifter=structs.CarState.GearShifter.drive)
    cs = SimpleNamespace(out=o, steer_warning=err, hands_on_level=0, eac_fault=False, eac_status=status, epb_eac_allow=1, epb_eac_allow_age=0, acc_state=4,
                         das_control_counters=deque(), msg_stw_actn_req={}, cluster_stock={},
                         stock_steer_counters=[(t // 2) % 16] if t % 2 == 0 else [], stock_ap_active=False)
    CC = structs.CarControl()
    CC.enabled = True
    CC.latActive = lat
    CC.actuators.steeringAngleDeg = -10.0
    _o, can = ctl.update(CC.as_reader(), cs, t * 10_000_000)
    for f in can:
      addr, dat = (f.address, f.dat) if hasattr(f, "address") else (f[0], f[1])
      if addr == 0x488:
        types.append((t, dat[2] >> 6, -(((dat[0] & 0x7F) << 8 | dat[1]) - 16384) * 0.1))
    if any(ty == 1 for _t, ty, _a in types) and err == E4:
      status, err = ACT, IDLE          # EPAS took the session on the first request frame
      t_clear = t
    if err == IDLE and t > t_clear + 6:
      lat = True                       # steerFaultTemporary dropped, controlsd gives latActive back
      first_lat = first_lat if first_lat is not None else t
  assert not any(ty == 1 for t, ty, _a in types if t < ERR4_SETTLE_FRAMES - 1), "nothing before the settle"
  assert ctl.ap1_tmp_fault.last_result == "cleared" and ctl.ap1_tmp_fault.probes == 1
  soft = [a for t, ty, a in types if first_lat < t < first_lat + 25 and ty == 1]
  assert soft and all(abs(a - 4.0) < 0.2 for a in soft), "measured-wheel soft-start after the hand-back"
  assert any(ty == 1 and a < 4.0 for t, ty, a in types if t > first_lat + 40), "then the planner angle, rate limited"


@pytest.mark.parametrize("platform", [S, X])
def test_code4_onset_while_active_drops_lateral_on_that_frame(platform):
  """Engaged and steering (ACTIVE/IDLE, latActive on). Code 4 appears while ACTIVE: no more ANGLE from that frame,
  and no recovery request while the EPAS stays ACTIVE or INHIBITED with it."""
  ctl = make_controller(long=False, fingerprint=platform)
  sent = []
  for t in range(400):
    onset = t >= 200
    status = ACT if t < 210 else (INH if t < 220 else ACT)   # ACTIVE/4 onset, INHIBITED/4, then ACTIVE/4 again
    err = E4 if onset else IDLE
    o = SimpleNamespace(steeringAngleDeg=2.0, steeringTorque=0.0, steeringRateDeg=0.0, vEgo=8.0, gasPressed=False,
                        standstill=False, gearShifter=structs.CarState.GearShifter.drive)
    cs = SimpleNamespace(out=o, steer_warning=err, hands_on_level=0, eac_fault=False, eac_status=status, epb_eac_allow=1, epb_eac_allow_age=0,
                         acc_state=4, das_control_counters=deque(), msg_stw_actn_req={}, cluster_stock={},
                         stock_steer_counters=[(t // 2) % 16] if t % 2 == 0 else [], stock_ap_active=False)
    CC = structs.CarControl()
    CC.enabled = True
    CC.latActive = t <= 200            # controlsd sees steerFaultTemporary one frame later
    CC.actuators.steeringAngleDeg = -5.0
    _o, can = ctl.update(CC.as_reader(), cs, t * 10_000_000)
    for f in can:
      addr, dat = (f.address, f.dat) if hasattr(f, "address") else (f[0], f[1])
      if addr == 0x488:
        sent.append((t, dat[2] >> 6))
  assert any(ty == 1 for t, ty in sent if t < 200)
  assert not any(ty == 1 for t, ty in sent if t >= 200), "dropped on the onset frame, no request while not AVAILABLE"
  assert ctl.ap1_tmp_fault.probes == 0
