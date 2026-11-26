"""Standstill Tap Speed stored in m/s (AP1TapFromZeroMs). Gas / Brake row helpers in both units and the card /
planner consumers (AP1 tap from stop, Pre-AP from-stop and the moving double pull raise).

The store is the real shared ParamStore over the BogPilot file store (a Params stand-in that knows no keys), so the
exact text ParamStore writes and reads is what these tests check.
"""
import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1.op_long_set_speed import OpLongSetSpeed, parse_tap_from_zero_mph
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.car.cruise import VCruiseHelper
from openpilot.selfdrive.controls.lib.phase3_speed_control import EngageTapFromZero
from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake as GB

KEY = "AP1TapFromZeroMs"


class NoKeyParams:
  def all_keys(self):
    return []

  def check_key(self, key):
    raise KeyError(key)


class NS:
  def __init__(self, **kw):
    self.__dict__.update(kw)


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "prefs"))
  return ParamStore(params=NoKeyParams())


def metric(store, on):
  store.put_bool("IsMetric", on)


def old_kph(n):
  return parse_tap_from_zero_mph(str(n)) * CV.MPH_TO_KPH   # the previous kph for a saved n mph


# ---- UI row ----

def test_key_name_and_default_row(store):
  assert GB.TAP_FROM_ZERO_KEY == KEY
  assert GB.tap_from_zero_value_text(store) == "15 mph" == GB.tap_from_zero_default_text(store)
  assert GB.tap_from_zero_is_default(store)
  metric(store, True)
  assert GB.tap_from_zero_value_text(store) == "24 km/h" == GB.tap_from_zero_default_text(store)
  assert store.raw(KEY) is None   # showing never writes


def test_imperial_steps_whole_mph_5_to_30(store):
  assert GB.nudge_tap_from_zero(store, +1) == 16
  assert store.raw(KEY) == repr(16 * 0.44704) and GB.tap_from_zero_value_text(store) == "16 mph"
  for _ in range(40):
    GB.nudge_tap_from_zero(store, +1)
  assert GB.tap_from_zero_value_text(store) == "30 mph" and float(store.raw(KEY)) == 30 * 0.44704
  for _ in range(40):
    GB.nudge_tap_from_zero(store, -1)
  assert GB.tap_from_zero_value_text(store) == "5 mph" and float(store.raw(KEY)) == 5 * 0.44704


def test_metric_steps_whole_kph_8_to_48(store):
  metric(store, True)
  assert GB.nudge_tap_from_zero(store, +1) == 25   # from the shown 24 km/h
  assert float(store.raw(KEY)) == 25 / 3.6 and GB.tap_from_zero_value_text(store) == "25 km/h"
  for _ in range(60):
    GB.nudge_tap_from_zero(store, +1)
  assert GB.tap_from_zero_value_text(store) == "48 km/h" and float(store.raw(KEY)) == 48 / 3.6
  for _ in range(60):
    GB.nudge_tap_from_zero(store, -1)
  assert GB.tap_from_zero_value_text(store) == "8 km/h" and float(store.raw(KEY)) == 8 / 3.6


def test_switching_units_never_changes_the_stored_speed(store):
  GB.nudge_tap_from_zero(store, +1)   # 16 mph
  saved = store.raw(KEY)
  for _ in range(5):
    metric(store, True)
    assert GB.tap_from_zero_value_text(store) == "26 km/h"
    metric(store, False)
    assert GB.tap_from_zero_value_text(store) == "16 mph"
  assert store.raw(KEY) == saved
  metric(store, True)
  GB.nudge_tap_from_zero(store, -1)   # 25 km/h, an edit in km/h
  saved = store.raw(KEY)
  metric(store, False)
  assert GB.tap_from_zero_value_text(store) == "16 mph"   # 15.53 mph shows as 16
  metric(store, True)
  assert GB.tap_from_zero_value_text(store) == "25 km/h" and store.raw(KEY) == saved


def test_edits_round_trip_in_their_unit(store):
  for on, steps, shown in ((False, (+1, -1), "15 mph"), (True, (+1, -1), "24 km/h")):
    metric(store, on)
    for d in steps:
      GB.nudge_tap_from_zero(store, d)
    assert GB.tap_from_zero_value_text(store) == shown


def test_edge_values_do_not_step_out_of_range_in_the_other_unit(store):
  store.put(KEY, repr(48 / 3.6))      # 48 km/h shows as 30 mph; + in mph is refused, nothing written
  assert GB.tap_from_zero_value_text(store) == "30 mph"
  assert GB.nudge_tap_from_zero(store, +1) == 30 and store.raw(KEY) == repr(48 / 3.6)
  store.put(KEY, repr(5 * 0.44704))   # 5 mph shows as 8 km/h; - in km/h is refused
  metric(store, True)
  assert GB.tap_from_zero_value_text(store) == "8 km/h"
  assert GB.nudge_tap_from_zero(store, -1) == 8 and store.raw(KEY) == repr(5 * 0.44704)


def test_locked_row_writes_nothing(store):
  assert GB.nudge_tap_from_zero(store, +1, can_edit=lambda: False) == 15
  assert store.raw(KEY) is None


@pytest.mark.parametrize("raw", ["", "foo", "nan", "inf", "99", "0", "-3"])
def test_invalid_value_shows_and_steps_from_the_default(store, raw):
  store.put(KEY, raw)
  assert GB.tap_from_zero_value_text(store) == "15 mph" and GB.tap_from_zero_is_default(store)
  assert GB.nudge_tap_from_zero(store, +1) == 16


def test_reset_writes_the_default_in_ms(store):
  GB.nudge_tap_from_zero(store, +1)
  assert not GB.tap_from_zero_is_default(store)
  GB.reset_tap_from_zero(store, KEY, GB.tap_from_zero_default_ms(), can_edit=lambda: True, long_on=lambda: True)
  assert store.raw(KEY) == "6.7056" and GB.tap_from_zero_is_default(store)


def test_24_kph_is_not_the_15_mph_default(store):
  store.put(KEY, repr(24 / 3.6))
  assert GB.tap_from_zero_value_text(store) == "15 mph" and not GB.tap_from_zero_is_default(store)


# ---- consumers: identical speeds for migrated values ----

def migrated(store, n):
  store.put(KEY, repr(n * 0.44704))   # what migrate_tap_from_zero_ms writes for a saved n mph
  return EngageTapFromZero(store=store, clock=lambda: 0.0)


def test_engage_helper_kph_and_ms_identical_for_every_migrated_value(store):
  for n in range(5, 31):
    helper = migrated(store, n)
    assert helper() == old_kph(n)
    assert helper.ms() == old_kph(n) * CV.KPH_TO_MS


def test_engage_helper_default_and_invalid(store):
  assert EngageTapFromZero(store=store, clock=lambda: 0.0)() == old_kph(15)
  store.put(KEY, "garbage")
  assert EngageTapFromZero(store=store, clock=lambda: 0.0)() == old_kph(15)


def _ap1_tap(kph):
  car = OpLongSetSpeed()
  car.update("STANDBY", 0.0, True, tap=True, tap_from_zero_kph=kph)
  return car.update("ENABLED", 0.0, True, tap_from_zero_kph=kph)


def test_ap1_tap_from_stop_identical(store):
  for n in range(5, 31):
    assert _ap1_tap(migrated(store, n)()) == _ap1_tap(old_kph(n))


def _preap():
  return VCruiseHelper(NS(pcmCruise=False))


def test_preap_from_stop_first_pull_and_full_capture_identical(store):
  for n in range(5, 31):
    new, old = migrated(store, n)(), old_kph(n)
    a, b = _preap(), _preap()
    cs = NS(vEgo=0.0, buttonEvents=[])
    a.initialize_v_cruise(cs, False, preap_from_stop_kph=new)
    b.initialize_v_cruise(cs, False, preap_from_stop_kph=old)
    assert a.v_cruise_kph == b.v_cruise_kph
    for metric_on in (False, True):
      a.capture_preap_full(0.0, 0.0, is_metric=metric_on, from_stop_kph=new)
      b.capture_preap_full(0.0, 0.0, is_metric=metric_on, from_stop_kph=old)
      assert a.v_cruise_kph == b.v_cruise_kph == pytest.approx(n * CV.MPH_TO_KPH)


def test_preap_moving_double_pull_raise_identical(store):
  """A moving double pull below the from-stop speed is raised to it; above it keeps the current speed."""
  for n in (5, 15, 20, 30):
    new, old = migrated(store, n)(), old_kph(n)
    for v_mph in (3.4, n - 0.6, n + 2.4):
      a, b = _preap(), _preap()
      a.capture_preap_full(v_mph * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=new)
      b.capture_preap_full(v_mph * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=old)
      assert a.v_cruise_kph == b.v_cruise_kph
