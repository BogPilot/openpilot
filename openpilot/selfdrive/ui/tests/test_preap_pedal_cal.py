"""Guided Comma Pedal calibration screen: state-to-screen mapping, session rules, Pre-AP vehicle rows, native renders.

Pure tests need no window. Native tests (RAYLIB_BACKEND=headless) render the real widgets; set PREAP_SHOTS=/dir to write the PNGs.
"""
import os
import tempfile
import unittest
from types import SimpleNamespace

from opendbc.car.tesla_ap1.preap import calib, params as pp
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from openpilot.selfdrive.ui.bogpilot import preap_pedal_cal as cal

LONG_REASON = ("span 5.69 below 10; interceptor never quiet before the press and the car saw accel while the pedal was still moving; "
               "factor 17.577 outside 0.4-3.0; try again with your foot fully off the pedal")   # the 0.9.7 wording, kept for the legacy cut-off comparison
# What the car says now (calib.validate_calibration): plain words, one short sentence, the range in it.
FAIL_REASON = calib.validate_calibration(0.8, 140.0)[1]
FAIL_REASON_LONG = (FAIL_REASON + " The accelerator pedal moved while the car was still reading idle. Keep your foot fully off the accelerator "
                    "and brake pedals until the check mark appears, then press the accelerator pedal fully once.")


def preap_cp(long_on=True):
  return SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS", dashcamOnly=False, openpilotLongitudinalControl=long_on,
                         alphaLongitudinalAvailable=False, radarUnavailable=True, autoResumeSng=False)


def ap1_cp():
  return SimpleNamespace(carFingerprint="TESLA_AP1_MODELS", dashcamOnly=False, openpilotLongitudinalControl=True,
                         alphaLongitudinalAvailable=False, radarUnavailable=True, autoResumeSng=False)


class Clock:
  def __init__(self, t=1000.0):
    self.t = t

  def __call__(self):
    return self.t


class PedalCase(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.mkdtemp(prefix="pedalcal-")
    self._old = pp._params_dir
    from pathlib import Path
    pp._params_dir = Path(self.tmp)
    self.clock = Clock()
    # live presence is the car message (carState.bogpilot.preapPedalDetected); a fake stands in for ui_state's SubMaster
    self._live = False
    self._old_live_source = cal.live_source
    cal.live_source = lambda: self._live

  def tearDown(self):
    pp._params_dir = self._old
    cal.live_source = self._old_live_source

  # helpers: what the car process publishes
  def heard(self, on=True):
    pp.set_bool(K.PEDAL_DETECTED, on)
    self._live = on

  def calibrated(self, factor=0.941, zero=0.8):
    pp.set_float(K.PEDAL_CALIB_ZERO, zero)
    pp.set_float(K.PEDAL_CALIB_FACTOR, factor)
    pp.set_bool(K.PEDAL_CALIB_DONE, True)

  def session(self, moving=lambda: False, timeout_s=cal.TIMEOUT_S):
    return cal.PedalCalSession(monotonic=self.clock, wall=self.clock, moving=moving, timeout_s=timeout_s)

  def values(self):
    return {k: pp.get_str(k) for k in (K.PEDAL_CALIB_DONE, K.PEDAL_CALIB_ZERO, K.PEDAL_CALIB_FACTOR, K.PEDAL_CALIB_MIN, K.PEDAL_CALIB_MAX)}


class TestStateToScreen(PedalCase):
  def test_coast_step_asks_for_foot_off(self):
    s = cal.screen_for(cal.Snapshot(armed=True, stage="coast", live=True), elapsed=5)
    self.assertEqual((s.phase, s.instruction), (cal.COAST, "Keep your foot off the accelerator and brake pedals"))
    self.assertIn("Keep your foot off the accelerator and brake pedals until the check mark appears", s.detail)
    self.assertEqual([st for _, st in s.steps], [cal.ACTIVE, cal.TODO, cal.TODO])
    self.assertEqual(s.buttons, ("Cancel",))
    self.assertFalse(s.terminal)
    self.assertIn("85 s left", s.detail)

  def test_coast_detected_ticks_step_one_and_asks_for_the_press(self):
    s = cal.screen_for(cal.Snapshot(armed=True, stage="coast_ok", live=True), elapsed=10)
    self.assertEqual((s.phase, s.instruction), (cal.PRESS, "Press the accelerator pedal fully once, then let go"))
    self.assertEqual([st for _, st in s.steps], [cal.DONE, cal.ACTIVE, cal.TODO])
    self.assertIn("slowly all the way down", s.detail)

  def test_saved_shows_ready_and_scale(self):
    s = cal.screen_for(cal.Snapshot(live=True, calibrated=True, factor=0.94137), phase_hint=cal.SAVED)
    self.assertEqual(s.phase, cal.SAVED)
    self.assertIn("The Comma Pedal is ready for openpilot to control your speed", s.detail)
    self.assertIn("Pedal scale: 0.941 (1.000 = no adjustment)", s.detail)
    self.assertEqual(s.factor, 0.94137)
    self.assertEqual([st for _, st in s.steps], [cal.DONE] * 3)
    self.assertEqual(s.buttons, ("Done",))

  def test_failed_carries_the_full_reason_unelided(self):
    s = cal.screen_for(cal.Snapshot(live=True, message=LONG_REASON, stage="failed"), phase_hint=cal.FAIL)
    self.assertIn(LONG_REASON, s.detail)
    self.assertNotIn("...", s.detail)
    self.assertIn("previous calibration was not changed", s.detail)
    self.assertEqual(s.buttons, ("Close", "Try again"))
    self.assertEqual(s.steps[1][1], cal.FAILED)

  def test_timeout_and_moved_and_blocked_are_clear(self):
    t = cal.screen_for(cal.Snapshot(live=True), phase_hint=cal.TIMED_OUT)
    self.assertIn("%d seconds" % int(cal.TIMEOUT_S), t.instruction)
    self.assertIn("Nothing was changed", t.detail)
    m = cal.screen_for(cal.Snapshot(live=True), phase_hint=cal.MOVED)
    self.assertEqual(m.instruction, "The car moved")
    b = cal.screen_for(cal.Snapshot(), phase_hint=cal.BLOCKED, reason="Put the car in Park first.")
    self.assertEqual((b.phase, b.detail, b.buttons), (cal.BLOCKED, "Put the car in Park first.", ("Close",)))

  def test_pedal_not_heard_while_armed_says_so_and_keeps_cancel(self):
    s = cal.screen_for(cal.Snapshot(armed=True, stage="coast", live=False), elapsed=3)
    self.assertEqual(s.phase, cal.PEDAL_LOST)
    self.assertEqual(s.buttons, ("Cancel",))

  def test_status_row_text(self):
    self.assertEqual(cal.status_text(cal.Snapshot()), "Not detected")
    self.assertEqual(cal.status_text(cal.Snapshot(calibrated=True)), "Not detected (calibrated)")
    self.assertEqual(cal.status_text(cal.Snapshot(live=True)), "Needs calibration")
    self.assertEqual(cal.status_text(cal.Snapshot(live=True, message="x")), "Needs calibration (last try failed)")
    self.assertEqual(cal.status_text(cal.Snapshot(live=True, calibrated=True, factor=0.9412)), "Calibrated")
    self.assertEqual(cal.status_text(cal.Snapshot(live=True, armed=True)), "Calibrating")
    self.assertEqual(cal.status_text(cal.Snapshot(live=True, out_of_range=True)), "Recalibrate: scale out of range")
    self.assertEqual(cal.status_text(cal.Snapshot(live=True, out_of_range=True, message="x")), "Recalibrate: scale out of range")
    self.assertEqual(cal.status_text(cal.Snapshot(live=True, calibrated=True, out_of_range=True)), "Calibrated")
    # long fail reasons never reach the row
    self.assertLess(len(cal.status_text(cal.Snapshot(live=True, message=LONG_REASON))), 40)

  def test_blocked_reason_rules(self):
    self.assertEqual(cal.blocked_reason(live=True, moving=False), "")
    self.assertIn("Put the car in Park", cal.blocked_reason(live=True, moving=True))
    self.assertIn("not being heard", cal.blocked_reason(live=False, moving=False))

  def test_intro_has_the_full_text_and_start_cancel(self):
    html = cal.intro_html()
    for needle in ("Put the car in Park", "Keep your foot off the accelerator and brake pedals", "the car sees no input",
                   "Press the accelerator pedal fully once, slowly, all the way down, then let go", "A small twitch is ignored",
                   "about two seconds",
                   "only if the reading is sensible", "leave your current calibration exactly as it was", "90 seconds"):
      self.assertIn(needle, html)
    self.assertNotIn(">>", html)
    self.assertEqual(cal.INTRO_BUTTONS, ("Start", "Cancel"))
    # the whole old 229-char confirm is covered and the new text is longer (it scrolls, it is never clipped to 3 lines)
    self.assertGreater(len(html), 600)


class TestPedalStatusLive(PedalCase):
  def test_saved_scale_outside_the_window_reads_recalibrate_and_is_not_rewritten(self):
    self.heard()
    self.calibrated(0.60, 0.8)                 # saved before the window was tightened: normal full pedal commands would go over the panda cap
    snap = cal.read_snapshot(self.clock.t)
    self.assertTrue(snap.out_of_range and not snap.calibrated)
    self.assertEqual(cal.status_text(snap), "Recalibrate: scale out of range")
    self.assertEqual(pp.get_float(K.PEDAL_CALIB_FACTOR), 0.60)       # never rewritten
    self.assertTrue(pp.get_bool(K.PEDAL_CALIB_DONE))
    self.calibrated(0.94, 0.8)
    self.assertEqual(cal.status_text(cal.read_snapshot(self.clock.t)), "Calibrated")

  def test_status_follows_the_car_published_state_and_goes_stale(self):
    self.heard(False)
    self.assertEqual(cal.status_text(cal.read_snapshot(self.clock.t)), "Not detected")
    self.heard(True)
    self.assertEqual(cal.status_text(cal.read_snapshot(self.clock.t)), "Needs calibration")
    self.calibrated()
    self.assertEqual(cal.status_text(cal.read_snapshot(self.clock.t)), "Calibrated")
    # the car stops: PedalDetected stays latched True but carState is no longer alive
    self._live = False
    self.assertEqual(cal.status_text(cal.read_snapshot(self.clock.t + 10)), "Not detected (calibrated)")
    self._live = True
    pp.set_bool(K.PEDAL_CALIB_ARMED, True)
    self.assertEqual(cal.status_text(cal.read_snapshot(self.clock.t)), "Calibrating")


class TestCarStateLiveSource(unittest.TestCase):
  class _SM:
    def __init__(self, alive, detected):
      self.alive = {"carState": alive}
      self._cs = SimpleNamespace(bogpilot=SimpleNamespace(preapPedalDetected=detected))

    def __getitem__(self, key):
      assert key == "carState"
      return self._cs

  def test_live_needs_an_alive_car_state_that_hears_the_pedal(self):
    self.assertTrue(cal.car_state_pedal_live(self._SM(True, True)))
    self.assertFalse(cal.car_state_pedal_live(self._SM(False, True)))
    self.assertFalse(cal.car_state_pedal_live(self._SM(True, False)))

  def test_a_missing_service_reads_not_live(self):
    self.assertFalse(cal.car_state_pedal_live(SimpleNamespace(alive={})))

  def test_reading_the_row_writes_nothing(self):
    tmp = tempfile.mkdtemp(prefix="pedalcal-ro-")
    old, old_src = pp._params_dir, cal.live_source
    from pathlib import Path
    pp._params_dir = Path(tmp)
    try:
      cal.live_source = lambda: True
      for _ in range(50):
        cal.read_snapshot()
      self.assertEqual(os.listdir(tmp), [])
    finally:
      pp._params_dir, cal.live_source = old, old_src


class TestFailureMessage(PedalCase):
  def test_full_reason_is_kept_up_to_the_cap_and_never_changes_calibration(self):
    from opendbc.car.tesla_ap1.preap import calib
    before = self.values()
    calib.fail_calibration(LONG_REASON)
    self.assertEqual(pp.get_str(K.PEDAL_CALIB_MESSAGE), LONG_REASON)
    self.assertEqual(len(LONG_REASON), 192)
    calib.fail_calibration("x" * 1000)
    self.assertEqual(len(pp.get_str(K.PEDAL_CALIB_MESSAGE)), calib.MESSAGE_MAX)
    self.assertEqual(self.values(), before)
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))


class TestSession(PedalCase):
  def car(self, raw, di_gas, n=1, detected=True):
    """Drive the real car-side capture with fake samples."""
    from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
    if not hasattr(self, "_ctl"):
      from opendbc.car.tesla_ap1.values import CAR, DBC
      cp = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
      self._ctl = PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], cp)
    for _ in range(n):
      self._ctl._update_detection_and_calib(SimpleNamespace(preap_pedal_detected=detected, preap_pedal_raw=raw, di_gas=di_gas))

  def test_full_guided_pass_coast_press_saved(self):
    self.heard()
    s = self.session()
    self.assertTrue(s.begin())
    self.assertTrue(pp.get_bool(K.PEDAL_CALIB_ARMED))
    self.assertEqual(s.tick().phase, cal.COAST)
    self.car(0.8, 0.0, n=calib.COAST_FRAMES + 2)
    self.clock.t += 4
    self.heard()                              # the car refreshes its heartbeat every second
    scr = s.tick()
    self.assertEqual(scr.phase, cal.PRESS)
    self.car(3.0, 0.004)                      # the car first reports throttle: this reading is the zero
    self.car(50.0, 0.5, n=20)
    self.assertEqual(s.tick().phase, cal.PRESS)           # still measuring until the car reads full throttle
    self.car(107.0, 0.996)                    # full throttle: saved (scale 100 / (107 - 3))
    scr = s.tick()
    self.assertEqual(scr.phase, cal.SAVED)
    self.assertTrue(0.9 < scr.factor < 1.0)
    self.assertTrue(calib.is_pedal_calibrated())
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))

  def test_bad_press_fails_with_the_reason_and_changes_nothing(self):
    self.heard()
    self.calibrated(1.25, 2.0)
    before = self.values()
    s = self.session()
    s.begin()
    self.car(0.8, 0.0, n=calib.COAST_FRAMES + 2)
    self.car(1.2, 0.004)                      # onset reading 1.2 ...
    self.car(11.4, 0.996)                     # ... full at 11.4: span 10.2 -> factor 9.8, rejected by the car
    scr = s.tick()
    self.assertEqual(scr.phase, cal.FAIL)
    self.assertIn("Pedal scale 9.8", scr.detail)
    self.assertIn("out of range", scr.detail)
    self.assertNotIn("factor", scr.detail)
    self.assertEqual(self.values(), before)   # the previous calibration is untouched
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))

  def test_cancel_at_every_step_leaves_calibration_unchanged(self):
    for step in ("coast", "coast_ok"):
      self.heard()
      self.calibrated(1.1, 1.5)
      before = self.values()
      s = self.session()
      s.begin()
      self.car(0.8, 0.0, n=calib.COAST_FRAMES + (2 if step == "coast_ok" else -15))
      s.tick()
      s.cancel()
      self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))
      self.car(0.8, 0.0)                      # the car sees the disarm and drops its capture
      self.car(107.0, 0.9)                    # a later press does nothing
      self.assertEqual(self.values(), before, step)
      self.assertEqual(pp.get_str(K.PEDAL_CALIB_STAGE), "")
      if hasattr(self, "_ctl"):
        del self._ctl

  def test_timeout_disarms_and_says_so(self):
    self.heard()
    self.calibrated(1.1, 1.5)
    before = self.values()
    s = self.session(timeout_s=90)
    s.begin()
    self.clock.t += 89
    self.heard()
    self.assertNotEqual(s.tick().phase, cal.TIMED_OUT)
    self.clock.t += 2
    scr = s.tick()
    self.assertEqual(scr.phase, cal.TIMED_OUT)
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))
    self.assertEqual(self.values(), before)

  def test_car_moving_disarms(self):
    self.heard()
    state = {"moving": False}
    s = self.session(moving=lambda: state["moving"])
    s.begin()
    state["moving"] = True
    self.assertEqual(s.tick().phase, cal.MOVED)
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))

  def test_blocked_start_never_arms(self):
    self.heard(False)
    s = self.session()
    self.assertFalse(s.begin())
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))
    self.assertEqual(s.tick().phase, cal.BLOCKED)
    self.heard()
    s2 = self.session(moving=lambda: True)
    self.assertFalse(s2.begin())
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))

  def test_leaving_the_screen_disarms_and_retry_rearms(self):
    self.heard()
    s = self.session()
    s.begin()
    s.close()
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))
    self.assertTrue(s.retry())
    self.assertTrue(pp.get_bool(K.PEDAL_CALIB_ARMED))

  def test_arming_clears_a_stale_failure_and_never_resets_values(self):
    self.heard()
    self.calibrated(1.1, 1.5)
    before = self.values()
    calib.fail_calibration("old failure")
    self.assertEqual(pp.get_str(K.PEDAL_CALIB_STAGE), "failed")
    s = self.session()
    s.begin()
    self.assertEqual(pp.get_str(K.PEDAL_CALIB_MESSAGE), "")
    self.assertEqual(s.tick().phase, cal.COAST)       # the old failed stage must not latch a new attempt
    self.assertEqual(self.values(), before)


class TestPreApVehicleRows(PedalCase):
  def model(self, cp, offroad=True):
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import VehicleSettings
    tmp = tempfile.mkdtemp(prefix="vs-")
    from pathlib import Path
    m = VehicleSettings(MemParams(), lambda: cp, lambda: offroad, file_dir=Path(tmp), params_file=Path(tmp) / "DisableOpenpilotLongitudinal")
    m.moving_fn = lambda: False
    m.wall_fn = self.clock
    return m

  def test_preap_shows_only_active_rows_double_pull_hidden_without_aol(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    m = self.model(preap_cp())
    vis = {k for k in (pv.LONG, pv.CLUSTER, pv.REGEN, pv.DOUBLE_PULL, pv.PEDAL_STATUS, pv.PEDAL_CALIBRATE) if m.visible(k)}
    # no inert Double Pull switch; RegenComfortBrake is live on Pre-AP with openpilot long (comfort regen v2)
    self.assertEqual(vis, {pv.LONG, pv.REGEN, pv.PEDAL_STATUS, pv.PEDAL_CALIBRATE})
    self.assertEqual(m.title(pv.LONG), "Disable Pedal Longitudinal")
    from unittest import mock
    with mock.patch.object(pp, "aol_available", lambda: True):                       # what a future approved AOL would unlock
      self.assertTrue(m.visible(pv.DOUBLE_PULL))
    # a saved Double Pull value is neither shown nor rewritten
    pp.set_bool(K.DOUBLE_PULL, True)
    self.assertFalse(m.visible(pv.DOUBLE_PULL))
    self.assertEqual(open(os.path.join(self.tmp, K.DOUBLE_PULL)).read(), "1")
  def test_double_pull_row_follows_the_aol_seam_and_only_for_a_preap_car_with_pedal_long(self):
    from unittest import mock
    from openpilot.selfdrive.car import ap1_runtime
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    self.addCleanup(pp.register_aol_provider, None)
    m = self.model(preap_cp())
    self.assertFalse(m.visible(pv.DOUBLE_PULL))                       # no AOL lane function: hidden
    with mock.patch.object(ap1_runtime, "preap_aol_available", lambda cp: True, create=True):
      self.assertTrue(m.visible(pv.DOUBLE_PULL))                      # AOL lane says yes: shown
      self.assertFalse(self.model(preap_cp(long_on=False)).visible(pv.DOUBLE_PULL))
      self.assertFalse(self.model(ap1_cp()).visible(pv.DOUBLE_PULL))
    with mock.patch.object(ap1_runtime, "preap_aol_available", lambda cp: False, create=True):
      self.assertFalse(m.visible(pv.DOUBLE_PULL))

  def test_radar_rows_preap_only_and_nosecone_always_hidden(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    for cp in (preap_cp(), preap_cp(long_on=False)):
      m = self.model(cp)
      self.assertTrue(m.visible(pv.RADAR))
      self.assertFalse(m.visible(pv.RADAR_NOSECONE))                  # hidden: Radar Donor Type picks the position now
      self.assertFalse(m.read(pv.RADAR))
      pp.set_bool(K.RADAR_ENABLED, True)
      self.assertFalse(m.visible(pv.RADAR_NOSECONE))                  # still hidden with the radar on
      pp.set_bool(K.RADAR_ENABLED, False)
    pp.set_bool(K.RADAR_ENABLED, True)
    for row in (pv.RADAR, pv.RADAR_NOSECONE):
      self.assertFalse(self.model(ap1_cp()).visible(row), row)        # AP1 S: never shown, even with a stored value
      self.assertFalse(self.model(None).visible(row), row)

  def test_radar_rows_write_the_car_files_offroad_only(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    m = self.model(preap_cp())
    self.assertFalse(os.path.exists(os.path.join(self.tmp, K.RADAR_ENABLED)))   # nothing written until a tap
    self.assertTrue(m.write(pv.RADAR, True))
    self.assertEqual(open(os.path.join(self.tmp, K.RADAR_ENABLED)).read(), "1")
    self.assertFalse(m.write(pv.RADAR_NOSECONE, True))               # hidden row: no write
    self.assertFalse(os.path.exists(os.path.join(self.tmp, K.RADAR_BEHIND_NOSECONE)))
    pp.set_bool(K.RADAR_BEHIND_NOSECONE, True)                         # a value saved by an earlier build
    self.assertTrue(m.read(pv.RADAR_NOSECONE))
    onroad = self.model(preap_cp(), offroad=False)
    self.assertFalse(onroad.enabled(pv.RADAR))
    self.assertFalse(onroad.write(pv.RADAR, False))
    self.assertTrue(pp.get_bool(K.RADAR_ENABLED))
    self.assertFalse(self.model(ap1_cp()).write(pv.RADAR, False))
    self.assertTrue(pp.get_bool(K.RADAR_ENABLED))
    m.write(pv.RADAR, False)
    self.assertFalse(m.visible(pv.RADAR_NOSECONE))                   # saved nosecone kept, row hidden
    self.assertTrue(pp.get_bool(K.RADAR_BEHIND_NOSECONE))

  def test_ibooster_row_is_preap_only_default_off_and_offroad_only(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    self.assertEqual(pv.IBOOSTER, K.HAS_IBOOSTER)
    self.assertIs(pp.DEFAULTS[K.HAS_IBOOSTER], False)
    for cp in (preap_cp(), preap_cp(long_on=False)):
      m = self.model(cp)
      self.assertTrue(m.visible(pv.IBOOSTER))
      self.assertFalse(m.read(pv.IBOOSTER))                            # default Off
    self.assertFalse(os.path.exists(os.path.join(self.tmp, K.HAS_IBOOSTER)))   # nothing written until a tap
    self.assertFalse(self.model(ap1_cp()).visible(pv.IBOOSTER))       # AP1: factory iBooster, no row
    self.assertFalse(self.model(None).visible(pv.IBOOSTER))
    m = self.model(preap_cp())
    self.assertTrue(m.write(pv.IBOOSTER, True))
    self.assertEqual(open(os.path.join(self.tmp, K.HAS_IBOOSTER)).read(), "1")
    self.assertTrue(m.read(pv.IBOOSTER))
    self.assertFalse(self.model(preap_cp(), offroad=False).write(pv.IBOOSTER, False))
    self.assertFalse(self.model(ap1_cp()).write(pv.IBOOSTER, False))
    self.assertTrue(pp.get_bool(K.HAS_IBOOSTER))
    self.assertIn("ibooster", pv.DESCRIPTIONS[pv.IBOOSTER].lower())

  def test_pedal_rows_hide_when_pedal_long_is_off_for_the_car(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    m = self.model(preap_cp(long_on=False))
    self.assertTrue(m.visible(pv.LONG))
    for k in (pv.DOUBLE_PULL, pv.PEDAL_STATUS, pv.PEDAL_CALIBRATE):
      self.assertFalse(m.visible(k), k)

  def test_ap1_is_unchanged_and_has_no_pedal_rows(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    m = self.model(ap1_cp())
    self.assertEqual({k for k in (pv.LONG, pv.CLUSTER, pv.REGEN, pv.DOUBLE_PULL, pv.PEDAL_STATUS, pv.PEDAL_CALIBRATE) if m.visible(k)},
                     {pv.LONG, pv.CLUSTER, pv.REGEN})
    self.assertEqual(m.title(pv.LONG), "Disable openpilot Longitudinal Control")

  def test_double_pull_row_reads_and_writes_the_consumers_file(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    from unittest import mock
    patch = mock.patch.object(pp, "aol_available", lambda: True)
    patch.start()
    self.addCleanup(patch.stop)
    m = self.model(preap_cp())
    self.assertTrue(m.read(pv.DOUBLE_PULL))                      # shipped default, nothing written by reading
    self.assertFalse(os.path.exists(os.path.join(self.tmp, K.DOUBLE_PULL)))
    self.assertTrue(m.write(pv.DOUBLE_PULL, False))
    self.assertEqual(open(os.path.join(self.tmp, K.DOUBLE_PULL)).read(), "0")
    self.assertFalse(pp.get_bool(K.DOUBLE_PULL))                 # what PreApCarState reads each frame
    self.assertFalse(m.read(pv.DOUBLE_PULL))
    self.assertTrue(m.write(pv.DOUBLE_PULL, True))
    self.assertTrue(pp.get_bool(K.DOUBLE_PULL))

  def test_toggle_rows_are_offroad_only_calibrate_is_not(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    m = self.model(preap_cp(), offroad=False)
    self.assertFalse(m.enabled(pv.DOUBLE_PULL))     # hidden anyway while AOL is unavailable
    self.heard()
    self.assertTrue(m.enabled(pv.PEDAL_CALIBRATE))               # parked + heard
    m.moving_fn = lambda: True
    self.assertFalse(m.enabled(pv.PEDAL_CALIBRATE))
    m.moving_fn = lambda: False
    self.heard(False)
    self.assertFalse(m.enabled(pv.PEDAL_CALIBRATE))

  def test_status_row_is_live(self):
    m = self.model(preap_cp())
    self.heard(False)
    self.assertEqual(m.pedal_status(), "Not detected")
    self.heard()
    self.assertEqual(m.pedal_status(), "Needs calibration")
    self.calibrated()
    self.assertEqual(m.pedal_status(), "Calibrated")
    self._live = False                      # the car went quiet: carState stops (PedalDetected stays latched)
    self.assertEqual(m.pedal_status(), "Not detected (calibrated)")

  def test_build_and_panda_firmware_rows_are_preap_only_and_independent_of_pedal_long(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    for long_on in (True, False):
      m = self.model(preap_cp(long_on=long_on))
      self.assertTrue(m.visible(pv.BUILD_INFO) and m.visible(pv.PANDA_FIRMWARE))
    m = self.model(ap1_cp())
    self.assertFalse(m.visible(pv.BUILD_INFO) or m.visible(pv.PANDA_FIRMWARE))
    self.assertFalse(self.model(None).visible(pv.BUILD_INFO))

  def test_build_text_is_version_and_commit(self):
    from unittest import mock
    from openpilot.common import version as ver
    m = self.model(preap_cp())
    meta = ver.BuildMetadata("lane", ver.OpenpilotMetadata("0.11.2", "", "6476431ac0d1e2f3a4b5c6d7e8f9", "o", "d", "unknown", False))
    with mock.patch.object(ver, "get_build_metadata", lambda *a, **k: meta):
      self.assertEqual(m.build_text(), "0.11.2 (6476431ac)")
    dirty = ver.BuildMetadata("lane", ver.OpenpilotMetadata("0.11.2", "", "6476431ac0d1e2f3a4b5c6d7e8f9", "o", "d", "unknown", True))
    m2 = self.model(preap_cp())
    with mock.patch.object(ver, "get_build_metadata", lambda *a, **k: dirty):
      self.assertEqual(m2.build_text(), "0.11.2 (6476431ac) + local edits")
    m3 = self.model(preap_cp())
    with mock.patch.object(ver, "get_build_metadata", side_effect=RuntimeError("no build info")):
      self.assertEqual(m3.build_text(), "unknown")

  def test_panda_firmware_text_reads_what_pandad_wrote(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    m = self.model(preap_cp())
    self.assertEqual(m.panda_firmware_text(), pv.PANDA_FIRMWARE_UNKNOWN)
    pp.set_str(K.PANDA_FIRMWARE, "DEV-328a9d92-DEBUG")
    self.assertEqual(m.panda_firmware_text(), "DEV-328a9d92-DEBUG")

  def test_help_entries_exist_for_the_new_rows(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve, help_html
    for k in ("TeslaPreApDoublePull", "PedalStatus", "PedalCalibrate", "PreApBuild", "PreApPandaFirmware"):
      e = resolve(k)
      self.assertIsNotNone(e, k)
      self.assertNotIn("<", help_html(e).replace("<h2>", "").replace("</h2>", "").replace("<p>", "").replace("</p>", "")
                       .replace("<h4>", "").replace("</h4>", ""))


class MemParams:
  def __init__(self):
    self.d = {}

  def put_bool(self, k, v, block=False):
    self.d[k] = bool(v)

  def get_bool(self, k):
    return self.d.get(k, False)


# ----------------------------------------------------------------------------------------------------------------------
# Native (headless raylib)
# ----------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestPedalCalNative(PedalCase):
  @classmethod
  def setUpClass(cls):
    from openpilot.selfdrive.ui.tests import test_bogpilot_menu_097 as m
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.system.ui.widgets import Widget

    class Base(Widget):
      def _render(self, rect):
        pass

    cls.rl, cls.gui_app = rl, gui_app          # window + base widget, same recipe as the menu tests' NativeCase
    if not gui_app.big_ui() and not rl.is_window_ready():
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("Pre-AP pedal calibration native test")
    cls.base = Base()
    gui_app.push_widget(cls.base)
    cls._fallbacks = m.TestMenuNative._shape_fallbacks
    cls.shots = os.getenv("PREAP_SHOTS")
    if cls.shots:
      os.makedirs(cls.shots, exist_ok=True)

  def setUp(self):
    super().setUp()
    while len(self.gui_app._nav_stack) > 1:
      self.gui_app.pop_widget()

  def draw(self, widget, shot=None, frames=3):
    rl = self.rl
    from unittest import mock
    patches = []
    if shot and self.shots:
      patches = [mock.patch.object(rl, n, f) for n, f in self._fallbacks().items()]
      for p in patches:
        p.start()
    try:
      for i in range(frames):
        rl.begin_drawing()
        try:
          rl.clear_background(rl.BLACK)
          widget.render(rl.Rectangle(0, 0, self.gui_app.width, self.gui_app.height))
          if shot and self.shots and i == frames - 1:
            rl.rl_draw_render_batch_active()   # flush the batch: the framebuffer read does not, so few-draw screens came out black
            img = rl.load_image_from_screen()
            rl.export_image(img, os.path.join(self.shots, shot))
            rl.unload_image(img)
        finally:
          rl.end_drawing()
    finally:
      for p in patches:
        p.stop()

  def screen(self, session):
    w = cal.create_calibration_screen(session)
    self.gui_app.push_widget(w)
    return w

  # The drivers' problem on the 0.9.7 one-shot flow, recreated in the plain 0.11.2 ConfirmDialog / alert_dialog.
  LEGACY_CONFIRM = ("Park, foot off the pedal. OK arms calibration: keep foot off until the "
                    "interceptor is quiet and the car shows no gas, then press the pedal fully "
                    "once with your foot. A tiny twitch is rejected. Cancel leaves calibration unchanged.")

  def _plain_dialog_fit(self, text):
    """(px the plain dialog's 70 pt bold body needs, px it has) for the plain ConfirmDialog / alert_dialog at the device size."""
    from openpilot.system.ui.lib.application import FontWeight
    from openpilot.system.ui.lib.wrap_text import wrap_text
    from openpilot.system.ui.widgets.confirm_dialog import BUTTON_HEIGHT, MARGIN, OUTER_MARGIN, TEXT_PADDING
    width = self.gui_app.width - 2 * OUTER_MARGIN - 2 * MARGIN
    height = self.gui_app.height - 2 * OUTER_MARGIN - BUTTON_HEIGHT - MARGIN - TEXT_PADDING * 2
    return len(wrap_text(self.gui_app.font(FontWeight.BOLD), text, 70, int(width))) * 70, height

  def test_legacy_one_shot_flow_disappears_when_confirmed_and_long_results_are_cut_off(self):
    from openpilot.system.ui.widgets import DialogResult
    from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
    # (1) short duration: confirming pops the dialog at once. Nothing stays up while the calibration runs, nothing shows its result.
    results = []
    d = ConfirmDialog(self.LEGACY_CONFIRM, "OK", cancel_text="Cancel", callback=results.append)
    self.draw(d, "10a_legacy_one_shot_confirm.png")
    self.gui_app.push_widget(d)
    depth = len(self.gui_app._nav_stack)
    d._confirm_button_callback()
    self.assertEqual(len(self.gui_app._nav_stack), depth - 1)
    self.assertEqual(results, [DialogResult.CONFIRM])
    # (2) cut-off text, found in code: the ported fail_calibration kept only reason[:120]. The same 190 character reason the guided
    # screen shows in full (render 05) came out of the 0.9.7 store ending mid-word, without its "try again" advice.
    legacy = LONG_REASON[:120]
    self.assertTrue(legacy.endswith("fac"), legacy)
    self.assertNotIn("try again", legacy)
    self.draw(alert_dialog(legacy + " Your previous calibration was not changed."), "10b_legacy_failure_text_cut_off_at_120_chars.png")
    # the exact 0.9.7 confirm text itself fits at 2160x1080 (not a cause here)
    needed, have = self._plain_dialog_fit(self.LEGACY_CONFIRM)
    self.assertLessEqual(needed, have)
    # fixed: the full reason is stored and shown
    from opendbc.car.tesla_ap1.preap import calib
    calib.fail_calibration(LONG_REASON)
    self.assertGreater(len(LONG_REASON), 120)
    self.assertEqual(pp.get_str(K.PEDAL_CALIB_MESSAGE), LONG_REASON)
    # the guided intro carries the information in a scrollable body
    self.assertTrue(cal.create_intro_dialog(lambda r: None)._rich)

  def test_intro_is_scrollable_with_start_and_cancel(self):
    results = []
    d = cal.create_intro_dialog(results.append)
    self.assertEqual(d.html, cal.intro_html())
    self.assertTrue(d._rich)
    self.assertEqual(d._cancel_text, "Cancel")
    self.assertEqual(d._confirm_button._label.text if hasattr(d._confirm_button._label, "text") else "Start", "Start")
    self.draw(d, "01_intro_start_cancel.png")
    total = d._html_renderer.get_total_height(1400)
    self.assertGreater(total, 0)

  def test_every_step_renders(self):
    self.heard()
    self.calibrated()
    s = self.session()
    w = self.screen(s)                       # show_event -> begin() arms
    self.assertTrue(pp.get_bool(K.PEDAL_CALIB_ARMED))
    pp.set_str(K.PEDAL_CALIB_STAGE, "coast")
    self.draw(w, "02_step1_take_your_foot_off.png")
    pp.set_str(K.PEDAL_CALIB_STAGE, "coast_ok")
    self.clock.t += 12
    self.heard()
    self.draw(w, "03_step2_coast_detected_press_fully.png")
    pp.set_float(K.PEDAL_CALIB_FACTOR, 0.94137)
    calib.set_stage("saved")
    pp.set_bool(K.PEDAL_CALIB_ARMED, False)
    self.draw(w, "04_saved_with_factor.png")
    self.assertEqual(w.screen.phase, cal.SAVED)
    self.gui_app.pop_widget()

  def test_failed_long_reason_is_wrapped_and_visible(self):
    self.heard()
    s = self.session()
    w = self.screen(s)
    pp.set_str(K.PEDAL_CALIB_MESSAGE, FAIL_REASON)
    pp.set_bool(K.PEDAL_CALIB_ARMED, False)
    calib.set_stage("failed")
    self.draw(w, "05_failed_full_reason.png")
    self.assertIn(FAIL_REASON.rstrip("."), w.screen.detail)
    self.assertNotIn("factor", w.screen.detail.lower())
    pp.set_str(K.PEDAL_CALIB_MESSAGE, FAIL_REASON_LONG)
    self.draw(w, "05b_failed_long_reason_wraps.png")
    scr = w.screen
    self.assertEqual(scr.phase, cal.FAIL)
    size, lines = w._fit(scr.detail, self.gui_app.width - 200, 360) if hasattr(w, "_fit") else (0, [])
    self.assertGreaterEqual(len(lines), 2)
    self.assertNotIn("...", " ".join(lines))
    self.assertEqual(" ".join(lines).split(), scr.detail.split())   # nothing dropped by wrapping
    self.gui_app.pop_widget()

  def test_timeout_and_cancel_screens(self):
    self.heard()
    s = self.session(timeout_s=90)
    w = self.screen(s)
    self.clock.t += 95
    self.heard()
    self.draw(w, "06_timed_out.png")
    self.assertEqual(w.screen.phase, cal.TIMED_OUT)
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))
    w._press("Close")
    self.assertNotIn(w, self.gui_app._nav_stack)

  def test_cancel_button_and_pop_disarm(self):
    self.heard()
    s = self.session()
    w = self.screen(s)
    w.render(self.rl.Rectangle(0, 0, self.gui_app.width, self.gui_app.height))
    self.assertTrue(pp.get_bool(K.PEDAL_CALIB_ARMED))
    w._press("Cancel")
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))
    self.assertNotIn(w, self.gui_app._nav_stack)
    # popping any other way (back, navigation) also disarms
    s2 = self.session()
    w2 = self.screen(s2)
    self.assertTrue(pp.get_bool(K.PEDAL_CALIB_ARMED))
    self.gui_app.pop_widget()
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))

  def test_blocked_screen_renders_and_vehicle_page_rows(self):
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import create_vehicle_settings_layout
    self.heard(False)
    s = self.session()
    w = self.screen(s)
    self.draw(w, "07_blocked_pedal_not_heard.png")
    self.assertEqual(w.screen.phase, cal.BLOCKED)
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))
    self.gui_app.pop_widget()
    # Vehicle Settings page with the live Comma Pedal row
    old = ui_state.CP
    ui_state.CP = preap_cp()
    try:
      layout = create_vehicle_settings_layout(params=MemParams())
      layout.show_event()
      page = self.rl.Rectangle(550, 25, 1560, 1030)
      layout.model.wall_fn = self.clock
      self.heard()
      layout._status_cache = (0.0, "")
      self.draw_page(layout, page, "08_vehicle_settings_needs_calibration.png")
      self.assertEqual(layout._status(), "Needs calibration")
      self.calibrated()
      layout._status_cache = (0.0, "")
      self.draw_page(layout, page, "09_vehicle_settings_ready.png")
      self.assertEqual(layout._status(), "Calibrated")
    finally:
      ui_state.CP = old

  def draw_page(self, layout, page, shot):
    rl = self.rl
    from unittest import mock
    patches = []
    if shot and self.shots:
      patches = [mock.patch.object(rl, n, f) for n, f in self._fallbacks().items()]
      for p in patches:
        p.start()
    try:
      for i in range(3):
        rl.begin_drawing()
        try:
          rl.clear_background(rl.BLACK)
          rl.draw_rectangle_rounded(rl.Rectangle(510, 10, 1640, 1060), 0.04, 30, rl.Color(41, 41, 41, 255))
          layout.render(page)
          if shot and self.shots and i == 2:
            rl.rl_draw_render_batch_active()   # flush the batch: the framebuffer read does not, so few-draw screens came out black
            img = rl.load_image_from_screen()
            rl.export_image(img, os.path.join(self.shots, shot))
            rl.unload_image(img)
        finally:
          rl.end_drawing()
    finally:
      for p in patches:
        p.stop()


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestEngageFixesNative(PedalCase):
  """ renders: the Pre-AP Vehicle screen with the build and panda firmware rows, and the two new alerts (set PREAP_SHOTS=/dir for PNGs)."""
  setUpClass = classmethod(lambda cls: TestPedalCalNative.setUpClass.__func__(cls))

  def setUp(self):
    PedalCase.setUp(self)
    while len(self.gui_app._nav_stack) > 1:
      self.gui_app.pop_widget()

  draw = TestPedalCalNative.draw
  draw_page = TestPedalCalNative.draw_page

  def test_vehicle_screen_shows_build_and_panda_firmware(self):
    from unittest import mock
    from openpilot.common import version as ver
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import create_vehicle_settings_layout
    meta = ver.BuildMetadata("lane", ver.OpenpilotMetadata("0.11.2", "", "6476431ac11b72c1ece3b5ce1aa3a7302cef0fdc", "o", "d", "unknown", False))
    old = ui_state.CP
    ui_state.CP = preap_cp()
    try:
      with mock.patch.object(ver, "get_build_metadata", lambda *a, **k: meta):
        self.heard()
        self.calibrated()
        pp.set_str(K.PANDA_FIRMWARE, "DEV-328a9d92-DEBUG")
        layout = create_vehicle_settings_layout(params=MemParams())
        layout.model.wall_fn = self.clock
        layout.show_event()
        page = self.rl.Rectangle(550, 25, 1560, 1030)
        self.draw_page(layout, page, "20_vehicle_screen_build_and_panda_firmware.png")
        self.assertEqual(layout.model.build_text(), "0.11.2 (6476431ac)")
        self.assertEqual(layout._panda_firmware(), "DEV-328a9d92-DEBUG")
        self.assertTrue(layout.build_row.is_visible and layout.panda_row.is_visible)
        # before pandad has reported
        pp.set_str(K.PANDA_FIRMWARE, "")
        layout._fw_cache = (0.0, "")
        self.draw_page(layout, page, "21_vehicle_screen_panda_not_reported_yet.png")
        self.assertEqual(layout._panda_firmware(), "Not reported yet")
    finally:
      ui_state.CP = old

  def _alert_shot(self, alert, shot):
    """The real onroad AlertRenderer drawing, fed an events.py alert."""
    from openpilot.selfdrive.ui.onroad import alert_renderer as ar
    r = ar.AlertRenderer()
    rl = self.rl
    out = ar.Alert(text1=alert.alert_text_1, text2=alert.alert_text_2, size=int(alert.alert_size), status=int(alert.alert_status))
    rect = rl.Rectangle(0, 0, self.gui_app.width, self.gui_app.height)

    class Show(type(r)):
      def get_alert(self, sm):
        return out
    r.__class__ = Show
    from unittest import mock
    patches = [mock.patch.object(rl, n, f) for n, f in self._fallbacks().items()] if self.shots else []
    for q in patches:
      q.start()
    try:
      for i in range(3):
        rl.begin_drawing()
        try:
          rl.clear_background(rl.Color(60, 66, 74, 255))
          r.render(rect)
          if self.shots and i == 2:
            rl.rl_draw_render_batch_active()
            img = rl.load_image_from_screen()
            rl.export_image(img, os.path.join(self.shots, shot))
            rl.unload_image(img)
        finally:
          rl.end_drawing()
    finally:
      for q in patches:
        q.stop()

  def test_new_alerts_render(self):
    from opendbc.car import structs
    from openpilot.cereal import log
    from openpilot.selfdrive.selfdrived.events import EVENTS, ET
    EventName = log.OnroadEvent.EventName
    self._alert_shot(EVENTS[EventName.preapNotArmed][ET.USER_DISABLE], "22_alert_cruise_didnt_arm.png")
    for cause, name in ((3, "mismatch"), (2, "fault"), (4, "counter_stuck")):
      cs = structs.CarState.new_message()
      cs.bogpilot.preapPedalFailCause = cause
      self._alert_shot(EVENTS[EventName.pedalRetrying][ET.WARNING](None, cs.as_reader(), None, False, 0, None), f"23_alert_pedal_retrying_{name}.png")


if __name__ == "__main__":
  unittest.main()
