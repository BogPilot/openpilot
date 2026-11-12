"""Stalk set-speed rules: deep (next/prev 5 mph), shallow (±1 mph), rolling exact vEgo, standstill tap-from-0."""
import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1.op_long_set_speed import TAP_FROM_ZERO_KPH
from opendbc.car.tesla_ap1.slc_raise import Ap1RaiseHoldoff, next_5_ms, prev_5_ms, step_1_ms

MPH = CV.MPH_TO_MS
DT = Ap1RaiseHoldoff.DT_DEFAULT


def test_deep_tip_helpers_from_non_multiple_and_exact_multiple():
  assert next_5_ms(37 * MPH) == pytest.approx(40 * MPH)
  assert prev_5_ms(37 * MPH) == pytest.approx(35 * MPH)
  assert next_5_ms(40 * MPH) == pytest.approx(45 * MPH)
  assert prev_5_ms(40 * MPH) == pytest.approx(35 * MPH)


def test_shallow_tip_helpers_plus_minus_one():
  assert step_1_ms(37 * MPH, 1) == pytest.approx(38 * MPH)
  assert step_1_ms(37 * MPH, -1) == pytest.approx(36 * MPH)
  assert step_1_ms(40 * MPH, 1) == pytest.approx(41 * MPH)
  assert step_1_ms(40 * MPH, -1) == pytest.approx(39 * MPH)


def _hold(v_ego=20 * MPH, current=37 * MPH, tap_from_zero=True):
  h = Ap1RaiseHoldoff()
  if tap_from_zero:
    h.tap_from_zero_ms = TAP_FROM_ZERO_KPH * CV.KPH_TO_MS
  # Engage first so later tips are the already-enabled path.
  h.update(False, False, True, False, 0.0, v_ego, current_set_ms=current, dt=DT)
  h.update(True, False, True, False, 0.0, v_ego, current_set_ms=current, dt=DT)
  h.update(True, False, False, False, 0.0, v_ego, current_set_ms=current, dt=DT)
  return h


def test_deep_up_down_from_non_multiple_and_exact_multiple():
  h = _hold(current=37 * MPH)
  h.update(True, False, True, False, 0.0, 20 * MPH, current_set_ms=37 * MPH, dt=DT, tip_full=True)
  assert h.tip_ms == pytest.approx(40 * MPH)
  h.update(True, False, False, False, 0.0, 20 * MPH, current_set_ms=40 * MPH, dt=DT)
  h.update(True, True, False, False, 0.0, 20 * MPH, current_set_ms=40 * MPH, dt=DT, tip_full=True)
  assert h.tip_ms == pytest.approx(35 * MPH)

  h = _hold(current=40 * MPH)
  h.update(True, False, True, False, 0.0, 20 * MPH, current_set_ms=40 * MPH, dt=DT, tip_full=True)
  assert h.tip_ms == pytest.approx(45 * MPH)
  h.update(True, False, False, False, 0.0, 20 * MPH, current_set_ms=45 * MPH, dt=DT)
  h.update(True, True, False, False, 0.0, 20 * MPH, current_set_ms=45 * MPH, dt=DT, tip_full=True)
  assert h.tip_ms == pytest.approx(40 * MPH)
  # deep from an exact multiple 40 goes to 35
  h.update(True, False, False, False, 0.0, 20 * MPH, current_set_ms=40 * MPH, dt=DT)
  # reset tip by using current 40 after clearing? tip_ms is still 40; deep down from 40:
  # After 45->40, tip is 40. Need another cycle from exact 40 down to 35.
  h2 = _hold(current=40 * MPH)
  h2.update(True, True, False, False, 0.0, 20 * MPH, current_set_ms=40 * MPH, dt=DT, tip_full=True)
  assert h2.tip_ms == pytest.approx(35 * MPH)


def test_shallow_plus_minus_one_while_moving_with_a_set():
  h = _hold(current=37 * MPH)
  h.update(True, False, True, False, 0.0, 20 * MPH, current_set_ms=37 * MPH, dt=DT, tip_full=False)
  assert h.tip_ms == pytest.approx(38 * MPH)
  h.update(True, False, False, False, 0.0, 20 * MPH, current_set_ms=38 * MPH, dt=DT)
  h.update(True, True, False, False, 0.0, 20 * MPH, current_set_ms=38 * MPH, dt=DT, tip_full=False)
  assert h.tip_ms == pytest.approx(37 * MPH)


def test_rolling_no_set_tap_or_engage_latches_exact_vego():
  v = 22.4 * MPH  # not a multiple of 5
  h = Ap1RaiseHoldoff()
  h.tap_from_zero_ms = TAP_FROM_ZERO_KPH * CV.KPH_TO_MS
  h.update(False, False, True, False, 0.0, v, current_set_ms=0.0, dt=DT)
  allow, sticky = h.update(True, False, True, False, 0.0, v, current_set_ms=0.0, dt=DT)
  assert sticky == pytest.approx(v)
  assert h.tip_ms == 0.0

  # Already enabled, no existing set, rolling tap: exact vEgo, not 15 mph and not next-5.
  h = Ap1RaiseHoldoff()
  h.tap_from_zero_ms = TAP_FROM_ZERO_KPH * CV.KPH_TO_MS
  h.update(True, False, False, False, 0.0, v, current_set_ms=0.0, dt=DT)  # enable with no recent stalk
  h.update(True, False, True, False, 0.0, v, current_set_ms=0.0, dt=DT, tip_full=True)
  assert h.tip_ms == pytest.approx(v)
  assert h.tip_ms != pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS)
  assert h.tip_ms != pytest.approx(next_5_ms(v))


def test_standstill_tap_uses_tap_from_zero_setting():
  h = Ap1RaiseHoldoff()
  h.tap_from_zero_ms = 20 * MPH
  # Engage at standstill (vEgo < 0.1 m/s) with a recent UP tap.
  h.update(False, False, True, False, 0.0, 0.0, current_set_ms=0.0, dt=DT)
  allow, sticky = h.update(True, False, True, False, 0.0, 0.0, current_set_ms=0.0, dt=DT)
  assert sticky == pytest.approx(20 * MPH)

  # Already enabled at standstill with no set: a tap uses the setting, even if deep.
  h = Ap1RaiseHoldoff()
  h.tap_from_zero_ms = 20 * MPH
  h.update(True, False, False, False, 0.0, 0.0, current_set_ms=0.0, dt=DT)
  h.update(True, False, True, False, 0.0, 0.0, current_set_ms=0.0, dt=DT, tip_full=True)
  assert h.tip_ms == pytest.approx(20 * MPH)


def test_dn_tip_from_crawl_latch_does_not_raise():
  # 0.5 kph is below TIP_MIN (1 mph ≈ 1.6 kph). A DN tip must not raise the set.
  v = 0.5 * CV.KPH_TO_MS
  assert v < Ap1RaiseHoldoff.TIP_MIN_MS

  h = Ap1RaiseHoldoff()
  h.update(True, False, False, False, 0.0, v, current_set_ms=v, dt=DT)
  h.update(True, True, False, False, 0.0, v, current_set_ms=v, dt=DT, tip_full=False)
  assert h.tip_ms > 0
  assert h.tip_ms <= v

  h = Ap1RaiseHoldoff()
  h.update(True, False, False, False, 0.0, v, current_set_ms=v, dt=DT)
  h.update(True, True, False, False, 0.0, v, current_set_ms=v, dt=DT, tip_full=True)
  assert h.tip_ms > 0
  assert h.tip_ms <= v

  # Hold upgrade from a shallow DN also must not raise a crawl latch.
  h = Ap1RaiseHoldoff()
  h.update(True, False, False, False, 0.0, v, current_set_ms=v, dt=DT)
  h.update(True, True, False, False, 0.0, v, current_set_ms=v, dt=DT, tip_full=False)
  for _ in range(int(Ap1RaiseHoldoff.TIP_HOLD_S / DT) + 2):
    h.update(True, True, False, False, 0.0, v, current_set_ms=v, dt=DT, tip_full=False)
  assert h.tip_ms > 0
  assert h.tip_ms <= v


def test_normal_dn_from_37_goes_to_35_or_36():
  h = _hold(current=37 * MPH)
  h.update(True, True, False, False, 0.0, 20 * MPH, current_set_ms=37 * MPH, dt=DT, tip_full=True)
  assert h.tip_ms == pytest.approx(35 * MPH)

  h = _hold(current=37 * MPH)
  h.update(True, True, False, False, 0.0, 20 * MPH, current_set_ms=37 * MPH, dt=DT, tip_full=False)
  assert h.tip_ms == pytest.approx(36 * MPH)
