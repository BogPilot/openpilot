"""Pre-AP "pedal not responding": carState.bogpilot.preapPedalNotResponding and the Ap1Events rewrite."""
from types import SimpleNamespace

import pytest

from opendbc.car import Bus
from opendbc.car.tesla_ap1.ap1_events import Ap1Events, PEDAL_NOT_RESPONDING, PEDAL_RETRYING, WRONG_CAR_MODE
from opendbc.car.tesla_ap1.preap import calib
from opendbc.car.tesla_ap1.preap.pedal_feedback import PEDAL_TIMEOUT_MS
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import CLOCK, Rig, _params_dir  # noqa: F401  (autouse fixture)
from opendbc.car.tesla_ap1.values import CANBUS


class PedalRig(Rig):
  """The shared Rig plus a Comma Pedal that sends GAS_SENSOR on the cam bus (pedal CAN bus 2, the default)."""

  def __init__(self, long=True):
    super().__init__(long=long)
    self.idx = 0

  def pedal_frame(self, advance=True, **extra):
    if advance:
      self.idx = (self.idx + 1) % 16
    values = {"INTERCEPTOR_GAS": 10.0, "INTERCEPTOR_GAS2": 10.0, "STATE": 0, "IDX": self.idx}
    values.update(extra)
    addr, dat, _ = self.packer.make_can_msg("GAS_SENSOR", 0, values)
    self.parsers[Bus.cam].update([(self.nanos, [(addr, dat, CANBUS.autopilot_chassis)])])

  def step(self, pedal=True, advance=True):
    """One 10 ms car frame; the pedal sends every 2nd frame (50 Hz) while it is alive."""
    if pedal and (int(CLOCK[0] * 100) % 2 == 0):
      self.pedal_frame(advance=advance)
    elif not pedal:
      # card updates every parser every step; an update with no GAS_SENSOR frame empties vl_all, as on the car
      self.parsers[Bus.cam].update([(self.nanos, [])])
    return self.frame()

  def run_ms(self, ms, **kw):
    out = None
    for _ in range(ms // 10):
      out = self.step(**kw)
    return out


def test_a_live_pedal_is_never_flagged():
  r = PedalRig()
  out = r.run_ms(2000)
  assert not out.bogpilot.preapPedalNotResponding
  assert out.bogpilot.preapPedalDetected


def test_pedal_that_stops_is_flagged_after_the_timeout_not_before():
  r = PedalRig()
  r.run_ms(1000)
  out = r.run_ms(PEDAL_TIMEOUT_MS - 100, pedal=False)
  assert not out.bogpilot.preapPedalNotResponding            # a short gap is not an alarm
  out = r.run_ms(300, pedal=False)
  assert out.bogpilot.preapPedalNotResponding
  assert not out.cruiseState.available
  out = r.run_ms(500)                                         # it comes back: clears on its own
  assert not out.bogpilot.preapPedalNotResponding


def test_stale_stream_with_a_frozen_counter_is_flagged():
  r = PedalRig()
  r.run_ms(1000)
  out = r.run_ms(1000, advance=False)                         # frames keep arriving but the counter never moves
  assert out.bogpilot.preapPedalNotResponding


def test_a_pedal_that_was_never_heard_is_flagged_when_pedal_long_is_on():
  r = PedalRig()
  out = r.run_ms(1000, pedal=False)
  assert out.bogpilot.preapPedalNotResponding and not out.bogpilot.preapPedalDetected


def test_never_flagged_without_pedal_longitudinal():
  r = PedalRig(long=False)                                    # stock TACC (or "Disable Pedal Longitudinal" on): the pedal is not needed
  out = r.run_ms(1500, pedal=False)
  assert not out.bogpilot.preapPedalNotResponding


def test_flag_is_independent_of_calibration():
  r = PedalRig()
  r.run_ms(500)
  assert not calib.is_pedal_calibrated()
  assert not r.run_ms(500).bogpilot.preapPedalNotResponding   # uncalibrated is its own state (Needs calibration)


def _bog(**kw):
  base = dict(ap1DriverYield=False, preapLatOnly=False, ap1HandsOnLevel=0, ap1EacInhibited=False, preapPedalNotResponding=False,
              preapPedalUnavailable=False)
  base.update(kw)
  return SimpleNamespace(**base)


def test_events_add_pedal_not_responding_and_replace_cruise_mode_disabled():
  ev = Ap1Events()
  assert ev.update(["wrongCarMode"], False, False, _bog()) == ["wrongCarMode"]                  # no pedal fault: untouched
  out = ev.update(["wrongCarMode", "doorOpen"], False, False, _bog(preapPedalNotResponding=True))
  assert PEDAL_NOT_RESPONDING in out and WRONG_CAR_MODE not in out and "doorOpen" in out
  assert out.count(PEDAL_NOT_RESPONDING) == 1
  assert ev.update([PEDAL_NOT_RESPONDING], True, True, _bog(preapPedalNotResponding=True)).count(PEDAL_NOT_RESPONDING) == 1


def test_events_do_not_touch_other_rewrites():
  ev = Ap1Events()
  out = ev.update([], True, True, _bog(preapLatOnly=True, preapPedalNotResponding=True))
  assert "gasPressedOverride" in out and PEDAL_NOT_RESPONDING in out


def test_events_add_pedal_retrying_only_while_engaged_and_the_pedal_failed_to_take_authority():
  ev = Ap1Events()
  assert PEDAL_RETRYING not in ev.update([], True, True, _bog())                                       # healthy
  assert PEDAL_RETRYING not in ev.update([], False, False, _bog(preapPedalUnavailable=True))           # not engaged: nothing to retry
  out = ev.update([], True, True, _bog(preapPedalUnavailable=True))
  assert out.count(PEDAL_RETRYING) == 1 and PEDAL_NOT_RESPONDING not in out
  assert ev.update([PEDAL_RETRYING], True, True, _bog(preapPedalUnavailable=True)).count(PEDAL_RETRYING) == 1


def test_a_missing_stream_still_wins_over_retrying():
  out = Ap1Events().update(["wrongCarMode"], True, True, _bog(preapPedalUnavailable=True, preapPedalNotResponding=True))
  assert PEDAL_NOT_RESPONDING in out and PEDAL_RETRYING not in out and WRONG_CAR_MODE not in out
