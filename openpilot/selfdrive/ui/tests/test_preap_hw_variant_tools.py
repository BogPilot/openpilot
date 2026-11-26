"""Pre-AP hardware-variant tools on the Vehicle Settings page: Pedal Emergency Disable, Test Radar / Calibrate Radar, Reset Hardware
Settings. Pure Python (temp stores, no raylib). Credit: NotAutopilot nap-dev (MIT) for the ideas; see preap_radar_tools.py."""
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.preap import calib, hw_tools, params as preap_params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.values import CAR, DBC
from openpilot.selfdrive.ui.bogpilot import onroad_policy as op
from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
from openpilot.selfdrive.ui.bogpilot import preap_radar_tools as rt
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import (AP1, HW_RESET, LONG, PEDAL_EMERGENCY, PREAP, RADAR, RADAR_CALIBRATE, RADAR_TEST,
                                                            VehicleSettings)
from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP

PACKER = CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar])


class Drive:
  def __init__(self):
    self.started = self.parked = self.engaged = False


@pytest.fixture
def env(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "bp"))
  monkeypatch.setattr(preap_params, "_params_dir", tmp_path / "params_bogpilot")
  drive = Drive()
  op.set_state(op.DriveState(lambda: drive.started, lambda: drive.parked, lambda: drive.engaged))
  op.set_prompt_ui(lambda *a, **k: None)
  op.new_visit()
  yield SimpleNamespace(drive=drive, root=tmp_path)
  op.set_state(None)
  op.set_prompt_ui(None)
  op.new_visit()


def make_model(env, fingerprint=PREAP, long_on=True, offroad=lambda: True):
  puts, changes = [], []
  cp = SimpleNamespace(carFingerprint=fingerprint, dashcamOnly=False, openpilotLongitudinalControl=long_on, alphaLongitudinalAvailable=False)
  files = env.root / "bogpilot"
  files.mkdir(exist_ok=True)
  model = VehicleSettings(SimpleNamespace(put_bool=lambda k, v, block=False: puts.append((k, v))), lambda: cp, offroad, files,
                          env.root / LONG, started=lambda: env.drive.started, on_change=changes.append)
  model.moving_fn = lambda: env.drive.started and not env.drive.parked
  model.engaged_fn = lambda: env.drive.engaged
  model.puts, model.changes, model.cp_obj = puts, changes, cp
  return model


def calibrated():
  calib.apply_calibration_result({"ok": 1.0, "pedal_calib_zero": 12.0, "pedal_calib_factor": 1.5, "pedal_calib_min": -3.0,
                                  "pedal_calib_max": 99.6})


# ---------------------------------------------------------------- rows, help, policy
def test_new_keys_have_help_and_policy():
  for key in (PEDAL_EMERGENCY, RADAR_TEST, RADAR_CALIBRATE, HW_RESET):
    assert key in HELP and HELP[key].what and HELP[key].note
    text = " ".join(str(x) for x in (HELP[key].title, HELP[key].what, HELP[key].when, HELP[key].note))
    assert text.isascii() and "<" not in text
  assert op.row_class(RADAR_TEST, "vehicle_controls") == op.PARKED and op.row_class(RADAR_CALIBRATE, "vehicle_controls") == op.PARKED
  assert op.row_class(PEDAL_EMERGENCY, "vehicle_controls") == op.REBOOT        # allowed while driving
  assert op.allowed(op.row_class(PEDAL_EMERGENCY, "vehicle_controls"), started=True, parked=False)


def test_visibility_follows_the_car_and_the_radar_switch(env):
  m = make_model(env)
  assert m.visible(PEDAL_EMERGENCY) and m.visible(HW_RESET)
  assert not m.visible(RADAR_TEST) and not m.visible(RADAR_CALIBRATE)           # Bosch Radar off
  preap_params.set_bool(RADAR, True)
  assert m.visible(RADAR_TEST) and m.visible(RADAR_CALIBRATE)
  assert not make_model(env, long_on=False).visible(PEDAL_EMERGENCY)             # pedal longitudinal off: nothing to stop
  ap1 = make_model(env, fingerprint=AP1)
  assert not any(ap1.visible(k) for k in (PEDAL_EMERGENCY, RADAR_TEST, RADAR_CALIBRATE, HW_RESET))
  assert not make_model(env, fingerprint="TESLA_UNKNOWN").visible(HW_RESET)


# ---------------------------------------------------------------- Pedal Emergency Disable
def test_emergency_offroad_clears_calibration_and_writes_the_flag(env):
  m = make_model(env)
  calibrated()
  assert m.emergency_disable_pedal() is None
  assert not calib.is_pedal_calibrated()
  assert m.puts == [(LONG, True)] and m.changes == [PEDAL_EMERGENCY]


def test_emergency_while_driving_stops_pedal_now_and_stages_the_flag(env):
  env.drive.started = True
  env.drive.engaged = True                                                       # works while engaged and moving
  m = make_model(env)
  calibrated()
  assert calib.pedal_long_allowed(user_wants_long=True, detected=True)
  assert m.enabled(PEDAL_EMERGENCY)
  assert m.emergency_disable_pedal() is None
  assert not calib.pedal_long_allowed(user_wants_long=True, detected=True)       # live stop, no restart needed
  assert m.puts == []                                                            # the planner-read flag is NOT flipped mid-drive
  assert op.pending(LONG) is True                                                # staged: applied when the car is off
  assert m.changes == [PEDAL_EMERGENCY]                                          # reboot prompt


def test_emergency_is_not_behind_the_edit_gate(env):
  m = make_model(env, offroad=lambda: False)
  calibrated()
  assert m.enabled(PEDAL_EMERGENCY) and m.emergency_disable_pedal() is None
  assert not calib.is_pedal_calibrated()


def test_emergency_refused_when_the_row_is_not_for_this_car(env):
  m = make_model(env, long_on=False)
  calibrated()
  assert m.emergency_disable_pedal() is not None
  assert calib.is_pedal_calibrated() and m.puts == []                            # nothing happened


def test_emergency_flag_failure_still_clears_the_calibration_and_says_so(env):
  m = make_model(env)
  calibrated()
  m.params = SimpleNamespace(put_bool=lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
  problem = m.emergency_disable_pedal()
  assert problem == pv.PEDAL_EMERGENCY_FLAG_FAILED
  assert not calib.is_pedal_calibrated()


def test_emergency_cancels_a_running_calibration(env):
  m = make_model(env)
  calib.arm_calibration()
  assert preap_params.get_bool(K.PEDAL_CALIB_ARMED)
  m.emergency_disable_pedal()
  assert not preap_params.get_bool(K.PEDAL_CALIB_ARMED)


# ---------------------------------------------------------------- Reset Hardware Settings
def test_reset_row_is_locked_while_engaged_and_while_the_edit_gate_is_closed(env):
  m = make_model(env)
  assert m.enabled(HW_RESET)
  env.drive.engaged = True
  assert not m.enabled(HW_RESET)
  env.drive.engaged = False
  assert not make_model(env, offroad=lambda: False).enabled(HW_RESET)


def test_reset_writer_refuses_when_engaged_and_outside_the_table(env):
  m = make_model(env)
  preap_params.set_bool(RADAR, True)
  env.drive.engaged = True
  with pytest.raises(PermissionError):
    m.write_hw_default(RADAR, False)
  assert preap_params.get_bool(RADAR) is True
  env.drive.engaged = False
  with pytest.raises(KeyError):
    m.write_hw_default(K.AUTO_SPEED, False)


def test_reset_through_the_shared_helper_writes_only_its_keys(env):
  from openpilot.selfdrive.ui.bogpilot.step_defaults import reset_section
  m = make_model(env)
  calibrated()
  preap_params.set_bool(RADAR, True)
  preap_params.set_float(K.RADAR_OFFSET, -0.3)
  preap_params.set_bool(K.AUTO_SPEED, True)
  preap_params.set_bool(K.PEDAL_CALIB_ARMED, True)
  written = reset_section(m.hw_reset_defaults, m.write_hw_default)
  m.finish_hw_reset()
  assert written == list(hw_tools.HW_RESET_KEYS)
  assert not calib.is_pedal_calibrated() and not preap_params.get_bool(RADAR) and preap_params.radar_offset_m() == 0.0
  assert not preap_params.get_bool(K.PEDAL_CALIB_ARMED)
  assert preap_params.get_bool(K.AUTO_SPEED)                                         # not in the NAP scope
  assert m.changes == [HW_RESET] and m.puts == []                                    # Disable Pedal Longitudinal untouched


def test_reset_confirmation_text_names_the_scope_and_would_show_the_red_slider(env):
  from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import dialogs
  assert "reset" in pv.HW_RESET_CONFIRM.lower()
  assert pv.HW_RESET_CONFIRM.isascii()
  for scope in ("pedal calibration", "pedal CAN bus", "radar settings", "auto-detected AP1 retrofit stalk"):
    assert scope in pv.HW_RESET_CONFIRM
  assert dialogs._destructive(pv.HW_RESET_CONFIRM, "Reset")
  assert dialogs._destructive(pv.PEDAL_EMERGENCY_QUESTION, "Disable")               # "clear": red slide-to-confirm on the comma 4


# ---------------------------------------------------------------- radar screens: gate
def test_blocked_reason_parked_only():
  b = rt.blocked_reason
  assert b(False, True, False, False) == "Turn on Bosch Radar first."
  assert b(True, True, True, False) == "Disengage first."
  assert "car on" in b(True, False, False, False)
  assert "Park" in b(True, True, False, True)
  assert b(True, True, False, False) == ""


def test_model_radar_screen_blocked_uses_park_and_engaged(env):
  m = make_model(env)
  assert m.radar_screen_blocked(True, False) == "Turn on Bosch Radar first."
  preap_params.set_bool(RADAR, True)
  assert m.radar_screen_blocked(False, False) and m.radar_screen_blocked(True, True) == "Disengage first."
  env.drive.started = True                                                           # moving: not parked
  assert "Park" in m.radar_screen_blocked(True, False)
  env.drive.parked = True
  assert m.radar_screen_blocked(True, False) is None


# ---------------------------------------------------------------- radar screens: decoding
def cycle(points, t, hw=0, dirty=0, alert=None, prob=96.875):
  """One full radar cycle at CAN time t: SGU, every slot (the given tracked), 0x501, ending on RadarPoint31_B (the trigger)."""
  msgs = [PACKER.make_can_msg("TeslaRadarSguInfo", 1, {"RADC_HWFail": hw, "RADC_SensorDirty": dirty}),
          PACKER.make_can_msg("TeslaRadarAlertMatrix", 1, alert or {})]
  for i in range(32):
    if i < len(points):
      d, y, v = points[i]
      a = {"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": d, "LatDist": y, "LongSpeed": v, "ProbExist": prob}
    else:
      a = {"Tracked": 0, "Index": 1}
    msgs += [PACKER.make_can_msg(f"RadarPoint{i}_A", 1, a), PACKER.make_can_msg(f"RadarPoint{i}_B", 1, {"Index2": 1})]
  return [(int(t * 1e9), msgs)]


def test_reader_decodes_points_sorted_by_distance():
  r = rt.RawRadarReader()
  v = r.update(cycle([(40.0, 1.0, -3.0), (10.0, -0.5, 0.0)], 1.0), 1.0)
  assert v.fresh and [round(t.d_rel) for t in v.tracks] == [10, 40]
  assert v.tracks[0].y_rel == pytest.approx(-0.5, abs=0.07) and v.tracks[1].v_rel == pytest.approx(-3.0, abs=0.07)
  assert rt.health_label(v) == "LIVE" and "2 tracked points" in rt.health_detail(v)


def test_reader_applies_offset_first_then_flip_like_radar_interface():
  base = rt.RawRadarReader().update(cycle([(10.0, 1.0, 0.0)], 1.0), 1.0).tracks[0].y_rel
  off = rt.RawRadarReader(offset_m=0.25).update(cycle([(10.0, 1.0, 0.0)], 1.0), 1.0).tracks[0].y_rel
  flip = rt.RawRadarReader(flip=True).update(cycle([(10.0, 1.0, 0.0)], 1.0), 1.0).tracks[0].y_rel
  both = rt.RawRadarReader(offset_m=0.25, flip=True).update(cycle([(10.0, 1.0, 0.0)], 1.0), 1.0).tracks[0].y_rel
  assert off == pytest.approx(base + 0.25) and flip == pytest.approx(-base) and both == pytest.approx(-(base + 0.25))


def test_reader_applies_the_bosch_point_filter():
  r = rt.RawRadarReader()
  assert r.update(cycle([(10.0, 0.0, 0.0)], 1.0, prob=20.0), 1.0).tracks == ()        # ProbExist < 50 %
  assert r.update(cycle([(0.0, 0.0, 0.0)], 2.0), 2.0).tracks == ()                    # LongDist 0: not a target


def test_reader_goes_stale_and_reports_no_radar():
  r = rt.RawRadarReader()
  assert not r.update([], 0.0).fresh and rt.health_label(r.update([], 0.0)) == "NO RADAR"      # never spoke
  r.update(cycle([(10.0, 0.0, 0.0)], 1.0), 1.0)
  assert r.update([], 1.3).fresh and r.update([], 1.3).tracks
  stale = r.update([], 1.0 + rt.FRESH_S + 0.1)
  assert not stale.fresh and stale.tracks == () and rt.health_label(stale) == "NO RADAR"


def test_reader_health_fault_reject_and_aligning():
  r = rt.RawRadarReader()
  assert rt.health_label(r.update(cycle([(10.0, 0, 0)], 1.0, hw=1), 1.0)) == "FAULT"
  v = r.update(cycle([(10.0, 0, 0)], 2.0, alert={"RADC_a037_vinValidity": 1}), 2.0)
  assert rt.health_label(v) == "REJECT" and v.alerts == ("vinValidity",) and "vinValidity" in rt.health_detail(v)
  v = r.update(cycle([(10.0, 0, 0)], 3.0, alert={"RADC_a005_adjustmentReq": 1}), 3.0)
  assert rt.health_label(v) == "ALIGNING" and v.adjusting == ("adjustmentReq",)
  assert rt.health_label(r.update(cycle([], 4.0), 4.0)) == "NO TRACKS"


def test_reader_survives_garbage():
  class Boom:
    vl = {}

    def update(self, _):
      raise RuntimeError("bad frame")
  assert rt.RawRadarReader(parser=Boom()).update([(1, [])], 1.0) == rt.RadarView()


# ---------------------------------------------------------------- radar screens: aiming maths
def tr(d, y, v=0.0, i=0):
  return rt.Track(i, d, y, v)


def fresh_view(*tracks):
  return rt.RadarView(tracks=tuple(tracks), fresh=True)


def test_aim_uses_the_nearest_target_in_the_window_and_the_median():
  est = rt.AimEstimator(samples=5)
  assert est.update(fresh_view(tr(1.0, 0.0), tr(30.0, 0.0))) is None               # outside 2.5-14.5 m
  assert est.update(fresh_view(tr(6.0, 0.30), tr(9.0, -2.0))) == pytest.approx(0.30)
  for y in (0.32, 0.28, 5.0, 0.31):                                                # one outlier cycle (a far track) does not move the median
    est.update(fresh_view(tr(6.0, y if y < 1 else 0.30)))
  assert est.reading() == pytest.approx(0.30, abs=0.02) and est.distance == pytest.approx(6.0)
  assert est.update(rt.RadarView()) is None and est.reading() is None               # stale radar clears it


def test_aim_ignores_targets_far_to_the_side():
  assert rt.AimEstimator().update(fresh_view(tr(8.0, rt.CANDIDATE_Y_MAX + 0.5))) is None
  assert rt.AimEstimator().update(fresh_view(tr(8.0, -rt.CANDIDATE_Y_MAX))) == pytest.approx(-rt.CANDIDATE_Y_MAX)


@pytest.mark.parametrize("reading,offset,flip,expected", [
  (0.35, 0.0, False, -0.35), (-0.20, 0.0, False, 0.20), (0.35, 0.10, False, -0.25),
  (0.35, 0.0, True, 0.35), (0.35, 0.10, True, 0.45), (0.0, 0.2, False, 0.2), (1.5, 0.0, False, None), (-1.2, 0.0, True, None)])
def test_suggested_offset_cancels_the_reading_with_and_without_flip(reading, offset, flip, expected):
  got = rt.suggested_offset(reading, offset, flip)
  assert got == (pytest.approx(expected) if expected is not None else None)


def test_suggested_offset_really_zeroes_the_reading_through_the_reader():
  for flip in (False, True):
    raw_y = 0.42
    cur = 0.1
    reading = rt.RawRadarReader(offset_m=cur, flip=flip).update(cycle([(8.0, raw_y, 0.0)], 1.0), 1.0).tracks[0].y_rel
    fix = rt.suggested_offset(reading, cur, flip)
    again = rt.RawRadarReader(offset_m=fix, flip=flip).update(cycle([(8.0, raw_y, 0.0)], 1.0), 1.0).tracks[0].y_rel
    assert abs(again) < 0.12                                      # within the CAN signal's own resolution


def test_side_and_signed_text_are_ascii():
  assert rt.side_text(0.354) == "0.35 m left" and rt.side_text(-0.2) == "0.20 m right" and rt.side_text(0.0) == "0.00 m"
  assert rt.signed_m(-0.35) == "-0.35 m" and rt.signed_m(0.0) == "0.00 m" and rt.signed_m(0.004) == "0.00 m"


# ---------------------------------------------------------------- radar screens: session
class FakeSource:
  def __init__(self, *views):
    self.views, self.opened, self.closed, self.i = list(views), 0, 0, 0

  def open(self):
    self.opened += 1

  def close(self):
    self.closed += 1

  def poll(self, now):
    v = self.views[min(self.i, len(self.views) - 1)]
    self.i += 1
    return v


def session(mode, *views, **gates):
  return rt.RadarToolSession(mode, FakeSource(*views), now=lambda: 0.0, **gates)


def test_test_screen_shows_tracks_and_health():
  s = session(rt.TEST, fresh_view(tr(10.0, 0.1, 1.0, 3), tr(50.0, -2.0)))
  st = s.tick()
  assert st.title == "Test Radar" and st.phase == "running" and st.health == "LIVE" and len(st.tracks) == 2
  assert st.plot["range"] == rt.RANGE_M and st.plot["box"] is None and st.reading is None


def test_calibrate_screen_reads_the_target_and_suggests_an_offset():
  s = session(rt.CALIBRATE, fresh_view(tr(7.0, 0.35)), offset_m=0.0, flip=False)
  st = s.tick()
  assert st.title == "Calibrate Radar" and st.aim_state == "off" and st.aim_line == "0.35 m left"
  assert "reads 0.35 m" in st.footer and "-0.35 m" in st.hint and st.plot["box"] == (rt.ALIGN_D_MIN, rt.ALIGN_D_MAX, rt.ALIGN_Y_MAX)


def test_calibrate_screen_on_target_has_no_hint_and_no_target_says_so():
  st = session(rt.CALIBRATE, fresh_view(tr(7.0, 0.04))).tick()
  assert st.aim_state == "on_target" and st.aim_line == "ON TARGET" and st.hint == ""
  st = session(rt.CALIBRATE, fresh_view(tr(40.0, 0.0))).tick()
  assert st.aim_state == "none" and st.aim_line == "No target" and "straight ahead" in st.footer
  st = session(rt.CALIBRATE, rt.RadarView()).tick()
  assert st.aim_line == "No target" and "No radar frames" in st.footer


def test_calibrate_hint_when_the_fix_is_out_of_range():
  st = session(rt.CALIBRATE, fresh_view(tr(7.0, 1.6)), offset_m=0.0).tick()
  assert "Re-aim the radar" in st.hint


@pytest.mark.parametrize("gate,reason", [({"engaged": lambda: True}, "Disengage"), ({"moving": lambda: True}, "Park"),
                                         ({"started": lambda: False}, "car on"), ({"radar_on": lambda: False}, "Bosch Radar")])
def test_session_stops_when_a_gate_closes_and_stays_stopped(gate, reason):
  s = session(rt.TEST, fresh_view(tr(10.0, 0.0)), **gate)
  st = s.tick()
  assert st.phase == "stopped" and st.health == "STOPPED" and reason in st.footer
  assert s.source.i == 0                                                            # the radar stream is not read once stopped


def test_session_keeps_the_last_picture_after_it_stops_and_never_restarts():
  moving = {"v": False}
  s = session(rt.CALIBRATE, fresh_view(tr(7.0, 0.35)), moving=lambda: moving["v"])
  assert s.tick().phase == "running"
  moving["v"] = True
  stopped = s.tick()
  assert stopped.phase == "stopped" and stopped.aim_line == "0.35 m left" and stopped.tracks
  moving["v"] = False
  assert s.tick().phase == "stopped"                                                 # parking again does not silently resume


def test_session_opens_and_closes_its_source_once():
  s = session(rt.TEST, fresh_view())
  s.begin()
  s.begin()
  s.close()
  assert (s.source.opened, s.source.closed) == (1, 1)


def test_screens_are_display_only_no_params_written(env):
  before = sorted(p.name for p in (env.root).rglob("*") if p.is_file())
  s = session(rt.CALIBRATE, fresh_view(tr(7.0, 0.35)))
  for _ in range(5):
    s.tick()
  assert sorted(p.name for p in (env.root).rglob("*") if p.is_file()) == before


def test_module_has_no_writers():
  src = Path(rt.__file__).read_text()
  for needle in ("set_bool(", "set_int(", "set_float(", "set_str(", "put_bool", "sendcan", "_write_text"):
    assert needle not in src, needle
  assert not any(math.isnan(t.d_rel) for t in rt.RadarView().tracks)
