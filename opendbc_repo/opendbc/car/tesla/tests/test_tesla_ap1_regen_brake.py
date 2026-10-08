"""AP1 regen-sized comfort braking toggle (ap1_regen_brake.py). Ported from BogPilot test_ap1_regen_brake.py.

The longitudinal MPC side (runtime x_obstacle shift, consistency vs stock) is tested in StarPilot's
selfdrive/controls/lib/longitudinal_mpc_lib/tests/test_ap1_comfort_brake.py.
"""

import pytest

import opendbc.car.tesla.ap1_regen_brake as rb
from opendbc.car.tesla.ap1_regen_brake import (
  AP1_REGEN_COMFORT_BRAKE,
  STOCK_COMFORT_BRAKE,
  ap1_comfort_brake,
  regen_comfort_brake_enabled,
  set_regen_comfort_brake,
)

AP1 = "TESLA_MODEL_S_HW1"


@pytest.fixture
def toggle_path(tmp_path, monkeypatch):
  path = tmp_path / "RegenComfortBrake"
  monkeypatch.setattr(rb, "_regen_comfort_path", path)
  return path


def test_constants():
  assert STOCK_COMFORT_BRAKE == 2.5
  assert AP1_REGEN_COMFORT_BRAKE < STOCK_COMFORT_BRAKE
  # Route 0000002a: regen alone topped out near 1.0 m/s^2 at 30-35 mph before friction joined.
  assert AP1_REGEN_COMFORT_BRAKE == 1.0


def test_regen_toggle_default_on_for_ap1_only(toggle_path):
  assert regen_comfort_brake_enabled(AP1) is True
  assert regen_comfort_brake_enabled("TESLA_AP1_MODELS") is True
  assert ap1_comfort_brake(AP1) == AP1_REGEN_COMFORT_BRAKE
  for fp in ("TESLA_MODEL_S_PREAP", "TESLA_MODEL_3", "HONDA_CIVIC", "", None):
    assert regen_comfort_brake_enabled(fp) is False, fp
    assert ap1_comfort_brake(fp) == STOCK_COMFORT_BRAKE, fp


def test_regen_toggle_explicit_off_on(toggle_path):
  set_regen_comfort_brake(False, path=toggle_path)
  assert ap1_comfort_brake(AP1) == STOCK_COMFORT_BRAKE
  set_regen_comfort_brake(True, path=toggle_path)
  assert ap1_comfort_brake(AP1) == AP1_REGEN_COMFORT_BRAKE


@pytest.mark.parametrize("text,want", [("", True), ("1", True), ("on", True), ("true", True),
                                       ("0", False), ("off", False), ("false", False), ("junk", True)])
def test_regen_toggle_file_values(toggle_path, text, want):
  toggle_path.write_text(text)
  assert regen_comfort_brake_enabled(AP1) is want
  assert regen_comfort_brake_enabled(AP1, stored=text) is want
