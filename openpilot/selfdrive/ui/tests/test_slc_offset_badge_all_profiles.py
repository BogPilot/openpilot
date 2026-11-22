"""ShowSLCOffset (green offset badge on the speed limit sign): on by default for every Tesla profile, none writes 0,
saved values are kept, and the badge follows the setting."""
import pytest

from openpilot.common import bogpilot_ap1_profile as prof
from openpilot.common.bogpilot_ap1_profile import (
  AP1_CAR_MODEL, AP1_PARAM_PROFILE, AP1_SLC_KEYS, LEGACY_SLC_PROFILE, LEGACY_TESLA_LONG_PROFILE, _profile_for_units,
  ap1_slc_profile_for_units, apply_ap1_defaults_once, apply_legacy_slc_defaults_once, legacy_slc_profile_for_units,
)
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.ui.tests.test_slc_legacy_profile import AP1X, PREAP, fresh

KEY = "ShowSLCOffset"
TESLA_CARS = (AP1_CAR_MODEL, AP1X, PREAP)


def test_registry_default_is_on():
  assert BOGPILOT_PARAMS[KEY][2] == "1"


def test_no_profile_table_writes_off():
  for name in dir(prof):
    table = getattr(prof, name)
    if isinstance(table, dict) and KEY in table:
      assert str(table[KEY]) == "1", name
  assert AP1_PARAM_PROFILE[KEY] == "1" and KEY in AP1_SLC_KEYS
  assert KEY not in LEGACY_SLC_PROFILE
  for ack_profile in LEGACY_TESLA_LONG_PROFILE.values():
    assert ack_profile.get(KEY, "1") == "1"


@pytest.mark.parametrize("metric", [False, True])
@pytest.mark.parametrize("car", TESLA_CARS)
def test_every_tesla_profile_leaves_it_on_on_a_fresh_install(tmp_path, car, metric):
  p = fresh(car, metric)
  if car == AP1_CAR_MODEL:
    assert _profile_for_units(p)[KEY] == "1"
    apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  else:
    assert legacy_slc_profile_for_units(p).get(KEY, "1") == "1"
    apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert p.get(KEY) == "1"


@pytest.mark.parametrize("car", TESLA_CARS)
def test_saved_off_is_kept(tmp_path, car):
  p = fresh(car, False)
  p.put(KEY, "0")
  if car == AP1_CAR_MODEL:
    apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  else:
    apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert p.get(KEY) == "0"
