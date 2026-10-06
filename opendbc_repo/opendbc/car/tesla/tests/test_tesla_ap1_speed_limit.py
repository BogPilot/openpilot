"""AP1 CAN → starpilotCarState.dashboardSpeedLimit (m/s).

Pure decode tests (CarState wiring is in test_tesla_ap1_milestone2.py).
Stock fused frames come from fixtures (real payloads, no PII).

Not a product, no warranty, driver remains responsible, comply with local law.
"""

import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla.ap1_speed_limit import (
  dashboard_speed_limit_ms,
  fused_speed_limit_ms,
  mpp_speed_limit_ms,
  ui_map_speed_limit_ms,
  units_are_metric,
)
from opendbc.car.tesla.tests.fixtures.ap1_speed_limit_seq import (
  FUSED_NONE_PHYS,
  FUSED_TRANSITIONS,
  FUSED_UNKNOWN_PHYS,
  STOCK_FUSED_FRAMES,
  ZONE_SAMPLES,
)

MPH = CV.MPH_TO_MS


def test_units_default_mph():
  assert units_are_metric(0) is False
  assert units_are_metric(1) is True
  assert units_are_metric(None) is False
  assert units_are_metric("x") is False


def test_fused_sna_and_none_are_zero():
  assert fused_speed_limit_ms(None, False) == 0.0
  assert fused_speed_limit_ms(FUSED_UNKNOWN_PHYS, False) == 0.0
  assert fused_speed_limit_ms(FUSED_NONE_PHYS, False) == 0.0
  assert fused_speed_limit_ms(150.0, False) == 0.0
  assert fused_speed_limit_ms(155.0, True) == 0.0


def test_fused_zones_to_ms_mph():
  for mph in (5, 25, 30, 35, 40, 45, 70):
    assert fused_speed_limit_ms(float(mph), False) == pytest.approx(mph * MPH)


def test_ui_map_enum_and_sna():
  assert ui_map_speed_limit_ms(0, False) == 0.0
  assert ui_map_speed_limit_ms(30, False) == 0.0  # UNLIMITED
  assert ui_map_speed_limit_ms(31, False) == 0.0  # SNA
  assert ui_map_speed_limit_ms(None, False) == 0.0
  assert ui_map_speed_limit_ms(7, False) == pytest.approx(30 * MPH)   # LEQ_30
  assert ui_map_speed_limit_ms(10, False) == pytest.approx(45 * MPH)  # LEQ_45
  assert ui_map_speed_limit_ms(6, False) == pytest.approx(25 * MPH)


def test_mpp_zero_is_no_limit():
  assert mpp_speed_limit_ms(0, False) == 0.0
  assert mpp_speed_limit_ms(None, False) == 0.0
  assert mpp_speed_limit_ms(45.0, False) == pytest.approx(45 * MPH)


def test_priority_mobileye_then_ui_then_mpp():
  # Fused wins even when UI/mpp disagree
  assert dashboard_speed_limit_ms(45.0, 6, 25.0, 0) == pytest.approx(45 * MPH)
  # No fused → UI map enum
  assert dashboard_speed_limit_ms(0.0, 10, 25.0, 0) == pytest.approx(45 * MPH)
  assert dashboard_speed_limit_ms(None, 7, 55.0, 0) == pytest.approx(30 * MPH)
  # No fused, no UI → mpp
  assert dashboard_speed_limit_ms(0.0, 31, 40.0, 0) == pytest.approx(40 * MPH)
  # All empty
  assert dashboard_speed_limit_ms(0.0, 0, 0.0, 0) == 0.0
  assert dashboard_speed_limit_ms(155.0, 30, 0.0, 0) == 0.0


def test_zone_samples_from_logs():
  for fused, ui, mpp, units in ZONE_SAMPLES:
    got = dashboard_speed_limit_ms(fused, ui, mpp, units)
    assert got == pytest.approx(fused * MPH)
    # UI alone would match the same posted mph for these agreeing samples
    assert ui_map_speed_limit_ms(ui, False) == pytest.approx(fused * MPH)


def test_fused_down_transitions_from_logs():
  """Logged stock fused drops (45→35, 45→25, 40→35, …)."""
  downs = [(a, b) for a, b in FUSED_TRANSITIONS if a > b]
  assert (45.0, 35.0) in downs
  assert (45.0, 25.0) in downs
  assert (40.0, 35.0) in downs
  assert (35.0, 25.0) in downs
  for a, b in downs:
    before = dashboard_speed_limit_ms(a, None, None, 0)
    after = dashboard_speed_limit_ms(b, None, None, 0)
    assert before == pytest.approx(a * MPH)
    assert after == pytest.approx(b * MPH)
    assert after < before


def test_stock_frame_unpack_matches_fused_phys():
  """cluster.unpack on real src-2 payloads → DAS_fusedSpeedLimit physical."""
  from opendbc.car.tesla import ap1_cluster as c
  for fused_phys, hexdat in STOCK_FUSED_FRAMES:
    vals = c.unpack(c.AUTOPILOT_STATUS, bytes.fromhex(hexdat))
    assert vals["DAS_fusedSpeedLimit"] == pytest.approx(fused_phys)
    assert fused_speed_limit_ms(vals["DAS_fusedSpeedLimit"], False) == pytest.approx(fused_phys * MPH)

