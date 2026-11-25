"""AP1 stalk twist -> LongitudinalPersonality: one Params write after the ring rests, the value shown at once.

Each Params write fsyncs and takes the shared params lock. Writing on every detent with 100 ms read-back
retries queued many writes during one twist, which onroad stalled other processes' blocking writes.
No car, sockets or install.
"""
import ast
import inspect
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from opendbc.car.tesla_ap1 import stalk_follow as SF
from openpilot.common.traffic_mode_hold import TrafficModeHold
from openpilot.selfdrive.controls.lib import phase3_following as F
from openpilot.selfdrive.ui.bogpilot import phase2_driver_alerts as DA

KEY = "LongitudinalPersonality"
AGGRESSIVE, STANDARD, RELAXED = 0, 1, 2

# DTR_Dist_Rq change points (s, raw) of a logged AP1 Model S twist while engaged: down to detent 1 with a 1.6 s rest
# on detent 4 and 1.9 s on detent 1, then quickly back up to detent 7. 0x45 is 10 Hz; the value holds between points.
LOGGED_TWIST = ((0.04, 200), (2.94, 166), (3.14, 133), (3.44, 100), (5.04, 66), (5.15, 33), (5.64, 0),
                (7.54, 33), (7.64, 100), (7.74, 133), (7.85, 166), (7.94, 200))
# the same detents with no rest longer than 0.2 s
QUICK_TWIST = tuple((0.2 * i, raw) for i, (_, raw) in enumerate(LOGGED_TWIST))


class Store:
  """Params stand-in. Writes land `latency` s after they are issued, one at a time (a slow fsync queue)."""

  def __init__(self, stored, latency=0.0, lose=False):
    self.stored = stored
    self.latency = latency
    self.lose = lose
    self.now = 0.0
    self.busy_until = 0.0
    self.queue = []
    self.puts = []

  def tick(self, now):
    self.now = now
    while self.queue and self.queue[0][0] <= now:
      self.stored = self.queue.pop(0)[1]

  def get(self, key, block=False, return_default=False):
    assert key == KEY
    return self.stored

  def put(self, key, value, block=False):
    assert key == KEY
    self.puts.append((round(self.now, 2), value))
    if self.lose:
      return
    done = max(self.now, self.busy_until) + self.latency
    self.busy_until = done
    self.queue.append((done, value))
    self.tick(self.now)


def run(sync, store, changes, end, dt=0.01, screen=None):
  """Drive the sync at 100 Hz like selfdrived (stalk through ap1StalkFollowS) with its 10 Hz params thread."""
  dec, i, t, shown = None, 0, 0.0, []
  current = store.stored
  while t < end:
    store.tick(t)
    if screen and abs(t - screen[0]) < dt / 2:
      store.stored = screen[1]
    while i < len(changes) and changes[i][0] <= t + 1e-9:
      dec = SF.parse_stalk_raw(changes[i][1], dec)
      i += 1
    if dec is not None:
      cs = NS(bogpilot=NS(ap1StalkFollowS=SF.follow_seconds(dec)))
      current = F.ap1_personality_step(sync, cs, current, t)
    if round(t / dt) % 10 == 0:
      current = sync.resolve(store.stored, t)
    shown.append((round(t, 2), current))
    t = round(t + dt, 6)
  return shown


def at(shown, t):
  return next(v for ts, v in shown if ts >= t)


# ---------- write count and timing ----------
def test_settle_time_is_0_3_s():
  assert F.AP1_PERSONALITY_SETTLE_S == pytest.approx(0.3)


def test_quick_twist_writes_once_final_value_after_rest():
  store = Store(STANDARD)
  sync = F.Ap1PersonalitySync(store)
  run(sync, store, QUICK_TWIST, 20.0)
  last = QUICK_TWIST[-1][0]
  assert store.puts == [(pytest.approx(last + F.AP1_PERSONALITY_SETTLE_S, abs=0.02), RELAXED)]
  assert store.stored == RELAXED


def test_quick_twist_back_to_the_stored_value_writes_nothing():
  store = Store(RELAXED)
  sync = F.Ap1PersonalitySync(store)
  shown = run(sync, store, QUICK_TWIST, 20.0)
  assert store.puts == []
  assert at(shown, 0.5) == STANDARD          # shown while moving (crossed detent 5), not written
  assert at(shown, 19.0) == RELAXED


def test_logged_twist_writes_once_per_rest_never_while_moving():
  store = Store(RELAXED)
  sync = F.Ap1PersonalitySync(store)
  run(sync, store, LOGGED_TWIST, 25.0)
  # one write per rest of at least the settle time: 1.6 s on detent 4 (standard, crossed at detent 5), 0.49 s on
  # detent 2 (aggressive, crossed at detent 3), none during the 1.9 s on detent 1, one when the ring stops at detent 7.
  # The old sync issued 6 (instant disk) to 22 (0.3 s per write) puts here.
  assert [v for _, v in store.puts] == [STANDARD, AGGRESSIVE, RELAXED]
  change_times = [t for t, _ in LOGGED_TWIST]
  for t_put, _ in store.puts:
    last_change = max(t for t in change_times if t <= t_put)
    assert t_put - last_change >= F.AP1_PERSONALITY_SETTLE_S - 0.01
  assert store.puts[0][0] == pytest.approx(3.44 + F.AP1_PERSONALITY_SETTLE_S, abs=0.02)
  assert store.puts[1][0] == pytest.approx(5.15 + F.AP1_PERSONALITY_SETTLE_S, abs=0.02)
  assert store.puts[2][0] == pytest.approx(7.94 + F.AP1_PERSONALITY_SETTLE_S, abs=0.02)


@pytest.mark.parametrize("latency", [0.3, 6.0])
def test_slow_disk_does_not_add_writes(latency):
  store = Store(STANDARD, latency=latency)
  sync = F.Ap1PersonalitySync(store)
  run(sync, store, QUICK_TWIST, 40.0)
  assert [v for _, v in store.puts] == [RELAXED]
  assert store.stored == RELAXED
  store = Store(RELAXED, latency=latency)
  sync = F.Ap1PersonalitySync(store)
  run(sync, store, LOGGED_TWIST, 40.0)
  assert [v for _, v in store.puts] == [STANDARD, AGGRESSIVE, RELAXED]
  assert store.stored == RELAXED


def test_lost_write_is_retried_once_only():
  store = Store(STANDARD, lose=True)
  sync = F.Ap1PersonalitySync(store)
  run(sync, store, QUICK_TWIST, 90.0)
  last = QUICK_TWIST[-1][0] + F.AP1_PERSONALITY_SETTLE_S
  assert store.puts == [(pytest.approx(last, abs=0.02), RELAXED),
                        (pytest.approx(last + F.AP1_PERSONALITY_VERIFY_S, abs=0.02), RELAXED)]


def test_crossed_detent_rule_kept():
  store = Store(RELAXED)
  sync = F.Ap1PersonalitySync(store)
  shown = run(sync, store, ((0.0, 200), (0.1, 33)), 10.0)   # 7 -> 2 in one frame: last named detent crossed is 3
  assert store.puts == [(pytest.approx(0.1 + F.AP1_PERSONALITY_SETTLE_S, abs=0.02), AGGRESSIVE)]
  assert at(shown, 0.11) == AGGRESSIVE


def test_detents_1_and_2_never_write():
  store = Store(STANDARD)
  sync = F.Ap1PersonalitySync(store)
  changes = tuple((0.5 * i, (0, 33)[i % 2]) for i in range(60))
  shown = run(sync, store, changes, 40.0)
  assert store.puts == []
  assert {v for _, v in shown} == {STANDARD}


def test_no_write_while_resting_on_traffic_then_once_after_leaving():
  store = Store(RELAXED)
  sync = F.Ap1PersonalitySync(store)
  run(sync, store, ((0.0, 200), (0.1, 0)), 30.0)          # crossed 5 and 3 on the way to detent 1
  assert store.puts == []
  run(sync, store, ((0.0, 33),), 5.0)                      # leaves detent 1: rests on detent 2
  assert [v for _, v in store.puts] == [AGGRESSIVE]


def test_startup_on_the_stored_detent_writes_nothing():
  for raw, stored in ((66, AGGRESSIVE), (133, STANDARD), (200, RELAXED), (33, STANDARD), (166, RELAXED)):
    store = Store(stored)
    sync = F.Ap1PersonalitySync(store)
    run(sync, store, ((0.0, raw),), 10.0)
    assert store.puts == []


# ---------- shown at once, hold, screen change ----------
def test_stalk_value_is_shown_in_the_same_step():
  store = Store(RELAXED)
  sync = F.Ap1PersonalitySync(store)
  dec = SF.parse_stalk_raw(200, None)
  cs = NS(bogpilot=NS(ap1StalkFollowS=SF.follow_seconds(dec)))
  assert F.ap1_personality_step(sync, cs, RELAXED, 0.0) == RELAXED
  dec = SF.parse_stalk_raw(66, dec)
  cs = NS(bogpilot=NS(ap1StalkFollowS=SF.follow_seconds(dec)))
  assert F.ap1_personality_step(sync, cs, RELAXED, 0.1) == AGGRESSIVE
  assert store.puts == []


def test_stale_stored_value_does_not_revert_within_hold():
  store = Store(RELAXED, latency=3.0)
  sync = F.Ap1PersonalitySync(store)
  shown = run(sync, store, ((0.0, 200), (0.1, 66)), 12.0)
  assert store.puts == [(pytest.approx(0.1 + F.AP1_PERSONALITY_SETTLE_S, abs=0.02), AGGRESSIVE)]
  assert all(v == AGGRESSIVE for t, v in shown if t >= 0.1)   # write lands 3 s later; nothing flips back meanwhile


def test_hold_ends_after_five_seconds_when_the_write_never_lands():
  store = Store(RELAXED, lose=True)
  sync = F.Ap1PersonalitySync(store)
  shown = run(sync, store, ((0.0, 200), (0.1, 66)), 9.0)
  written = 0.1 + F.AP1_PERSONALITY_SETTLE_S
  assert at(shown, written + F.AP1_PERSONALITY_HOLD_S - 0.2) == AGGRESSIVE
  assert at(shown, written + F.AP1_PERSONALITY_HOLD_S + 0.2) == RELAXED


def test_screen_change_during_the_rest_wins_and_drops_the_stalk_write():
  store = Store(STANDARD)
  sync = F.Ap1PersonalitySync(store)
  shown = run(sync, store, ((0.0, 133), (0.1, 66)), 10.0, screen=(0.3, RELAXED))   # inside the 0.3 s rest
  assert store.puts == []
  assert at(shown, 0.2) == AGGRESSIVE
  assert at(shown, 0.5) == RELAXED and shown[-1][1] == RELAXED


def test_screen_change_after_the_write_is_not_fought():
  store = Store(STANDARD)
  sync = F.Ap1PersonalitySync(store)
  shown = run(sync, store, ((0.0, 133), (0.1, 66)), 30.0, screen=(2.0, RELAXED))
  assert [v for _, v in store.puts] == [AGGRESSIVE]
  assert shown[-1][1] == RELAXED and store.stored == RELAXED


# ---------- seconds -> decision ----------
def test_decision_from_seconds_inverts_follow_seconds():
  dec = None
  for raw in (0, 33, 66, 100, 133, 166, 200):
    dec = SF.parse_stalk_raw(raw, dec)
    back = SF.decision_from_seconds(SF.follow_seconds(dec))
    assert (back.detent, back.profile, back.traffic) == (dec.detent, dec.profile, dec.traffic)
    assert SF.ap1_stalk_commands(back) == SF.ap1_stalk_commands(dec)
  for v in (0.0, None, float("nan"), 1.3, -1.25, "x"):
    assert SF.decision_from_seconds(v) is None


def test_twist_following_off_publishes_zero_and_writes_nothing():
  store = Store(STANDARD)
  sync = F.Ap1PersonalitySync(store)
  for t in range(300):
    assert F.ap1_personality_step(sync, NS(bogpilot=NS(ap1StalkFollowS=0.0)), STANDARD, t * 0.01) == STANDARD
  assert store.puts == [] and sync.shown is None


# ---------- which cars ----------
def cp(fp, long=True, brand="tesla_ap1"):
  return NS(brand=brand, carFingerprint=fp, openpilotLongitudinalControl=long)


@pytest.fixture
def adopted(monkeypatch):
  monkeypatch.setattr(F, "personality_adopted", lambda store=None: True)


@pytest.mark.usefixtures("adopted")
def test_gate_model_s_pre_ap_and_model_x_with_long_only():
  p = Store(STANDARD)
  assert isinstance(F.ap1_personality_sync_for(cp("TESLA_AP1_MODELS"), p), F.Ap1PersonalitySync)
  assert isinstance(F.ap1_personality_sync_for(cp("TESLA_AP1_MODELS", long=False), p), F.Ap1PersonalitySync)
  assert isinstance(F.ap1_personality_sync_for(cp("TESLA_PREAP_MODELS"), p), F.Ap1PersonalitySync)
  assert isinstance(F.ap1_personality_sync_for(cp("TESLA_AP1_MODELX", long=True), p), F.Ap1PersonalitySync)
  assert F.ap1_personality_sync_for(cp("TESLA_AP1_MODELX", long=False), p) is None
  assert F.ap1_personality_sync_for(cp("TESLA_AP1_MODELS", brand="tesla"), p) is None


def test_gate_needs_personality_adoption(monkeypatch):
  monkeypatch.setattr(F, "personality_adopted", lambda store=None: False)
  assert F.ap1_personality_sync_for(cp("TESLA_AP1_MODELS"), Store(STANDARD)) is None


@pytest.mark.usefixtures("adopted")
def test_model_x_with_long_writes_like_the_s():
  store = Store(STANDARD)
  sync = F.ap1_personality_sync_for(cp("TESLA_AP1_MODELX", long=True), store)
  run(sync, store, QUICK_TWIST, 20.0)
  assert [v for _, v in store.puts] == [RELAXED]


# ---------- Traffic Mode stays on card ----------
def test_card_traffic_flag_only_and_no_params():
  traffic = F.Ap1StalkTraffic()
  hold = TrafficModeHold()
  assert traffic.update(None) is None
  dec, seen = None, []
  for raw in (200, 133, 66, 33, 0, 0, 33, 200):
    dec = SF.parse_stalk_raw(raw, dec)
    flag = traffic.update(dec)
    hold.apply_stalk(flag)
    seen.append((flag, hold.enabled))
  assert seen == [(False, False)] * 4 + [(True, True)] * 2 + [(False, False)] * 2
  assert not hasattr(traffic, "params")


def test_traffic_mode_alert_from_the_stalk_still_fires():
  traffic = F.Ap1StalkTraffic()
  hold = TrafficModeHold()
  alerts = DA.DriverAlerts()
  dec, out, t = None, [], 0.0
  for raw in (200, 200, 33, 0, 0, 33, 33):
    dec = SF.parse_stalk_raw(raw, dec)
    hold.apply_stalk(traffic.update(dec))
    enabled = hold.update_button(False, t)
    out += [a for a, _ in alerts.update(DA.DriverInput(t, warning_ok=True, traffic_mode=enabled))]
    t += 0.1
  assert out == ["TrafficModeOn", "TrafficModeOff"]


ROOT = Path(__file__).resolve().parents[2]  # openpilot/selfdrive


def test_card_no_longer_writes_the_personality():
  src = (ROOT / "car/card.py").read_text()
  assert "Ap1PersonalitySync" not in src and "Ap1StalkTraffic()" in src
  assert "put(\"LongitudinalPersonality\"" not in src and "put('LongitudinalPersonality'" not in src


def test_card_state_update_feeds_traffic_hold_from_the_stalk():
  """Run the real card.state_update body with stand-ins: the stalk detent reaches TrafficModeHold, Params untouched."""
  tree = ast.parse((ROOT / "car/card.py").read_text())
  car_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Car")
  method = next(n for n in car_class.body if isinstance(n, ast.FunctionDef) and n.name == "state_update")
  method.returns = None
  src = ast.unparse(method)
  assert "self.ap1_stalk_traffic.update(" in src and "self.traffic_mode_hold.apply_stalk(stalk_traffic)" in src
  i = src.index("self.ap1_stalk_traffic.update(")
  assert "twist_follow_on(self.CI.CS)" in src[i - 200:i]


# ---------- selfdrived wiring ----------
def test_selfdrived_applies_the_stalk_before_events_and_publish():
  from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD
  step = inspect.getsource(SelfdriveD.step)
  i = step.index("ap1_personality_step(")
  assert i < step.index("self.update_events(CS)") < step.index("self.publish_selfdriveState(CS)")
  init = inspect.getsource(SelfdriveD.__init__)
  assert "ap1_personality_sync_for(self.CP, self.params)" in init
  thread = inspect.getsource(SelfdriveD.params_thread)
  assert "sync.resolve(stored, time.monotonic())" in thread


class OneLoop:
  def __init__(self):
    self.n = 0

  def is_set(self):
    self.n += 1
    return self.n > 1


def params_thread_once(sd, monkeypatch):
  from openpilot.selfdrive.selfdrived import selfdrived as SD
  monkeypatch.setattr(SD.time, "sleep", lambda s: None)
  SD.SelfdriveD.params_thread(sd, OneLoop())
  return sd.personality


def test_selfdrived_params_thread_hold_and_screen_change(monkeypatch):
  from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD
  store = Store(RELAXED, lose=True)
  store.get_bool = lambda key, block=False: False
  sd = object.__new__(SelfdriveD)
  sd.params = store
  sd.CP = NS(openpilotLongitudinalControl=True)
  sd.ap1_personality = F.Ap1PersonalitySync(store)
  sd.personality = RELAXED
  dec = SF.parse_stalk_raw(66, SF.parse_stalk_raw(200, None))
  sd.ap1_personality.update(SF.parse_stalk_raw(200, None), time.monotonic())
  sd.ap1_personality.update(dec, time.monotonic())
  sd.personality = sd.ap1_personality.shown
  assert params_thread_once(sd, monkeypatch) == AGGRESSIVE      # stale stored relaxed does not revert it
  store.stored = STANDARD                                       # screen change
  assert params_thread_once(sd, monkeypatch) == STANDARD
  assert sd.ap1_personality.shown is None
  sd.ap1_personality = None                                     # other cars: stock read
  store.stored = RELAXED
  assert params_thread_once(sd, monkeypatch) == RELAXED
