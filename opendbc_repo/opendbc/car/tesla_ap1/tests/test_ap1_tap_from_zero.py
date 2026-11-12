"""Planner side of the AP1 openpilot-long tap from 0 (slc_raise.Ap1RaiseHoldoff / ap1_cruise_ms)."""
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1.op_long_set_speed import TAP_FROM_ZERO_KPH
from opendbc.car.tesla_ap1.slc_raise import Ap1RaiseHoldoff, ap1_cruise_ms

TAP_MS = TAP_FROM_ZERO_KPH * CV.KPH_TO_MS


def _engage_with_tap(hold, v_ego=0.0):
  hold.update(False, False, True, False, 0.0, v_ego)          # UP tap, not engaged
  return hold.update(True, False, False, False, 0.0, v_ego)   # engage within the recent window


def test_legacy_sticky_zero_unchanged_when_off():
  hold = Ap1RaiseHoldoff()
  allow, sticky = _engage_with_tap(hold)
  assert sticky == 0.0 and not allow


def test_tap_engage_at_standstill_is_15_mph():
  hold = Ap1RaiseHoldoff()
  hold.tap_from_zero_ms = TAP_MS
  _allow, sticky = _engage_with_tap(hold)
  assert sticky == TAP_MS


def test_engaged_tip_from_zero_is_15_mph():
  for lever in ("up", "dn"):
    hold = Ap1RaiseHoldoff()
    hold.tap_from_zero_ms = TAP_MS
    hold.update(True, False, False, False, 0.0, 0.0)
    hold.update(True, lever == "dn", lever == "up", False, 0.0, 0.0, current_set_ms=0.0)
    assert hold.tip_ms == TAP_MS


def test_sticky_zero_is_none_only_when_asked():
  assert ap1_cruise_ms(5.0, 0.0, 0.0, False, None, 0.0, 6.7, False, 0.0) == 0.0
  assert ap1_cruise_ms(5.0, 0.0, 0.0, False, None, 0.0, 6.7, False, 0.0, sticky_zero_is_none=True) == 5.0
  assert ap1_cruise_ms(5.0, 3.0, 0.0, False, None, 0.0, 6.7, False, 0.0, sticky_zero_is_none=True) == 3.0
