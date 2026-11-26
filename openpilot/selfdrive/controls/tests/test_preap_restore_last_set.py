"""Pre-AP pedal engage set speed. Default (Pre AP Auto Speed OFF, NAP): a pull engage is a LATCHED speed, the current speed or,
on a re-engage, the LAST speed-control set of the drive (always on, moving or at a stop). An up/down tip entry from steering only
latches the current speed. Once latched, tips keep the +-1 / hold-repeat / deep-to-5 detent behaviour. Pre AP Auto Speed ON: the
pull engages the automatic speed (SetSpeedLimit) and never restores. At a stop with nothing to restore: NAP's 0, or the from-stop
speed with Pre-AP From-Stop Speed ON (which also wins over restoring at a stop) or Auto Speed ON.

Sim.step() runs the same calls, in the same order, as selfdrive/car/card.py (update_v_cruise -> note_preap_long_set ->
enable-edge initialize_v_cruise -> FULL capture edge); test_card_wires_the_same_calls checks card.py still does that."""
from pathlib import Path

import pytest

from openpilot.common.constants import CV
from openpilot.selfdrive.car import cruise
from openpilot.selfdrive.car.cruise import V_CRUISE_MIN, V_CRUISE_UNSET, PreapPullPolicy, VCruiseHelper

MPH = CV.MPH_TO_KPH
LIGHT_UP, LIGHT_DOWN, DEEP_UP = 16, 32, 4
FROM_STOP_KPH = 15 * MPH


class NS:
  def __init__(self, **kw):
    self.__dict__.update(kw)


def _cs(v_mph, lever=0, metric=False):
  v = v_mph * (CV.KPH_TO_MS if metric else CV.MPH_TO_MS)
  return NS(cruiseState=NS(available=True, standstill=False, speed=0.0, speedCluster=0.0), bogpilot=NS(spdCtrlLvr=lever),
            buttonEvents=[], gasPressed=False, vEgo=v)


class Sim:
  """One Pre-AP pedal drive as card sees it (100 Hz). enabled = openpilot engaged, long = speed control (FULL)."""

  def __init__(self, fingerprint="TESLA_PREAP_MODELS", metric=False, auto_speed=False, from_stop=False):
    self.h = VCruiseHelper(NS(pcmCruise=False, carFingerprint=fingerprint))
    self.policy = PreapPullPolicy(auto_speed, from_stop)
    self.metric = metric
    self.enabled = self.enabled_prev = self.long_prev = False
    self.v = 40.0

  def step(self, *, lever=0, capture=False, tip_entry=False, limit_kph=0.0):
    h, cs = self.h, _cs(self.v, lever, self.metric)
    h.update_v_cruise(cs, self.enabled, self.metric)
    h.note_preap_long_set(self.long_prev)
    if self.enabled and not self.enabled_prev:
      from_stop = FROM_STOP_KPH if self.policy.use_from_stop() else 0.0
      restore = h.preap_restore_kph(cs.vEgo) if self.policy.restore_allowed(cs.vEgo) else None
      h.initialize_v_cruise(cs, False, limit_kph, preap_from_stop_kph=from_stop, is_metric=self.metric, preap_restore_kph=restore)
    if capture:
      # the FSM sets capture_from_stop on a FULL that starts at a stop; card applies it only when the policy says so
      restore = None
      if not tip_entry and self.policy.restore_allowed(cs.vEgo):
        restore = h.preap_restore_kph(cs.vEgo)
      if restore is not None:
        h.restore_preap_set(restore)
      else:
        h.capture_preap_full(cs.vEgo, 0.0 if tip_entry else limit_kph, is_metric=self.metric,
                             from_stop_kph=FROM_STOP_KPH if (cs.vEgo < 0.1 and self.policy.use_from_stop()) else 0.0)
    self.enabled_prev = self.enabled
    return h.v_cruise_kph

  def run(self, n=10, **kw):
    for _ in range(n):
      self.step(**kw)
    return self.mph()

  def mph(self):
    return round(self.h.v_cruise_kph / (1.0 if self.metric else MPH), 1)

  # gestures
  def pull_engage(self, limit_kph=0.0):                # first pull: steering only
    self.enabled = True
    self.step(limit_kph=limit_kph)
    self.long_prev = False
    return self.mph()

  def double_pull_full(self, limit_kph=0.0):           # FULL capture edge from a pull
    self.step(capture=True, limit_kph=limit_kph)
    self.long_prev = True
    return self.run(5)

  def tip_full(self, lever=LIGHT_UP):                  # FULL entry by a tip while steering only (latched on the release)
    self.step(lever=lever)
    self.step(capture=True, tip_entry=True)
    self.long_prev = True
    return self.run(5)

  def brake_to_steering_only(self):
    self.long_prev = False
    return self.run(5)

  def cancel(self):
    self.enabled = False
    self.long_prev = False
    return self.run(5)

  def tip(self, lever, secs=0.05):
    for _ in range(int(round(secs / 0.01))):
      self.step(lever=lever)
    return self.run(5)


def _first_full_at(s, v, limit_kph=0.0):
  s.v = v
  s.pull_engage(limit_kph)
  return s.double_pull_full(limit_kph)


def test_first_engage_of_a_drive_is_unchanged_current_speed_or_limit():
  s = Sim()
  assert s.h.preap_last_set_kph is None
  assert _first_full_at(s, 47.0) == 47.0
  s2 = Sim()
  assert _first_full_at(s2, 47.0, limit_kph=55 * MPH) == round(int(round(55 * MPH)) / MPH, 1)   # limit path keeps its whole-kph set


def test_pull_re_engage_restores_the_last_set_not_current_speed_or_limit():
  s = Sim()
  _first_full_at(s, 50.0)
  assert s.tip(LIGHT_UP) == 51.0                   # +1 in speed control: the stored set follows it
  s.cancel()
  s.v = 38.0
  assert s.pull_engage(limit_kph=65 * MPH) == 51.0     # the HUD shows the set the double pull will use
  assert s.double_pull_full(limit_kph=65 * MPH) == 51.0


def test_tip_entry_latches_current_speed_even_with_a_stored_set():
  s = Sim()
  _first_full_at(s, 50.0)
  s.cancel()
  s.v = 38.0
  s.pull_engage()
  assert s.tip_full(LIGHT_DOWN) == 38.0
  assert s.h.preap_last_set_kph == pytest.approx(38.0 * MPH, abs=0.05)   # the latched set becomes the new last set


def test_brake_then_double_pull_restores():
  s = Sim()
  _first_full_at(s, 60.0)
  s.brake_to_steering_only()
  s.v = 45.0
  assert s.double_pull_full() == 60.0


def test_standstill_re_engage_restores_the_last_set():
  assert cruise.PREAP_RESTORE_AT_STANDSTILL is True
  s = Sim()
  _first_full_at(s, 60.0)
  s.cancel()
  s.v = 0.0
  assert s.pull_engage() == 60.0                    # the HUD shows the set the double pull will use
  assert s.double_pull_full() == 60.0               # held at 0 until the accelerator (FSM), then 60


def test_standstill_brake_then_double_pull_restores():
  s = Sim()
  _first_full_at(s, 42.0)
  s.brake_to_steering_only()
  s.v = 0.0
  assert s.double_pull_full() == 42.0


def test_standstill_first_engage_is_nap_zero_by_default():
  s = Sim()
  s.v = 0.0
  assert s.pull_engage() == 0.0                     # NAP: the current speed, no from-stop speed, no 25 mph floor
  assert s.double_pull_full() == 0.0
  assert s.h.preap_last_set_kph is None             # a 0 set is never stored, so it is never restored


def test_from_stop_toggle_on_sets_the_from_stop_speed_and_wins_over_restore_at_a_stop():
  s = Sim(from_stop=True)
  s.v = 0.0
  assert s.pull_engage() == 15.0
  assert s.double_pull_full() == 15.0
  s.cancel()
  s.v = 50.0
  s.pull_engage()
  assert s.double_pull_full() == 15.0               # moving: restores the last set (15) as usual
  assert s.tip(LIGHT_UP, secs=0.05) == 16.0
  s.cancel()
  s.v = 0.0
  s.pull_engage()
  assert s.double_pull_full() == 15.0               # at a stop: the from-stop speed, not the restored 16
  s.cancel()
  s.v = 30.0
  s.pull_engage()
  assert s.double_pull_full() == 15.0               # moving again: the last set (the from-stop 15 that was latched)


def test_tip_entry_at_a_stop_latches_zero_by_default_and_from_stop_with_the_toggle():
  s = Sim()
  _first_full_at(s, 50.0)
  s.cancel()
  s.v = 0.0
  s.pull_engage()
  assert s.tip_full(LIGHT_UP) == 0.0                # a tip always latches the current speed, never restores
  s2 = Sim(from_stop=True)
  s2.v = 0.0
  s2.pull_engage()
  assert s2.tip_full(LIGHT_UP) == 15.0


def test_zero_set_tips_step_from_the_current_speed_and_never_lift_on_a_down_tip():
  s = Sim()
  s.v = 0.0
  s.pull_engage()
  s.double_pull_full()
  assert s.tip(LIGHT_DOWN) == 0.0                   # a down tip on a 0 set stays 0 (NAP clamps at 0)
  assert s.tip(LIGHT_UP) == round(V_CRUISE_MIN / MPH, 1)   # +1 from 0 at a stop is held up by the 8 km/h floor (NAP: 1 mph)
  s2 = Sim()
  s2.v = 0.0
  s2.pull_engage()
  s2.double_pull_full()
  assert s2.tip(DEEP_UP) == 5.0                     # deep from 0: the next 5
  s3 = Sim()
  s3.v = 0.0
  s3.pull_engage()
  s3.double_pull_full()
  s3.v = 22.0                                       # the driver drove off on the accelerator; the set is still 0
  assert s3.tip(LIGHT_UP) == 23.0                   # NAP max(set, current) + 1
  s4 = Sim()
  s4.v = 0.0
  s4.pull_engage()
  s4.double_pull_full()
  s4.v = 22.0
  assert s4.tip(DEEP_UP) == 25.0


def test_auto_speed_on_engages_the_automatic_speed_never_restores():
  s = Sim(auto_speed=True)
  limit = 55 * MPH
  first = _first_full_at(s, 47.0, limit_kph=limit)
  assert first == round(int(round(limit)) / MPH, 1)
  assert s.tip(LIGHT_UP) == 56.0                    # +1 from the whole-mph base (55.3 -> 55 + 1), as before
  s.cancel()
  s.v = 40.0
  s.pull_engage(limit_kph=limit)
  assert s.double_pull_full(limit_kph=limit) == first      # the limit again, not the restored +1
  s.cancel()
  s.v = 0.0
  s.pull_engage()
  assert s.double_pull_full() == 15.0               # Auto Speed ON from a stop: the from-stop speed (unchanged)


def test_auto_speed_on_tip_entry_still_latches_current_speed():
  s = Sim(auto_speed=True)
  s.v = 38.0
  s.pull_engage(limit_kph=55 * MPH)
  assert s.tip_full(LIGHT_UP) == 38.0


@pytest.mark.parametrize("auto,toggle,v,restore,from_stop", [
  (False, False, 20.0, True, False),
  (False, False, 0.0, True, False),
  (False, True, 20.0, True, True),
  (False, True, 0.0, False, True),
  (True, False, 20.0, False, True),
  (True, False, 0.0, False, True),
  (True, True, 0.0, False, True),
])
def test_pull_policy_table(auto, toggle, v, restore, from_stop):
  p = PreapPullPolicy(auto, toggle)
  assert p.restore_allowed(v) is restore and p.use_from_stop() is from_stop


def test_pull_policy_read_fails_to_the_defaults(monkeypatch):
  from opendbc.car.tesla_ap1.preap import params as pp
  def boom():
    raise OSError
  monkeypatch.setattr(pp, "preap_auto_speed", boom)
  p = PreapPullPolicy.read()
  assert (p.auto_speed, p.from_stop_toggle) == (False, False)
  assert PreapPullPolicy().restore_allowed(0.0) and not PreapPullPolicy().use_from_stop()


def test_restore_has_no_toggle_or_constant():
  assert not hasattr(cruise, "PREAP_RESTORE_LAST_SET")


def test_steering_only_sets_are_never_stored():
  s = Sim()
  s.v = 44.0
  s.pull_engage()                                   # steering only: display set 44
  s.tip(LIGHT_UP, secs=0.02)                        # a tip that does not enter FULL here (no capture edge in this sim)
  s.cancel()
  assert s.h.preap_last_set_kph is None
  s.v = 30.0
  s.pull_engage()
  assert s.double_pull_full() == 30.0               # nothing stored: captured as before


def test_new_drive_starts_empty():
  s = Sim()
  _first_full_at(s, 70.0)
  s2 = Sim()                                        # card restarts every drive; the stored set lives only in memory
  assert _first_full_at(s2, 33.0) == 33.0


def test_hold_repeat_and_deep_detent_start_from_the_restored_set():
  s = Sim()
  _first_full_at(s, 50.0)
  s.cancel()
  s.v = 30.0
  s.pull_engage()
  assert s.double_pull_full() == 50.0
  assert s.tip(LIGHT_UP, secs=1.2) == 56.0          # press +1, then after 0.35 s +1 every 0.2 s: 51..56
  assert s.tip(DEEP_UP) == 60.0                     # deep: next multiple of 5
  s.cancel()
  s.pull_engage()
  assert s.double_pull_full() == 60.0               # and that adjusted set is what the next re-engage restores


def test_metric_restore_is_exact():
  s = Sim(metric=True)
  _first_full_at(s, 80.0)
  s.cancel()
  s.v = 50.0
  s.pull_engage()
  assert s.double_pull_full() == 80.0


@pytest.mark.parametrize("fp", ["TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TOYOTA_COROLLA"])
def test_not_pre_ap_never_stores_or_restores(fp):
  h = VCruiseHelper(NS(pcmCruise=False, carFingerprint=fp))
  h.v_cruise_kph = 80.0
  h.note_preap_long_set(True)
  assert h.preap_last_set_kph is None and h.preap_restore_kph(20.0) is None
  h.preap_last_set_kph = 100.0                      # even if something stored a value, a non-Pre-AP helper ignores it
  assert h.preap_restore_kph(20.0) is None
  h.initialize_v_cruise(_cs(30.0), False, 0.0, preap_restore_kph=100.0)
  assert h.v_cruise_kph == int(round(max(30.0 * CV.MPH_TO_MS * CV.MS_TO_KPH, cruise.V_CRUISE_INITIAL)))


def test_pcm_cruise_initialize_is_untouched():
  h = VCruiseHelper(NS(pcmCruise=True, carFingerprint="TESLA_AP1_MODELS"))
  h.initialize_v_cruise(_cs(30.0), False, 0.0, preap_restore_kph=100.0)
  assert h.v_cruise_kph == V_CRUISE_UNSET


def test_card_wires_the_same_calls():
  src = (Path(__file__).resolve().parents[2] / "car" / "card.py").read_text()
  upd = src.index("self.v_cruise_helper.update_v_cruise(CS, self.sm['carControl'].enabled, self.is_metric)")
  note = src.index("self.v_cruise_helper.note_preap_long_set(bool(self.sm['carControl'].longActive))")
  pol_init = src.index("if self.preap_engage_set_limit is not None and self.preap_pull_policy.restore_allowed(float(self.CS_prev.vEgo)):")
  fs_init = src.index("from_stop = float(self.preap_from_stop()) if self.preap_pull_policy.use_from_stop() else 0.0")
  init = src.index("preap_restore_kph=restore)")
  fs_cap = src.index("and self.preap_pull_policy.use_from_stop()):")
  cap = src.index("if not tip_entry and self.preap_pull_policy.restore_allowed(float(CS.vEgo)):")
  assert upd < note < fs_init < pol_init < init < fs_cap < cap
  assert "self.preap_pull_policy = PreapPullPolicy.read()" in src and "self.preap_pull_policy = PreapPullPolicy()" in src
  # gated on the Pre-AP pedal helper, which card creates only for TESLA_PREAP_MODELS with pcmCruise False
  assert "if self.preap_engage_set_limit is not None:\n      # Pre-AP pedal only: remember" in src
  assert 'self.CP.carFingerprint == "TESLA_PREAP_MODELS" and not self.CP.pcmCruise' in src
