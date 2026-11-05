"""Pre-AP chassis parser freqs relaxed under GTW load."""
from pathlib import Path

import openpilot.selfdrive.car.tesla.carstate as carstate_mod


def test_preap_chassis_freqs_halved_in_source():
  src = Path(carstate_mod.__file__).read_text()
  assert '50 if preap else 100' in src
  assert '25 if preap else 50' in src
  assert '5 if preap else 10' in src
