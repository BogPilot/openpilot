"""Shared stalk-tip hold-repeat rule, AP1 openpilot long side (Ap1RaiseHoldoff at the 20 Hz planner tick) and the state machine itself.

Light (16 up / 32 down): +-1 on the press, then after 0.35 s +-1 every 0.2 s while held. Deep (4 up / 8 down): one step to the next /
previous 5, never repeats. Light -> deep mid-press: one upgrade to 5, never repeats. Release resets."""
import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1.slc_raise import Ap1RaiseHoldoff
from opendbc.car.tesla_ap1.stalk_repeat import (DEEP_DOWN, DEEP_UP, INITIAL_S, LIGHT_DOWN, LIGHT_UP, PERIOD_S, StalkTipRepeat,
                                                lever_to_dir_deep)

MPH = CV.MPH_TO_MS
DT = 0.05


def run_machine(seq, dt=0.01):
  """seq: [(lever, seconds)] -> [(time_s, event)]"""
  m = StalkTipRepeat()
  out, t = [], 0.0
  for lever, secs in seq:
    d, deep = lever_to_dir_deep(lever)
    for _ in range(int(round(secs / dt))):
      out += [(round(t, 4), e) for e in m.update(d, deep, dt)]
      t += dt
  return out


def test_lever_codes():
  assert lever_to_dir_deep(LIGHT_UP) == (1, False) and lever_to_dir_deep(DEEP_UP) == (1, True)
  assert lever_to_dir_deep(LIGHT_DOWN) == (-1, False) and lever_to_dir_deep(DEEP_DOWN) == (-1, True)
  for other in (0, 1, 2, 64, 255):
    assert lever_to_dir_deep(other) == (0, False)


@pytest.mark.parametrize("lever", [LIGHT_UP, LIGHT_DOWN])
def test_machine_light_hold_press_then_035_then_every_02(lever):
  ev = run_machine([(lever, 1.2), (0, 0.1)])
  assert ev[0] == (0.0, "press_light")
  times = [t for t, e in ev if e == "repeat"]
  assert times[:4] == pytest.approx([0.35, 0.55, 0.75, 0.95], abs=0.011)
  assert len(times) == 5   # 0.35 .. 1.15
  assert {e for _, e in ev} == {"press_light", "repeat"}


@pytest.mark.parametrize("lever", [LIGHT_UP, LIGHT_DOWN])
def test_machine_light_tap_under_035_is_a_single_step(lever):
  ev = run_machine([(lever, 0.34), (0, 0.5)])
  assert ev == [(0.0, "press_light")]


@pytest.mark.parametrize("lever", [DEEP_UP, DEEP_DOWN])
def test_machine_deep_press_steps_once_and_never_repeats(lever):
  ev = run_machine([(lever, 2.0), (0, 0.1)])
  assert ev == [(0.0, "press_deep")]


@pytest.mark.parametrize("light,deep", [(LIGHT_UP, DEEP_UP), (LIGHT_DOWN, DEEP_DOWN)])
@pytest.mark.parametrize("light_s", [0.05, 0.2, 0.3, 0.5, 0.9])
def test_machine_light_to_deep_upgrades_once_never_repeats(light, deep, light_s):
  ev = run_machine([(light, light_s), (deep, 2.0), (0, 0.1)])
  names = [e for _, e in ev]
  assert names.count("upgrade") == 1 and names[-1] == "upgrade"
  assert names.count("press_light") == 1
  # after the upgrade nothing more, however long deep is held
  assert ev[-1][0] == pytest.approx(light_s, abs=0.011)


def test_machine_release_and_repress_restart_the_delay():
  ev = run_machine([(LIGHT_UP, 0.30), (0, 0.02), (LIGHT_UP, 0.30), (0, 0.1)])
  assert [e for _, e in ev] == ["press_light", "press_light"]
  ev = run_machine([(LIGHT_UP, 0.40), (0, 0.02), (LIGHT_UP, 0.40), (0, 0.1)])
  assert [e for _, e in ev] == ["press_light", "repeat", "press_light", "repeat"]
  assert ev[3][0] == pytest.approx(0.42 + 0.35, abs=0.011)


def test_machine_direction_flip_without_release_is_a_new_press():
  ev = run_machine([(LIGHT_UP, 0.1), (LIGHT_DOWN, 0.1), (0, 0.1)])
  assert [e for _, e in ev] == ["press_light", "press_light"]


def test_machine_coarse_planner_ticks_still_hit_the_schedule():
  ev = run_machine([(LIGHT_UP, 1.0), (0, 0.1)], dt=0.05)
  assert [t for t, e in ev if e == "repeat"] == pytest.approx([0.35, 0.55, 0.75, 0.95], abs=0.051)


# ---- AP1 openpilot long: Ap1RaiseHoldoff ------------------------------------------------------------------------------------

def make_hold(base_mph=50, round_whole=True, metric=False):
  h = Ap1RaiseHoldoff(round_whole=round_whole, is_metric=metric)
  base = base_mph * MPH
  for _ in range(3):
    h.update(True, False, False, False, base, 20.0, current_set_ms=base, dt=DT, cruise_on=True)
  return h


def drive_hold(h, seq, base_mph=50):
  """Planner loop at 20 Hz, as phase3_speed_control: set hint = tip when set, tip_full = lever in (4, 8). -> [tip_ms in mph per tick]"""
  base = base_mph * MPH
  out = []
  for lever, secs in seq:
    up, dn, deep = lever in (LIGHT_UP, DEEP_UP), lever in (LIGHT_DOWN, DEEP_DOWN), lever in (DEEP_UP, DEEP_DOWN)
    for _ in range(int(round(secs / DT))):
      hint = h.tip_ms if h.tip_ms > 0 else base
      h.update(True, dn, up, False, base, 20.0, current_set_ms=hint, dt=DT, tip_full=deep, cruise_on=True)
      out.append(round(h.tip_ms / MPH, 3))
  return out


def stepped(vals):
  """distinct consecutive values"""
  r = []
  for v in vals:
    if not r or r[-1] != v:
      r.append(v)
  return r


@pytest.mark.parametrize("lever,sign", [(LIGHT_UP, 1), (LIGHT_DOWN, -1)])
def test_ap1_light_tap_under_035_is_one_step(lever, sign):
  h = make_hold(50)
  vals = drive_hold(h, [(lever, 0.30), (0, 1.0)])
  assert stepped(vals) == [50 + sign]


@pytest.mark.parametrize("lever,sign", [(LIGHT_UP, 1), (LIGHT_DOWN, -1)])
def test_ap1_light_hold_repeats_035_then_02(lever, sign):
  h = make_hold(50)
  vals = drive_hold(h, [(lever, 1.20), (0, 0.5)])
  assert stepped(vals) == [50 + sign * k for k in range(1, 7)]   # press + repeats at .35 .55 .75 .95 1.15
  first = [i for i, v in enumerate(vals) if v == 50 + 2 * sign][0]
  assert first * DT == pytest.approx(0.35, abs=DT)
  second = [i for i, v in enumerate(vals) if v == 50 + 3 * sign][0]
  assert (second - first) * DT == pytest.approx(0.2, abs=1e-6)
  assert vals[-1] == 50 + 6 * sign   # no -> 5 jump anywhere


def test_ap1_old_045_hold_upgrade_is_gone():
  h = make_hold(50)
  vals = drive_hold(h, [(LIGHT_UP, 0.60), (0, 0.2)])
  assert stepped(vals) == [51, 52, 53]
  assert 55 not in vals


@pytest.mark.parametrize("lever,sign,want", [(DEEP_UP, 1, 55), (DEEP_DOWN, -1, 45)])
@pytest.mark.parametrize("secs", [0.2, 1.5])
def test_ap1_deep_tap_and_long_hold_step_once(lever, sign, want, secs):
  h = make_hold(50)
  vals = drive_hold(h, [(lever, secs), (0, 0.5)])
  assert stepped(vals) == [want]


@pytest.mark.parametrize("lever,sign,want", [(DEEP_UP, 1, 40), (DEEP_DOWN, -1, 35)])
def test_ap1_deep_from_non_multiple(lever, sign, want):
  h = make_hold(37)
  assert stepped(drive_hold(h, [(lever, 1.2), (0, 0.2)], base_mph=37)) == [want]


@pytest.mark.parametrize("light,deep,sign,want", [(LIGHT_UP, DEEP_UP, 1, 55), (LIGHT_DOWN, DEEP_DOWN, -1, 45)])
@pytest.mark.parametrize("light_s", [0.1, 0.3])
def test_ap1_light_to_deep_upgrades_once_to_5_never_repeats(light, deep, sign, want, light_s):
  h = make_hold(50)
  vals = drive_hold(h, [(light, light_s), (deep, 1.5), (0, 0.3)])
  assert stepped(vals) == [50 + sign, want]


@pytest.mark.parametrize("light,deep,want", [(LIGHT_UP, DEEP_UP, [51, 52, 53, 54, 55]), (LIGHT_DOWN, DEEP_DOWN, [49, 48, 47, 46, 45])])
def test_ap1_light_to_deep_after_repeats_upgrades_from_the_current_set(light, deep, want):
  h = make_hold(50)
  vals = drive_hold(h, [(light, 0.80), (deep, 1.0), (0, 0.3)])   # press, repeats at .35 .55 .75, then deep -> next / prev 5 of the current set
  assert stepped(vals) == want


def test_ap1_release_and_repress_resets_the_delay():
  h = make_hold(50)
  vals = drive_hold(h, [(LIGHT_UP, 0.30), (0, 0.10), (LIGHT_UP, 0.30), (0, 0.5)])
  assert stepped(vals) == [51, 52]            # two taps, no repeat
  h = make_hold(50)
  vals = drive_hold(h, [(LIGHT_UP, 0.40), (0, 0.10), (LIGHT_UP, 0.40), (0, 0.5)])
  assert stepped(vals) == [51, 52, 53, 54]    # each press: step, then its own 0.35 s repeat


def test_ap1_repeat_down_never_below_1_mph_and_up_capped_at_145_kph():
  h = make_hold(3)
  vals = drive_hold(h, [(LIGHT_DOWN, 2.0), (0, 0.2)], base_mph=3)
  assert min(vals) >= 1 - 1e-6
  h = make_hold(89)
  vals = drive_hold(h, [(LIGHT_UP, 3.0), (0, 0.2)], base_mph=89)
  assert h.tip_ms <= 145.0 * CV.KPH_TO_MS + 1e-6


def test_ap1_whole_unit_rounding_of_the_base_with_repeats():
  h = make_hold(50)
  base = 50.4 * MPH   # fractional set
  out = []
  for up in [True] * 10 + [False] * 4:
    hint = h.tip_ms if h.tip_ms > 0 else base
    h.update(True, False, up, False, base, 20.0, current_set_ms=hint, dt=DT, tip_full=False, cruise_on=True)
    out.append(round(h.tip_ms / MPH, 3))
  assert stepped(out) == [51, 52]


def test_ap1_metric_repeat_steps_one_kph():
  h = make_hold(50, metric=True)
  base = 80 * CV.KPH_TO_MS
  h = Ap1RaiseHoldoff(round_whole=True, is_metric=True)
  for _ in range(3):
    h.update(True, False, False, False, base, 20.0, current_set_ms=base, dt=DT, cruise_on=True)
  out = []
  for up in [True] * 10 + [False] * 4:
    hint = h.tip_ms if h.tip_ms > 0 else base
    h.update(True, False, up, False, base, 20.0, current_set_ms=hint, dt=DT, tip_full=False, cruise_on=True)
    out.append(round(h.tip_ms * CV.MS_TO_KPH, 3))
  assert stepped(out) == [81, 82]


def test_ap1_tip_while_fully_disengaged_still_latches_and_does_not_step():
  """A tip with nothing engaged only engages cruise at the current speed (sticky latch), as before."""
  h = Ap1RaiseHoldoff(round_whole=True)
  v = 20.4 * MPH
  h.update(False, False, True, False, 0.0, v, dt=DT, cruise_on=False)
  for _ in range(10):
    h.update(False, False, True, False, 0.0, v, dt=DT, cruise_on=False)
  h.update(True, False, False, False, 0.0, v, dt=DT, cruise_on=True)
  assert h.sticky_vego and h.latched_vego_ms == pytest.approx(20 * MPH)
  assert h.tip_ms == 0.0
