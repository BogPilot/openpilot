"""Pre-AP: no radar-only low-speed lead (docs/tesla/DIVERGENCES_preap_radar_filters.md (3)); AP1 keeps the override."""
from openpilot.selfdrive.controls.radard import RadarD
from openpilot.selfdrive.controls.tests.test_preap_radar_filters_radard import drive


def test_low_speed_radar_only_lead_is_used_off_preap_only():
  slow = lambda t: 2.0                                                # below V_EGO_STATIONARY, track 10 m ahead, no camera lead
  stock = drive(RadarD(), slow, 10.0, 0.0, 1.0)
  preap = drive(RadarD(preap=True), slow, 10.0, 0.0, 1.0)
  assert all(present and radar for _, present, radar in stock)
  assert not any(present for _, present, _ in preap)


def test_preap_still_uses_a_camera_confirmed_radar_lead_at_low_speed():
  out = drive(RadarD(preap=True), lambda t: 2.0, 10.0, 0.9, 1.0, v_rel=-0.5)
  assert all(present and radar for _, present, radar in out)


def test_flag_values():
  assert RadarD().low_speed_override and not RadarD(preap=True).low_speed_override
