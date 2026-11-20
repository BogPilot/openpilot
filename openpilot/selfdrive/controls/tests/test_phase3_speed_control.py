"""Deterministic replay tests for phase3_speed_control (no msgq / pyray / render)."""
import math
import unittest
from types import SimpleNamespace as NS

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from opendbc.car.tesla_ap1.slc_raise import next_5_ms, prev_5_ms

MPH = sc.MPH_TO_MS
DT = sc.DT_MDL


class FakeStore:
  def __init__(self, **vals):
    self.vals = {k: str(v) for k, v in vals.items()}
    self.puts = []

  def raw(self, k): return self.vals.get(k)
  def invalidate(self, k=None): pass
  def put(self, k, v):
    v = ("1" if v else "0") if isinstance(v, bool) else (f"{v:g}" if isinstance(v, float) else str(v))   # ParamStore.put text rules
    self.vals[k] = v
    self.puts.append((k, v))
  def put_bool(self, k, v): self.put(k, bool(v))
  def _d(self, k): return BOGPILOT_PARAMS[k][2] if k in BOGPILOT_PARAMS and BOGPILOT_PARAMS[k][2] is not None else ""
  def get(self, k, default=None): return self.vals.get(k, self._d(k) if default is None else default)
  def get_bool(self, k, default=None):
    v = self.vals.get(k)
    if v is None:
      return bool(default) if default is not None else self._d(k) in ("1", "true")
    return v in ("1", "true")
  def get_float(self, k, default=None):
    try: return float(self.vals.get(k, self._d(k)))
    except ValueError: return float(default or 0.0)
  def get_int(self, k, default=None): return int(round(self.get_float(k, default)))
  def tuning_level(self): return 3
  def honoured(self, k, level=None): return (BOGPILOT_PARAMS[k][3] or 0) <= (3 if level is None else level)
  def _stock(self, k): return BOGPILOT_PARAMS[k][4] or ""
  def toggle_bool(self, k, level=None): return self.get_bool(k) if level != -1 and self.honoured(k, level) else self._stock(k) == "1"
  def toggle_float(self, k, level=None): return self.get_float(k) if level != -1 and self.honoured(k, level) else float(self._stock(k) or 0)
  def toggle_int(self, k, level=None): return int(self.toggle_float(k, level))
  def toggle_str(self, k, level=None): return self.get(k) if level != -1 and self.honoured(k, level) else self._stock(k)


CP_AP1 = NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True, radarUnavailable=False, enableBsm=True)


def toggles(**vals):
  vals.setdefault("SpeedLimitController", "1")
  vals.setdefault("SLCPriority1", "Dashboard")
  return onroad_toggles(FakeStore(**vals), CP_AP1)


class Sm(dict):
  def __init__(self):
    super().__init__()
    self.alive, self.valid = {}, {}
    self.set(limit=0.0)

  def set(self, limit=None, v_ego=20.0, enabled=True, cruise=True, up=False, dn=False, rwd=False, spd=0, gas=False,
          long_active=True, vcc=None, ok=True):
    bp = NS(accelPressed=up, decelPressed=dn, resumePressed=rwd, spdCtrlLvr=spd,
            dashboardSpeedLimit=self.get("_limit", 0.0) if limit is None else limit)
    self["_limit"] = bp.dashboardSpeedLimit
    self["carState"] = NS(bogpilot=bp, gasPressed=gas, vEgoCluster=v_ego, vCruiseCluster=0.0 if vcc is None else vcc,
                          cruiseState=NS(enabled=cruise))
    self["selfdriveState"] = NS(enabled=enabled)
    self["carControl"] = NS(longActive=long_active)
    for k in ("carState", "selfdriveState", "carControl"):
      self.alive[k] = self.valid[k] = ok
    return self


def make(t=None, store=None, cp=CP_AP1, adopted=True, auto_speed=True):
  t = t or toggles()
  return sc.Ap1SpeedControl(cp, store=store, toggles_fn=lambda: t, clock=lambda: 0.0, adopted=adopted, auto_speed=auto_speed)


def run(ctl, sm, v_cruise, v_ego, n=1, **kw):
  out = None
  for _ in range(n):
    sm.set(v_ego=v_ego, **kw)
    cs = sm["carState"]   # car-side set as VCruiseHelper saw it (pcmCruise): cruiseState.speed = v_cruise
    cs.cruiseState.available, cs.cruiseState.speed, cs.cruiseState.speedCluster = True, v_cruise, 0.0
    cs.vCruise = v_cruise * sc.MS_TO_KPH
    out = ctl.update(sm, v_cruise, v_ego, DT)
  return out


class TestOffsets(unittest.TestCase):
  def test_imperial_bands_and_25_edge(self):
    t = toggles()  # registry defaults 5,5,5,5,10,10,10 mph
    self.assertAlmostEqual(sc.offset_for(24 * MPH, t), 5 * MPH)
    self.assertAlmostEqual(sc.offset_for(25 * MPH, t), 5 * MPH)
    t2 = toggles(Offset1="1", Offset2="2", Offset5="7", Offset7="9")
    self.assertAlmostEqual(sc.offset_for(25 * MPH, t2), 2 * MPH)   # 25 mph is band 2, not 1 (0.9.7 fix)
    self.assertAlmostEqual(sc.offset_for(55 * MPH, t2), 7 * MPH)
    self.assertAlmostEqual(sc.offset_for(99 * MPH, t2), 9 * MPH)
    self.assertEqual(sc.offset_for(100 * MPH, t2), 0.0)

  def test_metric_bands_and_units(self):
    t = toggles(IsMetric="1", Offset3="8")
    self.assertAlmostEqual(sc.offset_for(50 / 3.6, t), 8 / 3.6)   # stored km/h
    self.assertAlmostEqual(sc.offset_for(29 / 3.6, t), 5 / 3.6)

  def test_bounds_and_invalid(self):
    self.assertAlmostEqual(sc.clip_offset_ms(500 * MPH, False), 99 * MPH)
    self.assertAlmostEqual(sc.clip_offset_ms(-500 / 3.6, True), -150 / 3.6)
    self.assertEqual(sc.clip_offset_ms(float("nan"), False), 0.0)
    for bad in (float("nan"), float("inf"), -3.0, 150.0, None, "x"):
      self.assertEqual(sc.dashboard_limit_ms(bad), 0.0)
    self.assertEqual(sc.dashboard_limit_ms(20.0), 20.0)

  def test_slc_off_offsets_zero(self):
    t = toggles(SpeedLimitController="0")
    self.assertEqual(sc.offset_for(30 * MPH, t), 0.0)


class TestInactive(unittest.TestCase):
  def test_passthrough_bit_exact(self):
    for ctl in (make(toggles(SpeedLimitController="0")),
                make(cp=NS(carFingerprint="TESLA_MODEL_3", openpilotLongitudinalControl=True)),
                make(cp=NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=False))):
      sm = Sm()
      self.assertEqual(run(ctl, sm, 13.37, 20.0, limit=45 * MPH, rwd=True), 13.37)
      plan = NS()
      ctl.fill(plan)
      self.assertEqual((plan.slcSpeedLimit, plan.slcSpeedLimitSource, ctl.experimental_mode), (0.0, "", False))
      self.assertFalse(hasattr(plan, "experimentalMode"))

  def test_stale_carstate_fail_closed_and_clears_latch(self):
    ctl, sm = make(), Sm()
    run(ctl, sm, 10.0, 20.0, limit=45 * MPH, cruise=False, up=True)
    run(ctl, sm, 10.0, 20.0, limit=45 * MPH, cruise=True)      # tip engage -> sticky 20
    self.assertTrue(ctl.holdoff.sticky_vego)
    self.assertEqual(run(ctl, sm, 10.0, 20.0, ok=False), 10.0)
    self.assertFalse(ctl.holdoff.sticky_vego)
    self.assertFalse(ctl.active)

  def test_nonfinite_input(self):
    ctl, sm = make(), Sm()
    self.assertTrue(math.isnan(run(ctl, sm, float("nan"), 20.0, limit=45 * MPH)))


class TestAp1Stalk(unittest.TestCase):
  def engage(self, ctl, sm, v_ego, limit, **press):
    run(ctl, sm, 10.0, v_ego, limit=limit, cruise=False, **press)
    run(ctl, sm, 10.0, v_ego, limit=limit, cruise=False)
    return run(ctl, sm, 10.0, v_ego, limit=limit, cruise=True)

  def test_pull_engage_tracks_posted_plus_offset(self):
    ctl, sm = make(), Sm()
    out = self.engage(ctl, sm, 20.0, 45 * MPH, rwd=True)
    self.assertAlmostEqual(out, 50 * MPH, places=4)              # 45 + Offset4 5 mph; DI seed 10 m/s ignored
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, limit=35 * MPH), 40 * MPH, places=4)  # follows a normal drop

  def test_unclassified_engage_latches_vego(self):
    """No stalk seen at the engage edge: latch vEgo (never SLC), held through higher and lower limits."""
    ctl, sm = make(), Sm()
    self.assertAlmostEqual(self.engage(ctl, sm, 20.0, 45 * MPH), 45 * MPH, places=4)   # v6: whole mph (20 m/s = 44.7 mph)
    self.assertTrue(ctl.holdoff.sticky_vego)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, limit=60 * MPH, n=10), 45 * MPH, places=4)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, limit=25 * MPH, n=10), 45 * MPH, places=4)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, limit=45 * MPH, rwd=True), 50 * MPH, places=4)  # pull -> SLC

  def test_pull_engage_follows_slc(self):
    ctl, sm = make(), Sm()
    self.assertAlmostEqual(self.engage(ctl, sm, 20.0, 45 * MPH, rwd=True), 50 * MPH, places=4)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, limit=55 * MPH, n=3), 65 * MPH, places=4)    # follows a raise (55 + 10 band)

  def test_tip_engage_is_sticky_through_limit_changes(self):
    ctl, sm = make(), Sm()
    out = self.engage(ctl, sm, 15 * MPH, 15 * MPH, up=True)
    self.assertAlmostEqual(out, 15 * MPH, places=4)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 15 * MPH, limit=35 * MPH, n=5), 15 * MPH, places=4)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 15 * MPH, limit=35 * MPH, rwd=True), 40 * MPH, places=4)  # pull clears

  def test_engaged_tips_plus_minus_one_and_next5(self):
    ctl, sm = make(), Sm()
    self.engage(ctl, sm, 20.0, 45 * MPH, rwd=True)               # set 50
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, up=True, spd=16), 51 * MPH, places=3)
    run(ctl, sm, 10.0, 20.0)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, dn=True, spd=8), prev_5_ms(51 * MPH), places=3)  # 50
    run(ctl, sm, 10.0, 20.0)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, up=True, spd=4), next_5_ms(50 * MPH), places=3)  # 55
    run(ctl, sm, 10.0, 20.0)
    self.assertAlmostEqual(run(ctl, sm, 10.0, 20.0, limit=25 * MPH, n=3), 55 * MPH, places=3)      # tip holds

  def test_tip_hold_repeat_and_floor(self):
    ctl, sm = make(), Sm()
    self.engage(ctl, sm, 3 * MPH, 0.0, dn=True)                  # sticky 3 mph
    run(ctl, sm, 10.0, 3 * MPH, dn=True, spd=32)
    run(ctl, sm, 10.0, 3 * MPH)
    run(ctl, sm, 10.0, 3 * MPH, dn=True, spd=32)
    run(ctl, sm, 10.0, 3 * MPH)
    out = run(ctl, sm, 10.0, 3 * MPH, dn=True, spd=32)
    self.assertAlmostEqual(ctl.holdoff.tip_ms, 1 * MPH, places=4)   # floor 1 mph, never 0
    ctl2, sm2 = make(), Sm()
    self.engage(ctl2, sm2, 20.0, 45 * MPH, rwd=True)
    run(ctl2, sm2, 10.0, 20.0, up=True, spd=16, n=int(0.45 / DT) + 2)
    self.assertAlmostEqual(ctl2.holdoff.tip_ms, 52 * MPH, places=3)  # 50 mph set, 0.5 s shallow hold: +1 on the press, +1 repeat at 0.35 s, never a +5
    self.assertGreater(out, 0)

  def test_disengage_clears_and_cap(self):
    ctl, sm = make(), Sm()
    self.engage(ctl, sm, 20.0, 45 * MPH, rwd=True)
    run(ctl, sm, 10.0, 20.0, up=True, spd=16)
    run(ctl, sm, 10.0, 20.0, cruise=False)
    self.assertEqual(ctl.holdoff.tip_ms, 0.0)
    ctl2, sm2 = make(toggles(Offset7="99")), Sm()
    out = self.engage(ctl2, sm2, 40.0, 99 * MPH, rwd=True)
    self.assertLessEqual(out, sc.V_CRUISE_MAX_MS + 1e-9)

  def test_guard_ignores_5mph_blip(self):
    ctl, sm = make(), Sm()
    self.engage(ctl, sm, 20.0, 45 * MPH, rwd=True)
    blip = [run(ctl, sm, 10.0, 20.0, limit=5 * MPH) for _ in range(int(1.4 / DT))]
    self.assertTrue(all(abs(b - 50 * MPH) < 1e-3 for b in blip))
    plan = NS()
    ctl.fill(plan)
    self.assertAlmostEqual(plan.slcSpeedLimit, 45 * MPH, places=4)
    self.assertEqual(plan.slcSpeedLimitSource, "Dashboard")

  def test_standstill_tap_holds_setting_in_ms(self):
    """Standstill tap latches AP1TapFromZeroMph in m/s (default 15, also 5 and 30) and later ticks never exceed it."""
    for mph in (15, 5, 30):
      for press in ({"up": True}, {"dn": True}):
        store = FakeStore(AP1TapFromZeroMph=str(mph))
        ctl, sm = make(store=store), Sm()
        want = mph * MPH
        out = self.engage(ctl, sm, 0.0, 0.0, **press)
        self.assertAlmostEqual(out, want, places=4, msg=f"{mph} mph {press}")
        self.assertAlmostEqual(ctl.holdoff.tap_from_zero_ms, want, places=4)
        later = [run(ctl, sm, out, 0.0) for _ in range(int(1.0 / DT) + 1)]
        self.assertTrue(all(abs(x - want) < 1e-3 for x in later), msg=f"{mph} mph later={later[:5]}...{later[-3:]}")
        self.assertTrue(all(x <= want + 1e-6 for x in later), msg=f"{mph} mph rose above setting")


class TestSlcSettings(unittest.TestCase):
  def test_confirmation_accept_deny_timeout(self):
    t = toggles(SLCConfirmation="1", SLCConfirmationHigher="1", SLCConfirmationLower="1")
    ctl, sm = make(t), Sm()
    run(ctl, sm, 30.0, 20.0, limit=45 * MPH, cruise=False)
    self.assertEqual(ctl.slc.target, 0.0)
    self.assertAlmostEqual(ctl.slc.unconfirmed_speed_limit, 45 * MPH)
    plan = NS()
    run(ctl, sm, 30.0, 20.0, limit=45 * MPH, cruise=False)
    ctl.fill(plan)
    self.assertTrue(plan.speedLimitChanged)
    run(ctl, sm, 30.0, 20.0, limit=45 * MPH, cruise=False, up=True, long_active=True)   # accept
    self.assertAlmostEqual(ctl.slc.target, 45 * MPH)
    run(ctl, sm, 30.0, 20.0, limit=35 * MPH, cruise=False, dn=True)                      # deny
    self.assertAlmostEqual(ctl.slc.target, 45 * MPH)
    self.assertAlmostEqual(ctl.slc.denied_target, 35 * MPH)
    ctl2, sm2 = make(t), Sm()
    run(ctl2, sm2, 30.0, 20.0, limit=45 * MPH, cruise=False, n=int(30 / DT) + 1)
    self.assertEqual(ctl2.slc.target, 0.0)                                               # ignored 30 s -> denied

  def test_fallbacks(self):
    ctl, sm = make(toggles(SLCFallback="0")), Sm()
    run(ctl, sm, 25.0, 20.0, limit=0.0, enabled=False)
    self.assertEqual(ctl.slc.target, 0.0)
    run(ctl, sm, 25.0, 20.0, limit=0.0, enabled=True)
    self.assertAlmostEqual(ctl.slc.target, 25.0)                                         # set speed
    store = FakeStore(PreviousSpeedLimit=str(40 * MPH))
    ctl2, sm2 = make(toggles(SLCFallback="2"), store=store), Sm()
    run(ctl2, sm2, 25.0, 20.0, limit=0.0)
    self.assertAlmostEqual(ctl2.slc.target, 40 * MPH)                                    # previous limit
    run(ctl2, sm2, 25.0, 20.0, limit=30 * MPH)
    self.assertIn(("PreviousSpeedLimit", str(30 * MPH)), store.puts)
    ctl3, sm3 = make(toggles(SLCFallback="1")), Sm()
    run(ctl3, sm3, 25.0, 20.0, limit=0.0)
    self.assertTrue(ctl3.experimental_mode)
    run(ctl3, sm3, 25.0, 20.0, limit=30 * MPH)
    self.assertFalse(ctl3.experimental_mode)

  def test_override_manual_and_set_speed(self):
    ctl, sm = make(toggles(SLCOverride="1")), Sm()
    run(ctl, sm, 30.0, 20.0, limit=35 * MPH, rwd=True, cruise=False)
    run(ctl, sm, 30.0, 20.0, limit=35 * MPH, cruise=True)
    run(ctl, sm, 30.0, 25.0, limit=35 * MPH, gas=True)
    self.assertAlmostEqual(ctl.slc.overridden_speed, 25.0)
    self.assertEqual(ctl.slc.source, "None")
    ctl2, sm2 = make(toggles(SLCOverride="2")), Sm()
    run(ctl2, sm2, 30.0, 20.0, limit=35 * MPH, rwd=True, cruise=False)
    run(ctl2, sm2, 30.0, 20.0, limit=35 * MPH, cruise=True)
    run(ctl2, sm2, 30.0, 25.0, limit=35 * MPH, gas=True)
    # AP1 openpilot long, pull engage: no driver-chosen set, so Max Set Speed is the current limit + offset (35 + 5),
    # not carState.vCruise (the car-layer engage latch).
    self.assertAlmostEqual(ctl2.slc.overridden_speed, 40 * MPH, places=4)
    preap = NS(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True, radarUnavailable=False, enableBsm=False)
    ctl4, sm4 = make(toggles(SLCOverride="2"), cp=preap), Sm()
    run(ctl4, sm4, 30.0, 20.0, limit=35 * MPH, rwd=True, cruise=False)
    run(ctl4, sm4, 30.0, 20.0, limit=35 * MPH, cruise=True)
    run(ctl4, sm4, 30.0, 25.0, limit=35 * MPH, gas=True)
    self.assertAlmostEqual(ctl4.slc.overridden_speed, 30.0)   # Pre-AP: v_cruise is the driver's captured set (0.9.7)
    ctl3, sm3 = make(toggles(SLCOverride="0")), Sm()
    run(ctl3, sm3, 30.0, 25.0, limit=35 * MPH, gas=True)
    self.assertEqual(ctl3.slc.overridden_speed, 0.0)

  def test_dashboard_authority_even_when_not_in_priority_list(self):
    ctl, sm = make(toggles(SLCPriority1="Navigation", SLCPriority2="None", SLCPriority3="None", SLCFallback="0")), Sm()
    run(ctl, sm, 25.0, 20.0, limit=45 * MPH, enabled=False)
    self.assertAlmostEqual(ctl.slc.target, 45 * MPH, places=4)
    self.assertEqual(ctl.slc.source, "Dashboard")
    # With no Dashboard (and no Navigation producer) the listed priorities find nothing.
    run(ctl, sm, 25.0, 20.0, limit=0.0, enabled=False)
    self.assertEqual(ctl.slc.target, 0.0)


class TestClusterLift(unittest.TestCase):
  def test_lift_when_plan_set_is_valid(self):
    # 0.9.7 lifted whenever plan.vCruise was a usable set, including an empty
    # source name ("active, no source yet"). 30 m/s = 108 kph.
    plan = NS(slcSpeedLimitSource="", vCruise=30.0)
    self.assertAlmostEqual(sc.cluster_set_kph(50.0, plan, True), 108.0)
    plan.slcSpeedLimitSource = "Dashboard"
    self.assertAlmostEqual(sc.cluster_set_kph(50.0, plan, True), 108.0)
    self.assertEqual(sc.cluster_set_kph(50.0, plan, False), 50.0)
    plan.vCruise = float("nan")
    self.assertEqual(sc.cluster_set_kph(50.0, plan, True), 50.0)
    plan.vCruise = 10.0
    self.assertEqual(sc.cluster_set_kph(50.0, plan, True), 50.0)   # never lowers
    self.assertEqual(sc.cluster_set_kph(50.0, None, False), 50.0)

  def test_engage_floor_hides_di_seed_then_lifts_to_slc(self):
    # DI seed 8 mph (~12.9 kph), vEgo 25 mph, later plan 40 mph (SLC+offset).
    di_kph = 8 * MPH * sc.MS_TO_KPH          # MPH in this file is 0.44704 (1 mph in m/s)
    v_ego = 25 * MPH
    slc = 40 * MPH
    # No plan yet: IC shows current speed, not 8 mph.
    shown = sc.cluster_set_kph(di_kph, None, False, v_ego_ms=v_ego, engage_floor=True)
    self.assertAlmostEqual(shown, v_ego * sc.MS_TO_KPH, places=4)
    self.assertGreater(shown, 20.0)   # well above 8 mph in kph
    # Plan still at the DI seed: floor holds vEgo (lift would not raise 8 mph to 25).
    plan = NS(slcSpeedLimitSource="", vCruise=8 * MPH)
    shown = sc.cluster_set_kph(di_kph, plan, True, v_ego_ms=v_ego, engage_floor=True)
    self.assertAlmostEqual(shown, v_ego * sc.MS_TO_KPH, places=4)
    # Plan has the SLC target: lift, floor no longer needed.
    plan.vCruise = slc
    shown = sc.cluster_set_kph(di_kph, plan, True, v_ego_ms=v_ego, engage_floor=False)
    self.assertAlmostEqual(shown, slc * sc.MS_TO_KPH, places=4)

  def test_engage_cluster_floor_releases_once_plan_catches_up(self):
    floor = sc.EngageClusterFloor()
    v_ego = 25 * MPH
    self.assertFalse(floor.update(False, False, 0.0, v_ego))
    self.assertTrue(floor.update(True, False, 0.0, v_ego))          # enabled, no plan yet
    self.assertTrue(floor.update(True, True, 8 * MPH, v_ego))      # plan still the 8 mph seed
    self.assertFalse(floor.update(True, True, v_ego, v_ego))       # plan reached vEgo (sticky or mid-raise)
    self.assertFalse(floor.update(True, True, 40 * MPH, v_ego))    # stays off so a down tip can show
    self.assertFalse(floor.update(False, True, 40 * MPH, v_ego))   # disengage clears
    self.assertTrue(floor.update(True, True, 8 * MPH, v_ego))      # next engage floors again

  def test_engage_cluster_floor_arms_only_on_the_enable_edge(self):
    """A DN tip below vEgo after the release must show the tipped set (20), not vEgo (20.9)."""
    floor = sc.EngageClusterFloor()
    v_ego = 20.9 * MPH
    self.assertTrue(floor.update(True, True, 8 * MPH, v_ego))      # enable edge: armed
    self.assertFalse(floor.update(True, True, 25 * MPH, v_ego))    # plan caught up: released
    for _ in range(50):
      self.assertFalse(floor.update(True, True, 20 * MPH, v_ego))  # DN tip to 20 below vEgo: stays released
    self.assertEqual(sc.cluster_set_kph(20 * MPH * 3.6, None, False, v_ego_ms=v_ego,
                                        engage_floor=floor.update(True, True, 20 * MPH, v_ego)), 20 * MPH * 3.6)
    self.assertFalse(floor.update(False, True, 20 * MPH, v_ego))   # disengage
    self.assertTrue(floor.update(True, True, 20 * MPH, v_ego))     # next enable edge arms again


class TestCerealAndIntegration(unittest.TestCase):
  def test_fill_real_bogpilot_plan(self):
    from openpilot.cereal import custom
    ctl, sm = make(), Sm()
    run(ctl, sm, 10.0, 20.0, limit=45 * MPH, rwd=True, cruise=False)
    run(ctl, sm, 10.0, 20.0, limit=45 * MPH)
    plan = custom.BogPilotPlan.new_message()
    ctl.fill(plan)
    self.assertAlmostEqual(plan.slcSpeedLimit, 45 * MPH, places=4)
    self.assertAlmostEqual(plan.slcSpeedLimitOffset, 5 * MPH, places=4)
    self.assertEqual(plan.slcSpeedLimitSource, "Dashboard")
    plan.vCruise = float(ctl.v_cruise_out)
    self.assertGreater(sc.cluster_set_kph(16.0, plan, True), 16.0)

  def _src(self, rel):
    from pathlib import Path
    return (Path(sc.__file__).resolve().parents[3] / rel).read_text()

  def test_shared_patches_when_integrated(self):
    planner = self._src("selfdrive/controls/lib/longitudinal_planner.py")
    if "speed_control" not in planner:
      self.skipTest("shared planner patch not applied")
    self.assertLess(planner.index("self.speed_control.update("), planner.index("self.curve_speed.update("))
    self.assertIn("self.speed_control.fill(", planner)
    self.assertIn("self.speed_control.resolve_experimental(", planner)
    self.assertIn("cluster_set_kph", self._src("selfdrive/car/card.py"))
    from pathlib import Path
    cs = (Path(sc.__file__).resolve().parents[4] / "opendbc_repo/opendbc/car/tesla_ap1/carstate.py").read_text()
    for f in ("fp_ret.accelPressed", "fp_ret.decelPressed", "fp_ret.resumePressed"):
      self.assertIn(f, cs)


class TestContract(unittest.TestCase):
  def test_constants_match_sources(self):
    from pathlib import Path
    root = Path(sc.__file__).resolve().parents[3]
    self.assertIn("CRUISING_SPEED = 5 ", (root / "selfdrive/controls/lib/bogpilot_csc.py").read_text())
    self.assertIn("V_CRUISE_MAX = 145\n", (root / "selfdrive/car/cruise.py").read_text())
    self.assertAlmostEqual(sc.V_CRUISE_MAX_MS, 145 / 3.6)

  def test_no_cloud_or_key_paths(self):
    from pathlib import Path
    src = Path(sc.__file__).read_text()
    # no network client / cloud endpoint / upload path in the consumer itself. The Mapbox filler lives in
    # system/bogpilot/osm/mapbox.py (user key only, optional); here the key is only ever read through the store.
    for bad in ("import requests", "mapbox_token", "WeatherToken", "api.mapbox", "athena", "upload", "urllib"):
      self.assertNotIn(bad, src)


class TestAdoptionAndDefaults(unittest.TestCase):
  """Policy "adoption" (the earlier stock-equivalent mode, kept as a switch): the registry default
  SpeedLimitController="1" must not wake the consumer until a panel row is used. The shipped policy is default_on (below)."""

  def setUp(self):
    self._policy = sc.ACTIVATION_POLICY
    sc.ACTIVATION_POLICY = "adoption"

  def tearDown(self):
    sc.ACTIVATION_POLICY = self._policy

  def ticking(self):
    t = [0.0]
    def clock():
      t[0] += 2.0   # beat the 1 s toggle cache every call
      return t[0]
    return clock

  def test_registry_default_is_on_but_consumer_is_dormant(self):
    self.assertEqual(BOGPILOT_PARAMS["SpeedLimitController"][2], "1")
    store = FakeStore()                                    # fresh install: nothing written
    ctl = sc.Ap1SpeedControl(CP_AP1, store=store, clock=self.ticking())
    sm = Sm()
    for _ in range(20):
      self.assertEqual(run(ctl, sm, 13.37, 20.0, limit=45 * MPH, rwd=True), 13.37)   # bit-exact passthrough
    plan = NS()
    ctl.fill(plan)
    self.assertEqual((plan.slcSpeedLimit, plan.slcSpeedLimitSource), (0.0, ""))
    self.assertFalse(ctl.active)
    self.assertEqual(store.puts, [])                       # reading / running never writes defaults

  def test_saved_values_without_marker_stay_dormant_and_untouched(self):
    store = FakeStore(SpeedLimitController="1", SLCOverride="2", Offset4="8", SLCFallback="0")
    before = dict(store.vals)
    ctl = sc.Ap1SpeedControl(CP_AP1, store=store, clock=self.ticking())
    self.assertEqual(run(ctl, Sm(), 20.0, 20.0, limit=30 * MPH), 20.0)
    self.assertEqual(store.vals, before)

  def test_configure_adopts_without_touching_other_saved_values(self):
    store = FakeStore(SLCOverride="1", Offset4="8", Offset1="3", SLCFallback="0")
    sc.configure(store, "SpeedLimitController", True)
    self.assertEqual(store.puts, [("SpeedLimitController", "1"), (sc.SLC_ACK, "1")])
    self.assertEqual({k: store.vals[k] for k in ("SLCOverride", "Offset4", "Offset1", "SLCFallback")},
                     {"SLCOverride": "1", "Offset4": "8", "Offset1": "3", "SLCFallback": "0"})
    with self.assertRaises(ValueError):
      sc.configure(store, "AccelerationProfile", 1)
    with self.assertRaises(ValueError):
      sc.configure(store, sc.SLC_ACK, False)

  def test_adopted_store_activates_real_toggle_path(self):
    store = FakeStore(Offset4="8")
    ctl = sc.Ap1SpeedControl(CP_AP1, store=store, clock=self.ticking())
    sm = Sm()
    self.assertEqual(run(ctl, sm, 30.0, 20.0, limit=45 * MPH), 30.0)
    sc.configure(store, "SLCOverride", 2)                  # any panel write adopts the group (default SLC "1")
    out = run(ctl, sm, 30.0, 20.0, limit=45 * MPH, rwd=True)  # pull engage: SLC mode (a no-stalk engage latches vEgo)
    self.assertAlmostEqual(out, 53 * MPH, places=4)        # 45 + saved Offset4 = 8 mph
    sc.configure(store, "SpeedLimitController", False)     # user turns SLC off: adopted but off -> passthrough
    self.assertEqual(run(ctl, sm, 30.0, 20.0, limit=45 * MPH), 30.0)

  def test_no_store_and_unreadable_marker_fail_closed(self):
    t = toggles()
    ctl = sc.Ap1SpeedControl(CP_AP1, toggles_fn=lambda: t, clock=lambda: 0.0)   # adopted=None, no store
    self.assertEqual(run(ctl, Sm(), 30.0, 20.0, limit=45 * MPH), 30.0)

    class Broken(FakeStore):
      def get_bool(self, k, default=None):
        raise OSError("boom")
    self.assertFalse(sc.slc_adopted(Broken()))


class TestExperimentalFallbackPolicy(unittest.TestCase):
  """The previous release baseline default is "or" (manual Experimental Mode is never cancelled by a known SLC limit)."""

  def ctl(self, fallback="1", **kw):
    return make(toggles(SLCFallback=fallback), **kw), Sm()

  def test_default_policy_is_or(self):
    self.assertEqual(sc.EXPERIMENTAL_POLICY, "or")
    self.assertEqual(self.ctl()[0].experimental_policy, "or")

  def test_replace_semantics_still_available(self):
    ctl, sm = self.ctl()
    ctl.experimental_policy = "replace"
    run(ctl, sm, 25.0, 20.0, limit=0.0)                                 # no limit known
    self.assertIs(ctl.experimental_override, True)
    self.assertTrue(ctl.resolve_experimental(False))                    # fallback turns experimental on
    run(ctl, sm, 25.0, 20.0, limit=30 * MPH)                            # limit known
    self.assertIs(ctl.experimental_override, False)
    self.assertFalse(ctl.resolve_experimental(True))                    # replace still cancels the manual flag
    self.assertFalse(ctl.resolve_experimental(False))

  def test_or_policy_never_cancels_manual(self):
    ctl, sm = self.ctl()
    run(ctl, sm, 25.0, 20.0, limit=30 * MPH)
    self.assertTrue(ctl.resolve_experimental(True))
    self.assertFalse(ctl.resolve_experimental(False))
    run(ctl, sm, 25.0, 20.0, limit=0.0)
    self.assertTrue(ctl.resolve_experimental(False))

  def test_no_override_leaves_manual_flag_alone(self):
    for fallback in ("0", "2"):                                         # Set Speed / Previous Limit
      ctl, sm = self.ctl(fallback)
      run(ctl, sm, 25.0, 20.0, limit=0.0)
      self.assertIsNone(ctl.experimental_override)
      self.assertTrue(ctl.resolve_experimental(True))
      self.assertFalse(ctl.resolve_experimental(False))
    ctl, sm = self.ctl(adopted=False)                                   # not adopted -> inactive
    run(ctl, sm, 25.0, 20.0, limit=0.0)
    self.assertIsNone(ctl.experimental_override)
    self.assertTrue(ctl.resolve_experimental(True))
    ctl, sm = self.ctl()
    run(ctl, sm, 25.0, 20.0, limit=0.0)
    run(ctl, sm, 25.0, 20.0, limit=0.0, ok=False)                       # stale carState -> inactive -> manual
    self.assertIsNone(ctl.experimental_override)
    self.assertFalse(ctl.resolve_experimental(False))



class TestDefaultOnActivation(unittest.TestCase):
  """SLC default ON as in 0.9.7: saved/registry values decide, nothing is rewritten."""

  def ticking(self):
    t = [0.0]
    def clock():
      t[0] += 2.0
      return t[0]
    return clock

  def test_default_policy_is_default_on(self):
    self.assertEqual(sc.ACTIVATION_POLICY, "default_on")
    self.assertTrue(sc.slc_adopted(FakeStore()))

  def test_fresh_install_follows_a_lower_limit_without_any_panel_use(self):
    store = FakeStore(Offset4="8", SLCPriority1="Dashboard")
    ctl = sc.Ap1SpeedControl(CP_AP1, store=store, clock=self.ticking())
    out = run(ctl, Sm(), 30.0, 20.0, limit=45 * MPH, rwd=True)  # pull engage: SLC mode (a no-stalk engage latches vEgo)
    self.assertAlmostEqual(out, 53 * MPH, places=4)
    self.assertEqual({k for k, _ in store.puts}, {"PreviousSpeedLimit"})   # 0.9.7 bookkeeping only; no saved pref is rewritten

  def test_user_turning_slc_off_is_passthrough(self):
    store = FakeStore(SpeedLimitController="0")
    ctl = sc.Ap1SpeedControl(CP_AP1, store=store, clock=self.ticking())
    self.assertEqual(run(ctl, Sm(), 30.0, 20.0, limit=45 * MPH), 30.0)

  def test_not_ap1_or_no_openpilot_long_is_passthrough(self):
    for cp in (NS(carFingerprint="OTHER", openpilotLongitudinalControl=True),
               NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=False)):
      ctl = sc.Ap1SpeedControl(cp, store=FakeStore(), clock=self.ticking())
      self.assertEqual(run(ctl, Sm(), 30.0, 20.0, limit=45 * MPH), 30.0)


if __name__ == "__main__":
  unittest.main()


class TestClusterShowsCurveSpeed(unittest.TestCase):
  """IC set through a curve: the CSC-capped plan set shows as is, down and back up (BogPilot 0.9.7), no hold."""

  def plan(self, v_mph, csc):
    return NS(vCruise=v_mph * MPH, cscControllingSpeed=csc)

  def op_long_mph(self, p, latch_mph):
    # AP1 openpilot long after the engage floor released: card.py passes no plan_v_ms.
    return sc.cluster_set_kph(latch_mph * MPH * 3.6, p, True, v_ego_ms=latch_mph * MPH, follow_plan=True) / 3.6 / MPH

  def test_digit_tracks_the_csc_target_through_a_corner(self):
    seq = [(30, False), (29.4, True), (28.2, True), (26.9, True), (25.4, True), (25.0, True), (27.5, True), (30, False)]
    for v, csc in seq:
      self.assertAlmostEqual(self.op_long_mph(self.plan(v, csc), 30), v, places=3)

  def test_short_and_shallow_caps_are_shown_too(self):
    for v, csc in [(40, False), (37, True), (40, False), (49.2, True), (50, False)]:
      self.assertAlmostEqual(self.op_long_mph(self.plan(v, csc), 40), v, places=3)

  def test_lift_only_over_the_car_cruise_set_like_0_9_7(self):
    # Without the openpilot-long latch the base is the car's cruise set (0.9.7 carstate DI_cruiseSet) and the IC shows
    # max(base, plan) (0.9.7 cluster_display_kph): a capped plan above the DI set shows, the DI set is the floor.
    p = self.plan(25.4, True)
    self.assertAlmostEqual(sc.cluster_set_kph(13 * MPH * 3.6, p, True) / 3.6 / MPH, 25.4, places=3)
    self.assertAlmostEqual(sc.cluster_set_kph(27 * MPH * 3.6, p, True) / 3.6 / MPH, 27, places=3)

  def test_no_curve_hold_in_the_card(self):
    import pathlib
    src = (pathlib.Path(sc.__file__).parents[2] / "car" / "card.py").read_text()
    self.assertNotIn("CurveDisplayHold", src)
    self.assertNotIn("plan_v_ms=", src)
    self.assertFalse(hasattr(sc, "CurveDisplayHold"))


class TestOpLongClusterFollowsPlan(unittest.TestCase):
  """AP1 openpilot long: the cluster base is the engage set, so the IC must not be max(engage set, plan)."""

  def plan(self, v_mph, csc=False):
    from types import SimpleNamespace
    return SimpleNamespace(vCruise=v_mph * MPH, cscControllingSpeed=csc)

  def test_engage_floor_holds_engage_set_then_down_tip_shows(self):
    floor, latch, v_ego = sc.EngageClusterFloor(), 30 * MPH, 14.6 * MPH
    def disp(p, tip=False):
      return sc.cluster_set_kph(latch * 3.6, p, True, v_ego_ms=v_ego, follow_plan=True,
                                engage_floor=floor.update(True, True, p.vCruise, v_ego, floor_ms=latch, tip=tip)) / 3.6 / MPH
    self.assertAlmostEqual(disp(self.plan(14.6)), 30, places=3)   # plan still at vEgo: IC holds the engage set
    self.assertAlmostEqual(disp(self.plan(30)), 30, places=3)     # plan reached it: released
    self.assertAlmostEqual(disp(self.plan(25)), 25, places=3)     # DN tips now show (not the 30 latch)
    self.assertAlmostEqual(disp(self.plan(20)), 20, places=3)

  def test_tip_releases_the_floor_at_once(self):
    floor, latch, v_ego = sc.EngageClusterFloor(), 40 * MPH, 24 * MPH
    self.assertTrue(floor.update(True, True, 24 * MPH, v_ego, floor_ms=latch))
    self.assertFalse(floor.update(True, True, 24 * MPH, v_ego, floor_ms=latch, tip=True))
    self.assertAlmostEqual(sc.cluster_set_kph(latch * 3.6, self.plan(24), True, v_ego_ms=v_ego,
                                              follow_plan=True) / 3.6 / MPH, 24, places=3)

  def test_without_follow_plan_unchanged(self):
    self.assertAlmostEqual(sc.cluster_set_kph(30 * MPH * 3.6, self.plan(25), True) / 3.6 / MPH, 30, places=3)
    self.assertAlmostEqual(sc.cluster_set_kph(10 * MPH * 3.6, self.plan(25), True) / 3.6 / MPH, 25, places=3)
    floor = sc.EngageClusterFloor()
    self.assertTrue(floor.update(True, True, 10 * MPH, 20 * MPH))
    self.assertFalse(floor.update(True, True, 20 * MPH, 20 * MPH))


class TestPlannerClusterUnlifted(unittest.TestCase):
  """The card lifts carState.vCruiseCluster for the IC (engage floor, plan follow). On AP1 S/X with
  openpilot long the planner must see the unlifted value, so the display hold never feeds the SLC override."""

  def _override_args(self, vcc, limit=35 * MPH, v_cruise=30.0, gas=True):
    ctl, sm = make(toggles(SLCOverride="1")), Sm()
    seen = []
    orig = ctl.slc.update_override
    ctl.slc.update_override = lambda *a, **k: (seen.append(a), orig(*a, **k))[1]
    run(ctl, sm, v_cruise, 20.0, limit=limit, rwd=True, cruise=False, vcc=vcc)
    run(ctl, sm, v_cruise, 20.0, limit=limit, cruise=True, vcc=vcc)
    out = run(ctl, sm, v_cruise, 25.0, n=5, limit=limit, gas=gas, vcc=vcc)
    return seen, out, ctl.slc.overridden_speed

  def test_planner_input_unchanged_by_display_hold(self):
    base = self._override_args(vcc=30.0 * sc.MS_TO_KPH)            # unlifted: cluster == set
    for lifted_kph in (150.0, 200.0, 254.0):                         # IC held / lifted far above the set
      lifted = self._override_args(vcc=lifted_kph)
      self.assertEqual(lifted[0], base[0])
      self.assertEqual(lifted[1:], base[1:])
    self.assertTrue(base[0] and all(a[1] == 0.0 for a in base[0]))   # v_cruise_diff 0 on AP1 (cluster == set)

  def test_unlifted_cluster_matches_vcruisehelper(self):
    cs = NS(vCruise=0.0, cruiseState=NS(available=True, speed=20.0, speedCluster=0.0))
    self.assertAlmostEqual(sc.unlifted_cluster_kph(cs), 72.0)
    cs.cruiseState.speedCluster = 21.0
    self.assertAlmostEqual(sc.unlifted_cluster_kph(cs), 75.6)
    cs.cruiseState.speed = 0.0
    self.assertEqual(sc.unlifted_cluster_kph(cs), 255.0)
    cs.cruiseState.speed = -1.0
    self.assertEqual(sc.unlifted_cluster_kph(cs), -1.0)

  def test_other_cars_keep_carstate_cluster(self):
    ctl = make(cp=NS(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True))
    self.assertFalse(ctl._cluster_lifted)
    self.assertTrue(make()._cluster_lifted)


class TestMaxSetSpeedGasOverride(unittest.TestCase):
  """SLCOverride 2 (Max Set Speed) under AP1 openpilot long. carState.vCruise there is the car-layer engage latch,
  which after a pull is the engage-time limit + offset. The gas release returns to a set the driver chose (tap latch
  or tip), else to the current limit + offset."""

  def _engage(self, ctl, sm, v_ego, limit_mph, v_set, **press):
    run(ctl, sm, 0.0, v_ego, limit=limit_mph * MPH, cruise=False, **press)
    run(ctl, sm, 0.0, v_ego, limit=limit_mph * MPH, cruise=False)
    return run(ctl, sm, v_set, v_ego, limit=limit_mph * MPH, cruise=True)

  def _gas_then_release(self, ctl, sm, v_set, limit_mph, gas_mph, long_active_on_gas, gas_s=0.2, release_s=2.0):
    for _ in range(int(gas_s / DT)):
      run(ctl, sm, v_set, gas_mph * MPH, limit=limit_mph * MPH, gas=True, long_active=long_active_on_gas)
    return [run(ctl, sm, v_set, gas_mph * MPH, limit=limit_mph * MPH) for _ in range(int(release_s / DT))]

  def test_pull_then_lower_limit_gas_release_returns_to_current_limit_plus_offset(self):
    for long_active_on_gas in (False, True):
      with self.subTest(long_active_on_gas=long_active_on_gas):
        ctl, sm = make(toggles(SLCOverride="2")), Sm()
        v_set = 50 * MPH   # car-layer set after the pull: 45 + 5, held until disengage
        self.assertAlmostEqual(self._engage(ctl, sm, 45 * MPH, 45, v_set, rwd=True), 50 * MPH, places=4)
        out = [run(ctl, sm, v_set, 40 * MPH, limit=35 * MPH) for _ in range(int(3.0 / DT))]
        self.assertAlmostEqual(out[-1], 40 * MPH, places=4)
        after = self._gas_then_release(ctl, sm, v_set, 35, 45, long_active_on_gas)
        self.assertAlmostEqual(after[-1], 40 * MPH, places=4)
        self.assertTrue(all(x <= 40 * MPH + 1e-6 for x in after), msg=f"rose above 40 mph: {max(after) / MPH:.2f}")
        self.assertFalse(ctl.slc.override_slc)

  def test_tap_engage_latch_is_still_restored_after_gas(self):
    ctl, sm = make(toggles(SLCOverride="2")), Sm()
    v_set = 50 * MPH   # rolling tap at 50 mph in a 45 zone: the car latches vEgo
    self.assertAlmostEqual(self._engage(ctl, sm, 50 * MPH, 45, v_set, up=True, spd=16), 50 * MPH, places=4)
    out = [run(ctl, sm, v_set, 50 * MPH, limit=35 * MPH) for _ in range(int(3.0 / DT))]
    self.assertAlmostEqual(out[-1], 50 * MPH, places=4)
    for long_active_on_gas in (False, True):
      after = self._gas_then_release(ctl, sm, v_set, 35, 55, long_active_on_gas)
      self.assertAlmostEqual(after[-1], 50 * MPH, places=4)
    # A gas override longer than the longitudinal drop window also comes back to the tap latch.
    after = self._gas_then_release(ctl, sm, v_set, 35, 55, False, gas_s=1.5)
    self.assertAlmostEqual(after[-1], 50 * MPH, places=4)

  def test_tipped_set_is_still_restored_after_gas(self):
    ctl, sm = make(toggles(SLCOverride="2")), Sm()
    v_set = 50 * MPH
    self._engage(ctl, sm, 45 * MPH, 45, v_set, rwd=True)
    run(ctl, sm, v_set, 45 * MPH, limit=45 * MPH, up=True, spd=16)
    tipped = run(ctl, sm, v_set, 45 * MPH, limit=45 * MPH)
    self.assertAlmostEqual(tipped, 51 * MPH, places=3)
    out = [run(ctl, sm, v_set, 45 * MPH, limit=35 * MPH) for _ in range(int(3.0 / DT))]
    self.assertAlmostEqual(out[-1], 51 * MPH, places=3)
    for long_active_on_gas in (False, True):
      after = self._gas_then_release(ctl, sm, v_set, 35, 55, long_active_on_gas)
      self.assertAlmostEqual(after[-1], 51 * MPH, places=3)


class TestEngageSetWithSlcOff(unittest.TestCase):
  """Pins the current car-layer engage set with SpeedLimitController off (documented divergence in
  DIVERGENCES_ap1_op_long_set_speed.md): a pull with a known dashboard limit still latches that limit, with no offset
  (offset_for is 0 with SLC off), and the planner passes the car-side set through unchanged."""

  def _pull(self, slc, v_ms, standstill, limit_ms):
    from opendbc.car.tesla_ap1.op_long_set_speed import OpLongSetSpeed
    off = sc.EngageLimitOffset(CP_AP1, toggles_fn=lambda: toggles(SpeedLimitController=slc), clock=lambda: 0.0)
    ols = OpLongSetSpeed()
    ols.update("STANDBY", v_ms, standstill, limit_ms=limit_ms, offset_fn=off, pull=True)
    return ols.update("ENABLED", v_ms, standstill, limit_ms=limit_ms, offset_fn=off), ols

  def test_pull_with_slc_off_latches_the_dashboard_limit_without_offset(self):
    for standstill, v_ms in ((False, 20.0), (True, 0.0)):
      out, ols = self._pull("0", v_ms, standstill, 45 * MPH)
      self.assertAlmostEqual(out, 45 * MPH, places=4, msg=f"standstill={standstill}")
      self.assertFalse(ols.speed_limit_unknown)
      on, _ = self._pull("1", v_ms, standstill, 45 * MPH)
      self.assertAlmostEqual(on, 50 * MPH, places=4)   # SLC on: limit + Offset4 (5 mph)

  def test_pull_with_slc_off_and_no_limit_is_unchanged(self):
    out, _ = self._pull("0", 20.0, False, 0.0)
    self.assertAlmostEqual(out, 45 * MPH, places=4)    # rolling: vEgo in whole mph (v6; 20 m/s = 44.7 mph)
    out, ols = self._pull("0", 0.0, True, 0.0)
    self.assertEqual(out, 0.0)                         # standstill: refused (NO_ENTRY ap1SpeedLimitUnknown)
    self.assertTrue(ols.speed_limit_unknown)

  def test_planner_passes_the_car_side_set_through_with_slc_off(self):
    ctl, sm = make(toggles(SpeedLimitController="0")), Sm()
    run(ctl, sm, 0.0, 20.0, limit=45 * MPH, rwd=True, cruise=False)
    outs = [run(ctl, sm, 45 * MPH, 20.0, limit=lim * MPH) for lim in (45, 35, 25, 55)]
    self.assertTrue(all(abs(o - 45 * MPH) < 1e-6 for o in outs), outs)


class TestHeldGasPassThrough(unittest.TestCase):
  """Gas held longer than LongEngageGate.DROP_S after longitudinal was ours (AP1 openpilot long, SLCOverride 2). The
  lateral-only pass-through used carState.vCruise, the car-layer engage latch (after a pull, the engage-time limit +
  offset). It now shows the driver's own set, else the current limit + offset, during the hold and after the release."""

  HOLD_S = sc.LongEngageGate.DROP_S + 1.0

  def _gas_hold_then_release(self, ctl, sm, v_set, limit_mph, v_from_mph, v_to_mph):
    n = int(self.HOLD_S / DT)
    during = [run(ctl, sm, v_set, (v_from_mph + (v_to_mph - v_from_mph) * i / n) * MPH, limit=limit_mph * MPH,
                  gas=True, long_active=False) for i in range(n)]
    after = [run(ctl, sm, v_set, v_to_mph * MPH, limit=limit_mph * MPH) for _ in range(int(2.0 / DT))]
    return during, after

  def test_pull_tip_down_to_20_lower_limit_gas_held_stays_at_20(self):
    ctl, sm = make(toggles(SLCOverride="2")), Sm()
    v_set = 40 * MPH   # car-layer set after the pull: 35 + 5, held until disengage
    run(ctl, sm, 0.0, 25 * MPH, limit=35 * MPH, rwd=True, cruise=False)
    run(ctl, sm, 0.0, 25 * MPH, limit=35 * MPH, cruise=False)
    self.assertAlmostEqual(run(ctl, sm, v_set, 25 * MPH, limit=35 * MPH), 40 * MPH, places=4)
    for _ in range(4):   # deep down tips: 40 -> 35 -> 30 -> 25 -> 20
      run(ctl, sm, v_set, 25 * MPH, limit=35 * MPH, dn=True, spd=8)
      run(ctl, sm, v_set, 25 * MPH, limit=35 * MPH)
    self.assertAlmostEqual(run(ctl, sm, v_set, 22 * MPH, limit=35 * MPH), 20 * MPH, places=3)
    out = [run(ctl, sm, v_set, 22 * MPH, limit=25 * MPH) for _ in range(int(3.0 / DT))]
    self.assertAlmostEqual(out[-1], 20 * MPH, places=3)
    during, after = self._gas_hold_then_release(ctl, sm, v_set, 25, 22, 28)
    self.assertTrue(all(abs(x - 20 * MPH) < 1e-3 for x in during), f"during: max {max(during) / MPH:.2f} mph")
    self.assertTrue(all(abs(x - 20 * MPH) < 1e-3 for x in after), f"after: max {max(after) / MPH:.2f} mph")

  def test_pull_no_tip_lower_limit_gas_held_stays_at_current_limit_plus_offset(self):
    ctl, sm = make(toggles(SLCOverride="2")), Sm()
    v_set = 50 * MPH   # car-layer set after the pull: 45 + 5
    run(ctl, sm, 0.0, 45 * MPH, limit=45 * MPH, rwd=True, cruise=False)
    run(ctl, sm, 0.0, 45 * MPH, limit=45 * MPH, cruise=False)
    self.assertAlmostEqual(run(ctl, sm, v_set, 45 * MPH, limit=45 * MPH), 50 * MPH, places=4)
    out = [run(ctl, sm, v_set, 40 * MPH, limit=35 * MPH) for _ in range(int(3.0 / DT))]
    self.assertAlmostEqual(out[-1], 40 * MPH, places=4)
    during, after = self._gas_hold_then_release(ctl, sm, v_set, 35, 40, 45)
    self.assertTrue(all(abs(x - 40 * MPH) < 1e-3 for x in during), f"during: max {max(during) / MPH:.2f} mph")
    self.assertTrue(all(abs(x - 40 * MPH) < 1e-3 for x in after), f"after: max {max(after) / MPH:.2f} mph")

  def test_gas_held_engage_before_longitudinal_keeps_the_pass_through(self):
    """Longitudinal never ours yet in this cruise session (gas-held engage): unchanged, carState.vCruise floored at vEgo."""
    ctl, sm = make(toggles(SLCOverride="2")), Sm()
    run(ctl, sm, 0.0, 20.0, limit=45 * MPH, rwd=True, cruise=False)
    outs = [run(ctl, sm, 10.0, 20.0, limit=45 * MPH, gas=True, long_active=False) for _ in range(int(self.HOLD_S / DT))]
    self.assertTrue(all(abs(x - 20.0) < 1e-6 for x in outs), outs[:3])

  # Release with a lagging longActive: the gas is up but carControl.longActive is still False for a few planner ticks
  # (it comes from controlsd's previous step). Those ticks are still lateral only and publish the same set.
  def _tip_to_20(self, ctl, sm):
    v_set = 40 * MPH   # car-layer set after the pull: 35 + 5
    run(ctl, sm, 0.0, 25 * MPH, limit=35 * MPH, rwd=True, cruise=False)
    run(ctl, sm, 0.0, 25 * MPH, limit=35 * MPH, cruise=False)
    run(ctl, sm, v_set, 25 * MPH, limit=35 * MPH)
    for _ in range(4):   # deep down tips: 40 -> 35 -> 30 -> 25 -> 20
      run(ctl, sm, v_set, 25 * MPH, limit=35 * MPH, dn=True, spd=8)
      run(ctl, sm, v_set, 25 * MPH, limit=35 * MPH)
    run(ctl, sm, v_set, 22 * MPH, limit=25 * MPH, n=int(3.0 / DT))
    return v_set, 25, 20 * MPH

  def _no_tip(self, ctl, sm):
    v_set = 50 * MPH   # car-layer set after the pull: 45 + 5
    run(ctl, sm, 0.0, 45 * MPH, limit=45 * MPH, rwd=True, cruise=False)
    run(ctl, sm, 0.0, 45 * MPH, limit=45 * MPH, cruise=False)
    run(ctl, sm, v_set, 45 * MPH, limit=45 * MPH)
    run(ctl, sm, v_set, 40 * MPH, limit=35 * MPH, n=int(3.0 / DT))
    return v_set, 35, 40 * MPH

  def _release_with_long_active_lag(self, setup, lag_ticks):
    ctl, sm = make(toggles(SLCOverride="2")), Sm()
    v_set, limit_mph, want = setup(ctl, sm)
    hold = [run(ctl, sm, v_set, 30 * MPH, limit=limit_mph * MPH, gas=True, long_active=False) for _ in range(int(self.HOLD_S / DT))]
    lag = [run(ctl, sm, v_set, 30 * MPH, limit=limit_mph * MPH, long_active=False) for _ in range(lag_ticks)]
    after = [run(ctl, sm, v_set, 30 * MPH, limit=limit_mph * MPH) for _ in range(int(1.0 / DT))]
    for name, outs in (("hold", hold), ("release lag", lag), ("after", after)):
      bad = [round(x / MPH, 2) for x in outs if abs(x - want) > 1e-3]
      self.assertFalse(bad, f"{name}: expected {want / MPH:.0f} mph, got {bad[:5]}")

  def test_release_long_active_lag_1_tick_after_tip(self):
    self._release_with_long_active_lag(self._tip_to_20, 1)

  def test_release_long_active_lag_2_ticks_after_tip(self):
    self._release_with_long_active_lag(self._tip_to_20, 2)

  def test_release_long_active_lag_5_ticks_after_tip(self):
    self._release_with_long_active_lag(self._tip_to_20, 5)

  def test_release_long_active_lag_1_tick_no_tip(self):
    self._release_with_long_active_lag(self._no_tip, 1)

  def test_release_long_active_lag_2_ticks_no_tip(self):
    self._release_with_long_active_lag(self._no_tip, 2)

  def test_release_long_active_lag_5_ticks_no_tip(self):
    self._release_with_long_active_lag(self._no_tip, 5)

  def test_reengage_with_gas_held_after_disengage_keeps_the_pass_through(self):
    """openpilot disengaged with cruise still on, then re-engaged with the gas held: that is an engage again, so the
    pass-through (carState.vCruise floored at vEgo) applies, as before longitudinal was ever ours."""
    ctl, sm = make(toggles(SLCOverride="2")), Sm()
    v_set, limit_mph, _ = self._no_tip(ctl, sm)
    run(ctl, sm, v_set, 40 * MPH, limit=limit_mph * MPH, enabled=False, long_active=False, n=int(self.HOLD_S / DT))
    outs = [run(ctl, sm, v_set, 55 * MPH, limit=limit_mph * MPH, gas=True, long_active=False) for _ in range(int(self.HOLD_S / DT))]
    self.assertTrue(all(abs(x - 55 * MPH) < 1e-3 for x in outs), [round(x / MPH, 2) for x in outs[:3]])

  def test_lateral_only_without_gas_after_long_keeps_the_pass_through(self):
    """longActive drops with no gas press (double-pull re-pull demote): the set is not ours, carState.vCruise passes through."""
    ctl, sm = make(toggles(SLCOverride="2")), Sm()
    v_set, limit_mph, _ = self._no_tip(ctl, sm)
    outs = [run(ctl, sm, v_set, 40 * MPH, limit=limit_mph * MPH, long_active=False) for _ in range(int(self.HOLD_S / DT))]
    self.assertAlmostEqual(outs[-1], v_set, places=4)

