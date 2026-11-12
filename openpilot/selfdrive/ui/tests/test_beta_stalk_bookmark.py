"""BETA-ONLY stalk bookmark: pure-Python unit tests (no build, no sockets, no live car).

Rule: docs/tesla/DIVERGENCES_beta_stalk_bookmark.md (fire at the 3rd release, extra taps never cancel, lockout,
0.30 s disengage guard, separate 0.30 s own-TX drop + own TX resets a counting train (lockout kept), explicit allow-list).
Synthetic carState at 100 Hz (1 kHz where ms resolution matters); selfdriveState as a per-sample flag.
"""
import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

HERE = Path(__file__).resolve()
MOD_PATH = HERE.parents[1] / 'beta_stalk_bookmark.py'
REPO = HERE.parents[4]
HOLD_PATH = REPO / 'opendbc_repo' / 'opendbc' / 'car' / 'tesla_ap1' / 'phase3_stalk_controls.py'
VALUES_PATH = REPO / 'opendbc_repo' / 'opendbc' / 'car' / 'tesla_ap1' / 'values.py'


def _load(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  mod = importlib.util.module_from_spec(spec)
  sys.modules[name] = mod
  spec.loader.exec_module(mod)
  return mod


bsb = _load('beta_stalk_bookmark_ut', MOD_PATH)


def stream(fwd, end_ms, *, step_ms=10, other=(), cs=lambda ms: False, sds=lambda ms: False, ok=lambda ms: True,
           drop=(), tx=(), det=None, hold=None):
  """fwd: [(start_ms, dur_ms)] FWD presses. other: [(start_ms, dur_ms, value)]. drop: ms ranges with no carState.
  tx: ms times of our own 0x45 TX. Returns (fire times in ms, detector, experimental toggles in ms)."""
  det = det if det is not None else bsb.Detector()
  fires, toggles = [], []
  tx = sorted(tx)
  for ms in range(0, end_ms + 1, step_ms):
    while tx and tx[0] <= ms:
      det.note_own_tx(tx.pop(0) / 1000.)
    if any(a <= ms < b for a, b in drop):
      continue
    spd = 0
    for a, d in fwd:
      if a <= ms < a + d:
        spd = 1
    for a, d, v in other:
      if a <= ms < a + d:
        spd = v
    if det.update(ms / 1000., spd, cs(ms), sds(ms), ok(ms)):
      fires.append(ms)
    if hold is not None:
      if hold.update(spd, bool(cs(ms) or sds(ms)), ms / 1000., (ms // 100 + 1) * 100_000_000, ok(ms), True, True, 1.23):
        toggles.append(ms)
  return fires, det, toggles


def taps(start, n, dur=100, gap=150):
  return [(start + i * (dur + gap), dur) for i in range(n)]


def rel3(start, dur=100, gap=150):
  return start + 3 * dur + 2 * gap      # 3rd release


# ---- U1 / V2(1): 3 taps -> 1 bookmark at the 3rd release
def test_u1_three_taps_fire_at_third_release():
  fires, _, _ = stream(taps(1000, 3), 4000)
  assert fires == [rel3(1000)]


# ---- U2: 2 taps -> 0
def test_u2_two_taps_nothing():
  assert stream(taps(1000, 2), 5000)[0] == []


# ---- V2(2): 4, 5, 6 taps within the gaps -> exactly 1, at tap 3 (extra taps neither cancel nor re-fire)
@pytest.mark.parametrize('n', [4, 5, 6])
def test_v2_extra_taps_give_exactly_one(n):
  fires, _, _ = stream(taps(1000, n), 8000)
  assert fires == [rel3(1000)]


# ---- V2(3) / V1 lockout: a tap 1.01 s after the last release starts a new train; 0.99 s cannot
def test_v2_new_train_after_lockout_1_01s():
  last = rel3(1000)
  fires, _, _ = stream(taps(1000, 3) + taps(last + 1010, 3), 9000)
  assert fires == [last, rel3(last + 1010)]


def test_v2_no_new_train_at_0_99s():
  last = rel3(1000)
  fires, _, _ = stream(taps(1000, 3) + taps(last + 990, 3), 9000)
  assert fires == [last]


# ---- U3: two triples 2 s apart -> 2
def test_u3_two_triples():
  fires, _, _ = stream(taps(1000, 3) + taps(1000 + 2000 + 650, 3), 9000)
  assert len(fires) == 2


def _engaged_until(ms_off):
  return lambda ms: ms < ms_off


# ---- U4: engaged cancel + 3 taps 0.74 s later -> 1; cancel + 2 taps -> 0 (the cancel never counts)
def test_u4_cancel_then_three_taps():
  # cancel press at 1000 (engaged at onset), both flags fall at 1010
  fwd = [(1000, 100)] + taps(1740, 3)
  assert stream(fwd, 5000, cs=_engaged_until(1010), sds=_engaged_until(1010))[0] == [rel3(1740)]


def test_u4_cancel_plus_two_taps_is_zero():
  fwd = [(1000, 100)] + taps(1740, 2)
  assert stream(fwd, 5000, cs=_engaged_until(1010), sds=_engaged_until(1010))[0] == []


# ---- U5: DI-first shapes. cs False / sds True at onset -> not counted; cs True / sds False -> not counted.
def test_u5_sds_still_engaged_not_counted():
  assert stream(taps(1000, 3), 5000, cs=lambda ms: False, sds=lambda ms: True)[0] == []


def test_u5_cs_still_engaged_not_counted():
  # also P3: stock-CC engaged (no-pedal pre-AP branch: cruiseState.enabled = DI acc_enabled) never counts
  assert stream(taps(1000, 3), 5000, cs=lambda ms: True, sds=lambda ms: False)[0] == []


# ---- U6: disengage guard 0.30 s from the most recent fall of cs OR sds
@pytest.mark.parametrize('cs_off,sds_off', [(1010, 1005), (1005, 1010)])
@pytest.mark.parametrize('delay,expect', [(290, 0), (310, 1)])
def test_u6_guard(cs_off, sds_off, delay, expect):
  t_dis = max(cs_off, sds_off)
  fwd = [(1000, 100)] + taps(t_dis + delay, 3)
  fires = stream(fwd, 6000, cs=_engaged_until(cs_off), sds=_engaged_until(sds_off))[0]
  assert len(fires) == expect


def test_u6_bounce_after_disengage_then_two_taps_zero():
  fwd = [(1000, 100), (1110, 100)] + taps(1500, 2)
  assert stream(fwd, 6000, cs=_engaged_until(1010), sds=_engaged_until(1010))[0] == []


# ---- V3 (pre-AP shape): cs always False, sds True -> False on the cancel frame
@pytest.mark.parametrize('gate', [True, False])
@pytest.mark.parametrize('delay,expect', [(290, 0), (310, 1)])
def test_v3_preap_shape_guard_from_sds(gate, delay, expect):
  fwd = [(1000, 100)] + taps(1000 + delay, 3)
  det = bsb.Detector(cruise_state_gate=gate)
  fires = stream(fwd, 6000, cs=lambda ms: False, sds=_engaged_until(1000), det=det)[0]
  assert len(fires) == expect


def test_cruise_state_gate_false_ignores_cs():
  det = bsb.Detector(cruise_state_gate=False)
  assert stream(taps(1000, 3), 5000, cs=lambda ms: True, det=det)[0] == [rel3(1000)]


# ---- U7: gap 1.00 ok / 1.01 abort; span 1.20 ok / 1.21 abort (1 kHz)
def test_u7_gap_limit():
  # gap 1.00 s is inside the limit (span exactly 1.20 s)
  assert stream([(1000, 50), (2050, 50), (2150, 50)], 5000, step_ms=1)[0] == [2200]
  # gap 1.01 s ends the train: tap 1 is dropped, so 3 taps give 0 ...
  assert stream([(1000, 50), (2060, 50), (2160, 50)], 5000, step_ms=1)[0] == []
  # ... and the late tap starts a new train that fires at its own 3rd release
  assert stream([(1000, 50), (2060, 50), (2160, 50), (2260, 50)], 5000, step_ms=1)[0] == [2310]


def test_u7_span_limit():
  ok = [(1000, 100), (1500, 100), (2100, 100)]       # span 1.20 s
  assert stream(ok, 5000, step_ms=1)[0] == [2200]
  bad = [(1000, 100), (1500, 100), (2110, 100)]      # span 1.21 s
  assert stream(bad, 5000, step_ms=1)[0] == []


# ---- U8 / P2: RWD (pull / double pull), UP/DN tips, engage edge inside a train -> 0
@pytest.mark.parametrize('other', [
  [(1300, 100, 2)],                          # single pull
  [(1260, 80, 2), (1400, 80, 2)],            # pre-AP double pull inside the train
  [(1300, 100, 4)], [(1300, 100, 8)], [(1300, 100, 16)], [(1300, 100, 32)],
])
def test_u8_other_lever_aborts(other):
  fwd = [(1000, 100), (1600, 100), (1850, 100)]
  assert stream(fwd, 5000, other=other)[0] == []


@pytest.mark.parametrize('which', ['cs', 'sds'])
def test_u8_engage_edge_aborts(which):
  on = lambda ms: 1300 <= ms < 1310
  kw = {which: on}
  fwd = [(1000, 100), (1600, 100), (1850, 100)]
  assert stream(fwd, 5000, **kw)[0] == []


# ---- U9: canValid False one frame / carState gap 0.26 s / invalid values -> 0
def test_u9_can_invalid_one_frame():
  assert stream(taps(1000, 3), 5000, ok=lambda ms: ms != 1300)[0] == []


def test_u9_carstate_gap():
  assert stream(taps(1000, 3), 5000, drop=[(1260, 1520)])[0] == []


@pytest.mark.parametrize('v', [3, 64])
def test_u9_invalid_value(v):
  assert stream(taps(1000, 3), 5000, other=[(1300, 10, v)])[0] == []


# ---- U10: stalk held FWD at onroad start -> nothing until IDLE
def test_u10_held_at_start():
  fwd = [(0, 200)] + taps(1300, 2)
  assert stream(fwd, 5000)[0] == []
  assert stream([(0, 200)] + taps(1300, 3), 5000)[0] == [rel3(1300)]


# ---- U13: durations 49 / 50 / 300 / 301 / 500 ms (1 kHz)
@pytest.mark.parametrize('dur,expect', [(49, 0), (50, 1), (300, 1), (301, 0), (500, 0)])
def test_u13_durations(dur, expect):
  fwd = [(1000, 100), (1250, 100), (1500, dur)]
  assert len(stream(fwd, 5000, step_ms=1)[0]) == expect


def test_u13_long_press_disarms_until_idle():
  # 500 ms press aborts and disarms; the remainder of that press can't start a train
  fwd = [(1000, 500)] + taps(1600, 2)
  assert stream(fwd, 5000)[0] == []


# ---- P1: own-0x45-TX drop (StockCCSpoofer cancel, AP1 cancel): never advances the counter
def test_p1_window_value():
  # two distinct constants that happen to share 0.30 s (NAP SPOOF_ECHO_WINDOW_MS = 300)
  assert bsb.TX_DROP_S == pytest.approx(0.30)
  assert bsb.DISENGAGE_GUARD_S == pytest.approx(0.30)
  assert 'TX_DROP_S' in vars(bsb) and 'DISENGAGE_GUARD_S' in vars(bsb)


@pytest.mark.parametrize('delay_ms', [6, 290])
def test_p1_echo_after_own_tx_ignored(delay_ms):
  # an echo-like FWD 6 ms (worst measured echo) or 290 ms after our TX is never counted; taps 2-3 alone -> 0
  assert stream(taps(1000, 3), 5000, step_ms=1, tx=[1000 - delay_ms])[0] == []


def test_p1_real_tap_310ms_after_tx_counts():
  assert stream(taps(1000, 3), 5000, step_ms=1, tx=[690])[0] == [rel3(1000)]


@pytest.mark.parametrize('tx_ms,expect', [(700, 0), (699, 1)])
def test_p1_window_boundary(tx_ms, expect):
  # onset 1000 ms; the 300 ms window is inclusive
  assert len(stream(taps(1000, 3), 5000, step_ms=1, tx=[tx_ms])[0]) == expect


def test_p1_window_independent_of_disengage_guard():
  # disengaged at 0 ms (guard over at 300 ms); TX at 900 still drops a tap at 1000
  sds = lambda ms: ms < 0
  assert stream(taps(1000, 3), 5000, step_ms=1, tx=[900], sds=sds)[0] == []


@pytest.mark.parametrize('tx_ms', [1050, 1120, 1300, 1530])
def test_p1_own_tx_mid_train_aborts(tx_ms):
  # TX during tap 1, between taps, after tap 2's release, or during tap 3: counting train reset, no bookmark
  fires, det, _ = stream(taps(1000, 3), 5000, step_ms=1, tx=[tx_ms])
  assert fires == []
  assert not det.taps and not det.counting and not det.locked


@pytest.mark.parametrize('tx_ms', [1700, 1950, 2400])
def test_p1_own_tx_during_lockout_keeps_one_bookmark(tx_ms):
  # bookmark fires at 1600 (3rd release); our TX lands in the lockout (idle, during tap 5, after tap 6's onset);
  # taps 4-9 follow in the same train (gaps 150 ms) -> still exactly 1 bookmark
  fires, det, _ = stream(taps(1000, 9), 6000, step_ms=1, tx=[tx_ms])
  assert fires == [rel3(1000)]


def test_p1_lockout_kept_through_tx_until_idle_1s():
  d = bsb.Detector()
  d.locked = True
  d.note_own_tx(1.0)
  assert d.locked and not d.counting_train()


def test_p1_mid_train_abort_then_new_train_fires():
  # TX aborts the first train; a fresh 3-tap train starting > 300 ms after the TX fires once
  fwd = taps(1000, 2) + taps(2000, 3)
  assert stream(fwd, 6000, step_ms=1, tx=[1300])[0] == [rel3(2000)]


def test_p1_tx_while_idle_does_not_disarm():
  fires, det, _ = stream(taps(1000, 3), 5000, step_ms=1, tx=[200])
  assert fires == [rel3(1000)]


def test_p1_counting_train_states():
  d = bsb.Detector()
  assert not d.counting_train()
  d.taps = [(0.0, 0.1)]
  assert d.counting_train()
  d.note_own_tx(1.0)
  assert not d.counting_train()
  d.counting = True
  assert d.counting_train()


def test_p1_sendcan_0x45_detection():
  frame = lambda a, s: NS(address=a, src=s)
  assert bsb.has_own_0x45(NS(sendcan=[frame(0x488, 0), frame(0x45, 0)]))
  assert bsb.has_own_0x45(NS(sendcan=[frame(0x45, 2)]))
  assert not bsb.has_own_0x45(NS(sendcan=[frame(0x488, 2), frame(0x370, 0)]))
  assert not bsb.has_own_0x45(None)


# ---- U11 / V2(4): Experimental FWD hold is unaffected; bookmark stays 1
hold_mod = _load('phase3_stalk_controls_ut', HOLD_PATH)


def _toggles_alone(fwd, end):
  h = hold_mod.ExperimentalHold(1)
  out = []
  for ms in range(0, end + 1, 10):
    spd = 1 if any(a <= ms < a + d for a, d in fwd) else 0
    if h.update(spd, False, ms / 1000., (ms // 100 + 1) * 100_000_000, True, True, True, 1.23):
      out.append(ms)
  return out


@pytest.mark.parametrize('fwd,bookmarks', [
  (taps(1000, 3) + [(1000 + 750, 1300)], 1),       # 4th press becomes a 1.30 s hold
  (taps(1000, 3) + [(4000, 1300)], 1),             # (a) triple, then hold after the lockout
  ([(1000, 1300)] + taps(3500, 3), 1),             # (b) hold, then triple
  (taps(1000, 2) + [(1500, 1300)], 0),             # (c) tap, tap, hold
])
def test_u11_experimental_hold_unchanged(fwd, bookmarks):
  fires, _, toggles = stream(fwd, 8000, hold=hold_mod.ExperimentalHold(1))
  assert len(fires) == bookmarks
  assert toggles == _toggles_alone(fwd, 8000)
  assert len(toggles) == 1


# ---- P4 / static: observe-only, no car-side imports
def test_p4_no_forbidden_imports():
  import ast
  tree = ast.parse(MOD_PATH.read_text())
  idents = set()
  for n in ast.walk(tree):
    if isinstance(n, ast.Name):
      idents.add(n.id)
    elif isinstance(n, ast.Attribute):
      idents.add(n.attr)
    elif isinstance(n, ast.alias):
      idents.add(n.name)
    elif isinstance(n, ast.ImportFrom):
      idents.add(n.module or '')
  for name in ('phase3_stalk_controls', 'ExperimentalHold', 'StalkControls', 'PreAPEngagement', 'engagement',
               'StockCCSpoofer', 'stock_cc_spoofer', 'preap_steer_drop', 'preap_panda_drop', 'CarState', 'CarController',
               'Params', 'can_sends', 'PubMaster'):
    assert not any(name in i for i in idents), name
  mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
  mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
  assert mods <= {'__future__', 'dataclasses', 'pathlib', 'openpilot.cereal.messaging'}, mods
  # only userBookmark is ever sent
  sends = re.findall(r"pm\.send\('(\w+)'", MOD_PATH.read_text())
  assert sends == ['userBookmark']


# ---- U12 / E4: explicit allow-list, AP1 Model S only, and inert off-list
def cp(fp, dashcam=False, passive=False):
  return NS(carFingerprint=fp, dashcamOnly=dashcam, passive=passive)


def test_e4_allow_list_is_exactly_ap1_s():
  assert [e.fingerprint for e in bsb.ALLOW_LIST] == ['TESLA_AP1_MODELS']
  assert bsb.ALLOW_LIST[0].cruise_state_gate is True


def test_e4_allow_list_fingerprints_exist_in_values():
  names = set(re.findall(r'^  (TESLA_\w+) = TeslaAp1PlatformConfig', VALUES_PATH.read_text(), re.M))
  assert {'TESLA_AP1_MODELS', 'TESLA_PREAP_MODELS', 'TESLA_AP1_MODELX'} <= names
  assert all(e.fingerprint in names for e in bsb.ALLOW_LIST)


@pytest.mark.parametrize('fp', ['TESLA_AP1_MODELS'])
def test_u12_gate_on(fp):
  assert bsb.entry_for(cp(fp)) is not None


@pytest.mark.parametrize('fp', ['TESLA_PREAP_MODELS', 'TESLA_AP1_MODELX', 'TESLA_AP2_MODELS', 'TESLA_AP2_MODELX',
                                'TESLA_MODEL_Y', 'TESLA_MODEL_X', 'TESLA_MODEL_3', 'TESLA_MODEL_S_RAVEN', '', 'MOCK'])
def test_u12_gate_off_list(fp):
  assert bsb.entry_for(cp(fp)) is None


def test_u12_gate_dashcam_passive_none():
  assert bsb.entry_for(cp('TESLA_AP1_MODELS', dashcam=True)) is None
  assert bsb.entry_for(cp('TESLA_AP1_MODELS', passive=True)) is None
  assert bsb.entry_for(None) is None
  assert bsb.entry_for(NS(carFingerprint='TESLA_AP1_MODELS')) is None   # missing flags fail closed


def test_u12_flag(tmp_path):
  f = tmp_path / 'BetaStalkBookmark'
  assert not bsb.flag_on(f)
  f.write_text('0')
  assert not bsb.flag_on(f)
  f.write_text('1\n')
  assert bsb.flag_on(f)


class _PM:
  def __init__(self):
    self.sent = []

  def send(self, s, m):
    self.sent.append(s)


@pytest.mark.parametrize('fp', ['TESLA_PREAP_MODELS', 'TESLA_AP1_MODELX', 'TESLA_AP1_MODELS'])
def test_u12_tick_inert_off_list_or_flag_off(fp, monkeypatch, tmp_path):
  # AP1 S case: flag file missing -> inert. Others: off-list -> inert even with the flag on.
  flag = tmp_path / 'BetaStalkBookmark'
  if fp != 'TESLA_AP1_MODELS':
    flag.write_text('1')
  monkeypatch.setattr(bsb, 'FLAG', flag)
  monkeypatch.setattr(bsb, '_state', None)
  monkeypatch.setattr(bsb, 'flag_on', lambda path=None: flag.is_file() and flag.read_text().strip() == '1')
  pm = _PM()
  ui = NS(started=True, sm={'carParams': cp(fp)})
  for _ in range(3):
    bsb.tick(pm, ui)
  assert bsb._state is False and pm.sent == []


# ---- Hand-count shapes of real tap attempts (ms relative, 1 kHz). Not a replay: see test_beta_stalk_bookmark_replay.py.
def _train(cancel_ms, cancel_dur, first_tap_ms, durs, gaps):
  fwd = [(cancel_ms, cancel_dur)]
  t = first_tap_ms
  for i, d in enumerate(durs):
    fwd.append((t, d))
    t += d + (gaps[i] if i < len(gaps) else 0)
  return fwd


@pytest.mark.parametrize('name,cancel,cs_off,sds_off,tap1,durs,gaps', [
  # attempt A: cancel 100 ms, sds falls +7 ms, cs +16 ms; taps from +741 ms
  ('A', (1000, 100), 1016, 1007, 1741, (100, 90, 72), (160, 150)),
  # attempt B: cancel 110 ms, cs +3 ms, sds +8 ms; taps from +1653 ms
  ('B', (1000, 110), 1003, 1008, 2653, (108, 71, 91), (140, 89)),
  # 0.9.7 log attempt: cancel 121 ms, flags fall during the press; taps from +810 ms
  ('fe', (1000, 121), 1060, 1060, 1810, (149, 141, 119), (120, 80)),
])
def test_hand_count_real_attempts_one_each(name, cancel, cs_off, sds_off, tap1, durs, gaps):
  fwd = _train(cancel[0], cancel[1], tap1, durs, gaps)
  fires = stream(fwd, 8000, step_ms=1, cs=_engaged_until(cs_off), sds=_engaged_until(sds_off))[0]
  assert fires == [tap1 + sum(durs) + sum(gaps)], name


def test_hand_count_fb_standstill_one():
  # 0.9.7 standstill attempt: disengaged 54.5 s earlier; taps 140, 110, 100 ms with 140 ms gaps
  fwd = _train(-100000, 0, 1000, (140, 110, 100), (140, 140))[1:]
  assert len(stream(fwd, 6000, step_ms=1)[0]) == 1


def test_hand_count_holds_and_singles_zero():
  holds = [(1000, 1952), (9142, 1980), (13940, 1819)]
  assert stream(holds, 20000)[0] == []
  singles = [(1000 + i * 22000, d) for i, d in enumerate((142, 161, 120, 131, 110))]
  assert stream(singles, 120000, cs=lambda ms: True, sds=lambda ms: True)[0] == []
