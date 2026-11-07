"""t913u: speed-limit pill, steering arc, pedals and screen recorder contracts (headless; no window, no device).

The recorder tests run the REAL ffmpeg encoder on synthetic frames in a temporary directory (sandbox only) and check
the saved files with ffprobe. Nothing here captures a screen or reads private data."""
import datetime
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load

SL = load("speed_limit_display")
ARC = load("steering_arc")
PED = load("pedals")
L = load("cluster_layout")
SR = load("screen_recorder")
MPH = 2.23694
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


class FakeSM:
  def __init__(self, now, **msgs):
    self.data = dict(msgs)
    self.recv_time = {k: now for k in msgs}
    self.alive = {k: True for k in msgs}
    self.valid = {k: True for k in msgs}

  def __getitem__(self, k):
    return self.data[k]


def fpcs(limit):
  return SimpleNamespace(dashboardSpeedLimit=limit, brakeLights=False)


def plan(**kw):
  base = dict(valid=True, training=False, controlling=False, csc_speed=0.0, road_curvature=0.0, slc_overridden_speed=0.0,
              slc_speed_limit=0.0, slc_speed_limit_offset=0.0, speed_limit_changed=False)
  base.update(kw)
  return L.CscStatus(**base)


ON = SL.LimitPolicy(show_speed_limits=True, speed_limit_controller=True)


class TestDashboardLimitSource(unittest.TestCase):
  def test_fresh_valid_current_drive(self):
    sm = FakeSM(100.0, frogpilotCarState=fpcs(29.0576))
    self.assertAlmostEqual(SL.read_dashboard_limit(sm, 100.2, 50.0), 29.0576, places=4)

  def test_rejects_stale_invalid_dead_previous_drive_and_missing(self):
    sm = FakeSM(100.0, frogpilotCarState=fpcs(29.0))
    self.assertIsNone(SL.read_dashboard_limit(sm, 100.0 + SL.LIMIT_STALE_S + 0.01, 50.0))
    self.assertIsNone(SL.read_dashboard_limit(sm, 100.1, 100.5))          # message from before this drive started
    sm.valid["frogpilotCarState"] = False
    self.assertIsNone(SL.read_dashboard_limit(sm, 100.1, 50.0))
    sm.valid["frogpilotCarState"] = True
    sm.alive["frogpilotCarState"] = False
    self.assertIsNone(SL.read_dashboard_limit(sm, 100.1, 50.0))
    self.assertIsNone(SL.read_dashboard_limit(FakeSM(100.0), 100.1, 50.0))
    self.assertIsNone(SL.read_dashboard_limit(None, 100.1, 50.0))
    # SubMaster.update() stamps recv_time after `now` was sampled: a message newer than `now` is fresh, not rejected
    self.assertAlmostEqual(SL.read_dashboard_limit(FakeSM(100.0, frogpilotCarState=fpcs(29.0)), 99.99, 50.0), 29.0)

  def test_bogus_values(self):
    for v in (float("nan"), float("inf"), -1.0, SL.MAX_LIMIT_MS + 1):
      self.assertIsNone(SL.read_dashboard_limit(FakeSM(1.0, frogpilotCarState=fpcs(v)), 1.0, 0.0), v)
    self.assertEqual(SL.read_dashboard_limit(FakeSM(1.0, frogpilotCarState=fpcs(0.5)), 1.0, 0.0), 0.0)  # "no limit"


class TestSpeedLimitView(unittest.TestCase):
  def test_dashboard_limit_has_no_offset_badge(self):
    v = SL.speed_limit_view(ON, 65 / MPH, plan(), MPH)       # C3X today: CSC plan with slc fields 0
    self.assertEqual((v.show_limit, v.limit, v.offset, v.limit_opacity, v.source), (True, "65", "", 1.0, "dashboard"))
    self.assertAlmostEqual(v.color_limit, 65, places=3)
    v = SL.speed_limit_view(ON, 65 / MPH, L.INVALID_CSC, MPH)
    self.assertEqual((v.limit, v.offset, v.source), ("65", "", "dashboard"))

  def test_real_slc_plan_wins_with_badge(self):
    v = SL.speed_limit_view(ON, 60 / MPH, plan(slc_speed_limit=65 / MPH, slc_speed_limit_offset=5 / MPH), MPH)
    self.assertEqual((v.limit, v.offset, v.source), ("65", "+5", "slc"))
    self.assertAlmostEqual(v.color_limit, 70, places=3)                   # ShowSLCOffset off: offset in the comparison
    v = SL.speed_limit_view(SL.LimitPolicy(show_speed_limits=True, show_speed_limit_offset=True), 0,
                            plan(slc_speed_limit=65 / MPH, slc_speed_limit_offset=-5 / MPH), MPH)
    self.assertEqual(v.offset, "-5")
    self.assertAlmostEqual(v.color_limit, 65, places=3)

  def test_override_and_no_limit(self):
    v = SL.speed_limit_view(ON, 0, plan(slc_speed_limit=65 / MPH, slc_overridden_speed=72 / MPH, slc_speed_limit_offset=5 / MPH), MPH)
    self.assertEqual((v.limit, v.offset, v.limit_opacity), ("72", "", 0.25))
    v = SL.speed_limit_view(ON, None, L.INVALID_CSC, MPH)
    self.assertEqual((v.show_limit, v.limit, v.source, v.color_limit), (True, "–", "none", 0.0))

  def test_gating(self):
    self.assertFalse(SL.speed_limit_view(SL.LimitPolicy(), 30.0, plan(), MPH).show_limit)
    hide = SL.LimitPolicy(show_speed_limits=True, hide_speed_limit=True)
    self.assertFalse(SL.speed_limit_view(hide, 30.0, plan(), MPH).show_limit)
    self.assertTrue(SL.speed_limit_view(hide, 30.0, plan(speed_limit_changed=True), MPH).show_limit)
    self.assertTrue(SL.speed_limit_view(SL.LimitPolicy(speed_limit_controller=True, vienna=True), 30.0, plan(), 3.6).vienna)
    self.assertEqual(SL.speed_limit_view(ON, 100 / 3.6, plan(), 3.6).limit, "100")    # metric units

  def test_nonfinite_plan_fields_ignored(self):
    v = SL.speed_limit_view(ON, 50 / MPH, plan(slc_speed_limit_offset=float("nan")), MPH)
    self.assertEqual((v.limit, v.offset, v.source), ("50", "", "dashboard"))

  def test_set_speed_colour(self):
    self.assertEqual(SL.set_speed_rgba(False, True, 70, 65), SL.GREY)
    self.assertEqual(SL.set_speed_rgba(True, True, 70, 65), SL.WHITE)      # limit + 5
    self.assertEqual(SL.set_speed_rgba(True, True, 80, 65), SL.ORANGE)     # limit + 15
    self.assertEqual(SL.set_speed_rgba(True, True, 95, 65), SL.RED)
    self.assertEqual(SL.set_speed_rgba(True, False, 95, 65), SL.WHITE)     # disengaged / override: white
    self.assertEqual(SL.set_speed_rgba(True, True, 95, 0), SL.WHITE)       # no limit
    mid = SL.set_speed_rgba(True, True, 75, 65)
    self.assertTrue(SL.WHITE[2] > mid[2] > SL.ORANGE[2])

  def test_policy_formulas(self):
    class Store:
      def __init__(self, **v):
        self.v = v
      def tuning_level(self):
        return 3
      def toggle_bool(self, k, level=None):
        return self.v.get(k, False)
    import importlib, sys
    toggles = SimpleNamespace(onroad_toggles=lambda store, cp: SimpleNamespace(
      tuning_level=3, navigation_ui=store.v.get("NavigationUI", False), show_speed_limits=store.v.get("NavigationUI", False) and store.v.get("ShowSpeedLimits", False),
      speed_limit_controller=store.v.get("SpeedLimitController", False), show_speed_limit_offset=False, debug_mode=store.v.get("DebugMode", False)))
    sys.modules["openpilot.common.bogpilot_onroad_toggles"], saved = toggles, sys.modules.get("openpilot.common.bogpilot_onroad_toggles")
    try:
      p = SL.policy_from_store(Store(NavigationUI=True, ShowSpeedLimits=True, UseVienna=True, AdvancedCustomUI=True, HideSpeedLimit=True))
      self.assertEqual((p.show_speed_limits, p.vienna, p.hide_speed_limit), (True, True, True))
      p = SL.policy_from_store(Store(NavigationUI=False, UseVienna=True, AdvancedCustomUI=True, HideSpeedLimit=True, DebugMode=True))
      self.assertEqual((p.vienna, p.hide_speed_limit), (False, False))
    finally:
      if saved is not None:
        sys.modules["openpilot.common.bogpilot_onroad_toggles"] = saved
      else:
        del sys.modules["openpilot.common.bogpilot_onroad_toggles"]

  def test_policy_reader_fails_closed(self):
    r = SL.LimitPolicyReader(store=SimpleNamespace(), clock=lambda: 0.0)
    self.assertEqual(r.get(), SL.CLOSED_POLICY)


def msgs(curv=0.0, desired=0.0, v=20.0, angle=0.0, lat=True, which="angleState", torque=0.0, roll=0.0):
  cs = SimpleNamespace(curvature=curv, desiredCurvature=desired, lateralControlState=SimpleNamespace(which=lambda: which))
  return (cs, SimpleNamespace(vEgo=v, steeringAngleDeg=angle), SimpleNamespace(latActive=lat),
          SimpleNamespace(actuatorsOutput=SimpleNamespace(torque=torque)), SimpleNamespace(roll=roll))


class TestSteeringArc(unittest.TestCase):
  def test_signs(self):
    # controlsState.curvature is right-turn positive -> fills right (positive)
    a = ARC.inputs_from_messages(*msgs(curv=0.004, desired=0.004), 3.0, "engaged", False)
    self.assertGreater(a.op, 0)
    a = ARC.inputs_from_messages(*msgs(curv=-0.004, desired=-0.004), 3.0, "engaged", False)
    self.assertLess(a.op, 0)
    # steeringAngleDeg positive = left wheel -> driver fill to the left at parking speed
    a = ARC.inputs_from_messages(*msgs(v=1.0, angle=90.0), 3.0, "disengaged", False)
    self.assertAlmostEqual(a.human, -0.5)
    self.assertEqual(a.human_lat_weight, 0.0)
    # torque control path: -carOutput.actuatorsOutput.torque (0.11.2 upstream)
    a = ARC.inputs_from_messages(*msgs(which="pidState", torque=0.3), 3.0, "engaged", False)
    self.assertAlmostEqual(a.op, -0.3)

  def test_utilization_formula(self):
    # 0.004 * 20^2 = 1.6 m/s^2 over 3.2 -> 0.5; roll compensation fully on above 15 m/s
    self.assertAlmostEqual(ARC.angle_utilization(0.004, 0.004, 20.0, 0.0, 3.2), 0.5)
    self.assertAlmostEqual(ARC.angle_utilization(0.004, 0.004, 20.0, 0.01, 3.2), (1.6 - 0.0981) / 3.2, places=5)
    self.assertAlmostEqual(ARC.angle_utilization(0.0, 0.004, 20.0, 0.0, 3.2), 0.5)    # desired - actual term
    self.assertEqual(ARC.angle_utilization(1.0, 1.0, 20.0, 0.0, 3.0), 1.0)
    self.assertAlmostEqual(ARC.angle_utilization(0.004, 0.004, 20.0, 0.0, 0.0), 1.6 / 3.0)  # default max lat accel

  def test_nonfinite_rejected(self):
    with self.assertRaises(ValueError):
      ARC.inputs_from_messages(*msgs(curv=float("nan")), 3.0, "engaged", False)

  def test_states_and_hysteresis(self):
    st = ARC.ArcState()
    eng = ARC.ArcInputs(op=0.6, human=-0.4, lat_active=True, active=True, engaged_colors=True)
    for _ in range(40):
      st.update(eng)
    self.assertFalse(st.human)
    self.assertAlmostEqual(st.torque, 0.6, places=3)
    ovr = ARC.ArcInputs(op=0.6, human=-0.4, lat_active=True, override=True, active=True)
    for i in range(ARC.SOURCE_HYSTERESIS_FRAMES - 1):
      st.update(ovr)
      self.assertFalse(st.human, i)
    st.update(ovr)
    self.assertTrue(st.human)
    self.assertTrue(st.show_tick)
    st.update(eng)   # one engaged frame does not flip back
    self.assertTrue(st.human)
    self.assertFalse(st.show_tick)
    st.reset()
    dis = ARC.ArcInputs(op=0.9, human=0.2, lat_active=False)
    for _ in range(60):
      st.update(dis)
    self.assertTrue(st.human)
    self.assertAlmostEqual(st.torque, 0.2, places=3)
    self.assertAlmostEqual(st.alpha, 0.55, places=3)
    self.assertAlmostEqual(st.op_target, 0.0)

  def test_geometry_and_tap_rect_match_daily_device(self):
    view = SimpleNamespace(x=30, y=30, width=2100, height=1020)
    x, y, w, h = ARC.tap_rect(view)
    # daily: QRectF(770, 816, 560, 204) in the 2100x1020 widget; the C3X content rect starts at (30, 30)
    self.assertEqual((x - 30, y - 30, w, round(h)), (770, 816, 560, 204))
    st = ARC.ArcState()
    st.torque = -1.0
    g = ARC.geometry(st, view)
    self.assertEqual(g["fill"], (-90.0, -90.0 - ARC.SPAN_DEG / 2))   # left turn fills toward -98.5 deg = left
    self.assertAlmostEqual(g["thickness"], ARC.THICKNESS_HI)
    self.assertAlmostEqual(g["cy"] - g["radius"], 30 + 1020 - ARC.OFFSET_HI)

  def test_human_angle_colour_ramp(self):
    self.assertEqual(ARC.human_angle_color(0), (90, 205, 255))
    self.assertEqual(tuple(round(c) for c in ARC.human_angle_color(180)), (255, 140, 0))
    self.assertEqual(tuple(round(c) for c in ARC.human_angle_color(500)), (255, 20, 147))


class TestPedals(unittest.TestCase):
  DYN = PED.PedalPolicy(show=True, dynamic=True)
  STA = PED.PedalPolicy(show=True, static=True)

  def test_daily_dynamic_response_unchanged(self):
    self.assertEqual(PED.daily_opacity(self.DYN, 0.0, False, False), (0.25, 0.25))   # rest
    self.assertEqual(PED.daily_opacity(self.DYN, 0.0, True, False), (1.0, 0.25))     # standstill: brake held
    self.assertEqual(PED.daily_opacity(self.DYN, -0.2, False, True), (0.25, 0.25))   # brake lights ignored in dynamic
    self.assertEqual(PED.daily_opacity(self.DYN, -0.6, False, False), (0.6, 0.25))
    self.assertEqual(PED.daily_opacity(self.DYN, -3.0, False, False), (1.0, 0.25))   # clamped like setOpacity
    self.assertEqual(PED.daily_opacity(self.DYN, 0.5, False, False), (0.25, 0.5))
    self.assertEqual(PED.daily_opacity(self.DYN, 2.0, False, False), (0.25, 1.0))

  def test_daily_static_and_plain_response_unchanged(self):
    self.assertEqual(PED.daily_opacity(self.STA, 0.0, False, False), (0.25, 0.25))
    self.assertEqual(PED.daily_opacity(self.STA, 0.0, False, True), (1.0, 0.25))
    self.assertEqual(PED.daily_opacity(self.STA, -0.3, False, False), (1.0, 0.25))
    self.assertEqual(PED.daily_opacity(self.STA, 0.3, False, False), (0.25, 1.0))
    self.assertEqual(PED.daily_opacity(PED.PedalPolicy(show=True), -2.0, False, False), (1.0, 1.0))

  def test_visual_mapping(self):
    self.assertEqual(PED.strength(0.25), 0.0)
    self.assertEqual(PED.strength(1.0), 1.0)
    self.assertAlmostEqual(PED.strength(0.625), 0.5)
    rest, strong = PED.visual(0.0, PED.BRAKE_DIM, PED.BRAKE_BRIGHT), PED.visual(1.0, PED.BRAKE_DIM, PED.BRAKE_BRIGHT)
    self.assertLess(rest["fill_a"], 20)                     # nearly transparent at rest
    self.assertLess(rest["edge_a"], 50)
    self.assertGreater(strong["fill_a"], 220)
    self.assertEqual(strong["fill_rgb"], PED.BRAKE_BRIGHT)
    prev = -1
    for k in (0.0, 0.25, 0.5, 0.75, 1.0):                   # opacity and brightness rise monotonically
      v = PED.visual(k, PED.GAS_DIM, PED.GAS_BRIGHT)
      self.assertGreater(v["fill_a"], prev)
      prev = v["fill_a"]

  def test_policy_gate(self):
    class S:
      def __init__(self, **v):
        self.v = v
      def tuning_level(self):
        return 3
      def toggle_bool(self, k, level=None):
        return self.v.get(k, False)
    on = dict(CustomUI=True, PedalsOnUI=True, DynamicPedalsOnUI=True)
    self.assertEqual(PED.policy_from_store(S(**on), True), PED.PedalPolicy(True, True, False))
    self.assertEqual(PED.policy_from_store(S(**on), False), PED.CLOSED)       # needs openpilot longitudinal
    self.assertFalse(PED.policy_from_store(S(PedalsOnUI=True), True).show)    # needs CustomUI

  def test_footprint_and_shapes_inside_daily_keepout(self):
    self.assertEqual(PED.pedal_rect(2160, False), (30, 486, 120, 120))
    self.assertEqual(PED.pedal_rect(2160, True), (2010, 486, 120, 120))
    for box, taper in ((PED.BRAKE_BOX, PED.BRAKE_TAPER), (PED.GAS_BOX, PED.GAS_TAPER)):
      pts = PED.rounded_trapezoid(box, taper, PED.RADIUS)
      self.assertTrue(all(0 <= x <= 120 and 0 <= y <= 120 for x, y in pts))


class FakeEncoder:
  def __init__(self, path, w, h, fail_at=None):
    self.path, self.lock_path, self.w, self.h = path, path + ".lock", w, h
    self.frames, self.error, self.closed, self.fail_at, self.running = 0, None, False, fail_at, True

  def alive(self):
    return self.running

  def open(self):
    Path(self.lock_path).write_text(str(os.getpid()))
    Path(self.path).write_bytes(b"")
    return True

  def write(self, data):
    if self.fail_at is not None and self.frames >= self.fail_at:
      self.error = "encoder write failed: broken pipe"
      return False
    self.frames += 1
    with open(self.path, "ab") as f:
      f.write(b"x")
    return True

  def close(self):
    self.closed = True
    ok = self.error is None and self.frames > 0
    if ok:
      os.remove(self.lock_path)
    else:
      for p in (self.path, self.lock_path):
        if os.path.exists(p):
          os.remove(p)
    return ok


def frame(w, h, rgba):
  return bytes(rgba) * (w * h)


def wait_until(cond, timeout=10.0):
  t = time.monotonic() + timeout
  while time.monotonic() < t:
    if cond():
      return True
    time.sleep(0.02)
  return cond()


class TestRecorderEngine(unittest.TestCase):
  def setUp(self):
    self.dir = tempfile.mkdtemp(prefix="bp_sr_")

  def tearDown(self):
    shutil.rmtree(self.dir, ignore_errors=True)

  def engine(self, **kw):
    kw.setdefault("free_fn", lambda p: 10 << 30)
    kw.setdefault("wallclock", lambda: datetime.datetime(2026, 11, 7, 13, 5, 9))
    return SR.RecorderEngine(self.dir, **kw)

  def test_segment_name_matches_daily_format(self):
    self.assertEqual(SR.segment_name(datetime.datetime(2026, 11, 7, 13, 5, 9)), "November_07_2026-01-05-09PM.mp4")

  def test_refuses_to_start_without_space(self):
    e = self.engine(free_fn=lambda p: (1 << 30) - 1, encoder_factory=lambda p, w, h: FakeEncoder(p, w, h))
    self.assertFalse(e.start())
    self.assertIn("not enough free space", e.last_error)
    self.assertFalse(e.recording)
    self.assertEqual(os.listdir(self.dir), [])

  def test_disk_fills_while_recording_stops_and_keeps_file(self):
    free = [10 << 30]
    now = [0.0]
    e = self.engine(free_fn=lambda p: free[0], clock=lambda: now[0], encoder_factory=lambda p, w, h: FakeEncoder(p, w, h))
    self.assertTrue(e.start())
    e.submit_frame(frame(4, 2, (1, 2, 3, 255)), 4, 2)
    self.assertTrue(wait_until(lambda: e.encoder is not None and e.encoder.frames == 1))
    free[0] = 100 << 20
    now[0] = SR.DISK_CHECK_S + 1
    e.submit_frame(frame(4, 2, (1, 2, 3, 255)), 4, 2)
    self.assertTrue(wait_until(lambda: not e.recording))
    e.stop()
    self.assertIn("not enough free space", e.last_error)
    self.assertEqual(len(e.saved), 1)
    self.assertFalse(any(n.endswith(".lock") for n in os.listdir(self.dir)))

  def test_encoder_failure_discards_partial_and_stops(self):
    encs = []
    def fac(p, w, h):
      encs.append(FakeEncoder(p, w, h, fail_at=0))
      return encs[-1]
    e = self.engine(encoder_factory=fac)
    self.assertTrue(e.start())
    e.submit_frame(frame(4, 2, (0, 0, 0, 255)), 4, 2)
    self.assertTrue(wait_until(lambda: not e.recording))
    e.stop()
    self.assertIn("broken pipe", e.last_error)
    self.assertEqual(os.listdir(self.dir), [])
    self.assertTrue(encs[0].closed)

  def test_segment_rotation_and_resolution_change(self):
    now = [0.0]
    names = iter(datetime.datetime(2026, 11, 7, 13, 5, s) for s in range(10))
    encs = []
    def fac(p, w, h):
      encs.append(FakeEncoder(p, w, h))
      return encs[-1]
    e = self.engine(clock=lambda: now[0], wallclock=lambda: next(names), max_segment_s=2.0, encoder_factory=fac)
    e.start()
    e.submit_frame(frame(4, 2, (9, 9, 9, 255)), 4, 2)
    self.assertTrue(wait_until(lambda: len(encs) == 1 and encs[0].frames == 1))
    now[0] = 2.5
    e.submit_frame(frame(4, 2, (9, 9, 9, 255)), 4, 2)
    self.assertTrue(wait_until(lambda: len(encs) == 2 and encs[1].frames == 1))
    e.submit_frame(frame(2, 2, (9, 9, 9, 255)), 2, 2)
    self.assertTrue(wait_until(lambda: len(encs) == 3))
    e.stop()
    self.assertEqual(len(e.saved), 3)
    self.assertTrue(all(x.closed for x in encs))

  def test_frames_due_and_repeat(self):
    now = [0.0]
    e = self.engine(clock=lambda: now[0], fps=10, encoder_factory=lambda p, w, h: FakeEncoder(p, w, h))
    self.assertEqual(e.frames_due(), 0)                  # not recording
    e.start()
    self.assertEqual(e.frames_due(), 1)
    e.submit_frame(frame(2, 2, (0, 0, 0, 255)), 2, 2, 1)
    self.assertEqual(e.frames_due(), 0)                  # next frame not due yet
    now[0] = 0.35                                        # slow UI frame: 3 frames owed
    self.assertEqual(e.frames_due(), 3)
    now[0] = 10.0
    self.assertEqual(e.frames_due(), SR.MAX_REPEAT)
    e.stop()

  def test_bad_frame_size_ignored(self):
    e = self.engine(encoder_factory=lambda p, w, h: FakeEncoder(p, w, h))
    e.start()
    e.submit_frame(b"\x00" * 7, 4, 2)
    time.sleep(0.2)
    self.assertIsNone(e.encoder)
    e.stop()
    self.assertEqual(os.listdir(self.dir), [])

  def test_stale_lock_cleanup(self):
    d = Path(self.dir)
    (d / "a.mp4").write_bytes(b"data")
    (d / "a.mp4.lock").write_text("999999")             # dead writer, non-empty fragmented file: keep the video
    (d / "b.mp4").write_bytes(b"")
    (d / "b.mp4.lock").write_text("999998")             # dead writer, empty file: remove
    (d / "c.mp4").write_bytes(b"live")
    (d / "c.mp4.lock").write_text(str(os.getppid()))    # live writer: untouched
    SR.cleanup_stale(self.dir)
    self.assertEqual(sorted(os.listdir(self.dir)), ["a.mp4", "c.mp4", "c.mp4.lock"])

  def test_unwritable_directory(self):
    e = SR.RecorderEngine("/proc/bogpilot_no_such_dir/x", free_fn=lambda p: 10 << 30)
    self.assertFalse(e.start())
    self.assertIn("cannot create", e.last_error)

  def test_toggle_glue_and_truthful_indicator(self):
    e = self.engine(encoder_factory=lambda p, w, h: FakeEncoder(p, w, h))
    r = SR.ScreenRecorder(e)
    self.assertEqual(r.status, "idle")
    self.assertTrue(r.toggle())
    self.assertFalse(r.recording)                       # armed only: no encoder, no frame yet
    self.assertEqual(r.status, "starting")
    e.submit_frame(frame(4, 2, (0, 0, 0, 255)), 4, 2)
    self.assertTrue(wait_until(lambda: r.recording))
    self.assertEqual(r.status, "recording")
    self.assertFalse(r.toggle())
    self.assertFalse(r.recording)
    self.assertEqual(r.status, "idle")
    r.stop()   # idempotent (offroad transition)

  def test_toggle_while_armed_stops(self):
    e = self.engine(encoder_factory=lambda p, w, h: FakeEncoder(p, w, h))
    r = SR.ScreenRecorder(e)
    r.toggle()
    self.assertFalse(r.toggle())
    self.assertFalse(e.recording)
    self.assertEqual(os.listdir(self.dir), [])

  def test_encoder_death_while_idle_clears_indicator_and_reports(self):
    encs = []
    def fac(p, w, h):
      encs.append(FakeEncoder(p, w, h))
      return encs[-1]
    e = self.engine(encoder_factory=fac)
    r = SR.ScreenRecorder(e)
    r.toggle()
    e.submit_frame(frame(4, 2, (0, 0, 0, 255)), 4, 2)
    self.assertTrue(wait_until(lambda: r.recording))
    encs[0].running = False                             # process died, no further frames arrive
    self.assertFalse(r.recording)                       # indicator truth is immediate
    self.assertTrue(wait_until(lambda: not e.recording))  # engine notices within its 0.1 s poll
    self.assertEqual(r.status, "error")
    self.assertIn("exited", r.last_error)
    self.assertTrue(wait_until(lambda: encs[0].closed))   # worker finalizes the dead segment
    self.assertTrue(r.toggle())                         # next start clears the error
    self.assertIsNone(r.last_error)
    r.stop()

  def test_interpreter_shutdown_finalizes(self):
    child = r"""
import importlib.util, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("sr", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = Path(sys.argv[2])
class Enc:
  def __init__(self, path, w, h): self.path, self.error, self.frames = path, None, 0
  def open(self): return True
  def alive(self): return True
  def write(self, d): self.frames += 1; return True
  def close(self): (root / "finalized").write_text("1"); return True
e = m.RecorderEngine(directory=str(root), encoder_factory=Enc, free_fn=lambda p: 1 << 40)
e.start(); e.submit_frame(bytes(16 * 16 * 4), 16, 16)
t = time.monotonic() + 2
while not e.active and time.monotonic() < t: time.sleep(0.005)
assert e.active
"""
    import sys
    subprocess.run([sys.executable, "-c", child, str(Path(SR.__file__)), self.dir], check=True, timeout=20)
    self.assertTrue((Path(self.dir) / "finalized").exists())


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe not available")
class TestRecorderRealEncode(unittest.TestCase):
  """Real ffmpeg encode of synthetic frames (sandbox temp dir only)."""

  def setUp(self):
    self.dir = tempfile.mkdtemp(prefix="bp_sr_real_")

  def tearDown(self):
    shutil.rmtree(self.dir, ignore_errors=True)

  def probe(self, path):
    out = subprocess.run([FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height,nb_read_frames,pix_fmt", "-of", "json", path],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["streams"][0]

  def test_start_stop_save_real_h264(self):
    e = SR.RecorderEngine(self.dir, free_fn=lambda p: 10 << 30)
    self.assertTrue(e.start())
    w, h = 320, 160
    for i in range(25):
      top = bytes((255, 0, 0, 255)) * (w * h // 2)
      bottom = bytes((0, 0, 255, 255)) * (w * h // 2)
      e.submit_frame(top + bottom, w, h)
      time.sleep(0.01)
    e.stop()
    self.assertIsNone(e.last_error)
    self.assertEqual(len(e.saved), 1)
    path = e.saved[0]
    self.assertTrue(path.endswith(".mp4"))
    self.assertFalse(os.path.exists(path + ".lock"))
    st = self.probe(path)
    self.assertEqual((st["codec_name"], st["width"], st["height"], st["pix_fmt"]), ("h264", w, h, "yuv420p"))
    self.assertGreaterEqual(int(st["nb_read_frames"]), 20)   # dropped-oldest queue may drop a few under load
    # colours survive the encode (top red, bottom blue)
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    px = lambda x, y: raw[(y * w + x) * 3:(y * w + x) * 3 + 3]  # noqa: E731
    self.assertGreater(px(160, 20)[0], 200)
    self.assertGreater(px(160, 140)[2], 200)

  def test_killed_writer_leaves_playable_fragmented_file(self):
    enc = SR.FfmpegEncoder(os.path.join(self.dir, "crash.mp4"), 64, 32, 10, 1_000_000)
    self.assertTrue(enc.open())
    for _ in range(60):
      enc.write(bytes((0, 255, 0, 255)) * (64 * 32))
    enc.proc.stdin.flush()
    time.sleep(2.0)
    enc.proc.kill()
    enc.proc.wait()
    st = self.probe(enc.path)                               # fragmented MP4 is readable without a trailer
    self.assertEqual(st["codec_name"], "h264")
    SR.cleanup_stale(self.dir)                              # killed pid is this test's child, so the lock is ours...
    self.assertTrue(os.path.exists(enc.path))

  def test_missing_encoder_binary(self):
    e = SR.RecorderEngine(self.dir, free_fn=lambda p: 10 << 30,
                          encoder_factory=lambda p, w, h: SR.FfmpegEncoder(p, w, h, 10, 1_000_000, ffmpeg="/nonexistent/ffmpeg"))
    self.assertTrue(e.start())
    e.submit_frame(bytes(4 * 8 * 8), 8, 8)
    self.assertTrue(wait_until(lambda: not e.recording))
    e.stop()
    self.assertIn("encoder start failed", e.last_error)
    self.assertEqual(os.listdir(self.dir), [])

  def test_encoder_rejects_stream(self):
    # odd width is rejected by libx264 yuv420p -> ffmpeg exits non-zero; partial file and lock are removed
    e = SR.RecorderEngine(self.dir, free_fn=lambda p: 10 << 30)
    self.assertTrue(e.start())
    for _ in range(5):
      e.submit_frame(bytes(4 * 7 * 7), 7, 7)
    time.sleep(0.5)
    e.stop()
    self.assertEqual(e.saved, [])
    self.assertIsNotNone(e.last_error)
    self.assertEqual([n for n in os.listdir(self.dir)], [])


class TestFrameHookSource(unittest.TestCase):
  def test_hook_runs_before_end_drawing_and_after_overlays(self):
    src = (Path(__file__).resolve().parents[5] / "system" / "ui" / "lib" / "application.py").read_text()
    body = src[src.index("  def render(self):"):]
    i_hook, i_end, i_grid = body.index("for hook in list(self._frame_hooks)"), body.index("rl.end_drawing()"), body.index("self._draw_grid()")
    self.assertLess(i_grid, i_hook)
    self.assertLess(i_hook, i_end)
    self.assertIn("self.remove_frame_hook(hook)", body[i_hook:i_end])


if __name__ == "__main__":
  unittest.main()
