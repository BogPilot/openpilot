"""SLC stalk hand-over in single-pull and double-pull engage modes (deterministic replays, no msgq).

Single-pull mode: one pull engages lat + long (cruiseState.enabled and longActive rise together) = 0.9.7.
Double-pull mode (pre-AP style): first pull = lateral only (cruise on, longActive False), second pull = lat + long.
The hand-over must follow the pull that engages longitudinal; a lateral-only pull never touches the set speed.
"""
import unittest
from types import SimpleNamespace

from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import DT, MPH, Sm, make, run, toggles
from opendbc.car.tesla_ap1.slc_raise import prev_5_ms

V_CRUISE = 20.0 * 1.0      # m/s planner/DI set while the stalk set is "ours" to compare against
V_EGO = 20.0
V_LATCH = 45 * sc.MPH_TO_MS   # v6: a tip / no-stalk engage latches vEgo in whole mph (20 m/s = 44.7 mph -> 45)


def frames(seconds):
  return max(1, int(round(seconds / DT)))


def lat_only(ctl, sm, seconds, limit, v_cruise=V_CRUISE, **kw):
  """cruise on, openpilot long NOT active."""
  return [run(ctl, sm, v_cruise, V_EGO, limit=limit, cruise=True, long_active=False, **kw) for _ in range(frames(seconds))]


def long_on(ctl, sm, seconds, limit, v_cruise=V_CRUISE, **kw):
  return [run(ctl, sm, v_cruise, V_EGO, limit=limit, cruise=True, long_active=True, **kw) for _ in range(frames(seconds))]


def off(ctl, sm, seconds, limit, **kw):
  return [run(ctl, sm, V_CRUISE, V_EGO, limit=limit, cruise=False, long_active=False, **kw) for _ in range(frames(seconds))]


class TestSinglePullMode(unittest.TestCase):
  """cruise-on and longActive rise together on the one pull."""

  def engage_pull(self, ctl, sm, limit):
    off(ctl, sm, 0.2, limit, rwd=True)            # pull seen before DI reports cruise on (0.8 s window)
    off(ctl, sm, 0.1, limit)
    return long_on(ctl, sm, 0.5, limit)

  def test_single_pull_engage_hands_to_slc(self):
    ctl, sm = make(), Sm()
    out = self.engage_pull(ctl, sm, 50 * MPH)
    self.assertAlmostEqual(out[-1], 55 * MPH, places=3)         # 50 + 5 mph offset, raised from the 44.7 mph set

  def test_longactive_lags_cruise_on_by_a_few_frames_still_hands_over(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)
    lag = lat_only(ctl, sm, 0.1, 50 * MPH)                        # 2 frames before longActive is seen
    self.assertTrue(all(o == V_CRUISE for o in lag))
    out = long_on(ctl, sm, 0.5, 50 * MPH)
    self.assertAlmostEqual(out[-1], 55 * MPH, places=3)

  def test_tip_engage_holds_set_speed(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, up=True)
    out = long_on(ctl, sm, 1.0, 50 * MPH)
    self.assertAlmostEqual(out[-1], V_LATCH, places=3)             # sticky vEgo, no raise
    self.assertAlmostEqual(long_on(ctl, sm, 0.5, 35 * MPH)[-1], V_LATCH, places=3)   # holds through a lower limit

  def test_repull_while_engaged_relatches_slc(self):
    ctl, sm = make(), Sm()
    self.engage_pull(ctl, sm, 50 * MPH)
    run(ctl, sm, V_CRUISE, V_EGO, dn=True, spd=8, limit=50 * MPH)
    tip = long_on(ctl, sm, 0.3, 50 * MPH)[-1]
    self.assertAlmostEqual(tip, prev_5_ms(55 * MPH), places=3)   # tip down fixed the speed at 65
    out = run(ctl, sm, V_CRUISE, V_EGO, rwd=True, limit=50 * MPH)   # pull while engaged: 0.9.7 clears the tip
    self.assertAlmostEqual(out, 55 * MPH, places=3)

  def test_cancel_resets_and_next_pull_engages_again(self):
    ctl, sm = make(), Sm()
    self.engage_pull(ctl, sm, 50 * MPH)
    off(ctl, sm, 0.5, 50 * MPH)
    self.assertFalse(ctl.engage.long_on)
    out = self.engage_pull(ctl, sm, 35 * MPH)
    self.assertAlmostEqual(out[-1], 40 * MPH, places=3)

  def test_di_seed_below_vego_does_not_become_the_set(self):
    """Stalk-engage with Tesla's 8-10 mph / ~vEgo/2 DI_cruiseSet must start at vEgo, then raise to SLC.

    The lag ticks before longActive pass through, floored at vEgo (gas-held engage fix): never the DI seed.
    The first long tick must not aim at 8-10 mph.
    """
    di = 8 * MPH
    v_ego = 25 * MPH
    slc = 50 * MPH
    ctl, sm = make(), Sm()
    for _ in range(frames(0.2)):
      run(ctl, sm, di, v_ego, limit=slc, cruise=False, long_active=False, rwd=True)  # 0.8 s stalk window
    lag = [run(ctl, sm, di, v_ego, limit=slc, cruise=True, long_active=False) for _ in range(frames(0.1))]
    self.assertTrue(all(abs(o - v_ego) < 1e-6 for o in lag), lag)  # lat-only lag: pass-through floored at vEgo
    out = [run(ctl, sm, di, v_ego, limit=slc, cruise=True, long_active=True) for _ in range(frames(0.5))]
    self.assertTrue(all(o > 20 * MPH for o in out), out)          # never 8-10 mph once long is ours
    self.assertAlmostEqual(out[-1], 55 * MPH, places=3)           # 50 + 5 mph offset


  def test_gas_held_engage_never_passes_the_half_di_seed(self):
    """Gas held through the engage: longActive stays 0 for seconds. The lat-only pass-through is floored at vEgo
    while cruise is on (was the ~vEgo/2 DI_cruiseSet). No stalk was seen at the cruise edge, so on release the set latches
    vEgo from that edge (never SLC, never below vEgo). A set above vEgo passes as is."""
    v_ego, slc = 24 * MPH, 35 * MPH
    ctl, sm = make(), Sm()
    held = [run(ctl, sm, 12 * MPH, v_ego, limit=slc, cruise=True, long_active=False, gas=True) for _ in range(frames(2.0))]
    self.assertTrue(all(abs(o - v_ego) < 1e-6 for o in held), held)
    above = [run(ctl, sm, 40 * MPH, v_ego, limit=slc, cruise=True, long_active=False, gas=True) for _ in range(frames(0.2))]
    self.assertTrue(all(abs(o - 40 * MPH) < 1e-6 for o in above), above)
    out = [run(ctl, sm, 12 * MPH, v_ego, limit=slc, cruise=True, long_active=True) for _ in range(frames(0.5))]
    self.assertTrue(all(o >= v_ego - 1e-6 for o in out), out)        # never the ~vEgo/2 DI seed
    self.assertTrue(all(abs(o - v_ego) < 1e-6 for o in out), out)    # no stalk seen: vEgo latch, not SLC


class TestDoublePullMode(unittest.TestCase):
  """first pull lateral only (longActive False), second pull lat + long."""

  def test_lateral_only_pull_does_not_hand_over_or_change_set_speed(self):
    for limit in (50 * MPH, 35 * MPH):                           # a raise case and a cap case
      ctl, sm = make(), Sm()
      off(ctl, sm, 0.2, limit, rwd=True)                          # pull 1
      out = lat_only(ctl, sm, 3.0, limit)
      self.assertTrue(all(o == V_CRUISE for o in out), (limit, out[:3], out[-3:]))   # never raised, never capped
      self.assertFalse(ctl.holdoff.sticky_vego)
      self.assertEqual(ctl.holdoff.tip_ms, 0.0)

  def test_long_engage_pull_after_lateral_only_pull_hands_to_slc(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)                         # pull 1: lat only
    self.assertTrue(all(o == V_CRUISE for o in lat_only(ctl, sm, 0.4, 50 * MPH)))
    out = long_on(ctl, sm, 0.5, 50 * MPH, rwd=True)               # pull 2 engages long
    self.assertAlmostEqual(out[-1], 55 * MPH, places=3)

  def test_long_engage_pull_slow_second_pull_still_hands_over(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)
    lat_only(ctl, sm, 2.0, 50 * MPH)
    lat_only(ctl, sm, 0.2, 50 * MPH, rwd=True)                    # pull 2 pressed, long engages a moment later
    out = long_on(ctl, sm, 0.5, 50 * MPH)
    self.assertAlmostEqual(out[-1], 55 * MPH, places=3)

  def test_tip_up_engage_after_lateral_only_pull_is_sticky_not_slc(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)
    lat_only(ctl, sm, 0.6, 50 * MPH)
    lat_only(ctl, sm, 0.1, 50 * MPH, up=True)                     # long engaged with the up tip, not a pull
    out = long_on(ctl, sm, 0.5, 50 * MPH)
    self.assertAlmostEqual(out[-1], V_LATCH, places=3)
    self.assertTrue(ctl.holdoff.sticky_vego)

  def test_pull_while_long_engaged_drops_to_lateral_then_second_pull_relatches(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)
    long_on(ctl, sm, 0.5, 50 * MPH, rwd=True)
    run(ctl, sm, V_CRUISE, V_EGO, dn=True, spd=8, limit=50 * MPH, cruise=True, long_active=True)
    self.assertAlmostEqual(long_on(ctl, sm, 0.3, 50 * MPH)[-1], prev_5_ms(55 * MPH), places=3)   # tip holds
    out = lat_only(ctl, sm, 1.6, 50 * MPH, rwd=True)               # pull 1 of the pair: car drops long, lateral stays
    self.assertAlmostEqual(out[-1], V_CRUISE, places=6)           # after DROP_S the set is not ours
    self.assertFalse(ctl.engage.long_on)
    out = long_on(ctl, sm, 0.5, 50 * MPH, rwd=True)                # pull 2: long again
    self.assertAlmostEqual(out[-1], 55 * MPH, places=3)

  def test_second_pull_within_drop_window_is_a_repull_while_engaged(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)
    long_on(ctl, sm, 0.5, 50 * MPH, rwd=True)
    run(ctl, sm, V_CRUISE, V_EGO, dn=True, spd=8, limit=50 * MPH, cruise=True, long_active=True)
    long_on(ctl, sm, 0.3, 50 * MPH)
    lat_only(ctl, sm, 0.4, 50 * MPH, rwd=True)                     # long dips for 0.4 s (< DROP_S)
    out = long_on(ctl, sm, 0.3, 50 * MPH, rwd=True)
    self.assertAlmostEqual(out[-1], 55 * MPH, places=3)            # tip cleared by the pull: SLC again

  def test_cancel_and_disengage_reset_the_gate(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)
    long_on(ctl, sm, 0.5, 50 * MPH, rwd=True)
    off(ctl, sm, 0.4, 50 * MPH)                                    # cancel / disengage
    self.assertFalse(ctl.engage.long_on)
    out = lat_only(ctl, sm, 2.0, 50 * MPH, rwd=True)               # lateral-only again: still hands nothing over
    self.assertTrue(all(o == V_CRUISE for o in out))

  def test_tip_after_pull_holds_set_in_double_pull_mode(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)
    long_on(ctl, sm, 0.5, 50 * MPH, rwd=True)
    run(ctl, sm, V_CRUISE, V_EGO, up=True, spd=4, limit=50 * MPH, cruise=True, long_active=True)
    held = long_on(ctl, sm, 0.3, 50 * MPH)[-1]
    self.assertAlmostEqual(held, 60 * MPH, places=3)               # next-5 from 55
    self.assertAlmostEqual(long_on(ctl, sm, 0.5, 25 * MPH)[-1], 60 * MPH, places=3)   # holds through a limit drop

  def test_brief_longactive_dip_keeps_a_tip(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.2, 50 * MPH, rwd=True)
    long_on(ctl, sm, 0.5, 50 * MPH)
    run(ctl, sm, V_CRUISE, V_EGO, dn=True, spd=8, limit=50 * MPH, cruise=True, long_active=True)
    held = long_on(ctl, sm, 0.3, 50 * MPH)[-1]
    out = lat_only(ctl, sm, 0.5, 50 * MPH)                         # 0.5 s dip (override alert)
    self.assertAlmostEqual(out[-1], held, places=3)
    self.assertAlmostEqual(long_on(ctl, sm, 0.3, 50 * MPH)[-1], held, places=3)


def gas_engage(ctl, sm, limit, v_tap, v_release, hold_s=2.0, **press):
  """Stalk pressed with the gas held at v_tap, cruise on lat-only while accelerating, long rises on release."""
  for _ in range(frames(0.1)):
    run(ctl, sm, V_CRUISE, v_tap, limit=limit, cruise=False, long_active=False, gas=True, **press)
  n = frames(hold_s)
  for i in range(n):
    v = v_tap + (v_release - v_tap) * i / n   # cruise edge at v_tap, then accelerating
    run(ctl, sm, V_CRUISE, v, limit=limit, cruise=True, long_active=False, gas=True)
  return [run(ctl, sm, V_CRUISE, v_release, limit=limit, cruise=True, long_active=True) for _ in range(frames(0.5))]


class TestEngageStalkAction(unittest.TestCase):
  """The stalk action is classified on the cruise edge and remembered until longActive rises."""

  def test_gas_held_tap_engage_stays_sticky(self):
    for press in ({"up": True}, {"dn": True}):
      ctl, sm = make(), Sm()
      out = gas_engage(ctl, sm, 50 * MPH, 20.0, 26.0, **press)     # release 2 s (> 0.8 s window) after the tap
      self.assertTrue(all(abs(o - V_LATCH) < 1e-6 for o in out), (press, out))   # vEgo at the tap, not at release
      self.assertTrue(ctl.holdoff.sticky_vego)
      self.assertAlmostEqual(long_on(ctl, sm, 0.5, 65 * MPH)[-1], V_LATCH, places=4)   # higher limit never raises it

  def test_gas_held_pull_follows_slc(self):
    ctl, sm = make(), Sm()
    out = gas_engage(ctl, sm, 50 * MPH, 20.0, 26.0, rwd=True)
    self.assertAlmostEqual(out[-1], 55 * MPH, places=3)
    self.assertFalse(ctl.holdoff.sticky_vego)

  def test_cancel_before_release_clears_remembered_action(self):
    ctl, sm = make(), Sm()
    for _ in range(frames(0.1)):
      run(ctl, sm, V_CRUISE, 20.0, limit=50 * MPH, cruise=False, long_active=False, gas=True, rwd=True)
    lat_only(ctl, sm, 0.5, 50 * MPH, gas=True)
    self.assertEqual(ctl.holdoff.engage_kind, "pull")
    off(ctl, sm, 1.0, 50 * MPH)                                     # cancel / brake: cruise drops
    self.assertIsNone(ctl.holdoff.engage_kind)
    out = long_on(ctl, sm, 0.5, 50 * MPH)                           # re-engage with no stalk seen
    self.assertAlmostEqual(out[-1], V_LATCH, places=4)                # the old pull is not reused: vEgo, not SLC

  def test_openpilot_disengage_clears_remembered_action(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.1, 50 * MPH, rwd=True)
    lat_only(ctl, sm, 0.3, 50 * MPH)
    run(ctl, sm, V_CRUISE, V_EGO, limit=50 * MPH, cruise=True, long_active=False, enabled=False)
    self.assertIsNone(ctl.holdoff.engage_kind)

  def test_unclassified_engage_latches_vego(self):
    ctl, sm = make(), Sm()
    out = gas_engage(ctl, sm, 50 * MPH, 20.0, 26.0)
    self.assertTrue(all(abs(o - V_LATCH) < 1e-6 for o in out), out)   # vEgo at the cruise edge
    self.assertEqual(ctl.holdoff.engage_kind, "none")

  def test_lat_only_tap_after_pull_overrides_it(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.1, 50 * MPH, rwd=True)
    lat_only(ctl, sm, 1.0, 50 * MPH)
    lat_only(ctl, sm, 0.1, 50 * MPH, dn=True)
    out = long_on(ctl, sm, 0.5, 50 * MPH)
    self.assertAlmostEqual(out[-1], V_LATCH, places=4)

  def test_gas_override_longer_than_drop_window_keeps_the_tap_latch(self):
    """A gas override past LongEngageGate.DROP_S used to drop the tap latch and hand the set to SLC."""
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.1, 50 * MPH, up=True)
    self.assertAlmostEqual(long_on(ctl, sm, 0.5, 50 * MPH)[-1], V_LATCH, places=4)
    for _ in range(frames(2.0)):
      run(ctl, sm, V_CRUISE, 27.0, limit=50 * MPH, cruise=True, long_active=False, gas=True)
    out = [run(ctl, sm, V_CRUISE, 27.0, limit=50 * MPH, cruise=True, long_active=True) for _ in range(frames(0.5))]
    self.assertTrue(all(abs(o - V_LATCH) < 1e-6 for o in out), out)

  def test_gas_override_longer_than_drop_window_keeps_a_tipped_set(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.1, 50 * MPH, rwd=True)
    long_on(ctl, sm, 0.5, 50 * MPH)
    run(ctl, sm, V_CRUISE, V_EGO, dn=True, spd=8, limit=50 * MPH, cruise=True, long_active=True)
    held = long_on(ctl, sm, 0.3, 50 * MPH)[-1]
    self.assertAlmostEqual(held, prev_5_ms(55 * MPH), places=3)
    lat_only(ctl, sm, 2.0, 50 * MPH, gas=True)
    self.assertAlmostEqual(long_on(ctl, sm, 0.5, 50 * MPH)[-1], held, places=3)

  def test_gas_override_after_pull_still_follows_slc(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.1, 50 * MPH, rwd=True)
    long_on(ctl, sm, 0.5, 50 * MPH)
    lat_only(ctl, sm, 2.0, 50 * MPH, gas=True)
    self.assertAlmostEqual(long_on(ctl, sm, 0.5, 50 * MPH)[-1], 55 * MPH, places=3)


class TestEngagedSlcTapLatch(unittest.TestCase):
  """Engaged in SLC (after a pull): a tap leaves SLC and latches until the next pull (e.g. a school zone)."""

  def slc_then_down_to(self, ctl, sm, limit, target_mph):
    off(ctl, sm, 0.1, limit, rwd=True)
    out = long_on(ctl, sm, 0.5, limit)
    while out[-1] > target_mph * MPH + 1e-3:
      run(ctl, sm, V_CRUISE, V_EGO, dn=True, spd=8, limit=limit, cruise=True, long_active=True)
      out = long_on(ctl, sm, 0.1, limit)
    return out[-1]

  def test_engaged_slc_tap_switches_to_latch(self):
    ctl, sm = make(), Sm()
    off(ctl, sm, 0.1, 25 * MPH, rwd=True)
    self.assertAlmostEqual(long_on(ctl, sm, 0.5, 25 * MPH)[-1], 30 * MPH, places=3)   # SLC: 25 + 5
    run(ctl, sm, V_CRUISE, V_EGO, dn=True, spd=32, limit=25 * MPH, cruise=True, long_active=True)
    out = long_on(ctl, sm, 0.3, 25 * MPH)[-1]
    self.assertAlmostEqual(out, 29 * MPH, places=3)               # existing tip rule: DN_1ST = -1 from the current set
    self.assertGreater(ctl.holdoff.tip_ms, 0.0)
    self.assertEqual(ctl.holdoff.engage_kind, "tap")
    self.assertAlmostEqual(self.slc_then_down_to(make(), Sm(), 25 * MPH, 15), 15 * MPH, places=3)  # DN_2ND steps 30-25-20-15

  def test_latched_limit_increase_never_raises_set(self):
    ctl, sm = make(), Sm()
    self.assertAlmostEqual(self.slc_then_down_to(ctl, sm, 25 * MPH, 15), 15 * MPH, places=3)
    for limit in (25 * MPH, 35 * MPH, 45 * MPH):                  # pass the 25 sign and beyond
      out = long_on(ctl, sm, 3.0, limit)
      self.assertTrue(all(abs(o - 15 * MPH) < 1e-3 for o in out), (limit, out[-3:]))

  def test_latched_limit_decrease_does_not_move_set(self):
    """Current behavior kept: a latched set also holds through a lower limit (only Curve Speed Control may lower it
    temporarily). The driver lowers it with a tap."""
    ctl, sm = make(), Sm()
    self.assertAlmostEqual(self.slc_then_down_to(ctl, sm, 45 * MPH, 40), 40 * MPH, places=3)
    out = long_on(ctl, sm, 3.0, 30 * MPH)
    self.assertTrue(all(abs(o - 40 * MPH) < 1e-3 for o in out), out[-3:])

  def test_pull_after_latch_returns_to_slc_limit_plus_offset(self):
    ctl, sm = make(), Sm()
    self.slc_then_down_to(ctl, sm, 25 * MPH, 15)
    long_on(ctl, sm, 1.0, 35 * MPH)
    out = run(ctl, sm, V_CRUISE, V_EGO, rwd=True, limit=35 * MPH, cruise=True, long_active=True)
    self.assertAlmostEqual(out, 40 * MPH, places=3)               # 35 + 5
    self.assertAlmostEqual(long_on(ctl, sm, 0.5, 45 * MPH)[-1], 50 * MPH, places=3)   # SLC tracking again

  def test_dash_set_follows_the_latched_set(self):
    """AP1 openpilot long shows the plan set as is outside the engage floor (cluster_set_kph follow_plan)."""
    plan = SimpleNamespace(vCruise=15 * MPH)
    kph = sc.cluster_set_kph(30 * MPH * sc.MS_TO_KPH, plan, True, follow_plan=True)
    self.assertAlmostEqual(kph, 15 * MPH * sc.MS_TO_KPH, places=3)


class TestGate(unittest.TestCase):
  def test_states(self):
    g = sc.LongEngageGate()
    self.assertEqual(g.update(False, False, DT), (False, False))
    self.assertEqual(g.update(True, False, DT), (False, True))     # cruise on, long not active: lateral only
    self.assertEqual(g.update(True, True, DT), (True, False))
    for _ in range(frames(0.9)):
      r = g.update(True, False, DT)
    self.assertEqual(r, (True, False))
    for _ in range(frames(0.3)):
      r = g.update(True, False, DT)
    self.assertEqual(r, (False, True))
    self.assertEqual(g.update(False, False, DT), (False, False))
    self.assertFalse(g.long_on)


class TestUnaffectedPaths(unittest.TestCase):
  def test_non_ap1_and_off_stay_passthrough(self):
    ctl, sm = make(toggles(SpeedLimitController="0")), Sm()
    self.assertEqual(run(ctl, sm, 13.37, V_EGO, limit=45 * MPH, rwd=True, cruise=True, long_active=False), 13.37)


if __name__ == "__main__":
  unittest.main()
