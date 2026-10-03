from openpilot.selfdrive.car.tesla.platform import classify_tesla_platform, long_control_allowed
from openpilot.selfdrive.car.tesla.stalk_follow import map_stalk_follow, parse_stalk_raw
from openpilot.selfdrive.car.tesla.tests.fixtures.ap1_parked_addrs import (
  ADDR_0X2B9_CAN_COUNTS,
  ADDR_0X2B9_PRESENT,
  ADDR_0X2BF_COUNT,
  CONTROLS_WENT_ACTIVE,
  DTR_DIST_RQ_RAW,
  OBSERVED_BUSES,
  ROUTE_LABEL,
  SOURCE_BRANCH,
  SOURCE_CAR,
  SOURCE_COMMIT,
  SOURCE_DASHCAM_ONLY,
  SOURCE_FINGERPRINT,
  VEGO_NEAR_ZERO,
  dual_panda_powertrain_seen,
)
from openpilot.selfdrive.car.tesla.values import CAR, TeslaPlatform

# Profiles already committed by stalk_follow.map_stalk_follow for these raw values.
EXPECTED = (
  (0, "traffic"),
  (33, "closer_than_aggressive"),
  (66, "aggressive"),
  (100, "between_aggressive_and_standard"),
  (133, "standard"),
  (166, "between_standard_and_relaxed"),
  (200, "relaxed"),
)


def test_route_label_has_no_dongle_and_recording_is_frog_ap1():
  assert ROUTE_LABEL == "ap1-parked-2026-10-03"
  assert "--" not in ROUTE_LABEL
  assert SOURCE_BRANCH == "frog_ap1"
  assert SOURCE_COMMIT == "73a16cdd"
  assert SOURCE_CAR == "TESLA_AP1_MODELS"
  assert SOURCE_FINGERPRINT == "fixed"
  # That recording only. This assertion does not change this tree's dashcamOnly.
  assert SOURCE_DASHCAM_ONLY is False
  assert CONTROLS_WENT_ACTIVE is False
  assert VEGO_NEAR_ZERO is True


def test_seven_observed_raw_values_map_to_stalk_profiles():
  assert DTR_DIST_RQ_RAW == tuple(raw for raw, _profile in EXPECTED)
  for raw, profile in EXPECTED:
    mapped = map_stalk_follow(raw)
    parsed = parse_stalk_raw(raw, None)
    parsed_float = parse_stalk_raw(float(raw), None)
    assert mapped.ready and mapped.valid
    assert mapped.profile == profile
    assert mapped.raw == raw
    assert parsed.profile == mapped.profile
    assert parsed.detent == mapped.detent
    assert parsed.follow_s == mapped.follow_s
    assert parsed.traffic is mapped.traffic
    assert parsed_float.profile == mapped.profile


def test_absent_0x2bf_is_not_the_dual_panda_powertrain_fingerprint():
  assert OBSERVED_BUSES == (0, 1, 2)
  assert ADDR_0X2BF_COUNT == 0
  assert dual_panda_powertrain_seen(ADDR_0X2BF_COUNT) is False
  assert dual_panda_powertrain_seen(0) is False
  for bus in OBSERVED_BUSES:
    assert ADDR_0X2B9_PRESENT[bus] is True
    assert ADDR_0X2B9_CAN_COUNTS[bus] > 0
  # A CAN address dict is not how ap1_s is recognized, with or without 0x2bf.
  capture = {bus: {0x2B9: ADDR_0X2B9_CAN_COUNTS[bus]} for bus in OBSERVED_BUSES}
  assert 0x2BF not in capture.get(6, {})
  assert classify_tesla_platform(capture) is None
  assert classify_tesla_platform({6: {0x2BF: 1}}) is None
  platform = classify_tesla_platform(CAR.TESLA_AP1_MODELS)
  assert platform == TeslaPlatform.ap1_s
  assert long_control_allowed(platform) is False
