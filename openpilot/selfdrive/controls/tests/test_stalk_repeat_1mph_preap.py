"""Shared stalk-tip hold-repeat rule, Tesla Pre-AP with pedal (VCruiseHelper, pcmCruise=False, 100 Hz card step).
Same detent state machine as AP1 openpilot long (opendbc tesla_ap1/stalk_repeat.py); the stock 50-tick +-5 long press is not used."""
import pytest

from openpilot.common.constants import CV
from openpilot.selfdrive.car.cruise import VCruiseHelper

MPH = CV.MPH_TO_KPH
LIGHT_UP, LIGHT_DOWN, DEEP_UP, DEEP_DOWN = 16, 32, 4, 8
DT = 0.01


class NS:
  def __init__(self, **kw):
    self.__dict__.update(kw)


def make(set_mph=50, metric=False, fingerprint="TESLA_PREAP_MODELS"):
  h = VCruiseHelper(NS(pcmCruise=False, carFingerprint=fingerprint))
  h.v_cruise_kph = set_mph * (1.0 if metric else MPH)
  return h


def cs(lever, standstill=False, gas=False, v_ego=20.0):
  return NS(cruiseState=NS(available=True, standstill=standstill, speed=0.0, speedCluster=0.0), bogpilot=NS(spdCtrlLvr=lever),
            buttonEvents=[], gasPressed=gas, vEgo=v_ego)


def drive(h, seq, metric=False, enabled=True, **kw):
  """-> list of the set speed in display units per 10 ms step"""
  unit = 1.0 if metric else MPH
  out = []
  for lever, secs in seq:
    for _ in range(int(round(secs / DT))):
      h.update_v_cruise(cs(lever, **kw), enabled, metric)
      out.append(round(h.v_cruise_kph / unit, 1))
  return out


def stepped(vals):
  r = []
  for v in vals:
    if not r or r[-1] != v:
      r.append(v)
  return r


@pytest.mark.parametrize("lever,sign", [(LIGHT_UP, 1), (LIGHT_DOWN, -1)])
def test_light_tap_under_035_is_one_step(lever, sign):
  assert stepped(drive(make(50), [(lever, 0.30), (0, 1.0)])) == [50 + sign]


@pytest.mark.parametrize("lever,sign", [(LIGHT_UP, 1), (LIGHT_DOWN, -1)])
def test_light_tap_steps_on_the_press_not_the_release(lever, sign):
  h = make(50)
  assert drive(h, [(lever, 0.02)])[-1] == 50 + sign
  assert stepped(drive(h, [(0, 0.5)])) == [50 + sign]


@pytest.mark.parametrize("lever,sign", [(LIGHT_UP, 1), (LIGHT_DOWN, -1)])
def test_light_hold_repeats_035_then_02(lever, sign):
  vals = drive(make(50), [(lever, 1.20), (0, 0.5)])
  assert stepped(vals) == [50 + sign * k for k in range(1, 7)]
  idx = {v: next(i for i, x in enumerate(vals) if x == v) for v in set(vals)}
  assert idx[50 + 2 * sign] * DT == pytest.approx(0.35, abs=0.011)
  for k in range(2, 6):
    assert (idx[50 + (k + 1) * sign] - idx[50 + k * sign]) * DT == pytest.approx(0.2, abs=0.011)
  assert vals[-1] == 50 + 6 * sign   # never a +-5 from the hold (the stock timer did +-5 at 0.5 s)


def test_stock_5_step_at_050s_does_not_happen():
  vals = drive(make(50), [(LIGHT_UP, 0.52), (0, 0.2)])   # the stock timer: +5 -> 55 at tick 50 (0.5 s)
  assert max(vals) == 52


@pytest.mark.parametrize("lever,want", [(DEEP_UP, 55), (DEEP_DOWN, 45)])
@pytest.mark.parametrize("secs", [0.2, 1.5, 3.0])
def test_deep_tap_and_long_hold_step_once(lever, want, secs):
  assert stepped(drive(make(50), [(lever, secs), (0, 0.5)])) == [want]


@pytest.mark.parametrize("lever,want", [(DEEP_UP, 40), (DEEP_DOWN, 35)])
def test_deep_from_non_multiple(lever, want):
  assert stepped(drive(make(37), [(lever, 1.5), (0, 0.2)])) == [want]


@pytest.mark.parametrize("light,deep,want", [(LIGHT_UP, DEEP_UP, [51, 55]), (LIGHT_DOWN, DEEP_DOWN, [49, 45])])
@pytest.mark.parametrize("light_s", [0.05, 0.2, 0.3])
def test_light_to_deep_upgrades_once_never_repeats(light, deep, want, light_s):
  assert stepped(drive(make(50), [(light, light_s), (deep, 2.0), (0, 0.3)])) == want


@pytest.mark.parametrize("light,deep,want", [(LIGHT_UP, DEEP_UP, [51, 52, 53, 54, 55]), (LIGHT_DOWN, DEEP_DOWN, [49, 48, 47, 46, 45])])
def test_light_to_deep_after_repeats_uses_the_current_set(light, deep, want):
  assert stepped(drive(make(50), [(light, 0.80), (deep, 1.0), (0, 0.3)])) == want


@pytest.mark.parametrize("light,deep,want", [(LIGHT_UP, DEEP_UP, [54, 55]), (LIGHT_DOWN, DEEP_DOWN, [46, 45])])
def test_light_then_deep_from_4_or_6_mod_5_goes_to_the_next_5_of_the_press_base(light, deep, want):
  base = 53 if light == LIGHT_UP else 47
  # 53 +1 = 54, deep -> next 5 of the press base 53 = 55 ; 47 -1 = 46, deep -> prev 5 of 47 = 45
  assert stepped(drive(make(base), [(light, 0.1), (deep, 0.5), (0, 0.2)])) == want


def test_release_and_repress_resets_the_delay():
  assert stepped(drive(make(50), [(LIGHT_UP, 0.30), (0, 0.02), (LIGHT_UP, 0.30), (0, 0.5)])) == [51, 52]
  assert stepped(drive(make(50), [(LIGHT_UP, 0.40), (0, 0.02), (LIGHT_UP, 0.40), (0, 0.5)])) == [51, 52, 53, 54]


def test_direction_flip_without_release_is_a_new_press():
  assert stepped(drive(make(50), [(LIGHT_UP, 0.1), (LIGHT_DOWN, 0.1), (0, 0.2)])) == [51, 50]


def test_fractional_set_is_rounded_to_a_whole_unit_before_the_step():
  h = make(50)
  h.v_cruise_kph = 50.4 * MPH
  assert stepped(drive(h, [(LIGHT_UP, 0.1), (0, 0.1)])) == [51]
  h = make(50)
  h.v_cruise_kph = 50.6 * MPH
  assert stepped(drive(h, [(LIGHT_DOWN, 0.1), (0, 0.1)])) == [50]
  h = make(50)
  h.v_cruise_kph = 51.6 * MPH
  assert stepped(drive(h, [(DEEP_UP, 0.1), (0, 0.1)])) == [55]


def test_metric_steps_whole_kph_and_5s():
  assert stepped(drive(make(80, metric=True), [(LIGHT_UP, 0.8), (0, 0.2)], metric=True)) == [81, 82, 83, 84]
  assert stepped(drive(make(82, metric=True), [(DEEP_UP, 1.0), (0, 0.2)], metric=True)) == [85]
  assert stepped(drive(make(80, metric=True), [(DEEP_DOWN, 1.0), (0, 0.2)], metric=True)) == [75]


def test_not_enabled_or_enabled_after_the_press_changes_nothing():
  h = make(50)
  assert stepped(drive(h, [(LIGHT_UP, 1.0), (0, 0.2)], enabled=False)) == [50]
  h = make(50)
  drive(h, [(LIGHT_UP, 0.05)], enabled=False)           # lever down while long is not ours (tip engage) ...
  assert stepped(drive(h, [(LIGHT_UP, 1.0), (0, 0.2)], enabled=True)) == [50]   # ... enabling mid-press never steps or repeats


def test_standstill_up_tip_never_steps_but_down_may():
  assert stepped(drive(make(50), [(LIGHT_UP, 1.0), (0, 0.2)], standstill=True)) == [50]
  assert stepped(drive(make(50), [(DEEP_UP, 1.0), (0, 0.2)], standstill=True)) == [50]


def test_down_tip_with_gas_never_goes_below_v_ego():
  h = make(50)
  out = drive(h, [(LIGHT_DOWN, 1.0), (0, 0.2)], gas=True, v_ego=48 * CV.MPH_TO_MS)
  assert min(out) >= 48 - 0.1


def test_limits_min_and_max():
  h = make(6)
  assert min(drive(h, [(LIGHT_DOWN, 2.0)])) * MPH >= 8 - 1e-6
  h = make(89)
  assert max(drive(h, [(LIGHT_UP, 3.0)])) * MPH <= 145.0 + 0.2   # display rounding of 145 km/h (90.1 mph)
  assert h.v_cruise_kph <= 145.0 + 1e-6


def test_other_cars_keep_the_stock_timer_logic():
  """Not Tesla Pre-AP: the stock VCruiseHelper long press (+5 at 50 ticks) is unchanged."""
  from opendbc.car.structs import car
  BE, BT = car.CarState.ButtonEvent, car.CarState.ButtonEvent.Type
  h = VCruiseHelper(NS(pcmCruise=False, carFingerprint="TOYOTA_COROLLA"))
  assert h._tesla_rpt is None
  h.v_cruise_kph = 80.0
  press = BE(type=BT.accelCruise, pressed=True)
  c = cs(0)
  c.buttonEvents = [press]
  h.update_v_cruise(c, True, True)
  c.buttonEvents = []
  for _ in range(60):
    h.update_v_cruise(c, True, True)
  assert h.v_cruise_kph == 85.0


def test_pcm_cruise_tesla_is_untouched():
  h = VCruiseHelper(NS(pcmCruise=True, carFingerprint="TESLA_PREAP_MODELS"))
  c = cs(LIGHT_UP)
  c.cruiseState.speed = 20.0
  c.cruiseState.speedCluster = 20.0
  h.update_v_cruise(c, True, False)
  assert h.v_cruise_kph == pytest.approx(20.0 * CV.MS_TO_KPH)


def test_capture_and_moving_double_pull_floor_are_untouched():
  h = make(50)
  h.capture_preap_full(8.4 * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=15 * MPH)
  assert h.v_cruise_kph == pytest.approx(15 * MPH)
  h.capture_preap_full(22.4 * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=15 * MPH)
  assert h.v_cruise_kph == pytest.approx(22 * MPH)
  # a tip after the capture steps from the whole captured speed
  assert stepped(drive(h, [(LIGHT_UP, 0.1), (0, 0.1)])) == [23]
