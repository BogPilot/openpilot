"""Latched EAC_ERROR_HIGH_ANGLE_RATE_REQ (7) recovery on AP1 (epas_gate.EpasTmpFaultRecovery, code 7 rules).

Recorded on the bench comma (combined build 3): after a 130 ms card stall the EPAS latched INHIBITED/7, then AVAILABLE/7,
and lateral stayed off for the rest of the drive through five re-engagements: code 7 is a temporary fault, so latActive
stayed false, nothing sent ANGLE, and only a new ANGLE request clears the latch. The code 4 recovery now covers code 7 too,
with the same bounds and a tighter status rule: only while the EPAS reports AVAILABLE with code 7.
"""
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1 import epas_gate
from opendbc.car.tesla_ap1.epas_gate import (ERR4_MAX_PROBES, ERR4_PROBE_FRAMES, ERR4_SETTLE_FRAMES, ERR4_WAIT_FRAMES,
                                            EpasTmpFaultRecovery)
from opendbc.car.tesla_ap1.steer_fault import AP1_RECOVERABLE_LATCHED, AP1_RECOVERABLE_RATE_REQ, steer_fault_temporary
from opendbc.car.tesla_ap1.tests import ap1_steer_stall_window as W
from opendbc.car.tesla_ap1.tests.ap1_harness import decode, make_controller
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401  (autouse fixture)
from opendbc.car.tesla_ap1.values import CAR

S, X = CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX
AV, ACT, INH = "EAC_AVAILABLE", "EAC_ACTIVE", "EAC_INHIBITED"
E4, E7, IDLE = "EAC_ERROR_TMP_FAULT", "EAC_ERROR_HIGH_ANGLE_RATE_REQ", "EAC_ERROR_IDLE"
STATUS = {0: INH, 1: AV, 2: ACT, 3: "EAC_FAULT", 4: "SNA"}
ERROR = {0: IDLE, 3: "EAC_ERROR_HANDS_ON", 4: E4, 6: "EAC_ERROR_HIGH_ANGLE_REQ", 7: E7, 9: "EAC_ERROR_HIGH_ANGLE_RATE_SAFETY"}


def run(rec, n, engaged=True, lat=False, status=AV, err=E7, hands=0, epb=1, fault=False, yield_=False, v=14.4):
  return [rec.update(engaged, lat, status, err, hands, epb, fault, yield_, v_ego=v) for _ in range(n)]


def started(rec, **kw):
  out = run(rec, ERR4_SETTLE_FRAMES, **kw)
  assert out == [False] * (ERR4_SETTLE_FRAMES - 1) + [True], "no request before the settle"
  return rec


# ---- state machine ---------------------------------------------------------------------------------

def test_code7_stays_a_temporary_fault():
  assert AP1_RECOVERABLE_RATE_REQ == E7 and E7 in AP1_RECOVERABLE_LATCHED and E4 in AP1_RECOVERABLE_LATCHED
  assert steer_fault_temporary(E7, ap1=True) and steer_fault_temporary(E7, ap1=False)


def test_code7_same_bounds_as_code4():
  rec = EpasTmpFaultRecovery()
  out = run(rec, 3 * (ERR4_PROBE_FRAMES + ERR4_WAIT_FRAMES) + 1000)
  on = np.flatnonzero(out)
  runs = np.split(on, np.flatnonzero(np.diff(on) > 1) + 1)
  assert len(runs) == ERR4_MAX_PROBES == 3
  assert runs[0][0] == ERR4_SETTLE_FRAMES - 1
  assert all(len(r) <= ERR4_PROBE_FRAMES <= 30 for r in runs)
  gaps = [b[0] - a[-1] - 1 for a, b in zip(runs, runs[1:])]
  assert all(g >= ERR4_WAIT_FRAMES >= 200 for g in gaps)
  assert rec.state == epas_gate.R_DONE


@pytest.mark.parametrize("status", [ACT, INH, "EAC_FAULT", "SNA"])
def test_code7_never_starts_or_runs_outside_available(status):
  rec = EpasTmpFaultRecovery()
  assert not any(run(rec, 500, status=status)), "never starts"
  rec = started(EpasTmpFaultRecovery())
  assert run(rec, 3) == [True] * 3
  assert run(rec, 1, status=status) == [False]
  assert rec.last_result in ("abort:status", "abort:eac_fault")


def test_code7_active_aborts_but_code4_active_keeps_running():
  rec = started(EpasTmpFaultRecovery())
  assert run(rec, 1, status=ACT) == [False] and rec.last_result == "abort:status"
  rec = started(EpasTmpFaultRecovery(), err=E4)
  assert run(rec, 1, status=ACT, err=E4) == [True], "code 4 rule unchanged"
  assert run(rec, 1, status=ACT, err=E7) == [False] and rec.last_result == "abort:status"


@pytest.mark.parametrize("kw,reason", [(dict(epb=0), "epb_allow"), (dict(epb=None), "epb_allow"), (dict(hands=2), "hands"),
                                       (dict(yield_=True), "override"), (dict(v=0.3), "speed"), (dict(fault=True), "eac_fault"),
                                       (dict(err="EAC_ERROR_HIGH_ANGLE_RATE_SAFETY"), "error_code"),
                                       (dict(err="EAC_ERROR_HIGH_ANGLE_SAFETY"), "error_code")])
def test_code7_every_code4_abort_applies(kw, reason):
  rec = EpasTmpFaultRecovery()
  assert not any(run(rec, 100, **kw))
  rec = started(EpasTmpFaultRecovery())
  assert run(rec, 1, **kw) == [False] and rec.last_result == "abort:" + reason


def test_code7_clear_hands_back():
  rec = started(EpasTmpFaultRecovery())
  assert run(rec, 4) == [True] * 4
  assert run(rec, 2, err=IDLE) == [True] * 2, "AVAILABLE/IDLE: hold until latActive is back"
  assert run(rec, 1, status=ACT, err=IDLE, lat=True) == [False] and rec.last_result == "cleared"


# ---- controller: replay of the recorded latch -----------------------------------------------------

def _cs(row, err_override=None):
  _t, stock, st, er, hands, wheel, v, _en, _lat, _plan = row
  o = SimpleNamespace(steeringAngleDeg=wheel, steeringTorque=0.0, steeringRateDeg=0.0, vEgo=v, vEgoRaw=v, gasPressed=False,
                      standstill=False, gearShifter=structs.CarState.GearShifter.drive)
  return SimpleNamespace(out=o, steer_warning=ERROR[er if err_override is None else err_override], hands_on_level=hands,
                         eac_fault=False, eac_status=STATUS[st], epb_eac_allow=1, epb_eac_allow_age=0, acc_state=4,
                         das_control_counters=deque(), msg_stw_actn_req={}, cluster_stock={}, stock_steer_counters=list(stock),
                         stock_ap_active=False)


def _replay(platform, err_override=None):
  """Recorded card steps from the code 7 latch on (INHIBITED/7, then AVAILABLE/7; engaged, latActive off, EPB allow 1),
  extended with the last row so the 0.5 s settle can finish. Returns [(t_us, 0x488 values or None, row)]."""
  rows = [r for r in W.ROWS if r[0] >= 825_441]
  last = rows[-1]
  rows += [(last[0] + 10_000 * (i + 1), (((last[1][-1] if last[1] else 0) + i // 2 + 1) % 16,) if i % 2 == 0 else ()) +
           last[2:] for i in range(150)]
  ctl = make_controller(long=platform == S, fingerprint=platform)
  out = []
  for row in rows:
    t_us, _s, _st, _er, _h, _w, _v, en, lat, plan = row
    CC = structs.CarControl()
    CC.enabled = bool(en)
    CC.latActive = bool(lat)
    CC.actuators.steeringAngleDeg = plan
    _o, can = ctl.update(CC.as_reader(), _cs(row, err_override), 1_000_000_000 + t_us * 1000)
    steer = [decode(m[0], m[1])[1] for m in can if m[0] == 0x488]
    out.append((t_us, steer[0] if steer else None, row, ctl.ap1_tmp_fault.active))
  return ctl, out


@pytest.mark.parametrize("platform", [S, X])
def test_recorded_code7_latch_gets_one_bounded_measured_wheel_request(platform):
  ctl, out = _replay(platform)
  angle = [(t, s, r) for t, s, r, _a in out if s is not None and int(s["DAS_steeringControlType"]) == 1]
  assert angle, "the recovery sends ANGLE into the latched AVAILABLE/7 EPAS"
  assert all(r[2] == 1 and r[3] == 7 for _t, _s, r in angle), "only while the recorded EPAS says AVAILABLE/7"
  assert all(abs(s["DAS_steeringAngleRequest"] + r[5]) <= 0.11 for _t, s, r in angle), "at the measured wheel"
  active = [a for *_x, a in out]
  first = active.index(True)
  assert sum(active) <= ERR4_PROBE_FRAMES and all(active[first:first + sum(active)]), "one request, at most 0.3 s"
  assert ctl.ap1_tmp_fault.probes == 1 and ctl.ap1_tmp_fault.last_result == "timeout"
  assert out[first][2][0] - 869_903 >= (ERR4_SETTLE_FRAMES - 1) * 8_000, "only after the AVAILABLE/7 settle"


@pytest.mark.parametrize("platform", [S, X])
def test_recorded_latch_with_a_code_outside_the_recovery_sends_no_angle(platform):
  _ctl, out = _replay(platform, err_override=9)   # HIGH_ANGLE_RATE_SAFETY: still never recovered
  assert not any(s is not None and int(s["DAS_steeringControlType"]) == 1 for _t, s, _r, _a in out)
