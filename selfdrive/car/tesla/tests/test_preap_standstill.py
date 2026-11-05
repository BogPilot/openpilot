"""Pre-AP standstill: NAP DI STANDSTILL only (not vEgo), cruiseState.standstill False."""
from pathlib import Path

import openpilot.selfdrive.car.tesla.carstate as carstate_mod


def test_preap_carstate_uses_di_standstill_not_vego():
  src = Path(carstate_mod.__file__).read_text()
  assert 'CAR.TESLA_PREAP_MODELS' in src
  assert 'ret.standstill = (cruise_state == "STANDSTILL")' in src
  # Still has the default vEgo path for AP1 / other platforms.
  assert 'ret.standstill = (ret.vEgo < 0.1)' in src


def test_preap_cruise_state_standstill_stays_false():
  src = Path(carstate_mod.__file__).read_text()
  assert 'ret.cruiseState.standstill = False' in src
