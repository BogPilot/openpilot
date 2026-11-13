"""BogPilot: NoLogging gate for the manager (BogPilot 0.9.7 toggle.no_logging, frogpilot_variables.py:931 @568fea947).

NoLogging under DeviceManagement, each honoured only at its tuning level, read straight from params with the same rules
as bogpilot_settings.get_bool (unset reads as the default; below its tuning level a key reads as its default).
The manager does not import bogpilot_settings: that module imports BOGPILOT_BRANCHES from openpilot.common.version,
which this tree does not define (known latent bug, see docs/tesla/DIVERGENCES_nologging.md), and process_config /
helpers must always import. The 0.9.7 vetting-branch / force_onroad exceptions are not ported: ON records nothing.
"""
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS


def _default(key: str) -> str:
  return BOGPILOT_PARAMS[key][2] or ""


def _tuning_level(params) -> int:
  return params.get_int("TuningLevel") if params.get_bool("TuningLevelConfirmed") else 3


def _get_bool(params, key: str) -> bool:
  if _tuning_level(params) >= BOGPILOT_PARAMS[key][3]:
    return params.get_bool(key) if params.get(key) is not None else _default(key) == "1"
  return _default(key) == "1"


def no_logging(params) -> bool:
  """True = record nothing (process_config.allow_logging / logging_allowed, helpers.save_bootlog)."""
  return _get_bool(params, "DeviceManagement") and _get_bool(params, "NoLogging")
