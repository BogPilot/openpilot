"""Pre-AP standstill: NAP DI STANDSTILL only (not vEgo), cruiseState.standstill False."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_preap_carstate_uses_di_standstill_not_vego():
  src = (ROOT / "selfdrive/car/tesla/carstate.py").read_text()
  assert "CAR.TESLA_PREAP_MODELS" in src
  assert 'ret.standstill = (cruise_state == "STANDSTILL")' in src
  # Still has the default vEgo path for AP1 / other platforms.
  assert "ret.standstill = (ret.vEgo < 0.1)" in src


def test_preap_cruise_state_standstill_stays_false():
  src = (ROOT / "selfdrive/car/tesla/carstate.py").read_text()
  assert "ret.cruiseState.standstill = False" in src
