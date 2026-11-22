"""AP1 lead side check (phantom brake Option C) in radard: real match_vision_to_track / get_lead / RadarD.

Default off. On: at 34 mph and up, a radar track more than 2.5 m (or 2x the camera's sideways std) from the camera lead
cannot be its match; the camera lead is used instead. Below 34 mph, and with the setting off, the match is stock.
"""
from openpilot.cereal import log
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.radard import KalmanParams, RadarD, RADAR_TO_CAMERA, Track, get_lead, match_vision_to_track

HWY = 25.0            # 56 mph
SLOW = 15.0           # 33.6 mph: below the 34 mph floor
KP = KalmanParams(DT_MDL)


def lead(x=60.0, y=0.0, v=HWY - 2.0, prob=0.9, y_std=0.5):
  m = log.ModelDataV2.LeadDataV3.new_message()
  m.prob = prob
  m.x, m.y, m.v, m.a = [x + RADAR_TO_CAMERA], [y], [v], [0.0]
  m.xStd, m.yStd, m.vStd = [2.0], [y_std], [1.0]
  return m


def track(tid, d, y_rel, v_lead, v_ego=HWY):
  t = Track(tid, v_lead, KP)
  t.update(d, y_rel, v_lead - v_ego, v_lead)
  return t


def tracks(*ts):
  return {t.identifier: t for t in ts}


def test_off_is_stock_and_default_off():
  assert RadarD().side_check is False and RadarD(lead_threshold=.35, vision_only_gate=True).side_check is False
  adj = track(1, 60.0, 3.5, HWY - 2.0)                                       # 3.5 m to the side of the camera lead
  assert match_vision_to_track(HWY, lead(), tracks(adj)) is adj
  assert match_vision_to_track(HWY, lead(), tracks(adj), side_check=False) is adj


def test_adjacent_track_rejected_at_highway_speed_camera_lead_used():
  adj = track(1, 60.0, 3.5, HWY - 2.0)
  assert match_vision_to_track(HWY, lead(), tracks(adj), side_check=True) is None
  out = get_lead(HWY, True, tracks(adj), lead(), HWY, 0.9, low_speed_override=False, lead_threshold=.35, vision_only_gate=True,
                 side_check=True)
  assert out['present'] and out['radar'] is False and out['radarTrackId'] == -1
  assert abs(out['dRel'] - 60.0) < 1e-6


def test_below_34_mph_unchanged():
  adj = track(1, 60.0, 3.5, SLOW - 2.0, v_ego=SLOW)
  assert match_vision_to_track(SLOW, lead(v=SLOW - 2.0), tracks(adj), side_check=True) is adj


def test_limit_2_5_m_inclusive_and_widened_by_camera_std():
  ok = track(1, 60.0, 2.5, HWY - 2.0)
  assert match_vision_to_track(HWY, lead(), tracks(ok), side_check=True) is ok
  far = track(2, 60.0, 2.6, HWY - 2.0)
  assert match_vision_to_track(HWY, lead(), tracks(far), side_check=True) is None
  assert match_vision_to_track(HWY, lead(y_std=1.5), tracks(far), side_check=True) is far     # limit 3.0 m


def test_sign_convention_uses_camera_lead_position():
  # camera lead 3 m to the right (model y = +3 right-positive => radar yRel -3); a track at yRel -3 is the same car
  same = track(1, 60.0, -3.0, HWY - 2.0)
  assert match_vision_to_track(HWY, lead(y=3.0), tracks(same), side_check=True) is same
  assert match_vision_to_track(HWY, lead(y=-3.0), tracks(same), side_check=True) is None


def test_in_lane_track_preferred_over_adjacent():
  adj = track(1, 60.0, 3.0, HWY - 2.0)        # the stock match (better distance and speed fit)
  inl = track(2, 66.0, 0.2, HWY - 4.0)
  m = lead(x=60.0, y=-0.4, v=HWY - 2.0, y_std=1.0)
  assert match_vision_to_track(HWY, m, tracks(adj, inl)) is adj
  assert match_vision_to_track(HWY, m, tracks(adj, inl), side_check=True) is inl


def test_low_speed_override_untouched():
  close = track(3, 10.0, 0.0, 0.0, v_ego=2.0)
  out = get_lead(2.0, True, tracks(close), lead(x=10.0, v=0.0), 2.0, 0.9, low_speed_override=True, lead_threshold=.35,
                 side_check=True)
  assert out['present'] and out['radar'] and out['radarTrackId'] == 3
