"""v6: the stalk tip behaves the same on AP1 and Pre-AP.

While lat is active and long is not (after the first pull, or after a brake override ended long), a tip up/down latches the CURRENT
speed rounded to a whole display unit (mph) and engages long; once long is engaged, tips adjust the set normally. AP1 rounds its tip
latch the same way (op_long_set_speed.py rule 2, slc_raise.round_latch_ms). Pre-AP pedal only; no-pedal is unchanged.
"""
import math

import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1 import op_long_set_speed as OLS
from opendbc.car.tesla_ap1 import slc_raise
from opendbc.car.tesla_ap1.preap.engagement import Mode, PreAPEngagement
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_engagement import full, step
from opendbc.car.tesla_ap1.tests.test_preap_from_stop_v5 import TIP_DN, TIP_UP, Card, _settle, tip

MPH = CV.MPH_TO_KPH


# ---- Pre-AP FSM: tip after a brake override ----

def _full_then_brake_override(e, v=10.0):
  full(e, 0, v_ego=v)
  assert e.mode == Mode.FULL
  d = step(e, 400, op=True, brake=True, v_ego=v)         # brake edge while moving: speed control off, steering stays
  assert d.mode == Mode.LAT_ONLY and d.lat_only and not d.long_wanted


def test_tip_after_brake_override_engages_long_with_a_capture():
  e = PreAPEngagement()
  _full_then_brake_override(e)
  step(e, 450, op=True, brake=False)                      # brake released
  d = tip(e, 500, v_ego=10.0)
  assert d.mode == Mode.FULL and d.long_wanted and d.capture_edge and d.capture_tip and not d.capture_from_stop


def test_tip_with_the_brake_still_held_while_moving_is_refused():
  e = PreAPEngagement()
  _full_then_brake_override(e)
  d = tip(e, 500, v_ego=10.0, brake=True)
  assert d.mode == Mode.LAT_ONLY and not d.long_wanted


def test_gas_override_does_not_leave_full_so_a_tip_is_a_normal_adjust():
  e = PreAPEngagement()
  full(e, 0)
  d = step(e, 400, op=True, gas=True)
  assert d.mode == Mode.FULL                              # the accelerator never ends FULL on Pre-AP (openpilot's override state does)
  d = tip(e, 500, gas=True)
  assert d.mode == Mode.FULL and not d.capture_edge       # a tip in FULL is a set-speed step, never a new latch


def test_no_tip_entry_from_off_or_after_cancel():
  e = PreAPEngagement()
  assert tip(e, 0).mode == Mode.OFF
  full(e, 100)
  step(e, 600, op=True, cancel=True)                      # stalk cancel ends the session
  assert tip(e, 700).mode == Mode.OFF


# ---- Pre-AP real car state + card set-speed order ----

def _full_rolling(k, v_kph):
  _settle(k, 200, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  _settle(k, 9, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  _settle(k, 60, v_kph=v_kph)
  assert k.c.mode == Mode.FULL


@pytest.mark.parametrize("mph,want", [(12.6, 13), (12.4, 12), (30.6, 31)])
def test_rig_tip_after_brake_override_latches_the_rounded_current_speed(mph, want):
  k = Card()
  v = 12.6 * MPH
  _full_rolling(k, v)
  _settle(k, 3, v_kph=v, brake=True)                      # brake override while rolling
  assert k.c.mode == Mode.LAT_ONLY
  out = _settle(k, 40, v_kph=mph * MPH)                   # brake released, speed now mph
  assert out.bogpilot.preapLatOnly
  k.step(stalk=TIP_UP, v_kph=mph * MPH)
  out = k.step(stalk=0, v_kph=mph * MPH)
  assert k.c.mode == Mode.FULL and not out.bogpilot.preapLatOnly
  assert abs(k.mph() - want) < 0.01, "whole mph, and the engaging tip's own +1 is replaced by the latch"
  _settle(k, 20, v_kph=mph * MPH)
  assert any(any(e["enabled"]) for e in k.c.log[-10:]), "pedal ENABLE flows"
  k.step(stalk=TIP_UP, v_kph=mph * MPH)
  k.step(stalk=0, v_kph=mph * MPH)
  assert abs(k.mph() - (want + 1)) < 0.1, "once engaged a tip is a normal +1 step"


def test_rig_tip_from_first_pull_latches_rounded_speed_not_exact():
  k = Card()
  v = 17.6 * MPH
  _settle(k, 200, v_kph=v)
  k.step(stalk=PULL, v_kph=v)
  _settle(k, 60, v_kph=v)
  k.step(stalk=TIP_DN, v_kph=v)
  k.step(stalk=0, v_kph=v)
  assert abs(k.mph() - 18) < 0.01 and k.c.mode == Mode.FULL


def test_rig_brake_held_tip_does_not_engage():
  k = Card()
  v = 14 * MPH
  _full_rolling(k, v)
  _settle(k, 3, v_kph=v, brake=True)
  k.step(stalk=TIP_UP, v_kph=v, brake=True)
  out = k.step(stalk=0, v_kph=v, brake=True)
  assert k.c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly


# ---- AP1: the tip latch is a whole display unit ----

def _engage(ols, v_ms, tap=True, pull=False, limit_ms=0.0, standstill=False, is_metric=False):
  ols.update("STANDBY", v_ms, standstill, tap=tap, pull=pull)
  return ols.update("ENABLED", v_ms, standstill, limit_ms=limit_ms, is_metric=is_metric)


@pytest.mark.parametrize("mph,want", [(12.6, 13), (12.4, 12), (30.6, 31), (45.0, 45), (6.7, 7)])
def test_ap1_rolling_tap_latches_whole_mph(mph, want):
  v = OLS.OpLongSetSpeed()
  out = _engage(v, mph * CV.MPH_TO_MS)
  assert out * CV.MS_TO_MPH == pytest.approx(want, abs=1e-6)


def test_ap1_rolling_tap_metric_latches_whole_kph():
  out = _engage(OLS.OpLongSetSpeed(), 50.4 * CV.KPH_TO_MS, is_metric=True)
  assert out * CV.MS_TO_KPH == pytest.approx(50.0, abs=1e-6)


def test_ap1_no_stalk_and_pull_without_limit_also_round():
  assert _engage(OLS.OpLongSetSpeed(), 20.4 * CV.MPH_TO_MS, tap=False) * CV.MS_TO_MPH == pytest.approx(20.0, abs=1e-6)
  assert _engage(OLS.OpLongSetSpeed(), 20.6 * CV.MPH_TO_MS, tap=False, pull=True) * CV.MS_TO_MPH == pytest.approx(21.0, abs=1e-6)


def test_ap1_single_pull_with_a_known_limit_is_unchanged():
  out = _engage(OLS.OpLongSetSpeed(), 12.6 * CV.MPH_TO_MS, tap=False, pull=True, limit_ms=25 * CV.MPH_TO_MS)
  assert out * CV.MS_TO_MPH == pytest.approx(25.0, abs=1e-6)       # SLC + offset, no rounding of the limit path


def test_ap1_standstill_tap_is_still_the_from_stop_value_and_tiny_speed_never_becomes_zero():
  out = _engage(OLS.OpLongSetSpeed(), 0.0, standstill=True)
  assert out * CV.MS_TO_MPH == pytest.approx(15.0, abs=1e-6)
  assert OLS.round_whole_kph(0.3 * MPH) == pytest.approx(0.3 * MPH)  # under half a mph keeps the exact latch (never 0)


def test_ap1_tap_while_rolling_then_stop_uses_the_rounded_tap_speed():
  v = OLS.OpLongSetSpeed()
  v.update("STANDBY", 12.6 * CV.MPH_TO_MS, False, tap=True)
  out = v.update("ENABLED", 0.0, True)
  assert out * CV.MS_TO_MPH == pytest.approx(13.0, abs=1e-6)


@pytest.mark.parametrize("mph,metric,want", [(12.6, False, 13.0), (12.4, False, 12.0), (50.4, True, 50.0), (0.3, False, 0.3)])
def test_ap1_planner_latch_round_latch_ms(mph, metric, want):
  unit = CV.KPH_TO_MS if metric else CV.MPH_TO_MS
  back = CV.MS_TO_KPH if metric else CV.MS_TO_MPH
  assert slc_raise.round_latch_ms(mph * unit, metric) * back == pytest.approx(want, abs=1e-6)
  assert slc_raise.round_latch_ms(0.0) == 0.0
  assert math.isfinite(slc_raise.round_latch_ms(10.0))


# ---- panda gate: a tip never re-arms controls_allowed ----

def test_rig_tip_after_brake_override_is_refused_when_the_panda_reports_controls_not_allowed():
  from opendbc.car.tesla_ap1.preap.panda_link import LinkInput
  k = Card()
  v = 12.6 * MPH
  _full_rolling(k, v)
  _settle(k, 3, v_kph=v, brake=True)
  _settle(k, 40, v_kph=v)
  k.c.rig.cs.preap_link = LinkInput(controls_allowed=False)    # the panda dropped controls on the brake press (safety.h:360)
  k.step(stalk=TIP_UP, v_kph=v)
  out = k.step(stalk=0, v_kph=v)
  assert k.c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly, "needs a new pull: only a pull sets controls_allowed"
  k.c.rig.cs.preap_link = LinkInput(controls_allowed=True)
  k.step(stalk=TIP_UP, v_kph=v)
  k.step(stalk=0, v_kph=v)
  assert k.c.mode == Mode.FULL


def test_tip_never_sets_controls_allowed_in_the_panda_source():
  import pathlib
  h = pathlib.Path(__file__).resolve().parents[3] / "safety" / "modes" / "tesla_preap.h"
  src = h.read_text()
  body = src[src.index("static void tesla_preap_stalk"):src.index("tesla_preap_lever_engage_prev = (lever == 2);")]
  assert body.count("pcm_cruise_check(true)") == 1 and "if (lever == 2)" in body, "only the pull (lever 2) arms controls"
  assert "lever == 4" not in body and "lever == 8" not in body and "lever == 16" not in body and "lever == 32" not in body


@pytest.mark.parametrize("v", [1.0, 3.0, 6.0])
def test_tip_below_from_stop_never_asks_for_the_raise_but_a_double_pull_does(v):
  # below the from-stop speed a tip latches the current speed (capture_tip, no from-stop); a moving double pull is raised (Auto Speed ON).
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=v)
  step(e, 10, op=True, v_ego=v)
  d = step(e, 600, op=True, v_ego=v)
  assert d.mode == Mode.LAT_ONLY
  d = tip(e, 700, v_ego=v)
  assert d.mode == Mode.FULL and d.capture_tip and not d.capture_from_stop
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=v)
  step(e, 10, op=True, v_ego=v)
  d = step(e, 250, pull=True, op=True, v_ego=v, auto_speed=True)
  assert d.mode == Mode.FULL and d.capture_from_stop and not d.capture_tip
