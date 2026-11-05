"""Pre-AP Always On Lateral: lat without enabled, lat held at stop."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_preap_carcontroller_aol_no_enabled_gate():
  src = (ROOT / "selfdrive/car/tesla/preap/carcontroller.py").read_text()
  assert "lat_active = bool(CC.latActive) and hands < 3" in src
  assert "lat_active = bool(CC.latActive) and bool(CC.enabled)" not in src


def test_controlsd_preap_holds_lat_at_standstill():
  src = (ROOT / "selfdrive/controls/controlsd.py").read_text()
  assert "preap_hold_lat" in src
  assert "standstill_blocks_lat" in src
  assert "TESLA_PREAP_MODELS" in src
