"""SLC <-> Map Data / Mapbox filler: 0.9.7 update_limits order (speed_limit_controller.py:250-314), offline.

Each case names the 0.9.7 branch it checks. No network, no mapd, no msgq."""
import unittest
from types import SimpleNamespace as NS

from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import DT, MPH, FakeStore, Sm, make, toggles
from openpilot.system.bogpilot.osm.map_data import MapData
from openpilot.system.bogpilot.osm.mapbox import MapboxFiller


class Ctx:
  """MapContext stand-in: fixed map data + gps, optional Mapbox filler."""
  def __init__(self, limit=0.0, nxt=0.0, mapbox=None, gps=True):
    self.map = MapData(limit, limit, nxt, 0.0, False)
    self.gps_position = {"latitude": 0.5, "longitude": -0.5, "bearing": 90.0} if gps else None
    self.mapbox = mapbox
    self.want_own_gps = False
    self.calls = 0

  def update(self, v_ego, hi, lo):
    self.calls += 1
    return self.map

  def now_dt(self):
    import datetime
    return datetime.datetime(2026, 11, 9, tzinfo=datetime.timezone.utc)


class FakeMapbox(MapboxFiller):
  def __init__(self, limit=0.0, ok=True):
    super().__init__()
    self.fake_limit = limit
    self.ok = ok
    self.updates = 0
    self.resets = 0

  @property
  def budget_ok(self):
    return self.ok

  def update(self, *a, **k):
    self.updates += 1
    self.mapbox_limit = self.fake_limit

  def reset(self):
    self.resets += 1
    super().reset()


def slc_with(ctx=None, mapbox=None, **tog):
  ctl = make(toggles(**tog))
  ctl.slc.map_ctx = ctx
  ctl.slc.mapbox = mapbox
  ctl.slc.t = ctl.toggles()
  return ctl.slc


def limits(slc, dash=0.0, nav=0.0, v_cruise=20.0, enabled=True, n=1):
  for _ in range(n):
    slc.update_limits(dash, v_cruise, enabled, False, False, True, navigation_speed_limit=nav, v_ego=15.0, steering_deg=0.0)
  return slc.source, slc.target


class TestOrder(unittest.TestCase):
  def test_dashboard_is_current_limit_authority_when_present(self):
    # Even if Navigation is Priority 1, a live Dashboard limit is the posted current.
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Navigation", SLCPriority2="Dashboard", SLCPriority3="Map Data")
    self.assertEqual(limits(s, dash=35 * MPH, nav=45 * MPH), ("Dashboard", 35 * MPH))

  def test_ordered_priorities_apply_when_dashboard_is_missing(self):
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Navigation", SLCPriority2="Dashboard", SLCPriority3="Map Data")
    self.assertEqual(limits(s, dash=0.0, nav=45 * MPH), ("Navigation", 45 * MPH))

  def test_ordered_falls_to_second_then_third(self):
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Navigation", SLCPriority2="Dashboard", SLCPriority3="Map Data")
    self.assertEqual(limits(s, dash=35 * MPH, nav=0.0), ("Dashboard", 35 * MPH))
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Navigation", SLCPriority2="Dashboard", SLCPriority3="Map Data")
    self.assertEqual(limits(s, dash=0.0, nav=0.0), ("Map Data", 25 * MPH))

  def test_source_not_in_priority_list_is_ignored(self):
    # 0.9.7 for/else: only the three listed priorities are consulted -> "None", 0 (then fallback rules apply)
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Navigation", SLCPriority2="Dashboard", SLCPriority3="Dashboard",
                 SLCFallback="0")
    src, tgt = limits(s, dash=0.0, nav=0.0, v_cruise=30.0)
    self.assertNotEqual(src, "Map Data")
    self.assertEqual(tgt, 30.0)     # Set Speed fallback

  def test_highest_and_lowest_among_non_dashboard_sources(self):
    # Dashboard present: it stays the authority even under Highest/Lowest.
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Highest")
    self.assertEqual(limits(s, dash=35 * MPH, nav=45 * MPH), ("Dashboard", 35 * MPH))
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Lowest")
    self.assertEqual(limits(s, dash=35 * MPH, nav=45 * MPH), ("Dashboard", 35 * MPH))
    # Dashboard missing: Highest/Lowest still pick among the remaining sources.
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Highest")
    self.assertEqual(limits(s, dash=0.0, nav=45 * MPH), ("Navigation", 45 * MPH))
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Lowest")
    self.assertEqual(limits(s, dash=0.0, nav=45 * MPH), ("Map Data", 25 * MPH))

  def test_below_one_ms_is_no_limit(self):
    s = slc_with(Ctx(limit=0.5), SLCPriority1="Highest", SLCFallback="2")
    self.assertEqual(limits(s)[1], 0.0)

  def test_map_ctx_updated_each_call_before_sources(self):
    ctx = Ctx(limit=30 * MPH)
    s = slc_with(ctx, SLCPriority1="Map Data")
    limits(s, n=3)
    self.assertEqual(ctx.calls, 3)
    self.assertEqual(s.map_speed_limit, 30 * MPH)

  def test_no_map_ctx_is_dashboard_only(self):
    s = slc_with(None, SLCPriority1="Dashboard")
    self.assertEqual(limits(s, dash=35 * MPH), ("Dashboard", 35 * MPH))
    self.assertEqual(s.map_speed_limit, 0.0)


class TestMapboxFiller(unittest.TestCase):
  def test_filler_used_only_when_nothing_else(self):
    mb = FakeMapbox(limit=30 * MPH)
    s = slc_with(Ctx(limit=0.0, mapbox=mb), mb, SLCPriority1="Navigation", SLCPriority2="Dashboard", SLCPriority3="Map Data",
                 SLCMapboxFiller="1", MapboxSecretKey="pk.test")
    self.assertEqual(limits(s)[0], "Mapbox")
    self.assertEqual(s.target, 30 * MPH)
    self.assertEqual(s.mapbox_limit, 30 * MPH)

  def test_filler_not_called_while_another_source_has_a_limit(self):
    mb = FakeMapbox(limit=30 * MPH)
    s = slc_with(Ctx(limit=25 * MPH, mapbox=mb), mb, SLCPriority1="Map Data", SLCMapboxFiller="1", MapboxSecretKey="pk.test")
    limits(s, n=2)       # first tick: target==0 -> filler runs once; once a target exists it is bypassed
    self.assertEqual(s.source, "Map Data")
    calls_after_target = mb.updates
    limits(s, n=5)
    self.assertEqual(mb.updates, calls_after_target)
    self.assertGreaterEqual(mb.resets, 1)      # else branch: mapbox_limit = 0, segment_distance = 0
    self.assertEqual(s.mapbox_limit, 0.0)

  def test_budget_exhausted_skips_filler(self):
    mb = FakeMapbox(limit=30 * MPH, ok=False)
    s = slc_with(Ctx(limit=0.0, mapbox=mb), mb, SLCPriority1="Map Data", SLCMapboxFiller="1", MapboxSecretKey="pk.test",
                 SLCFallback="0")
    src, tgt = limits(s, v_cruise=22.0)
    self.assertEqual(mb.updates, 0)
    self.assertEqual(tgt, 22.0)

  def test_filler_toggle_off_or_no_key_is_harmless(self):
    for vals in ({"SLCMapboxFiller": "0", "MapboxSecretKey": "pk.test"}, {"SLCMapboxFiller": "1"}):
      mb = FakeMapbox(limit=30 * MPH)
      ctl = make(toggles(SLCPriority1="Map Data", SLCFallback="0", **vals))
      ctl.slc.map_ctx = Ctx(limit=0.0, mapbox=mb)
      self.assertFalse(ctl.toggles().slc_mapbox_filler)

  def test_fallback_after_failed_filler(self):
    mb = FakeMapbox(limit=0.0)     # filler found nothing
    s = slc_with(Ctx(limit=0.0, mapbox=mb), mb, SLCPriority1="Map Data", SLCMapboxFiller="1", MapboxSecretKey="pk.test",
                 SLCFallback="0")
    src, tgt = limits(s, v_cruise=22.0)
    self.assertEqual((src, tgt), ("None", 22.0))


class TestFallbacks(unittest.TestCase):
  def test_previous_limit_fallback(self):
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Map Data", SLCFallback="2")
    limits(s, n=2)
    self.assertEqual(s.target, 25 * MPH)
    s.map_ctx = Ctx(limit=0.0)
    limits(s, n=2)
    self.assertEqual(s.target, 25 * MPH)        # previous limit retained (0.9.7 fallback 2)

  def test_set_speed_fallback_only_while_enabled(self):
    s = slc_with(Ctx(limit=0.0), SLCPriority1="Map Data", SLCFallback="0")
    self.assertEqual(limits(s, v_cruise=22.0, enabled=False)[1], 0.0)
    self.assertEqual(limits(s, v_cruise=22.0, enabled=True)[1], 22.0)


class TestPlannerFill(unittest.TestCase):
  def test_fill_publishes_map_fields_only_while_active(self):
    ctl = make(toggles(SLCPriority1="Map Data"))
    ctl.slc.map_ctx = Ctx(limit=27 * MPH, nxt=35 * MPH)
    sm = Sm()
    ctl.update(sm.set(limit=0.0), 25.0, 20.0, DT)
    plan = NS()
    ctl.fill(plan)
    self.assertAlmostEqual(plan.slcMapSpeedLimit, 27 * MPH, places=3)
    self.assertAlmostEqual(plan.slcNextSpeedLimit, 35 * MPH, places=3)
    self.assertEqual(plan.slcMapboxSpeedLimit, 0.0)
    ctl2 = make(toggles(SpeedLimitController="0"))
    ctl2.slc.map_ctx = Ctx(limit=27 * MPH)
    ctl2.update(Sm().set(), 25.0, 20.0, DT)
    plan2 = NS()
    ctl2.fill(plan2)
    self.assertEqual((plan2.slcMapSpeedLimit, plan2.slcSpeedLimitSource), (0.0, ""))

  def test_map_data_follows_up_and_down_without_confirmation(self):
    # 0.9.7 on legacy Tesla: confirmation toggles are off by default, the limit just applies
    ctl = make(toggles(SLCPriority1="Map Data"))
    ctx = Ctx(limit=35 * MPH)
    ctl.slc.map_ctx = ctx
    sm = Sm()
    for lim in (35 * MPH, 45 * MPH, 25 * MPH):
      ctx.map = MapData(lim, lim, 0.0, 0.0, False)
      for _ in range(3):
        ctl.update(sm.set(limit=0.0, v_ego=lim), 30.0, lim, DT)
      self.assertAlmostEqual(ctl.slc.target, lim, places=3)

  def test_inactive_slc_never_reads_map(self):
    ctl = make(toggles(SpeedLimitController="0"))
    ctx = Ctx(limit=27 * MPH)
    ctl.slc.map_ctx = ctx
    out = ctl.update(Sm().set(), 25.0, 20.0, DT)
    self.assertEqual(out, 25.0)
    self.assertEqual(ctx.calls, 0)


class TestMapSourcesWiring(unittest.TestCase):
  def test_injected_toggles_are_hermetic(self):
    ctl = make(toggles())
    ctl.toggles()
    self.assertIsNone(ctl.slc.map_ctx)

  def test_real_context_built_lazily_with_store(self):
    store = FakeStore(SpeedLimitController="1", SLCMapboxFiller="1", MapboxSecretKey="pk.test")
    ctl = sc.Ap1SpeedControl(NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True), store=store,
                             clock=lambda: 0.0, adopted=True)
    t = ctl.toggles()
    self.assertTrue(t.speed_limit_controller)
    self.assertTrue(t.slc_mapbox_filler)
    self.assertIsNotNone(ctl.slc.map_ctx)
    self.assertIsNotNone(ctl.slc.mapbox)
    self.assertEqual(ctl.slc.mapbox.mapbox_token, "pk.test")
    self.assertTrue(ctl.slc.map_ctx.want_own_gps)

  def test_no_key_means_no_filler(self):
    store = FakeStore(SpeedLimitController="1", SLCMapboxFiller="1")
    ctl = sc.Ap1SpeedControl(NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True), store=store,
                             clock=lambda: 0.0, adopted=True)
    self.assertFalse(ctl.toggles().slc_mapbox_filler)
    self.assertIsNone(ctl.slc.mapbox)
    self.assertFalse(ctl.slc.map_ctx.want_own_gps)

  def test_broken_osm_import_leaves_sources_absent(self):
    import sys
    saved = sys.modules.get("openpilot.system.bogpilot.osm.consumer")
    sys.modules["openpilot.system.bogpilot.osm.consumer"] = None      # import raises ImportError
    try:
      store = FakeStore(SpeedLimitController="1")
      ctl = sc.Ap1SpeedControl(NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True), store=store,
                               clock=lambda: 0.0, adopted=True)
      ctl.toggles()
      self.assertIsNone(ctl.slc.map_ctx)
      out = ctl.update(Sm().set(limit=30 * MPH), 25.0, 20.0, DT)
      self.assertGreater(out, 0)
    finally:
      if saved is None:
        sys.modules.pop("openpilot.system.bogpilot.osm.consumer", None)
      else:
        sys.modules["openpilot.system.bogpilot.osm.consumer"] = saved


if __name__ == "__main__":
  unittest.main()
