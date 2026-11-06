"""Safer driver-press pedal calibration (no ALLOUTPUT) — host-safe unit tests."""
from __future__ import annotations

from pathlib import Path

from openpilot.selfdrive.car.tesla.preap.calib import (
  FACTOR_MAX,
  FACTOR_MIN,
  MIN_SPAN,
  STATUS_CALIBRATING,
  STATUS_FAILED,
  STATUS_NEEDS_CALIBRATION,
  STATUS_READY,
  compute_calibration,
  pedal_status,
  validate_calibration,
)

ROOT = Path(__file__).resolve().parents[4]


def test_rejects_known_bad_small_span():
  # Bad Ready was raw 0.762→6.451 (span 5.69, factor ≈17.577).
  result, reason = validate_calibration(0.762, 6.451)
  assert result is None
  assert "span" in reason
  assert MIN_SPAN == 10.0


def test_compute_calibration_does_not_ok_small_span():
  bad = compute_calibration(0.762, 6.451)
  assert bad.get("ok") == 0.0
  assert "span" in str(bad.get("reason", ""))


def test_accepts_sane_real_press_factor():
  # Real press ~0.94 factor ⇒ span ≈ 100/0.94 ≈ 106.4
  coast, pressed = 0.8, 0.8 + (100.0 / 0.94)
  result, reason = validate_calibration(coast, pressed)
  assert reason == "ok" and result is not None
  assert result["ok"] == 1.0
  assert FACTOR_MIN <= result["pedal_calib_factor"] <= FACTOR_MAX
  assert abs(result["pedal_calib_factor"] - 0.94) < 0.02
  ok = compute_calibration(coast, pressed)
  assert ok.get("ok") == 1.0


def test_rejects_insane_factor_even_if_span_clears_min():
  # span 12 ≥ 10 but factor 100/12 ≈ 8.33 > FACTOR_MAX
  result, reason = validate_calibration(0.0, 12.0)
  assert result is None
  assert "factor" in reason


def test_pedal_status_calibrating_and_failed_without_ready():
  assert pedal_status(detected=True, calibrated=False, armed=True, message="") == STATUS_CALIBRATING
  assert pedal_status(detected=True, calibrated=False, armed=False, message="span 5.69 below 10") == STATUS_FAILED
  assert pedal_status(detected=True, calibrated=False, armed=False, message="") == STATUS_NEEDS_CALIBRATION
  assert pedal_status(detected=True, calibrated=True, armed=False, message="") == STATUS_READY


def test_no_alloutput_in_calib_or_carcontroller():
  for rel in (
    "selfdrive/car/tesla/preap/calib.py",
    "selfdrive/car/tesla/preap/carcontroller.py",
    "selfdrive/car/tesla/preap/params.py",
  ):
    src = (ROOT / rel).read_text()
    assert "set_safety_mode" not in src
    # Docstrings may mention the ban; forbid callable/unlock usage only.
    assert "mode = 17" not in src and "mode=17" not in src


def test_carcontroller_requires_di_gas_with_interceptor():
  src = (ROOT / "selfdrive/car/tesla/preap/carcontroller.py").read_text()
  assert "PRESS_DI_MIN" in src and "COAST_DI_MAX" in src
  assert "fail_calibration" in src
  assert "PRESS_RAW_DELTA" in src
  # Old twitch threshold must not remain as the sole press gate.
  assert "+ 5.0" not in src
