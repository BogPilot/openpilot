"""First-install defaults for Driver Camera in Reverse and Experimental Mode. Never applied on an upgrade.

Runs from bogpilot_startup.before_defaults, i.e. before manager_init writes the registered (compiled) defaults
(openpilot/system/manager/manager.py, "set unset params to their default value"). At that point:

- HasAcceptedTerms (openpilot/common/params_keys.h, compiled default "0") is unset only on a device that has
  never booted this software (fresh install, or all params erased). Every earlier boot wrote it, so an upgrade
  never counts as a fresh install.
- Each value below is written only if its own key is still unset, so an explicit ON or OFF is never changed.
- The same boot's default loop then writes HasAcceptedTerms "0", so every later boot is not fresh: no marker
  is needed, and a boot interrupted before that loop just retries the same unset-only writes.

Values:
- DriverCamera = on. The compiled default stays "0" (params_keys_bogpilot.h, from the BogPilot 0.9.7
  367e1fe table), so libparams_c.so is unchanged; "Reset toggles to default" still resets it to off.
- ExperimentalModeConfirmed = on, so the AP1 stalk hold (opendbc tesla_ap1/phase3_stalk_controls.py
  apply_experimental_toggle) switches modes on the first drive without the settings confirmation dialog first.
  The stock dialog (selfdrive/ui/layouts/settings/toggles.py; NAP has the same) is otherwise the only writer.
  The AP1 profile never writes this key (bogpilot_ap1_profile.py NEVER_PROFILE_KEYS); this maintainer-chosen
  first-install default is the documented exception (docs/tesla/DIVERGENCES.md).
- ExperimentalMode = off: the drive mode starts in Chill. LongitudinalPersonality keeps its compiled default
  (Standard / Regular).

Longitudinal availability is not touched here: the stalk switch still needs experimental_supported(cp)
(AP1 Model S with openpilot longitudinal), and selfdrived drops ExperimentalMode without openpilot longitudinal.
"""
from __future__ import annotations

FRESH_INSTALL_KEY = "HasAcceptedTerms"
FRESH_INSTALL_DEFAULTS: tuple[tuple[str, bool], ...] = (
  ("DriverCamera", True),
  ("ExperimentalModeConfirmed", True),
  ("ExperimentalMode", False),
)


def is_fresh_install(params) -> bool:
  return params.get(FRESH_INSTALL_KEY) is None


def apply_fresh_install_defaults(params) -> list[str]:
  """Returns the keys written. Any upgrade (HasAcceptedTerms already stored) gets nothing."""
  if not is_fresh_install(params):
    return []
  written: list[str] = []
  for key, value in FRESH_INSTALL_DEFAULTS:
    if params.get(key) is None:
      params.put_bool(key, value, block=True)
      written.append(key)
  return written
