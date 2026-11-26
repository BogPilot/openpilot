"""Adaptive Accel Near Lead row: Gas / Brake page (3X and comma 4 share the model), legacy Teslas only, offroad-only like the page,
default OFF, help text present, nothing written by showing it."""
from types import SimpleNamespace as NS
import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.ui.bogpilot import onroad_policy, toggle_help
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
from openpilot.selfdrive.ui.tests.test_gas_brake_profiles_default_on import Store

KEY = "AdaptiveAccelLead"
LEGACY = ["TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"]


def controller(platform, can_edit=lambda: True, **values):
  store = Store(LongitudinalTune="1", **values)
  cp = NS(carFingerprint=platform, openpilotLongitudinalControl=True)
  return SettingsController("profiles", store, cp=cp, can_edit=can_edit), store


def test_key_is_a_bool_off_by_default():
  kind, default = BOGPILOT_PARAMS[KEY][1], BOGPILOT_PARAMS[KEY][2]
  assert (kind, default) == ("BOOL", "0")


@pytest.mark.parametrize("platform", LEGACY)
def test_row_shows_on_legacy_teslas_after_the_profiles(platform):
  c, store = controller(platform)
  keys = [r.key for r in c.rows()]
  assert keys[keys.index("HumanAcceleration") + 1] == KEY and store.writes == []
  assert not store.get_bool(KEY)


@pytest.mark.parametrize("cp", [None, NS(openpilotLongitudinalControl=True),
                                NS(carFingerprint="TOYOTA_COROLLA_TSS2", openpilotLongitudinalControl=True),
                                NS(carFingerprint="HONDA_CIVIC", openpilotLongitudinalControl=True)])
def test_no_inert_row_on_other_cars_or_before_the_car_is_known(cp):
  store = Store(LongitudinalTune="1", Phase3ProfilesEnabled="1")
  c = SettingsController("profiles", store, cp=cp)
  assert KEY not in [r.key for r in c.rows()]


def test_toggle_writes_through_the_guarded_change_and_is_refused_while_the_edit_gate_is_closed():
  c, store = controller("TESLA_AP1_MODELS")
  assert c.change(KEY, True) and store.values[KEY] in (True, "1", 1, "true")
  closed, store2 = controller("TESLA_AP1_MODELS", can_edit=lambda: False)
  assert not closed.change(KEY, True) and KEY not in store2.values


def test_row_follows_the_gas_brake_page_class():
  # Gas / Brake is ONROAD as in FrogPilot 0.9.7 (onroad-097-full). The cap reads the toggle live (Profiles.read on every
  # planner update), so it needs no reboot-class override: the row simply follows the page.
  assert onroad_policy.PAGE_CLASS["gas_brake"] == onroad_policy.ONROAD
  assert onroad_policy.row_class(KEY, "gas_brake") == onroad_policy.ONROAD
  assert KEY not in onroad_policy.ROW_CLASS


def test_help_text_exists_and_says_what_it_limits():
  entry = toggle_help.HELP[KEY]
  text = " ".join([entry.what, entry.note, entry.when])
  assert "close" in text.lower() and "braking" in text.lower() and "NAP" in entry.note
  assert entry.default == "Off"
