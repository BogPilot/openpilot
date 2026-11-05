"""Pre-AP chassis parser freqs relaxed under GTW load."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_preap_chassis_freqs_halved_in_source():
  src = (ROOT / "selfdrive/car/tesla/carstate.py").read_text()
  assert "50 if preap else 100" in src
  assert "25 if preap else 50" in src
  assert "5 if preap else 10" in src
