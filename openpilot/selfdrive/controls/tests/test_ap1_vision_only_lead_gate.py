"""AP1 and Pre-AP vision-only lead gate (docs/tesla/DIVERGENCES_ap1_vision_only_lead_gate.md): real RadarD, fake SubMaster.

Rule: threshold 35, and a camera-only lead (no radar track matched) strictly beyond 50 m needs prob >= 0.6, unless ego is
closing on it at 5 m/s or more. Radar-matched leads, near leads and every other platform are untouched.
"""
from openpilot.cereal import log
from openpilot.selfdrive.controls.radard import (RadarD, VISION_ONLY_CLOSING_MS, VISION_ONLY_FAR_M, VISION_ONLY_FAR_PROB,
                                                 RADAR_TO_CAMERA, vision_only_gate_platform, vision_only_lead_blocked)
from openpilot.selfdrive.controls.tests.test_preap_radar_filters_radard import drive

V_EGO = 20.0


def gated(**kw):
  return RadarD(lead_threshold=.35, vision_only_gate=True, **kw)


def lead_present(rd, d_rel, prob, v_rel=0.0, n_points=0, seconds=1.0):
  out = drive(rd, lambda t: V_EGO, d_rel, prob, seconds, v_rel=v_rel, n_points=n_points)
  return all(present for _, present, _ in out), any(present for _, present, _ in out)


def lead_msg(x_cam, v_lead):
  m = log.ModelDataV2.LeadDataV3.new_message()
  m.x, m.v = [x_cam], [v_lead]
  return m


def test_constants_are_the_chosen_rule():
  assert (VISION_ONLY_FAR_M, VISION_ONLY_FAR_PROB, VISION_ONLY_CLOSING_MS) == (50., .6, 5.)


def test_far_low_prob_vision_lead_is_blocked():
  assert lead_present(gated(), 60.0, 0.5) == (False, False)
  assert lead_present(gated(), 60.0, 0.36) == (False, False)


def test_stock_and_non_ap1_keep_the_far_low_prob_lead():
  assert RadarD(lead_threshold=.35).vision_only_gate is False
  assert lead_present(RadarD(lead_threshold=.35), 60.0, 0.5) == (True, True)


def test_prob_boundary_is_at_least_0_6():
  assert lead_present(gated(), 60.0, 0.6)[0]
  assert lead_present(gated(), 60.0, 0.61)[0]
  assert lead_present(gated(), 60.0, 0.59) == (False, False)


def test_distance_boundary_is_strictly_beyond_50_m():
  assert lead_present(gated(), 49.0, 0.5)[0]
  assert lead_present(gated(), 50.5, 0.5) == (False, False)
  # at exactly 50 m the lead is kept (the rule says "beyond"); checked on the pure function with exact floats
  assert not vision_only_lead_blocked(V_EGO, lead_msg(RADAR_TO_CAMERA + 49.999, V_EGO), 0.5)
  assert vision_only_lead_blocked(V_EGO, lead_msg(RADAR_TO_CAMERA + 50.001, V_EGO), 0.5)


def test_closing_speed_exemption_at_5_m_s():
  assert lead_present(gated(), 60.0, 0.5, v_rel=-5.0)[0]            # closing 5.0 m/s: exempt
  assert lead_present(gated(), 60.0, 0.5, v_rel=-8.0)[0]
  assert lead_present(gated(), 60.0, 0.5, v_rel=-4.9) == (False, False)   # closing 4.9: still blocked
  assert lead_present(gated(), 60.0, 0.5, v_rel=+3.0) == (False, False)   # pulling away: blocked


def test_near_vision_lead_is_never_blocked():
  assert lead_present(gated(), 30.0, 0.4)[0]
  assert lead_present(gated(), 50.0 - 1.0, 0.36)[0]


def test_below_the_35_threshold_is_not_a_lead_either_way():
  assert lead_present(gated(), 30.0, 0.30) == (False, False)


def test_radar_matched_far_lead_is_untouched():
  out = drive(gated(), lambda t: V_EGO, 60.0, 0.5, 1.0, n_points=1)
  assert all(present and radar for _, present, radar in out)


def test_second_lead_slot_uses_the_same_gate():
  rd = gated()
  drive(rd, lambda t: V_EGO, 60.0, 0.5, 1.0, n_points=0)
  assert not rd.radar_state.leadOne.present and not rd.radar_state.leadTwo.present
  rd = gated()
  drive(rd, lambda t: V_EGO, 60.0, 0.5, 1.0, v_rel=-6.0, n_points=0)
  assert rd.radar_state.leadOne.present and rd.radar_state.leadTwo.present


def test_empty_lead_fields_do_not_raise():
  m = log.ModelDataV2.LeadDataV3.new_message()
  assert not vision_only_lead_blocked(V_EGO, m, 0.5)


def test_platform_selection_is_ap1_model_s_and_preap_model_s_only():
  assert vision_only_gate_platform("TESLA_AP1_MODELS")
  assert vision_only_gate_platform("TESLA_PREAP_MODELS")
  for other in ("TESLA_AP1_MODELX", "TESLA_AP2_MODELS", "TESLA_MODEL_3", "TOYOTA_COROLLA", "MOCK", "", None):
    assert not vision_only_gate_platform(other)


def preap_gated(**kw):
  return RadarD(lead_threshold=.35, vision_only_gate=True, preap=True, **kw)


def test_preap_far_low_prob_vision_lead_is_blocked():
  assert lead_present(preap_gated(), 60.0, 0.5) == (False, False)
  assert lead_present(preap_gated(), 60.0, 0.36) == (False, False)
  assert lead_present(RadarD(lead_threshold=.35, preap=True), 60.0, 0.5) == (True, True)   # gate off: stock


def test_preap_boundaries_and_exemption_match_ap1():
  assert lead_present(preap_gated(), 60.0, 0.6)[0]
  assert lead_present(preap_gated(), 60.0, 0.59) == (False, False)
  assert lead_present(preap_gated(), 49.0, 0.5)[0]
  assert lead_present(preap_gated(), 60.0, 0.5, v_rel=-5.0)[0]
  assert lead_present(preap_gated(), 60.0, 0.5, v_rel=-4.9) == (False, False)


def test_preap_radar_matched_far_lead_is_untouched():
  out = drive(preap_gated(), lambda t: V_EGO, 60.0, 0.5, 1.0, n_points=1)
  assert all(present and radar for _, present, radar in out)


def test_preap_stuck_track_camera_fallback_near_is_untouched():
  # Pre-AP stuck-track fallback (radar track dropped, camera lead kept) inside 50 m must still be a lead with the gate on
  rd = preap_gated()
  v = lambda t: 5.0 + 1.0 * t
  out = drive(rd, v, 17.25, 0.9, 10.0)
  assert all(present and not radar for t, present, radar in out if t > 5.5)
