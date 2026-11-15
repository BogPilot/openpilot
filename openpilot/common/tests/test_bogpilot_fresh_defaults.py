"""First-install defaults (openpilot/common/bogpilot_fresh_defaults.py): fresh install, upgrade, stalk from Chill.

The real manager_init and BogPilot startup hooks run against in-memory params (the harness from
openpilot/system/manager/test/test_bogpilot_startup.py); no process, hardware or real Params is used.
"""
from types import SimpleNamespace as NS

import pytest

from opendbc.car.tesla_ap1.phase3_stalk_controls import AP1, apply_experimental_toggle, experimental_hold_unconfirmed
from openpilot.common import bogpilot_fresh_defaults as fresh
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.system.manager import bogpilot_startup as lifecycle
from openpilot.system.manager.test.test_bogpilot_startup import MemoryParams, imported_manager

# Registered (compiled) defaults the manager loop writes, as in params_keys.h / params_keys_bogpilot.h.
COMPILED = {"HasAcceptedTerms": "0", "DriverCamera": "0", "IsMetric": False}
FRESH = {"DriverCamera": True, "ExperimentalModeConfirmed": True, "ExperimentalMode": False}


class DeviceParams(MemoryParams):
  def all_keys(self):
    return list(set(super().all_keys()) | {"HasAcceptedTerms", "ExperimentalMode", "ExperimentalModeConfirmed"})

  def get_default_value(self, key):
    return COMPILED.get(key)


def cp(long=True):
  return NS(carFingerprint=AP1, dashcamOnly=False, passive=False, openpilotLongitudinalControl=long)


def pull_hold():
  return NS(canValid=True, bogpilot=NS(ap1StalkPullToggle=True, ap1StalkFwdToggle=False))


def boot(tmp_path, params):
  with imported_manager(tmp_path, params) as (manager, _process):
    manager.manager_init()
    manager.manager_cleanup()
  return params


def test_registered_default_is_unchanged():
  # The compiled default stays "0": libparams_c.so is not rebuilt for this change.
  assert BOGPILOT_PARAMS["DriverCamera"][2] == "0"


def test_fresh_install_gets_defaults(tmp_path):
  p = boot(tmp_path, DeviceParams())
  for key, value in FRESH.items():
    assert p.values[key] is value, key
  # Written before the registered defaults, so the compiled "0" never replaces DriverCamera on.
  assert p.history.index(("put", "DriverCamera")) < p.history.index(("put", "HasAcceptedTerms"))
  assert p.values["HasAcceptedTerms"] == "0"


def test_second_boot_is_not_fresh(tmp_path):
  p = boot(tmp_path, DeviceParams())
  p.values["DriverCamera"] = False   # turned off in settings after the first boot
  p.values["ExperimentalModeConfirmed"] = False
  p.history.clear()
  boot(tmp_path, p)
  assert p.values["DriverCamera"] is False and p.values["ExperimentalModeConfirmed"] is False
  assert not any(h == ("put", k) for h in p.history for k in FRESH)


@pytest.mark.parametrize("saved", [True, False, "1", "0"])
def test_upgrade_keeps_explicit_values(tmp_path, saved):
  p = DeviceParams()
  p.values.update({"HasAcceptedTerms": "2", "DriverCamera": saved, "ExperimentalModeConfirmed": saved, "ExperimentalMode": saved})
  boot(tmp_path, p)
  for key in FRESH:
    assert p.values[key] == saved, key


def test_upgrade_never_confirms_experimental(tmp_path):
  # An upgraded device that never accepted the Experimental Mode dialog keeps the dialog.
  p = DeviceParams()
  p.values.update({"HasAcceptedTerms": "2", "DriverCamera": "0"})
  boot(tmp_path, p)
  assert "ExperimentalModeConfirmed" not in p.values and "ExperimentalMode" not in p.values
  assert p.values["DriverCamera"] == "0"


def test_fresh_install_keeps_any_value_already_set():
  p = DeviceParams()
  p.values.update({"DriverCamera": False, "ExperimentalMode": True})
  assert fresh.apply_fresh_install_defaults(p) == ["ExperimentalModeConfirmed"]
  assert p.values["DriverCamera"] is False and p.values["ExperimentalMode"] is True


def test_stalk_switch_works_from_chill_on_first_install(tmp_path):
  p = boot(tmp_path, DeviceParams())
  assert p.get_bool("ExperimentalMode") is False                 # starts in Chill
  assert not experimental_hold_unconfirmed(p, cp(), pull_hold(), True)
  assert apply_experimental_toggle(p, cp(), pull_hold(), True) is True
  assert p.values["ExperimentalMode"] is True
  assert apply_experimental_toggle(p, cp(), pull_hold(), True) is False
  assert p.values["ExperimentalMode"] is False                   # and back to Chill


def test_stalk_still_needs_openpilot_longitudinal(tmp_path):
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


def test_toggle_reset_request_is_never_a_fresh_install(tmp_path):
  p = DeviceParams()
  p.values["DoToggleResetStock"] = True
  lifecycle.before_defaults(p, file_root=tmp_path, backup=lambda: None, reset=lambda *a, **k: NS(status="failed", error="x"))
  assert not any(k in p.values for k in FRESH)
