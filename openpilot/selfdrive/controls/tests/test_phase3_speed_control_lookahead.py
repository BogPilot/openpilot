"""Blended Dashboard + OSM look-ahead (phase3_speed_control). Synthetic OSM only."""
import math
import unittest
from types import SimpleNamespace as NS

from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import FakeStore, Sm, make, run, toggles, DT, MPH, CP_AP1

MPH_TO_MS = sc.MPH_TO_MS


class FakeMapData:
  def __init__(self, current, nxt=0.0, dist=0.0):
    self.limit = current
    self.current = current
    self.next_limit = nxt
    self.distance_to_next = dist
    self.lookahead_applied = False


class FakeCtx:
  def __init__(self, current, nxt=0.0, dist=0.0):
    self.data = FakeMapData(current, nxt, dist)

  def update(self, *a, **k):
    return self.data


def ctl_with_map(current, nxt=0.0, dist=0.0, horizon=10, **vals):
  vals.setdefault("SLCLookaheadLower", str(horizon))
  vals.setdefault("SLCLookaheadHigher", "0")
  vals.setdefault("SpeedLimitController", "1")
  vals.setdefault("SLCPriority1", "Dashboard")
  vals.setdefault("SLCPriority2", "Map Data")
  vals.setdefault("SLCPriority3", "Navigation")
  for i in range(1, 8):
    vals.setdefault(f"Offset{i}", "0")
  store = FakeStore(**vals)
  t = toggles(**store.vals)
  ctl = make(t=t, store=store)
  ctl.slc.map_ctx = FakeCtx(current, nxt, dist)
  ctl._map_tried = True
  return ctl, Sm()


class TestLookaheadHelpers(unittest.TestCase):
  def test_adapt_distance_65_to_45_at_2mphs(self):
    d = sc.adapt_distance_m(65 * MPH, 45 * MPH)
    # Average 55 mph for 10 s at 2 mph/s.
    self.assertAlmostEqual(d, 55 * MPH * 10.0, places=4)

  def test_trajectory_at_55mph_distance(self):
    # Constant-a distance is quadratic in speed, so 55 mph is not halfway in metres.
    d55 = sc.adapt_distance_m(55 * MPH, 45 * MPH)
    self.assertAlmostEqual(sc.trajectory_speed_ms(45 * MPH, d55), 55 * MPH, places=4)

  def test_clamp_horizon(self):
    self.assertEqual(sc.clamp_lookahead_horizon_s(10), 10)
    self.assertEqual(sc.clamp_lookahead_horizon_s(0), 0)
    self.assertEqual(sc.clamp_lookahead_horizon_s(-3), 0)
    self.assertEqual(sc.clamp_lookahead_horizon_s(30), 15)
    self.assertEqual(sc.clamp_lookahead_horizon_s("1.000000"), 1)
    self.assertEqual(sc.clamp_lookahead_horizon_s("nope"), 5)
    self.assertEqual(sc.clamp_lookahead_horizon_s(float("nan")), 5)


class TestLookaheadCeiling(unittest.TestCase):
  def _kw(self, **over):
    kw = dict(
      dashboard_ms=65 * MPH, osm_current_ms=65 * MPH, osm_next_ms=45 * MPH,
      distance_m=sc.adapt_distance_m(55 * MPH, 45 * MPH), v_ego=65 * MPH,
      horizon_s=10, current_set_ms=65 * MPH, next_set_ms=45 * MPH,
    )
    kw.update(over)
    return kw

  def test_early_slow_toward_lower_limit(self):
    ceil = sc.lookahead_ceiling_ms(**self._kw())
    self.assertIsNotNone(ceil)
    self.assertAlmostEqual(ceil, 55 * MPH, places=3)

  def test_no_early_raise(self):
    ceil = sc.lookahead_ceiling_ms(**self._kw(
      dashboard_ms=45 * MPH, osm_current_ms=45 * MPH, osm_next_ms=65 * MPH,
      current_set_ms=45 * MPH, next_set_ms=65 * MPH, v_ego=45 * MPH,
      distance_m=100.0,
    ))
    self.assertIsNone(ceil)

  def test_cap_does_not_start_before_adapt_distance(self):
    adapt = sc.adapt_distance_m(65 * MPH, 45 * MPH)
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(distance_m=adapt + 5.0)))
    start = sc.lookahead_ceiling_ms(**self._kw(distance_m=adapt))
    self.assertIsNotNone(start)
    self.assertAlmostEqual(start, 65 * MPH, places=3)
    # Implied deceleration on the trajectory is the 2 mph/s cap, never more.
    mid_d = adapt / 2.0
    mid = sc.lookahead_ceiling_ms(**self._kw(distance_m=mid_d))
    a = ((65 * MPH) ** 2 - mid ** 2) / (2.0 * mid_d)
    self.assertAlmostEqual(a, sc.EARLY_DECEL_MS2, places=4)

  def test_horizon_bounds_start_even_when_adapt_is_longer(self):
    # 65->45 needs ~10 s / 246 m; a 3 s horizon is only ~87 m, so 200 m is still outside.
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(horizon_s=3, distance_m=200.0)))

  def test_confirmation_clears_ceiling(self):
    # Dashboard already shows the upcoming 45 mph limit.
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(dashboard_ms=45 * MPH)))

  def test_at_point_without_confirmation_does_not_finish(self):
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(distance_m=0.5)))
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(distance_m=0.0)))

  def test_stale_or_missing_osm_is_inactive(self):
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(osm_next_ms=0.0, distance_m=100.0)))
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(osm_next_ms=float("nan"), distance_m=100.0)))
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(distance_m=float("nan"))))

  def test_horizon_zero_is_off(self):
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(horizon_s=0)))

  def test_does_not_look_ahead_below_15_mph(self):
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(
      osm_next_ms=10 * MPH, next_set_ms=10 * MPH, distance_m=50.0,
    )))

  def test_higher_window_unused_even_if_seconds_are_set(self):
    # Raising is refused regardless of a larger current/next swap the old Map Data path used.
    self.assertIsNone(sc.lookahead_ceiling_ms(**self._kw(
      dashboard_ms=45 * MPH, osm_current_ms=45 * MPH, osm_next_ms=65 * MPH,
      current_set_ms=45 * MPH, next_set_ms=65 * MPH, v_ego=45 * MPH,
      distance_m=10.0, horizon_s=15,
    )))


class TestLookaheadConsumer(unittest.TestCase):
  def test_early_slow_is_a_ceiling_not_a_posted_swap(self):
    d55 = sc.adapt_distance_m(55 * MPH, 45 * MPH)
    ctl, sm = ctl_with_map(65 * MPH, 45 * MPH, d55, horizon=10)
    out = run(ctl, sm, 65 * MPH, 65 * MPH, limit=65 * MPH, rwd=True)  # pull engage: SLC mode (a no-stalk engage latches vEgo)
    self.assertAlmostEqual(ctl.slc.target, 65 * MPH, places=4)          # posted stays Dashboard
    self.assertEqual(ctl.slc.source, "Dashboard")
    self.assertAlmostEqual(out, 55 * MPH, places=2)

  def test_horizon_zero_keeps_dashboard_set(self):
    adapt = sc.adapt_distance_m(65 * MPH, 45 * MPH)
    ctl, sm = ctl_with_map(65 * MPH, 45 * MPH, adapt / 2.0, horizon=0)
    out = run(ctl, sm, 65 * MPH, 65 * MPH, limit=65 * MPH)
    self.assertAlmostEqual(out, 65 * MPH, places=4)
    self.assertAlmostEqual(ctl.slc.target, 65 * MPH, places=4)

  def test_no_early_raise_in_consumer(self):
    ctl, sm = ctl_with_map(45 * MPH, 65 * MPH, 80.0, horizon=10)
    out = run(ctl, sm, 45 * MPH, 45 * MPH, limit=45 * MPH)
    self.assertAlmostEqual(out, 45 * MPH, places=4)
    self.assertAlmostEqual(ctl.slc.target, 45 * MPH, places=4)

  def test_disagreement_without_upcoming_point_dashboard_wins(self):
    # OSM current 45 vs Dashboard 65, no next point, even if Map Data is priority 1.
    ctl, sm = ctl_with_map(45 * MPH, 0.0, 0.0, horizon=10, SLCPriority1="Map Data")
    out = run(ctl, sm, 65 * MPH, 65 * MPH, limit=65 * MPH)
    self.assertEqual(ctl.slc.source, "Dashboard")
    self.assertAlmostEqual(ctl.slc.target, 65 * MPH, places=4)
    self.assertAlmostEqual(out, 65 * MPH, places=4)

  def test_highest_does_not_override_dashboard_authority(self):
    ctl, sm = ctl_with_map(65 * MPH, 0.0, 0.0, horizon=10, SLCPriority1="Highest")
    run(ctl, sm, 45 * MPH, 45 * MPH, limit=45 * MPH)
    self.assertEqual(ctl.slc.source, "Dashboard")
    self.assertAlmostEqual(ctl.slc.target, 45 * MPH, places=4)

  def test_stale_osm_falls_back_to_plain_dashboard(self):
    store = FakeStore(SpeedLimitController="1", SLCPriority1="Dashboard",
                      SLCLookaheadLower="10", **{f"Offset{i}": "0" for i in range(1, 8)})
    t = toggles(**store.vals)
    ctl = make(t=t, store=store)
    sm = Sm()
    out = run(ctl, sm, 65 * MPH, 65 * MPH, limit=65 * MPH)
    self.assertEqual(ctl.slc.source, "Dashboard")
    self.assertAlmostEqual(out, 65 * MPH, places=4)
    self.assertEqual(ctl.slc.next_speed_limit, 0.0)

  def test_confirmation_by_dashboard_finishes_the_drop(self):
    # Mid-approach the ceiling is 55; once Dashboard shows 45 the posted limit takes over.
    d55 = sc.adapt_distance_m(55 * MPH, 45 * MPH)
    ctl, sm = ctl_with_map(65 * MPH, 45 * MPH, d55, horizon=10)
    out = run(ctl, sm, 65 * MPH, 65 * MPH, limit=65 * MPH, rwd=True)  # pull engage: SLC mode (a no-stalk engage latches vEgo)
    self.assertAlmostEqual(out, 55 * MPH, places=2)
    # 65->45 is a sudden drop, so Ap1SlcLimitGuard holds the posted target for CONFIRM_S (2 s).
    out2 = run(ctl, sm, 65 * MPH, 65 * MPH, limit=45 * MPH, n=int(2.1 / DT) + 1)
    self.assertAlmostEqual(ctl.slc.target, 45 * MPH, places=4)
    self.assertAlmostEqual(ctl.slc_target, 45 * MPH, places=4)
    self.assertAlmostEqual(out2, 45 * MPH, places=4)

  def test_stored_one_second_horizon_is_preserved(self):
    store = FakeStore(SLCLookaheadLower="1.000000", SpeedLimitController="1")
    t = toggles(**store.vals)
    self.assertEqual(t.map_speed_lookahead_lower, 1)

  def test_default_horizon_is_five(self):
    store = FakeStore(SpeedLimitController="1")
    t = toggles(**store.vals)
    self.assertEqual(t.map_speed_lookahead_lower, 5)


class TestPreApAndXConsumer(unittest.TestCase):
  def test_preap_consumer_follows_dashboard(self):
    cp = NS(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True, radarUnavailable=False, enableBsm=False)
    store = FakeStore(SpeedLimitController="1", SLCPriority1="Dashboard",
                      **{f"Offset{i}": "0" for i in range(1, 8)})
    t = sc_onroad(store, cp)
    ctl = sc.Ap1SpeedControl(cp, store=store, toggles_fn=lambda: t, clock=lambda: 0.0, adopted=True)
    sm = Sm()
    out = run(ctl, sm, 30.0, 20.0, limit=45 * MPH, rwd=True)  # pull engage: SLC mode (a no-stalk engage latches vEgo)
    self.assertTrue(ctl.ap1)
    self.assertAlmostEqual(out, 45 * MPH, places=4)
    self.assertEqual(ctl.slc.source, "Dashboard")

  def test_ap1_x_consumer_follows_dashboard(self):
    cp = NS(carFingerprint="TESLA_AP1_MODELX", openpilotLongitudinalControl=True, radarUnavailable=False, enableBsm=False)
    store = FakeStore(SpeedLimitController="1", SLCPriority1="Dashboard",
                      **{f"Offset{i}": "0" for i in range(1, 8)})
    t = sc_onroad(store, cp)
    ctl = sc.Ap1SpeedControl(cp, store=store, toggles_fn=lambda: t, clock=lambda: 0.0, adopted=True)
    sm = Sm()
    out = run(ctl, sm, 30.0, 20.0, limit=45 * MPH, rwd=True)  # pull engage: SLC mode (a no-stalk engage latches vEgo)
    self.assertTrue(ctl.ap1)
    self.assertAlmostEqual(out, 45 * MPH, places=4)

  def test_model3_still_inactive(self):
    cp = NS(carFingerprint="TESLA_MODEL_3", openpilotLongitudinalControl=True, radarUnavailable=False, enableBsm=True)
    store = FakeStore(SpeedLimitController="1")
    t = sc_onroad(store, cp)
    ctl = sc.Ap1SpeedControl(cp, store=store, toggles_fn=lambda: t, clock=lambda: 0.0, adopted=True)
    sm = Sm()
    self.assertFalse(ctl.ap1)
    self.assertEqual(run(ctl, sm, 30.0, 20.0, limit=45 * MPH), 30.0)


def sc_onroad(store, cp):
  from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
  return onroad_toggles(store, cp)


if __name__ == "__main__":
  unittest.main()
