"""t1453: the Standstill Tap Speed is stored in m/s (AP1TapFromZeroMs) and shown in whole mph or whole km/h (IsMetric).

Parser bounds and invalid fallback, both display units, the display round trip, and the kph the car / planner get:
bit for bit the same as the pre-t1453 whole-mph setting for every value it could hold (5-30 mph).
"""
import math

import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1 import op_long_set_speed as ols
from opendbc.car.tesla_ap1.op_long_set_speed import (
  TAP_FROM_ZERO_DEFAULT_MS, TAP_FROM_ZERO_KPH, TAP_FROM_ZERO_MAX_MS, TAP_FROM_ZERO_MIN_MS, OpLongSetSpeed,
  format_ms_text, format_tap_from_zero_display, legacy_mph_valid, mph_to_ms, kph_to_ms, parse_tap_from_zero_mph,
  parse_tap_from_zero_ms, tap_from_zero_display_bounds, tap_from_zero_display_to_ms, tap_from_zero_display_value,
  tap_from_zero_kph_from_ms, tap_from_zero_kph_from_param,
)
from opendbc.car.tesla_ap1.slc_raise import Ap1RaiseHoldoff

MPHS = range(5, 31)
KPHS = range(8, 49)


def old_kph(mph_text):
  """The pre-t1453 consumer: tap_from_zero_kph_from_param(AP1TapFromZeroMph) = parse_tap_from_zero_mph(raw) * MPH_TO_KPH."""
  return parse_tap_from_zero_mph(mph_text) * CV.MPH_TO_KPH


def test_key_and_default():
  assert ols.TAP_FROM_ZERO_PARAM == "AP1TapFromZeroMs"
  assert ols.TAP_FROM_ZERO_LEGACY_MPH_PARAM == "AP1TapFromZeroMph"
  assert TAP_FROM_ZERO_DEFAULT_MS == 15 * 0.44704 == 6.7056
  assert format_ms_text(TAP_FROM_ZERO_DEFAULT_MS) == "6.7056"
  assert tap_from_zero_kph_from_param(None) == TAP_FROM_ZERO_KPH   # exactly 15 * 1.609344, as before


def test_migration_rule_is_exact_for_every_old_value():
  for n in MPHS:
    ms = mph_to_ms(n)
    assert ms == n * 0.44704
    assert float(format_ms_text(ms)) == ms   # stored text reads back bit for bit
    assert parse_tap_from_zero_ms(format_ms_text(ms)) == ms


@pytest.mark.parametrize("raw", [None, "", "  ", "foo", "nan", "inf", "-inf", "1e400", True, False, object(), b"\xff",
                                 "2.2", "13.42", "0", "-6.7056", 13.5, 2.0, float("nan")])
def test_invalid_or_out_of_range_falls_back_to_15_mph(raw):
  assert parse_tap_from_zero_ms(raw) == TAP_FROM_ZERO_DEFAULT_MS
  assert tap_from_zero_kph_from_param(raw) == TAP_FROM_ZERO_KPH


def test_bounds_are_8_kph_to_30_mph_and_never_clamped():
  assert TAP_FROM_ZERO_MIN_MS == 8 / 3.6
  assert TAP_FROM_ZERO_MAX_MS == 30 * 0.44704
  assert parse_tap_from_zero_ms(format_ms_text(8 / 3.6)) == 8 / 3.6
  assert parse_tap_from_zero_ms(format_ms_text(30 * 0.44704)) == 30 * 0.44704
  assert parse_tap_from_zero_ms(b"8.9408") == 8.9408
  assert parse_tap_from_zero_ms(8 / 3.6 - 1e-3) == TAP_FROM_ZERO_DEFAULT_MS   # not clamped to the edge
  assert parse_tap_from_zero_ms(30 * 0.44704 + 1e-3) == TAP_FROM_ZERO_DEFAULT_MS
  assert tap_from_zero_display_bounds(False) == (5, 30)
  assert tap_from_zero_display_bounds(True) == (8, 48)


def test_display_whole_mph_and_whole_kph():
  for n in MPHS:
    ms = mph_to_ms(n)
    assert format_tap_from_zero_display(ms, False) == f"{n} mph"
    assert format_tap_from_zero_display(ms, True) == f"{int(math.floor(n * 1.609344 + 0.5))} km/h"
  for k in KPHS:
    ms = kph_to_ms(k)
    assert format_tap_from_zero_display(ms, True) == f"{k} km/h"
    assert 5 <= tap_from_zero_display_value(ms, False) <= 30   # every metric value shows inside the mph range
  assert format_tap_from_zero_display(TAP_FROM_ZERO_DEFAULT_MS, False) == "15 mph"
  assert format_tap_from_zero_display(TAP_FROM_ZERO_DEFAULT_MS, True) == "24 km/h"
  assert format_tap_from_zero_display(mph_to_ms(5), True) == "8 km/h"
  assert format_tap_from_zero_display(mph_to_ms(30), True) == "48 km/h"
  assert format_tap_from_zero_display(kph_to_ms(8), False) == "5 mph"
  assert format_tap_from_zero_display(kph_to_ms(48), False) == "30 mph"


def test_display_round_trip_without_drift():
  """A shown whole unit stored and read back shows the same number in that unit, and the stored float is unchanged
  by reading it in the other unit (the display never writes)."""
  for metric, values in ((False, MPHS), (True, KPHS)):
    for v in values:
      ms = tap_from_zero_display_to_ms(v, metric)
      text = format_ms_text(ms)
      for _ in range(3):
        back = parse_tap_from_zero_ms(text)
        assert back == ms
        assert tap_from_zero_display_value(back, metric) == v
        tap_from_zero_display_value(back, not metric)   # other unit: display only
        text = format_ms_text(back)
      assert text == format_ms_text(ms)


def test_kph_identical_to_before_for_every_migrated_value():
  for n in MPHS:
    assert tap_from_zero_kph_from_param(format_ms_text(mph_to_ms(n))) == old_kph(str(n))   # bit for bit
    assert tap_from_zero_kph_from_ms(mph_to_ms(n)) == n * CV.MPH_TO_KPH


def test_metric_edits_give_whole_kph():
  for k in KPHS:
    assert tap_from_zero_kph_from_param(format_ms_text(kph_to_ms(k))) == float(k)
  assert tap_from_zero_kph_from_ms(5.0) == pytest.approx(18.0)   # neither unit: plain ms * 3.6


def test_legacy_parser_and_validity():
  for n in MPHS:
    assert legacy_mph_valid(str(n)) and legacy_mph_valid(n) and legacy_mph_valid(float(n))
  for raw in (None, "", "foo", "15.5", 15.5, "4", "31", True, b"\xff"):
    assert not legacy_mph_valid(raw)


def _tap_engage(tap_kph):
  car = OpLongSetSpeed()
  car.update("STANDBY", 0.0, True, tap=True, tap_from_zero_kph=tap_kph)
  return car.update("ENABLED", 0.0, True, tap_from_zero_kph=tap_kph)


def test_ap1_car_tap_from_stop_identical_for_migrated_values():
  for n in MPHS:
    new = _tap_engage(tap_from_zero_kph_from_param(format_ms_text(mph_to_ms(n))))
    assert new == _tap_engage(old_kph(str(n)))
    assert new == pytest.approx(n * 0.44704, abs=1e-9)


def test_ap1_planner_tap_from_stop_identical_for_migrated_values():
  for n in MPHS:
    outs = []
    for kph in (old_kph(str(n)), tap_from_zero_kph_from_param(format_ms_text(mph_to_ms(n)))):
      hold = Ap1RaiseHoldoff()
      hold.tap_from_zero_ms = kph * CV.KPH_TO_MS   # EngageTapFromZero.ms()
      hold.update(False, False, True, False, 0.0, 0.0)
      outs.append(hold.update(True, False, False, False, 0.0, 0.0))
    assert outs[0] == outs[1]
