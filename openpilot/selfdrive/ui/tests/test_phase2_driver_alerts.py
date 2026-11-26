"""Driver-feedback alerts: detector rules, runtime adapter, real Alert/AlertManager/soundd dispatch.

Real current Alert/AlertManager source and capnp enums are executed (no mock alert classes), through the same
AST loader the Green Light tests use. Not a process, socket, audio-device or raylib-render test.
"""
from dataclasses import replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace, MethodType
import math
import sys
import time
import unittest

MODULE_PATH = Path(__file__).parents[1] / "bogpilot" / "phase2_driver_alerts.py"
spec = importlib.util.spec_from_file_location("phase2_driver_alerts", MODULE_PATH)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

import openpilot.selfdrive.ui.tests.test_phase2_alerts as green_tests  # module only: its TestCase is not re-collected here

ROOT = MODULE_PATH.parents[3]


def inp(t=0., **kw):
  return replace(m.DriverInput(t, warning_ok=True), **kw)


class FakeStore:
  def __init__(self, values=None):
    self.values = values or {}

  def get_bool(self, key, default=False):
    return self.values.get(key, default)


class FakeCS(SimpleNamespace):
  pass


def cs(follow=0., traffic=False, can_valid=True):
  return FakeCS(canValid=can_valid, bogpilot=SimpleNamespace(ap1StalkFollowS=follow, trafficModeEnabled=traffic))


class FakePlanSM:
  """Stand-in for the one-service SubMaster: only what the runtime reads."""
  def __init__(self):
    self.updated = {"bogpilotPlan": False}
    self.alive = {"bogpilotPlan": True}
    self.valid = {"bogpilotPlan": True}
    self.recv_time = {"bogpilotPlan": 0.}
    self.plan = SimpleNamespace(forcingStop=False, forcingStopLength=0., speedLimitChanged=False)

  def update(self, timeout=0):
    pass

  def __getitem__(self, key):
    return self.plan

  def publish(self, t, **kw):
    for k, v in kw.items():
      setattr(self.plan, k, v)
    self.recv_time["bogpilotPlan"] = t
    self.updated["bogpilotPlan"] = True

  def idle(self):
    self.updated["bogpilotPlan"] = False


class TestDetectors(unittest.TestCase):
  def run_frames(self, d, frames):
    out = []
    for f in frames:
      out.append(d.update(f))
    return out

  # ---- force stop --------------------------------------------------------------------------------------------
  def test_force_stop_is_a_level_with_length_and_needs_engaged_fresh_plan(self):
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(0., plan_valid=True, forcing_stop=True, forcing_length=12.5)), (("ForcingStop", 12.5),))
    self.assertEqual(d.update(inp(.01, plan_valid=True, forcing_stop=False, forcing_length=12.5)), ())
    self.assertEqual(d.update(inp(.02, plan_valid=False, forcing_stop=True, forcing_length=12.5)), ())
    self.assertEqual(d.update(inp(.03, plan_valid=True, forcing_stop=True, forcing_length=12.5, warning_ok=False)), ())
    for bad in (math.nan, math.inf, -1.):
      self.assertEqual(d.update(inp(.04, plan_valid=True, forcing_stop=True, forcing_length=bad)), ())

  # ---- follow distance --------------------------------------------------------------------------------------
  def test_follow_distance_change_holds_one_second_and_ignores_first_ready_sample(self):
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(0., follow_s=1.45, live_follow_s=1.45)), ())      # first ready detent
    self.assertEqual(d.update(inp(.01, follow_s=1.45, live_follow_s=1.45)), ())
    self.assertEqual(d.update(inp(.02, follow_s=1.75, live_follow_s=1.9)), (("AP1FollowDistance", 1.9),))
    self.assertEqual(d.update(inp(.5, follow_s=1.75, live_follow_s=1.9)), (("AP1FollowDistance", 1.9),))
    self.assertEqual(d.update(inp(1.03, follow_s=1.75, live_follow_s=1.9)), ())     # window over
    self.assertEqual(d.update(inp(1.04, follow_s=1.75, live_follow_s=1.9)), ())     # no replay

  def test_follow_distance_not_ready_or_lost_never_alerts_and_resume_is_a_change_only_if_different(self):
    d = m.DriverAlerts()
    for t in (0., .01):
      self.assertEqual(d.update(inp(t, follow_s=0.)), ())
    d.update(inp(.02, follow_s=1.25, live_follow_s=1.25))
    self.assertEqual(d.update(inp(.03, follow_s=0.)), ())       # lost detent: hold previous, no alert
    self.assertEqual(d.update(inp(.04, follow_s=1.25, live_follow_s=1.25)), ())
    self.assertEqual(d.update(inp(.05, follow_s=math.nan)), ())
    self.assertEqual(d.update(inp(.06, follow_s=1.25, live_follow_s=1.25, can_valid=False)), ())

  def test_follow_distance_changes_while_can_invalid_are_not_taken(self):
    d = m.DriverAlerts()
    d.update(inp(0., follow_s=1.25, live_follow_s=1.25))
    self.assertEqual(d.update(inp(.01, follow_s=1.75, can_valid=False)), ())
    # the change is seen once CAN is valid again (the held state was still 1.25)
    self.assertEqual(d.update(inp(.02, follow_s=1.75, live_follow_s=1.75)), (("AP1FollowDistance", 1.75),))
    self.assertEqual(d.prev_follow, 1.75)

  # ---- traffic mode -----------------------------------------------------------------------------------------
  def test_traffic_mode_edges_engaged_or_not_and_first_sample_is_silent(self):
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(0., traffic_mode=True)), ())                       # started already ON
    self.assertEqual(d.update(inp(.01, traffic_mode=True)), ())
    self.assertEqual(d.update(inp(.02, traffic_mode=False)), (("TrafficModeOff", None),))
    self.assertEqual(d.update(inp(.03, traffic_mode=False)), ())
    self.assertEqual(d.update(inp(.04, traffic_mode=True)), (("TrafficModeOn", None),))
    self.assertEqual(d.update(inp(.05, traffic_mode=True)), ())
    # a flip while not engaged alerts too (the alert type is PERMANENT, so it shows engaged or not), once
    self.assertEqual(d.update(inp(.06, traffic_mode=False, warning_ok=False)), (("TrafficModeOff", None),))
    self.assertEqual(d.update(inp(.07, traffic_mode=False, warning_ok=False)), ())
    self.assertEqual(d.update(inp(.075, traffic_mode=True, warning_ok=False)), (("TrafficModeOn", None),))
    self.assertEqual(d.update(inp(.076, traffic_mode=True)), ())
    # the CAN-valid guard stays: a flip while CAN is invalid records nothing and never alerts
    self.assertEqual(d.update(inp(.08, traffic_mode=False, can_valid=False)), ())

  # ---- speed limit changed ----------------------------------------------------------------------------------
  def test_speed_limit_changed_is_one_alert_per_rising_edge_and_respects_the_toggle(self):
    d = m.DriverAlerts()
    base = dict(plan_valid=True, plan_updated=True, slc_alert=True)
    self.assertEqual(d.update(inp(0., slc_changed=False, **base)), ())
    self.assertEqual(d.update(inp(.05, slc_changed=True, **base)), (("SpeedLimitChanged", None),))
    self.assertEqual(d.update(inp(.10, slc_changed=True, **base)), ())
    self.assertEqual(d.update(inp(.15, slc_changed=False, **base)), ())
    self.assertEqual(d.update(inp(.20, slc_changed=True, **base)), (("SpeedLimitChanged", None),))
    # between plan messages (plan_updated False) nothing is re-evaluated
    self.assertEqual(d.update(inp(.201, slc_changed=True, plan_valid=True, plan_updated=False, slc_alert=True)), ())

  def test_speed_limit_changed_saved_off_stale_plan_and_pending_at_start(self):
    d = m.DriverAlerts()
    off = dict(plan_valid=True, plan_updated=True, slc_alert=False)
    self.assertEqual(d.update(inp(0., slc_changed=False, **off)), ())
    self.assertEqual(d.update(inp(.05, slc_changed=True, **off)), ())
    # turning the toggle on while the change is still pending is not an edge
    self.assertEqual(d.update(inp(.10, slc_changed=True, plan_valid=True, plan_updated=True, slc_alert=True)), ())
    # a stale plan clears the memory: the next valid True is an edge only after a valid False
    self.assertEqual(d.update(inp(.20, slc_changed=True, plan_valid=False, plan_updated=False, slc_alert=True)), ())
    self.assertEqual(d.update(inp(.25, slc_changed=True, plan_valid=True, plan_updated=True, slc_alert=True)),
                     (("SpeedLimitChanged", None),))

  # ---- loud blind spot --------------------------------------------------------------------------------------
  def test_loud_blindspot_needs_toggle_block_and_engagement(self):
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(0., blindspot_blocked=True, loud_blindspot=True)), (("LoudBlindspot", None),))
    self.assertEqual(d.update(inp(.01, blindspot_blocked=True, loud_blindspot=False)), ())
    self.assertEqual(d.update(inp(.02, blindspot_blocked=False, loud_blindspot=True)), ())
    self.assertEqual(d.update(inp(.03, blindspot_blocked=True, loud_blindspot=True, warning_ok=False)), ())

  def test_non_finite_time_resets_and_returns_nothing(self):
    d = m.DriverAlerts()
    d.update(inp(0., traffic_mode=True))
    self.assertEqual(d.update(inp(math.nan, traffic_mode=False)), ())
    self.assertIsNone(d.prev_traffic)


class TestToggles(unittest.TestCase):
  def test_defaults_are_on_and_saved_choice_wins(self):
    self.assertEqual(m.DRIVER_ALERT_KEYS, ("LoudBlindspotAlert", "SpeedLimitChangedAlert"))
    for key in m.DRIVER_ALERT_KEYS:
      self.assertTrue(m.read_enabled(FakeStore(), key))                    # fresh install
      self.assertTrue(m.read_enabled(FakeStore({key: True}), key))
      self.assertFalse(m.read_enabled(FakeStore({key: False}), key))       # saved OFF survives

  def test_store_failure_reads_off(self):
    class Boom:
      def get_bool(self, *a, **k):
        raise OSError("gone")
    for key in m.DRIVER_ALERT_KEYS:
      self.assertFalse(m.read_enabled(Boom(), key))

  def test_shipping_defaults_match_everywhere_and_are_never_profile_written(self):
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    from openpilot.common.bogpilot_ap1_profile import AP1_PARAM_PROFILE, NEVER_PROFILE_KEYS
    from openpilot.selfdrive.ui.bogpilot.bogpilot_defaults import DEFAULT_ROWS
    header = (ROOT / "common/params_keys_bogpilot.h").read_text()
    rows = {r[0]: r for r in DEFAULT_ROWS}
    for key in m.DRIVER_ALERT_KEYS:
      self.assertEqual(BOGPILOT_PARAMS[key][2], "1")
      self.assertEqual(rows[key][1], "1")
      self.assertIn('{"%s", {PERSISTENT, BOOL, "1"}}' % key, header)
      self.assertIn(key, NEVER_PROFILE_KEYS)
      self.assertNotIn(key, AP1_PARAM_PROFILE)

  def test_saved_off_survives_profile_apply_rules(self):
    """Same contract as Green Light: a key in NEVER_PROFILE_KEYS is never written, so a saved OFF stays OFF."""
    from openpilot.common.bogpilot_ap1_profile import NEVER_PROFILE_KEYS
    saved = {k: "0" for k in m.DRIVER_ALERT_KEYS}
    hostile = {k: "1" for k in m.DRIVER_ALERT_KEYS}
    for key, value in hostile.items():
      if key not in NEVER_PROFILE_KEYS:
        saved[key] = value
    self.assertEqual(saved, {k: "0" for k in m.DRIVER_ALERT_KEYS})
    for key in m.DRIVER_ALERT_KEYS:
      self.assertFalse(m.read_enabled(FakeStore({key: False}), key))

  def test_no_toggle_exists_for_the_always_on_alerts(self):
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    # 0.9.7 had no switch for these; none is invented.
    for key in ("ForceStopAlert", "FollowDistanceAlert", "TrafficModeAlert",
                "TurningAlert", "NoLaneAvailableAlert", "OpenpilotCrashedAlert", "StartupAlert"):
      self.assertNotIn(key, BOGPILOT_PARAMS)


class TestRuntime(unittest.TestCase):
  def runtime(self, values=None):
    sm = FakePlanSM()
    rt = m.DriverAlertRuntime(None, FakeStore(values), sm)
    return rt, sm

  def test_force_stop_from_plan_and_stale_plan_silences(self):
    rt, sm = self.runtime()
    sm.publish(1.0, forcingStop=True, forcingStopLength=30.)
    self.assertEqual(rt.update(cs(), 1.0, True), (("ForcingStop", 30.),))
    sm.idle()
    self.assertEqual(rt.update(cs(), 1.4, True), (("ForcingStop", 30.),))
    self.assertEqual(rt.update(cs(), 1.6, True), ())                  # older than 0.5 s
    sm.alive["bogpilotPlan"] = False
    sm.publish(2.0, forcingStop=True, forcingStopLength=30.)
    self.assertEqual(rt.update(cs(), 2.0, True), ())
    sm.alive["bogpilotPlan"] = True
    sm.valid["bogpilotPlan"] = False
    self.assertEqual(rt.update(cs(), 2.0, True), ())

  def test_speed_limit_changed_runtime_edge_with_saved_toggle(self):
    rt, sm = self.runtime()                                            # fresh install: default ON
    sm.publish(1.0, speedLimitChanged=False)
    self.assertEqual(rt.update(cs(), 1.0, True), ())
    sm.publish(1.05, speedLimitChanged=True)
    self.assertEqual(rt.update(cs(), 1.05, True), (("SpeedLimitChanged", None),))
    rt2, sm2 = self.runtime({"SpeedLimitChangedAlert": False})         # saved OFF
    sm2.publish(1.0, speedLimitChanged=False)
    rt2.update(cs(), 1.0, True)
    sm2.publish(1.05, speedLimitChanged=True)
    self.assertEqual(rt2.update(cs(), 1.05, True), ())

  def test_follow_distance_and_traffic_from_car_state(self):
    rt, sm = self.runtime()
    sm.publish(0.0)
    sm.idle()
    self.assertEqual(rt.update(cs(follow=1.45, traffic=False), 0.0, True), ())
    out = rt.update(cs(follow=1.0, traffic=True), 0.01, True)
    self.assertIn(("TrafficModeOn", None), out)
    self.assertTrue(any(n == "AP1FollowDistance" and abs(a - 1.0) < 1e-6 for n, a in out), out)

  def test_missing_car_state_fields_are_harmless(self):
    rt, sm = self.runtime()
    self.assertEqual(rt.update(FakeCS(canValid=True), 1.0, True), ())
    self.assertEqual(rt.update(FakeCS(canValid=True, bogpilot=None), 1.0, True), ())

  def test_loud_blindspot_follows_saved_choice(self):
    rt, _ = self.runtime()                                             # fresh install: default ON
    self.assertTrue(rt.loud_blindspot_enabled())
    self.assertEqual(rt.update(cs(), 1.0, True, blindspot_blocked=True), (("LoudBlindspot", None),))
    rt, _ = self.runtime({"LoudBlindspotAlert": False})                # saved OFF
    self.assertFalse(rt.loud_blindspot_enabled())
    self.assertEqual(rt.update(cs(), 1.0, True, blindspot_blocked=True), ())

  def test_live_follow_seconds_use_the_planner_profile_values(self):
    rt, _ = self.runtime()
    seen = {}

    class Toggles:
      aggressive_follow, standard_follow, relaxed_follow = 1.1, 1.3, 2.0
    import openpilot.selfdrive.controls.lib.phase3_following as pf
    real = pf.FollowingToggles.read
    pf.FollowingToggles.read = classmethod(lambda cls, store, CP: Toggles())
    try:
      seen["relaxed"] = rt._live_follow(1.75, 0.)
      seen["traffic"] = rt._live_follow(1.0, 5.)
    finally:
      pf.FollowingToggles.read = real
    self.assertAlmostEqual(seen["relaxed"], 2.0)
    self.assertAlmostEqual(seen["traffic"], 1.0)
    self.assertEqual(rt._live_follow(0., 9.), 0.)


class TestRealAlertPath(unittest.TestCase):
  """Producer -> dispatch -> real AlertManager -> real soundd selection, with the current source classes."""

  def setUp(self):
    self.ns, self.sndns, self.log, self.car = green_tests.TestPhase2Alerts._load_alert_and_sound_namespaces(None)
    self.api = SimpleNamespace(**self.ns)
    self.AudibleAlert = self.log.SelfdriveState.AudibleAlert

  def sound_for(self, alert):
    sound = SimpleNamespace(current_alert=self.AudibleAlert.none, current_sound=self.AudibleAlert.none,
                            current_sound_frame=0, loaded_sounds={}, pending_stop=False, current_volume=.5)
    self.sndns.setdefault("time", time)           # warningSoft starts a volume ramp from time.monotonic()
    sound.update_alert = MethodType(self.sndns["update_alert"], sound)
    ss = self.log.SelfdriveState.new_message()
    ss.alertSound = alert.audible_alert

    class SoundSM(dict):
      updated = {"selfdriveState": True}
    self.sndns["get_audible_alert"](sound, SoundSM(selfdriveState=ss))
    return self.sndns["sound_list"][sound.current_sound][:2]

  def dispatch(self, rt, am, frame, now, warning_ok=True, metric=False, blocked=False, car_state=None):
    ok = m.dispatch_driver_alerts(rt, am, frame, car_state or cs(), now, warning_ok, metric, blocked, event_api=self.api)
    self.assertTrue(ok)
    clear = set() if warning_ok else {self.ns["ET"].WARNING}
    am.process_alerts(frame, clear)

  def test_force_stop_reaches_ui_fields_in_feet_and_meters_and_plays_prompt(self):
    for metric, text in ((False, "Forcing the car to stop in 98.4 feet"), (True, "Forcing the car to stop in 30.0 meters")):
      sm = FakePlanSM()
      rt = m.DriverAlertRuntime(None, FakeStore(), sm)
      am = self.ns["AlertManager"]()
      sm.publish(1.0, forcingStop=True, forcingStopLength=30.)
      self.dispatch(rt, am, 100, 1.0, metric=metric)
      a = am.current_alert
      self.assertEqual(a.alert_text_1, text)
      self.assertEqual(a.alert_text_2, "Press the gas pedal or 'Resume' button to override")
      self.assertEqual(a.alert_size, self.ns["AlertSize"].mid)
      self.assertEqual(a.priority, self.ns["Priority"].MID)
      self.assertEqual(a.audible_alert, self.AudibleAlert.prompt)
      self.assertEqual(a.alert_type, "bogpilotForcingStop/warning")
      self.assertEqual(self.sound_for(a), ("warning.wav", 1))

  def test_force_stop_alert_ends_when_openpilot_stops_being_engaged(self):
    sm = FakePlanSM()
    rt = m.DriverAlertRuntime(None, FakeStore(), sm)
    am = self.ns["AlertManager"]()
    sm.publish(1.0, forcingStop=True, forcingStopLength=30.)
    self.dispatch(rt, am, 100, 1.0)
    self.assertEqual(am.current_alert.alert_type, "bogpilotForcingStop/warning")
    sm.publish(1.01, forcingStop=True, forcingStopLength=29.)
    self.dispatch(rt, am, 101, 1.01, warning_ok=False)                 # disengaged: WARNING entries are cleared
    self.assertEqual(am.current_alert.alert_text_1, "")

  def test_force_stop_outranks_stock_low_alerts_but_not_high_ones(self):
    am = self.ns["AlertManager"]()
    low = self.ns["Alert"]("Steer Left", "", self.ns["AlertStatus"].normal, self.ns["AlertSize"].small,
                           self.ns["Priority"].LOW, self.ns["VisualAlert"].none, self.ns["AudibleAlert"].none, 3.)
    low.alert_type, low.event_type = "preLaneChangeLeft/warning", "warning"
    high = self.ns["Alert"]("TAKE CONTROL", "", self.ns["AlertStatus"].critical, self.ns["AlertSize"].full,
                            self.ns["Priority"].HIGH, self.ns["VisualAlert"].none, self.ns["AudibleAlert"].none, 3.)
    high.alert_type, high.event_type = "fcw/warning", "warning"
    sm = FakePlanSM()
    rt = m.DriverAlertRuntime(None, FakeStore(), sm)
    sm.publish(1.0, forcingStop=True, forcingStopLength=30.)
    am.add_many(100, [low])
    self.dispatch(rt, am, 100, 1.0)
    self.assertEqual(am.current_alert.alert_type, "bogpilotForcingStop/warning")
    am.add_many(101, [high])
    self.dispatch(rt, am, 101, 1.01)
    self.assertEqual(am.current_alert.alert_type, "fcw/warning")

  def test_follow_distance_text_label_and_silence(self):
    sm = FakePlanSM()
    rt = m.DriverAlertRuntime(None, FakeStore(), sm)
    am = self.ns["AlertManager"]()
    self.dispatch(rt, am, 100, 1.0, car_state=cs(follow=1.45))
    self.assertEqual(am.current_alert.alert_text_1, "")
    self.dispatch(rt, am, 101, 1.01, car_state=cs(follow=1.0, traffic=False))
    self.assertEqual(am.current_alert.alert_text_1, "Follow distance: 1.00 s (traffic)")
    self.assertEqual(am.current_alert.audible_alert, self.AudibleAlert.none)
    self.assertEqual(am.current_alert.alert_type, "bogpilotAP1FollowDistance/permanent")
    self.dispatch(rt, am, 102, 1.02, car_state=cs(follow=1.75))
    self.assertEqual(am.current_alert.alert_text_1, "Follow distance: 1.75 s")
    for i in range(103, 210):                                          # ~1 s later it is gone
      self.dispatch(rt, am, i, i * .01, car_state=cs(follow=1.75))
    self.assertEqual(am.current_alert.alert_text_1, "")

  def test_traffic_mode_alerts_plain_text_prompt_sound_three_seconds(self):
    sm = FakePlanSM()
    rt = m.DriverAlertRuntime(None, FakeStore(), sm)
    am = self.ns["AlertManager"]()
    self.dispatch(rt, am, 100, 1.0, car_state=cs(traffic=False))
    self.dispatch(rt, am, 101, 1.01, car_state=cs(traffic=True))
    a = am.current_alert
    self.assertEqual((a.alert_text_1, a.audible_alert), ("Traffic Mode enabled", self.AudibleAlert.prompt))
    self.assertEqual(self.sound_for(a), ("warning.wav", 1))
    self.assertEqual(a.duration, 300)
    self.dispatch(rt, am, 102, 1.02, car_state=cs(traffic=False))
    self.assertEqual(am.current_alert.alert_text_1, "Traffic Mode Disabled")
    for alert in (am.current_alert,):
      self.assertTrue(alert.alert_text_1.isascii())

  def test_speed_limit_changed_alert_on_by_default_and_saved_off_wins(self):
    for saved, expect in ((None, "Speed limit changed"), (False, "")):
      sm = FakePlanSM()
      rt = m.DriverAlertRuntime(None, FakeStore({"SpeedLimitChangedAlert": saved} if saved is not None else {}), sm)
      am = self.ns["AlertManager"]()
      sm.publish(1.0, speedLimitChanged=False)
      self.dispatch(rt, am, 100, 1.0)
      sm.publish(1.05, speedLimitChanged=True)
      self.dispatch(rt, am, 105, 1.05)
      self.assertEqual(am.current_alert.alert_text_1, expect)
      if expect:
        self.assertEqual(am.current_alert.audible_alert, self.AudibleAlert.prompt)
        self.assertEqual(self.sound_for(am.current_alert), ("warning.wav", 1))

  def test_loud_blindspot_uses_warning_soft_loop_sound_and_ends_with_the_block(self):
    sm = FakePlanSM()
    rt = m.DriverAlertRuntime(None, FakeStore(), sm)                   # fresh install: ON
    am = self.ns["AlertManager"]()
    self.dispatch(rt, am, 100, 1.0, blocked=True)
    a = am.current_alert
    self.assertEqual((a.alert_text_1, a.audible_alert), ("Car Detected in Blindspot", self.AudibleAlert.warningSoft))
    self.assertEqual(a.alert_status, self.ns["AlertStatus"].userPrompt)
    self.assertEqual(self.sound_for(a), ("critical.wav", None))
    for i in range(101, 120):
      self.dispatch(rt, am, i, i * .01, blocked=False)
    self.assertEqual(am.current_alert.alert_text_1, "")

  def test_failure_isolation_removes_only_owned_entries(self):
    am = self.ns["AlertManager"]()
    stock = self.ns["Alert"]("Pay attention", "", self.ns["AlertStatus"].normal, self.ns["AlertSize"].small,
                             self.ns["Priority"].LOW, self.ns["VisualAlert"].none, self.ns["AudibleAlert"].preAlert, 3.)
    stock.alert_type, stock.event_type = "driverDistracted1/permanent", "permanent"
    am.add_many(0, [stock])
    am.process_alerts(0, set())

    class Boom:
      def update(self, *a, **k):
        raise RuntimeError("boom")
    self.assertFalse(m.dispatch_driver_alerts(Boom(), am, 1, cs(), 1.0, True, False, event_api=self.api))
    self.assertIn("driverDistracted1/permanent", am.alerts)
    self.assertIs(am.current_alert, stock)
    for t in m.OWNED_ALERT_TYPES:
      self.assertNotIn(t, am.alerts)

  def test_every_alert_type_is_owned_ascii_and_uses_existing_sounds(self):
    seen = []
    for name, arg in (("ForcingStop", 10.), ("AP1FollowDistance", 1.45), ("TrafficModeOn", None), ("TrafficModeOff", None),
                      ("SpeedLimitChanged", None), ("LoudBlindspot", None),
                      ("TurningLeft", None), ("TurningRight", None), ("NoLaneAvailable", 2.0),
                      ("OpenpilotCrashed", None), ("CustomStartup", (m.STARTUP_MESSAGE_TOP, m.STARTUP_MESSAGE_BOTTOM))):
      a = m.make_alert(name, arg, False, self.api)
      seen.append(a.alert_type)
      text = a.alert_text_1 + a.alert_text_2
      if name == "CustomStartup":
        self.assertEqual(a.alert_text_1, m.STARTUP_MESSAGE_TOP)
        self.assertTrue(text.replace("\u221e", "").isascii(), name)
      else:
        self.assertTrue(text.isascii(), name)
      self.assertNotIn("<", a.alert_text_1)
      if int(a.audible_alert):
        self.assertIn(a.audible_alert, self.sndns["sound_list"])
    self.assertEqual(tuple(seen), m.OWNED_ALERT_TYPES)
    with self.assertRaises(ValueError):
      m.make_alert("Nope", None, False, self.api)

  def test_traffic_mode_alerts_are_permanent_not_warning(self):
    for name in ("TrafficModeOn", "TrafficModeOff"):
      a = m.make_alert(name, None, False, self.api)
      self.assertEqual(a.event_type, self.api.ET.PERMANENT)
      self.assertEqual(a.alert_type, f"bogpilot{name}/permanent")
      self.assertIn(a.alert_type, m.OWNED_ALERT_TYPES)
    for t in ("bogpilotTrafficModeOn/warning", "bogpilotTrafficModeOff/warning"):
      self.assertNotIn(t, m.OWNED_ALERT_TYPES)


class TestSelfdrivedWiring(unittest.TestCase):
  """selfdrived imports msgq, so the wiring is checked from its real source."""

  @classmethod
  def setUpClass(cls):
    cls.src = (ROOT / "selfdrive/selfdrived/selfdrived.py").read_text()

  def test_dispatch_after_stock_alerts_and_before_process(self):
    s = self.src
    stock_add = s.index("self.AM.add_many(self.sm.frame, alerts)")
    green = s.index("dispatch_optional_alerts(self.bogpilot_alerts")
    driver = s.index("dispatch_driver_alerts(self.bogpilot_driver_alerts")
    process = s.index("self.AM.process_alerts(self.sm.frame, clear_event_types)")
    self.assertTrue(stock_add < green < driver < process)
    self.assertIn("ET.WARNING in self.state_machine.current_alert_types", s)

  def test_loud_blindspot_replaces_the_stock_event_only_when_runtime_and_toggle_allow(self):
    s = self.src
    block = s[s.index("self.bogpilot_blindspot_blocked = True"):]
    block = block[:block.index("else:\n        # Narrower than LaneDetectionWidth")]
    self.assertIn("self.bogpilot_driver_alerts is None or not self.bogpilot_driver_alerts.loud_blindspot_enabled()", block)
    self.assertIn("self.events.add(EventName.laneChangeBlocked)", block)
    self.assertIn("self.bogpilot_blindspot_blocked = False", s)
    self.assertIn("self.bogpilot_no_lane = None", s)
    self.assertIn("if self.sm['modelV2'].meta.laneChangeState == LaneChangeState.preLaneChange:", s)

  def test_main_submaster_is_not_given_the_plan_service(self):
    # A missing planner must never raise commIssue: the plan comes from the adapter's own SubMaster.
    start = self.src.index("self.sm = messaging.SubMaster([")
    self.assertNotIn("bogpilotPlan", self.src[start:start + 900])

  def test_runtime_failure_falls_back_to_stock(self):
    self.assertIn("self.bogpilot_driver_alerts = None", self.src)

  def test_custom_startup_replaces_stock_startup_events_only(self):
    s = self.src
    hook = s[s.index("# Add startup event"):s.index("# Don't add any more events if not initialized")]
    self.assertIn("EventName.startup, EventName.startupMaster", hook)
    self.assertIn("self.bogpilot_startup_pending = True", hook)
    self.assertIn("self.events.add(self.startup_event)", hook)
    self.assertIn("clear_error_log()", self.src)
    self.assertIn("not_running=self.bogpilot_not_running", self.src)
    self.assertIn("no_lane=self.bogpilot_no_lane", self.src)
    self.assertIn("startup=startup", self.src)

  def test_no_lane_suppresses_stock_pre_lane_change(self):
    s = self.src
    self.assertIn("no_lane, width = self.bogpilot_driver_alerts.no_lane_available(CS, self.sm, direction)", s)
    self.assertIn("if not no_lane:", s)
    # stock events only inside the not-blocked path
    start = s.index("# Narrower than LaneDetectionWidth")
    block = s[start:s.index("elif self.sm['modelV2'].meta.laneChangeState")]
    self.assertIn("EventName.preLaneChangeLeft", block)
    self.assertLess(block.index("if not no_lane:"), block.index("EventName.preLaneChangeLeft"))


class TestNewDetectors(unittest.TestCase):
  def test_turning_requires_toggle_engagement_speed_and_one_blinker(self):
    d = m.DriverAlerts()
    base = dict(warning_ok=True, can_valid=True, turn_desires=True, left_blinker=True,
                v_ego=5., standstill=False, min_lane_change_speed=8.94)
    self.assertEqual(d.update(inp(1., **base)), (("TurningLeft", None),))
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(1., **{**base, "left_blinker": False, "right_blinker": True})), (("TurningRight", None),))
    for kw in (
      {"turn_desires": False},
      {"warning_ok": False},
      {"can_valid": False},
      {"standstill": True},
      {"v_ego": 0.},
      {"v_ego": 8.94},
      {"left_blinker": True, "right_blinker": True},
      {"left_blinker": False, "right_blinker": False},
    ):
      d = m.DriverAlerts()
      self.assertEqual(d.update(inp(1., **{**base, **kw})), ())

  def test_no_lane_requires_pre_change_and_a_positive_minimum_width(self):
    d = m.DriverAlerts()
    base = dict(warning_ok=True, pre_lane_change=True, min_lane_width=2.0, lane_width=1.0)
    self.assertEqual(d.update(inp(1., **base)), (("NoLaneAvailable", 1.0),))
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(1., **{**base, "lane_width": None}))[0][0], "NoLaneAvailable")
    for kw in (
      {"pre_lane_change": False},
      {"warning_ok": False},
      {"min_lane_width": 0.},
      {"lane_width": 2.0},
      {"blindspot_blocked": True, "loud_blindspot": False},
    ):
      d = m.DriverAlerts()
      names = tuple(n for n, _ in d.update(inp(1., **{**base, **kw})))
      self.assertNotIn("NoLaneAvailable", names)

  def test_turning_is_not_shown_when_no_lane_is_active(self):
    # Mutually exclusive in practice (below vs at/above LC speed), but the detector prefers no-lane.
    d = m.DriverAlerts()
    req = d.update(inp(1., warning_ok=True, can_valid=True, turn_desires=True, left_blinker=True,
                       v_ego=5., pre_lane_change=True, min_lane_width=2.0, lane_width=1.0))
    self.assertEqual(req, (("NoLaneAvailable", 1.0),))

  def test_crash_is_a_level_from_error_log_or_a_down_process(self):
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(1., error_log=True)), (("OpenpilotCrashed", None),))
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(1., core_process_down=True, warning_ok=False)), (("OpenpilotCrashed", None),))
    d = m.DriverAlerts()
    self.assertEqual(d.update(inp(1.)), ())

  def test_startup_resolves_old_defaults_and_keeps_custom_text(self):
    self.assertEqual(m.read_startup_messages(None, None), (m.STARTUP_MESSAGE_TOP, m.STARTUP_MESSAGE_BOTTOM))
    self.assertEqual(m.read_startup_messages("", "  "), (m.STARTUP_MESSAGE_TOP, m.STARTUP_MESSAGE_BOTTOM))
    self.assertEqual(m.read_startup_messages("Hop in and buckle up!", "Human-tested, frog-approved"),
                     (m.STARTUP_MESSAGE_TOP, m.STARTUP_MESSAGE_BOTTOM))
    self.assertEqual(m.read_startup_messages("Hop in and buckle up!", "Human-tested, frog-approved 🐸"),
                     (m.STARTUP_MESSAGE_TOP, m.STARTUP_MESSAGE_BOTTOM))
    self.assertEqual(m.read_startup_messages("Custom top", "Custom bottom"), ("Custom top", "Custom bottom"))
    d = m.DriverAlerts()
    req = d.update(inp(1., startup=True, startup_top="Hop in and buckle up!", startup_bottom="keep this"))
    self.assertEqual(req, (("CustomStartup", (m.STARTUP_MESSAGE_TOP, "keep this")),))


class TestNewAlertPath(unittest.TestCase):
  def setUp(self):
    self.ns, self.sndns, self.log, self.car = green_tests.TestPhase2Alerts._load_alert_and_sound_namespaces(None)
    self.api = SimpleNamespace(**self.ns)
    self.AudibleAlert = self.log.SelfdriveState.AudibleAlert

  def sound_for(self, alert):
    return TestRealAlertPath.sound_for(self, alert)

  def dispatch(self, rt, am, frame, now, warning_ok=True, metric=False, blocked=False, car_state=None,
               startup=False, no_lane=None, error_log=False, not_running=False):
    ok = m.dispatch_driver_alerts(rt, am, frame, car_state or cs(), now, warning_ok, metric, blocked,
                                  event_api=self.api, not_running=not_running, startup=startup,
                                  no_lane=no_lane, error_log=error_log)
    self.assertTrue(ok)
    clear = set() if warning_ok else {self.ns["ET"].WARNING}
    am.process_alerts(frame, clear)

  def test_turning_left_and_right_texts_are_silent_and_lowest(self):
    from types import SimpleNamespace as NS
    settings = NS(turn_desires=True, minimum_speed=8.94, minimum_width=0.)
    for left, text, typ in ((True, "Turning left", "bogpilotTurningLeft/warning"),
                            (False, "Turning right", "bogpilotTurningRight/warning")):
      sm = FakePlanSM()
      rt = m.DriverAlertRuntime(None, FakeStore(), sm)
      rt.injected_settings = settings
      am = self.ns["AlertManager"]()
      car = cs()
      car.leftBlinker, car.rightBlinker, car.vEgo, car.standstill = left, not left, 5., False
      self.dispatch(rt, am, 100, 1.0, car_state=car)
      a = am.current_alert
      self.assertEqual((a.alert_text_1, a.alert_text_2, a.audible_alert), (text, "", self.AudibleAlert.none))
      self.assertEqual(a.alert_size, self.ns["AlertSize"].small)
      self.assertEqual(a.priority, self.ns["Priority"].LOWEST)
      self.assertEqual(a.alert_type, typ)
      self.assertEqual(a.duration, 10)

  def test_no_lane_width_text_in_feet_and_meters_and_suppress_helper(self):
    from types import SimpleNamespace as NS
    settings = NS(turn_desires=False, minimum_speed=8.94, minimum_width=2.0)
    for metric, text in ((False, "Detected lane width is only 3.3 feet"),
                         (True, "Detected lane width is only 1.0 meters")):
      sm = FakePlanSM()
      rt = m.DriverAlertRuntime(None, FakeStore(), sm)
      rt.injected_settings = settings
      am = self.ns["AlertManager"]()
      self.dispatch(rt, am, 100, 1.0, metric=metric, no_lane=(True, 1.0, True))
      a = am.current_alert
      self.assertEqual(a.alert_text_1, "No lane available")
      self.assertEqual(a.alert_text_2, text)
      self.assertEqual(a.alert_size, self.ns["AlertSize"].mid)
      self.assertEqual(a.audible_alert, self.AudibleAlert.none)
      self.assertEqual(a.alert_type, "bogpilotNoLaneAvailable/warning")

  def test_crash_alert_outranks_and_uses_prompt(self):
    sm = FakePlanSM()
    rt = m.DriverAlertRuntime(None, FakeStore(), sm)
    am = self.ns["AlertManager"]()
    self.dispatch(rt, am, 100, 1.0, error_log=True)
    a = am.current_alert
    self.assertEqual(a.alert_text_1, "openpilot crashed")
    self.assertEqual(a.alert_text_2, "Post the 'Error Log' at github.com/BogPilot/openpilot/issues")
    self.assertEqual(a.alert_status, self.ns["AlertStatus"].critical)
    self.assertEqual(a.alert_size, self.ns["AlertSize"].mid)
    self.assertEqual(a.priority, self.ns["Priority"].HIGHEST)
    self.assertEqual(a.audible_alert, self.AudibleAlert.prompt)
    self.assertEqual(a.alert_type, "bogpilotOpenpilotCrashed/immediateDisable")
    self.assertEqual(self.sound_for(a), ("warning.wav", 1))
    # Still shown after WARNING types are cleared (not engaged): event type is immediateDisable.
    self.dispatch(rt, am, 101, 1.01, warning_ok=False, error_log=True)
    self.assertEqual(am.current_alert.alert_text_1, "openpilot crashed")

  def test_custom_startup_uses_saved_or_default_text_for_five_seconds(self):
    class Store(FakeStore):
      def get(self, key):
        return self.values.get(key)
    sm = FakePlanSM()
    rt = m.DriverAlertRuntime(None, Store(), sm)
    am = self.ns["AlertManager"]()
    self.dispatch(rt, am, 100, 1.0, warning_ok=False, startup=True)
    a = am.current_alert
    self.assertEqual(a.alert_text_1, m.STARTUP_MESSAGE_TOP)
    self.assertEqual(a.alert_text_2, m.STARTUP_MESSAGE_BOTTOM)
    self.assertEqual(a.alert_size, self.ns["AlertSize"].mid)
    self.assertEqual(a.priority, self.ns["Priority"].LOWER)
    self.assertEqual(a.audible_alert, self.AudibleAlert.none)
    self.assertEqual(a.duration, 500)
    self.assertEqual(a.alert_type, "bogpilotCustomStartup/permanent")
    custom = Store({"StartupMessageTop": "Hello there", "StartupMessageBottom": "Stay ready"})
    rt = m.DriverAlertRuntime(None, custom, sm)
    am = self.ns["AlertManager"]()
    self.dispatch(rt, am, 100, 1.0, warning_ok=False, startup=True)
    self.assertEqual((am.current_alert.alert_text_1, am.current_alert.alert_text_2), ("Hello there", "Stay ready"))



if __name__ == "__main__":
  unittest.main()
