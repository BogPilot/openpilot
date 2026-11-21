"""Pre-AP AP1 stalk-retrofit auto-detect: detector rules and the PreApCarState wiring (no menu row, no setting).

Native tests only. No rlog I/O, no bench, no device.
"""
from __future__ import annotations

import pytest

from opendbc.car.tesla_ap1.preap import hw_tools, params
from opendbc.car.tesla_ap1.preap.stalk_retrofit import DETECT_FRAMES, SNA, StalkRetrofitDetector, VALID_DETENTS
from opendbc.car.tesla_ap1.stalk_follow import follow_seconds, parse_stalk_raw
from opendbc.car.tesla_ap1.tests import test_preap_carstate_controller as pcc


def _feed(det, raw, n=1, ts=None):
  """n frames of raw; ts is a starting frame timestamp (incremented per frame) or None (every call is a frame)."""
  for i in range(n):
    det.observe(raw, None if ts is None else ts + i)
  return None if ts is None else ts + n


# Run-length encoded dial-test segment from a real Pre-AP retrofit drive log (value, consecutive 10 Hz frames). No ids, no times.
DIAL_TEST_RUNS = [
  (33, 388), (100, 1), (133, 1), (166, 1), (200, 5), (166, 1), (33, 7), (133, 1), (200, 7), (166, 1), (66, 1), (0, 5),
  (33, 1), (100, 1), (166, 1), (200, 37), (166, 1), (133, 1), (66, 1), (33, 1), (0, 5), (66, 1), (133, 1), (200, 28),
  (0, 18), (33, 1), (100, 1), (133, 1), (166, 1), (200, 5), (133, 1), (100, 2), (33, 1), (0, 16), (33, 1), (100, 1),
  (133, 1), (166, 1), (200, 5), (166, 1), (100, 1), (33, 1), (0, 6), (100, 1), (200, 39),
]
FRAME_PERIOD_S = 0.1


class TestDetector:
  def test_detect_frames_is_pinned_at_25(self):
    # 25 new frames = 2.5 s at 10 Hz. Detection is saved after the first latch, so the slow rule is paid once. Do not change lightly.
    assert DETECT_FRAMES == 25

  def test_24_frames_do_not_latch_25_do(self):
    det = StalkRetrofitDetector()
    ts = _feed(det, 33, DETECT_FRAMES, ts=1)
    ts = _feed(det, 100, DETECT_FRAMES - 1, ts=ts)
    assert not det.latched
    _feed(det, 100, 1, ts=ts)
    assert det.latched

  def test_stale_repeats_of_one_frame_do_not_latch(self):
    det = StalkRetrofitDetector()
    ts = _feed(det, 33, DETECT_FRAMES, ts=1)
    for _ in range(DETECT_FRAMES * 100):       # one new frame at 100, then the 100 Hz loop re-reads it
      det.observe(100, ts)
    assert not det.latched
    # the same stale-repeat pattern at both positions from the first frame
    det2 = StalkRetrofitDetector()
    for _ in range(DETECT_FRAMES * 100):
      det2.observe(33, 7)
    for _ in range(DETECT_FRAMES * 100):
      det2.observe(100, 8)
    assert not det2.latched

  def test_constant_value_logs_never_latch(self):
    # stock Pre-AP (0), a Kostal-style column (255), a retrofit dial left at 33, an AP1 dial left at 200
    for raw in (0, SNA, 33, 200):
      det = StalkRetrofitDetector()
      _feed(det, raw, 20000, ts=1)
      assert not det.latched, raw

  def test_dial_test_replay_latches_at_about_44_6_s(self):
    det = StalkRetrofitDetector()
    n = 0
    latch_s = None
    for raw, frames in DIAL_TEST_RUNS:
      for _ in range(frames):
        n += 1
        det.observe(raw, int(n * FRAME_PERIOD_S * 1e9))
        if det.latched and latch_s is None:
          latch_s = (n - 1) * FRAME_PERIOD_S
    assert latch_s is not None
    assert latch_s == pytest.approx(44.6, abs=0.15)

  def test_stock_preap_constant_zero_never_latches(self):
    det = StalkRetrofitDetector()
    _feed(det, 0, 5000)
    assert not det.latched
    _feed(det, 0, 5000, ts=1)
    assert not det.latched

  def test_sna_only_never_latches(self):
    det = StalkRetrofitDetector()
    _feed(det, SNA, DETECT_FRAMES * 4)
    assert not det.latched

  def test_garbage_never_latches(self):
    det = StalkRetrofitDetector()
    for raw in (1, 15, 120, 201, 254, -1, 32.5, True, "66"):
      _feed(det, raw, DETECT_FRAMES)
    assert not det.latched

  def test_one_valid_detent_is_not_enough(self):
    det = StalkRetrofitDetector()
    _feed(det, 133, DETECT_FRAMES * 3)
    assert not det.latched

  def test_stock_zero_plus_one_other_held_detent_latches(self):
    # the retrofit dial sits at ACC_DIST_1 (0) like a stock stalk, then the driver turns it and leaves it
    det = StalkRetrofitDetector()
    _feed(det, 0, DETECT_FRAMES)
    assert not det.latched
    _feed(det, 100, DETECT_FRAMES)
    assert det.latched

  def test_two_distinct_valid_detents_each_held_latch_and_stay_latched(self):
    det = StalkRetrofitDetector()
    _feed(det, 133, DETECT_FRAMES)
    assert not det.latched
    _feed(det, 66, DETECT_FRAMES)
    assert det.latched
    _feed(det, SNA, 50)
    _feed(det, 0, 5000)
    assert det.latched

  def test_brief_second_detent_does_not_latch(self):
    det = StalkRetrofitDetector()
    _feed(det, 133, DETECT_FRAMES)
    _feed(det, 66, DETECT_FRAMES - 1)
    assert not det.latched
    _feed(det, 66, 1)
    assert det.latched

  def test_a_fast_spin_through_detents_does_not_latch(self):
    # each position passes in fewer than DETECT_FRAMES frames and the dial never rests on the same value twice in a row
    det = StalkRetrofitDetector()
    for _ in range(20):
      for raw in sorted(VALID_DETENTS):
        _feed(det, raw, DETECT_FRAMES - 1)
      for raw in sorted(VALID_DETENTS, reverse=True)[1:-1]:
        _feed(det, raw, DETECT_FRAMES - 1)
    assert not det.latched

  def test_sna_and_missing_break_the_run(self):
    for breaker in (SNA, None):
      det = StalkRetrofitDetector()
      _feed(det, 133, DETECT_FRAMES)
      _feed(det, 66, DETECT_FRAMES - 1)
      det.observe(breaker)
      _feed(det, 66, DETECT_FRAMES - 1)
      assert not det.latched, breaker

  def test_integer_floats_count(self):
    det = StalkRetrofitDetector()
    _feed(det, 133.0, DETECT_FRAMES)
    _feed(det, 200.0, DETECT_FRAMES)
    assert det.latched

  def test_same_frame_timestamp_is_not_a_new_frame(self):
    # carState runs at 100 Hz, STW_ACTN_RQ arrives at 10 Hz: a repeat of one frame must not shorten the hold
    # 66 on DETECT_FRAMES - 1 distinct frames, each repeated 10 times, is still not latched
    det2 = StalkRetrofitDetector()
    ts2 = _feed(det2, 133, DETECT_FRAMES, ts=1)
    for _ in range(DETECT_FRAMES - 1):
      for _ in range(10):
        det2.observe(66, ts2)
      ts2 += 1
    assert not det2.latched
    for _ in range(10):
      det2.observe(66, ts2)
    assert det2.latched

  def test_detent_table_matches_stalk_follow(self):
    from opendbc.car.tesla_ap1 import stalk_follow
    assert VALID_DETENTS == set(stalk_follow._DETENT_RAW)
    assert SNA == stalk_follow.SNA


class TestPreApCarStateWiring:
  @pytest.fixture(autouse=True)
  def _env(self, tmp_path, monkeypatch):
    monkeypatch.setattr(params, "_params_dir", tmp_path)
    pcc.CLOCK[0] = 1000.0
    pcc.AOL[0] = True
    monkeypatch.setattr(params, "aol_available", lambda: pcc.AOL[0])
    monkeypatch.setattr("opendbc.car.tesla_ap1.preap.carstate.time.monotonic", lambda: pcc.CLOCK[0])

  @staticmethod
  def _drive(rig, dtr, frames):
    out = None
    rig.base["STW_ACTN_RQ"] = {"DTR_Dist_Rq": dtr}
    for _ in range(frames):
      out = rig.frame()
    return out

  def test_stock_stalk_constant_zero_publishes_nothing(self):
    rig = pcc.Rig()
    out = self._drive(rig, 0, 400)
    assert out.bogpilot.ap1StalkFollowS == 0.0
    assert rig.cs.stalk_follow is None and not rig.cs.stalk_retrofit.latched

  def test_stock_stalk_never_seen_message_publishes_nothing(self):
    rig = pcc.Rig()
    for _ in range(200):
      out = rig.cs.update(rig.parsers)       # no STW_ACTN_RQ frame ever received: parser timestamp 0
    assert out.bogpilot.ap1StalkFollowS == 0.0
    assert not rig.cs.stalk_retrofit.latched

  def test_retrofit_dial_turned_and_held_enables_follow_seconds(self):
    rig = pcc.Rig()
    self._drive(rig, 0, DETECT_FRAMES + 2)
    assert rig.cs.stalk_follow is None
    out = self._drive(rig, 133, DETECT_FRAMES + 2)
    assert rig.cs.stalk_retrofit.latched
    assert out.bogpilot.ap1StalkFollowS == pytest.approx(follow_seconds(parse_stalk_raw(133, None)))
    out = self._drive(rig, 200, 3)             # follows the dial from now on, no hold needed
    assert out.bogpilot.ap1StalkFollowS == pytest.approx(1.75)

  def test_repeat_steps_on_one_frame_do_not_latch_a_stock_car(self):
    rig = pcc.Rig()
    self._drive(rig, 0, DETECT_FRAMES + 2)
    rig.base["STW_ACTN_RQ"] = {"DTR_Dist_Rq": 133}
    rig.frame()                                 # one CAN frame at a new value...
    for _ in range(500):                        # ...then 500 carState steps with no new frame
      out = rig.cs.update(rig.parsers)
    assert not rig.cs.stalk_retrofit.latched
    assert out.bogpilot.ap1StalkFollowS == 0.0


class TestSavedDetection:
  """PreAPStalkRetrofitDetected: written once at the first latch, skips detection at the next start, cleared by the HW reset."""
  KEY = params.PreApParamKeys.STALK_RETROFIT_DETECTED

  @pytest.fixture(autouse=True)
  def _env(self, tmp_path, monkeypatch):
    monkeypatch.setattr(params, "_params_dir", tmp_path)
    pcc.CLOCK[0] = 1000.0
    pcc.AOL[0] = True
    monkeypatch.setattr(params, "aol_available", lambda: pcc.AOL[0])
    monkeypatch.setattr("opendbc.car.tesla_ap1.preap.carstate.time.monotonic", lambda: pcc.CLOCK[0])
    self.dir = tmp_path

  @staticmethod
  def _drive(rig, dtr, frames):
    return TestPreApCarStateWiring._drive(rig, dtr, frames)

  def test_key_is_hidden_default_zero_and_file_backed(self):
    assert self.KEY == "PreAPStalkRetrofitDetected"
    assert params.DEFAULTS[self.KEY] is False
    assert not params.get_bool(self.KEY)
    from opendbc.car.tesla_ap1.preap import hw_tools as H
    assert self.KEY in H.HW_RESET_KEYS

  def test_written_once_at_the_first_latch_only(self, monkeypatch):
    writes = []
    real = params._write_text
    monkeypatch.setattr(params, "_write_text", lambda k, t: (writes.append((k, t)), real(k, t))[1])
    rig = pcc.Rig()
    self._drive(rig, 0, DETECT_FRAMES + 2)
    assert not rig.cs.stalk_retrofit.latched and not [w for w in writes if w[0] == self.KEY]
    assert not params.get_bool(self.KEY)
    self._drive(rig, 133, DETECT_FRAMES + 2)
    assert rig.cs.stalk_retrofit.latched
    assert [w for w in writes if w[0] == self.KEY] == [(self.KEY, "1")]
    self._drive(rig, 66, 300)                   # dial changes and many more steps: no further writes
    self._drive(rig, 200, 300)
    assert [w for w in writes if w[0] == self.KEY] == [(self.KEY, "1")]
    assert params.get_bool(self.KEY)

  def test_write_goes_through_the_step_cache_not_the_step(self, monkeypatch):
    cache = params.StepCache([self.KEY])        # not started: nothing may be flushed to disk by the 100 Hz path
    monkeypatch.setattr(params, "_step_cache", cache)
    rig = pcc.Rig()
    self._drive(rig, 0, DETECT_FRAMES + 2)
    self._drive(rig, 133, DETECT_FRAMES + 2)
    assert rig.cs.stalk_retrofit.latched
    assert not (self.dir / self.KEY).exists()   # no blocking file write from the car step
    assert cache._pending.get(self.KEY) == "1"  # queued for the params thread
    cache.refresh_once()
    assert (self.dir / self.KEY).read_text().strip() == "1"

  def test_saved_one_skips_detection_and_reads_the_dial_from_the_first_frame(self):
    (self.dir / self.KEY).write_text("1")
    rig = pcc.Rig()
    assert rig.cs.stalk_retrofit.latched
    out = self._drive(rig, 200, 1)              # first frame, no 5-frame hold
    assert out.bogpilot.ap1StalkFollowS == pytest.approx(1.75)
    out = self._drive(rig, 100, 1)
    assert out.bogpilot.ap1StalkFollowS == pytest.approx(follow_seconds(parse_stalk_raw(100, None)))

  def test_saved_zero_or_missing_still_detects(self):
    (self.dir / self.KEY).write_text("0")
    rig = pcc.Rig()
    assert not rig.cs.stalk_retrofit.latched
    out = self._drive(rig, 200, 1)
    assert out.bogpilot.ap1StalkFollowS == 0.0

  def test_saved_one_is_not_rewritten(self, monkeypatch):
    (self.dir / self.KEY).write_text("1")
    writes = []
    monkeypatch.setattr(params, "_write_text", lambda k, t: writes.append(k))
    rig = pcc.Rig()
    self._drive(rig, 200, 50)
    assert self.KEY not in writes

  def test_hardware_reset_clears_the_saved_detection(self):
    params.set_bool(self.KEY, True)
    assert params.get_bool(self.KEY)
    written = hw_tools.reset_hw_settings()
    assert self.KEY in written
    assert not params.get_bool(self.KEY)
    assert (self.dir / self.KEY).read_text().strip() == "0"

  def test_stock_car_never_saves(self):
    rig = pcc.Rig()
    self._drive(rig, 0, 600)
    assert not (self.dir / self.KEY).exists()

  def test_ap1_carstate_does_not_use_the_key_or_the_detector(self):
    import inspect
    from opendbc.car.tesla_ap1 import carstate as ap1_cs
    src = inspect.getsource(ap1_cs)
    assert "STALK_RETROFIT_DETECTED" not in src and "PreAPStalkRetrofitDetected" not in src
    assert "StalkRetrofitDetector" not in src
    assert not hasattr(ap1_cs, "StalkRetrofitDetector")


class TestDetectionStopsWhenLatched:
  def test_latched_detector_does_no_counting(self):
    det = StalkRetrofitDetector()
    ts = _feed(det, 33, DETECT_FRAMES, ts=1)
    ts = _feed(det, 100, DETECT_FRAMES, ts=ts)
    assert det.latched and not det.wants(ts)
    state = (det._run_val, det._run_len, set(det._confirmed), det._last_ts)
    _feed(det, 166, 500, ts=ts)
    _feed(det, SNA, 10, ts=ts + 500)
    assert (det._run_val, det._run_len, det._confirmed, det._last_ts) == state

  def test_saved_start_skips_detection_entirely(self):
    det = StalkRetrofitDetector()
    det.latch()
    assert det.latched and not det.wants(123456)
    _feed(det, 0, 100, ts=1)
    assert det._run_len == 0 and not det._confirmed

  def test_wants_only_for_new_real_frames(self):
    det = StalkRetrofitDetector()
    assert not det.wants(None) and not det.wants(0)
    assert det.wants(5)
    det.observe(33, 5)
    assert not det.wants(5) and det.wants(6)


class TestCarStateCallsDetectorOnlyWhenNeeded:
  @pytest.fixture(autouse=True)
  def _env(self, tmp_path, monkeypatch):
    monkeypatch.setattr(params, "_params_dir", tmp_path)
    pcc.CLOCK[0] = 1000.0
    pcc.AOL[0] = True
    monkeypatch.setattr(params, "aol_available", lambda: pcc.AOL[0])
    monkeypatch.setattr("opendbc.car.tesla_ap1.preap.carstate.time.monotonic", lambda: pcc.CLOCK[0])

  def test_observe_runs_per_new_frame_not_per_loop_step_and_never_after_latch(self):
    rig = pcc.Rig()
    calls = []
    real = rig.cs.stalk_retrofit.observe
    rig.cs.stalk_retrofit.observe = lambda raw, ts=None: (calls.append(ts), real(raw, ts))[1]
    TestPreApCarStateWiring._drive(rig, 0, 30)
    n_frames = len(calls)
    assert n_frames == 30                        # one call per new CAN frame
    for _ in range(300):                         # 300 loop steps with no new frame: no call at all
      rig.cs.update(rig.parsers)
    assert len(calls) == n_frames
    TestPreApCarStateWiring._drive(rig, 133, DETECT_FRAMES + DETECT_FRAMES)
    assert rig.cs.stalk_retrofit.latched
    after = len(calls)
    TestPreApCarStateWiring._drive(rig, 66, 200)
    assert len(calls) == after                   # latched: the detection path is skipped completely

  def test_saved_flag_means_observe_is_never_called(self, tmp_path):
    (tmp_path / params.PreApParamKeys.STALK_RETROFIT_DETECTED).write_text("1")
    rig = pcc.Rig()
    calls = []
    rig.cs.stalk_retrofit.observe = lambda *a, **k: calls.append(1)
    TestPreApCarStateWiring._drive(rig, 100, 300)
    assert calls == []
