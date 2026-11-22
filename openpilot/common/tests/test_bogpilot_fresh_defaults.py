"""First-install defaults: Driver Camera in Reverse registered on, Experimental Mode starts in Chill and is
pre-confirmed while bogpilot_fresh_defaults.FRESH_INSTALL_CONFIRM_EXPERIMENTAL is True (both switch settings tested).

The real manager_init and BogPilot startup hooks run against in-memory params (the harness from
openpilot/system/manager/test/test_bogpilot_startup.py); no process, hardware or real Params is used.
"""
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from opendbc.car.tesla_ap1.phase3_stalk_controls import AP1, apply_experimental_toggle, experimental_hold_unconfirmed
from openpilot.common import bogpilot_fresh_defaults as fresh
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.system.manager import bogpilot_startup as lifecycle
from openpilot.system.manager.test.test_bogpilot_startup import MemoryParams, imported_manager

HEADER = Path(__file__).resolve().parents[1] / "params_keys_bogpilot.h"
# Registered (compiled) defaults the manager loop writes, as in params_keys.h / params_keys_bogpilot.h.
COMPILED = {"HasAcceptedTerms": "0", "DriverCamera": "1", "IsMetric": False}
KEYS = ("DriverCamera", "ExperimentalModeConfirmed", "ExperimentalMode")


class DeviceParams(MemoryParams):
  def all_keys(self):
    return list(set(super().all_keys()) | {"HasAcceptedTerms", "ExperimentalMode", "ExperimentalModeConfirmed"})

  def get_default_value(self, key):
    return COMPILED.get(key)


@pytest.fixture(params=[True, False], ids=["confirm_on", "confirm_off"])
def confirm(request, monkeypatch):
  monkeypatch.setattr(fresh, "FRESH_INSTALL_CONFIRM_EXPERIMENTAL", request.param)
  return request.param


def cp(long=True):
  return NS(carFingerprint=AP1, dashcamOnly=False, passive=False, openpilotLongitudinalControl=long)


def pull_hold():
  return NS(canValid=True, bogpilot=NS(ap1StalkPullToggle=True, ap1StalkFwdToggle=False))


def boot(tmp_path, params):
  with imported_manager(tmp_path, params) as (manager, _process):
    manager.manager_init()
    manager.manager_cleanup()
  return params


def test_driver_camera_registered_default_is_on():
  assert BOGPILOT_PARAMS["DriverCamera"] == ("PERSISTENT", "BOOL", "1", 1, "1")
  assert re.search(r'\{"DriverCamera", \{PERSISTENT, BOOL, "1"\}\}', HEADER.read_text())
  assert "DriverCamera" not in dict(fresh.fresh_install_defaults(True))


def test_switch_is_on_for_this_build():
  assert fresh.FRESH_INSTALL_CONFIRM_EXPERIMENTAL is True
  assert dict(fresh.fresh_install_defaults()) == {"ExperimentalMode": False, "ExperimentalModeConfirmed": True}
  assert dict(fresh.fresh_install_defaults(False)) == {"ExperimentalMode": False}
  assert (fresh.FRESH_INSTALL_PERSONALITY_KEY, fresh.FRESH_INSTALL_PERSONALITY) == ("LongitudinalPersonality", 2)


def test_fresh_install_gets_defaults(tmp_path, confirm):
  p = boot(tmp_path, DeviceParams())
  assert p.values["DriverCamera"] == "1"                 # registered default
  assert p.values["ExperimentalMode"] is False           # Chill
  assert p.values.get("ExperimentalModeConfirmed") is (True if confirm else None)
  assert p.history.index(("put", "ExperimentalMode")) < p.history.index(("put", "HasAcceptedTerms"))
  assert p.values["HasAcceptedTerms"] == "0"


def test_second_boot_is_not_fresh(tmp_path, confirm):
  p = boot(tmp_path, DeviceParams())
  p.values.update({"DriverCamera": False, "ExperimentalModeConfirmed": False})   # turned off in settings
  p.history.clear()
  boot(tmp_path, p)
  assert p.values["DriverCamera"] is False and p.values["ExperimentalModeConfirmed"] is False
  assert not any(h == ("put", k) for h in p.history for k in KEYS)


@pytest.mark.parametrize("saved", [True, False, "1", "0"])
def test_upgrade_keeps_explicit_values(tmp_path, confirm, saved):
  p = DeviceParams()
  p.values.update({"HasAcceptedTerms": "2", **dict.fromkeys(KEYS, saved)})
  boot(tmp_path, p)
  for key in KEYS:
    assert p.values[key] == saved, key


def test_upgrade_never_confirms_experimental(tmp_path, confirm):
  # An upgraded device that never accepted the Experimental Mode dialog keeps the dialog, with either switch setting.
  p = DeviceParams()
  p.values.update({"HasAcceptedTerms": "2", "DriverCamera": "0"})
  boot(tmp_path, p)
  assert "ExperimentalModeConfirmed" not in p.values and "ExperimentalMode" not in p.values
  assert p.values["DriverCamera"] == "0"                 # earlier builds stored "0": kept
  assert not experimental_hold_unconfirmed(p, cp(), NS(canValid=True, bogpilot=NS(ap1StalkPullToggle=False, ap1StalkFwdToggle=False)), True)
  assert experimental_hold_unconfirmed(p, cp(), pull_hold(), True)


def test_fresh_install_keeps_any_value_already_set(confirm):
  p = DeviceParams()
  p.values.update({"ExperimentalMode": True, "ExperimentalModeConfirmed": False, "LongitudinalPersonality": 1})
  assert fresh.apply_fresh_install_defaults(p) == []
  assert p.values["ExperimentalMode"] is True and p.values["ExperimentalModeConfirmed"] is False
  assert p.values["LongitudinalPersonality"] == 1            # a personality already picked is kept


def test_fresh_install_selects_relaxed(tmp_path, confirm):
  # default: a new install starts on the Relaxed personality (log.capnp relaxed = 2)
  p = boot(tmp_path, DeviceParams())
  assert p.values["LongitudinalPersonality"] == fresh.FRESH_INSTALL_PERSONALITY == 2
  assert p.history.index(("put", "LongitudinalPersonality")) < p.history.index(("put", "HasAcceptedTerms"))


@pytest.mark.parametrize("saved", [None, 0, 1, 2])
def test_upgrade_never_changes_the_selected_personality(tmp_path, confirm, saved):
  # an upgraded device keeps its personality, including one never picked (the compiled default, Standard, still applies)
  p = DeviceParams()
  p.values["HasAcceptedTerms"] = "2"
  if saved is not None:
    p.values["LongitudinalPersonality"] = saved
  boot(tmp_path, p)
  assert p.values.get("LongitudinalPersonality") == saved
  assert ("put", "LongitudinalPersonality") not in p.history


def test_stalk_from_chill_on_first_install(tmp_path, confirm):
  p = boot(tmp_path, DeviceParams())
  assert p.get_bool("ExperimentalMode") is False                 # starts in Chill
  if confirm:
    assert not experimental_hold_unconfirmed(p, cp(), pull_hold(), True)
    assert apply_experimental_toggle(p, cp(), pull_hold(), True) is True
    assert p.values["ExperimentalMode"] is True
    assert apply_experimental_toggle(p, cp(), pull_hold(), True) is False
    assert p.values["ExperimentalMode"] is False                 # and back to Chill
  else:
    # Switch off: the hold is refused and raises the "confirm in settings" alert, as before this change.
    assert experimental_hold_unconfirmed(p, cp(), pull_hold(), True)
    assert apply_experimental_toggle(p, cp(), pull_hold(), True) is None
    assert p.values["ExperimentalMode"] is False


def test_stalk_still_needs_openpilot_longitudinal(tmp_path, confirm):
  p = boot(tmp_path, DeviceParams())
  assert apply_experimental_toggle(p, cp(long=False), pull_hold(), True) is None
  assert apply_experimental_toggle(p, NS(carFingerprint="TESLA_PREAP_MODELS", dashcamOnly=False, passive=False,
                                         openpilotLongitudinalControl=True), pull_hold(), True) is None
  assert p.values["ExperimentalMode"] is False


def test_startup_hook_failure_is_nonfatal(tmp_path, monkeypatch):
  monkeypatch.setattr(fresh, "apply_fresh_install_defaults", lambda params: (_ for _ in ()).throw(OSError()))
  result = lifecycle.before_defaults(DeviceParams(), file_root=tmp_path, backup=lambda: None,
                                     reset=lambda *a, **k: NS(status="not_requested"))
  assert "fresh-defaults: OSError" in result.errors


def test_toggle_reset_request_is_never_a_fresh_install(tmp_path, confirm):
  p = DeviceParams()
  p.values["DoToggleResetStock"] = True
  lifecycle.before_defaults(p, file_root=tmp_path, backup=lambda: None, reset=lambda *a, **k: NS(status="failed", error="x"))
  assert not any(k in p.values for k in KEYS)
