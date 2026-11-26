"""AP1 0x488 restart after a card stall (steer_resync.Ap1SteerResync, wired in CarController).

Recorded on the bench comma: card made no step for 130 ms, the panda forwarded the stock DAS 0x488 after 100 ms, and the
old controller resumed at once from a stale stock counter. Its first frame repeated the counter the panda had just
forwarded, the next frames went out 5 ms apart, and the EPAS latched INHIBITED + code 7 40 ms later.
"""
from collections import deque
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1.steer_counter import COUNTER_LEAD, Ap1SteerCounterSync
from opendbc.car.tesla_ap1.steer_resync import (LIVE_SPACING_NS, RESYNC_LIVE_FRAMES, STALL_NS, STOCK_GONE_FRAMES,
                                                Ap1SteerResync)
from opendbc.car.tesla_ap1.tests import ap1_steer_stall_window as W
from opendbc.car.tesla_ap1.tests.ap1_harness import decode, make_controller
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401  (autouse fixture)
from opendbc.car.tesla_ap1.values import CAR

S, X = CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX
STATUS = {0: "EAC_INHIBITED", 1: "EAC_AVAILABLE", 2: "EAC_ACTIVE", 3: "EAC_FAULT", 4: "SNA"}
ERROR = {0: "EAC_ERROR_IDLE", 3: "EAC_ERROR_HANDS_ON", 4: "EAC_ERROR_TMP_FAULT", 6: "EAC_ERROR_HIGH_ANGLE_REQ",
         7: "EAC_ERROR_HIGH_ANGLE_RATE_REQ"}
MS = 1_000_000


# ---- state machine ---------------------------------------------------------------------------------

def _live(r, frame, t_ns, steps, start_ctr, sent=True):
  """Normal 100 Hz loop with stock 0x488 every other step; openpilot sends on stock steps."""
  ctr = start_ctr
  out = []
  for i in range(steps):
    stock = [ctr] if i % 2 == 0 else []
    hold = r.update(stock, frame, t_ns)
    out.append(hold)
    if stock:
      ctr = (ctr + 1) % 16
      if sent and not hold:
        r.sent(frame, t_ns)
    frame += 1
    t_ns += 10 * MS
  return frame, t_ns, ctr, out


def test_normal_loop_never_holds():
  r = Ap1SteerResync()
  _f, _t, _c, out = _live(r, 0, 0, 2000, 0)
  assert not any(out) and r.stalls == 0


def test_one_lost_stock_frame_is_not_a_stall():
  r = Ap1SteerResync()
  f, t, c, _ = _live(r, 0, 0, 100, 0)
  assert not r.update([(c + 1) % 16], f, t + 10 * MS), "a jump of 2 (one stock frame lost on CAN)"
  assert r.stalls == 0


def test_clock_gap_while_owned_holds_until_three_live_stock_frames():
  r = Ap1SteerResync()
  f, t, c, _ = _live(r, 0, 0, 100, 0)
  t += STALL_NS + 10 * MS                    # card asleep, nothing drained (stock lost to the backlog elsewhere)
  assert r.update([], f, t) and r.last_reason == "clock"
  holds = []
  for i in range(2 * RESYNC_LIVE_FRAMES):
    f += 1
    t += 10 * MS
    stock = [c] if i % 2 == 0 else []
    if stock:
      c = (c + 1) % 16
    holds.append(r.update(stock, f, t))
  assert holds == [True] * (2 * RESYNC_LIVE_FRAMES - 2) + [False, False]
  assert r.stalls == 1


def test_backlog_burst_holds_and_backlog_steps_do_not_count_as_live():
  r = Ap1SteerResync()
  f, t, c, _ = _live(r, 0, 0, 100, 0)
  burst = [(c + i) % 16 for i in range(5)]
  assert r.update(burst, f, t + 10 * MS) and r.last_reason in ("clock", "stock_burst")
  c = (burst[-1] + 1) % 16
  # The rest of the backlog drains 3 ms apart: never live.
  for i in range(4):
    assert r.update([c], f + 1 + i, t + 10 * MS + (i + 1) * 3 * MS)
    c = (c + 1) % 16
  assert LIVE_SPACING_NS > 3 * MS


def test_burst_without_clock_also_detected_for_fixed_time_replays():
  r = Ap1SteerResync()
  f, _t, c, _ = _live(r, 0, 0, 20, 0)
  # now_nanos frozen (replay / fixed-time test): only the stock sign is used.
  assert r.update([(c + i) % 16 for i in range(3)], f, 0)
  assert r.last_reason == "stock_burst"


def test_no_hold_when_openpilot_did_not_own_the_stream():
  r = Ap1SteerResync()
  f, t, c, _ = _live(r, 0, 0, 50, 0, sent=False)
  assert not r.update([(c + i) % 16 for i in range(6)], f, t + 200 * MS), "disengaged: stock already flows, nothing to restart"


def test_missing_stock_stream_resumes_on_the_stale_cadence():
  r = Ap1SteerResync()
  f, t, _c, _ = _live(r, 0, 0, 50, 0)
  t += 150 * MS
  holds = [r.update([], f + i, t + i * 10 * MS) for i in range(STOCK_GONE_FRAMES)]  # the stall step counts as one
  assert all(holds[:-1]) and holds[-1] is False and r.resumed


def test_counter_sync_forget_gives_stock_plus_lead():
  s = Ap1SteerCounterSync()
  s.commit(4, 100)
  assert s.update([9], 101).counter == (9 + COUNTER_LEAD) % 16
  s.forget()
  assert s.update([9], 102).counter == (9 + COUNTER_LEAD) % 16 and s.last_counter is None


# ---- controller replay of the recorded stall ------------------------------------------------------

def _cs(row, status=None, err=None):
  t_us, stock, st, er, hands, wheel, v, _en, _lat, _plan = row
  o = SimpleNamespace(steeringAngleDeg=wheel, steeringTorque=0.0, steeringRateDeg=0.0, vEgo=v, vEgoRaw=v, gasPressed=False,
                      standstill=False, gearShifter=structs.CarState.GearShifter.drive)
  return SimpleNamespace(out=o, steer_warning=ERROR[er if err is None else err],
                         hands_on_level=hands, eac_fault=False, eac_status=STATUS[st if status is None else status],
                         epb_eac_allow=1, epb_eac_allow_age=0, acc_state=4, das_control_counters=deque(),
                         msg_stw_actn_req={}, cluster_stock={}, stock_steer_counters=list(stock), stock_ap_active=False)


def _replay(platform=S, hold_epas=False, fixed_clock=False):
  """Run the controller over the recorded card steps. hold_epas keeps the EPAS at its pre-stall state (ACTIVE / IDLE), the
  counterfactual where the restart works. Returns (t_us, 0x488 values or None, row) per step."""
  ctl = make_controller(long=platform == S, fingerprint=platform)
  out = []
  for i, row in enumerate(W.ROWS):
    t_us, _stock, _st, _er, _h, _w, _v, en, lat, plan = row
    CC = structs.CarControl()
    CC.enabled = bool(en)
    CC.latActive = True if hold_epas else bool(lat)
    CC.actuators.steeringAngleDeg = plan
    cs = _cs(row, status=2 if hold_epas else None, err=0 if hold_epas else None)
    _o, can = ctl.update(CC.as_reader(), cs, 0 if fixed_clock else 1_000_000_000 + t_us * 1000)
    steer = [decode(m[0], m[1])[1] for m in can if m[0] == 0x488]
    out.append((t_us, steer[0] if steer else None, row))
  return ctl, out


STALL_START_US, STALL_END_US = 628_107, 745_217


@pytest.mark.parametrize("platform", [S, X])
@pytest.mark.parametrize("fixed_clock", [False, True])
def test_recorded_stall_no_clash_no_burst(platform, fixed_clock):
  ctl, out = _replay(platform, fixed_clock=fixed_clock)
  assert ctl.ap1_steer_resync.stalls >= 1
  pre = [(t, s) for t, s, _r in out if t <= STALL_START_US and s is not None]
  assert pre, "openpilot owned 0x488 before the stall"
  post = [(t, s, r) for t, s, r in out if t >= STALL_END_US]
  sends = [(t, s, r) for t, s, r in post if s is not None]
  assert sends and sends[0][0] > STALL_END_US, "nothing on the first step after the stall (the old code sent here)"
  # Stock counters the panda forwarded between the stall and openpilot's first frame (all of them: we were silent).
  t_first = sends[0][0]
  forwarded = [c for t, _s, r in post if t <= t_first for c in r[1]]
  latest_stock = forwarded[-1]
  ctr0 = int(sends[0][1]["DAS_steeringControlCounter"])
  assert ctr0 == (latest_stock + COUNTER_LEAD) % 16, "fresh counter from the live stock stream"
  recent = set(forwarded[-6:])
  assert ctr0 not in recent, "never a counter the panda just forwarded from the stock DAS"
  # No catch-up burst: the frames after the restart are spaced like the stock stream.
  gaps = [(b[0] - a[0]) / 1000 for a, b in zip(sends, sends[1:]) if b[0] < t_first + 300_000]
  assert all(g >= 8.0 for g in gaps), gaps
  # Counters only move forward after the restart.
  ctrs = [int(s["DAS_steeringControlCounter"]) for t, s, _r in sends if t < 900_000]
  assert all((b - a) % 16 in (1, 2, 3) for a, b in zip(ctrs, ctrs[1:])), ctrs


@pytest.mark.parametrize("platform", [S, X])
def test_recorded_stall_restart_ramps_from_the_measured_wheel(platform):
  """Counterfactual EPAS (stays ACTIVE / IDLE): the restart is ANGLE at the measured wheel (soft-start), then the planner."""
  _ctl, out = _replay(platform, hold_epas=True)
  sends = [(t, s, r) for t, s, r in out if t >= STALL_END_US and s is not None]
  first = sends[:6]
  assert all(int(s["DAS_steeringControlType"]) == 1 for _t, s, _r in first)
  # 0x488 carries the angle with the opposite sign of carState.steeringAngleDeg (teslacan / carstate).
  assert all(abs(s["DAS_steeringAngleRequest"] + r[5]) <= 0.11 for _t, s, r in first), \
    [(s["DAS_steeringAngleRequest"], r[5]) for _t, s, r in first]


def test_old_behaviour_reference():
  """The recording itself: card's first post-stall step drained 5 stock counters at once (what trips the detector)."""
  rows = {r[0]: r for r in W.ROWS}
  assert rows[STALL_END_US][1] == (3, 4, 5, 6, 7)
  assert STALL_END_US - STALL_START_US > 100_000, "longer than the panda's 100 ms substitute window"
