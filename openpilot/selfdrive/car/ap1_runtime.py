"""AP1 option reads and volume defaults; experimental AOL is not in this release."""
from pathlib import Path

AP1 = "TESLA_AP1_MODELS"


def read_option(params, key, default=""):
  try:
    value = params.get(key)
  except Exception:
    value = None
  if value is None:
    try:
      value = (Path("/data/params_bogpilot") / key).read_text().strip()
    except OSError:
      return default
  if isinstance(value, bytes):
    value = value.decode("utf-8", "replace")
  return str(value).strip().lower()


def apply_ap1_volume_defaults(CP, params, store=None, profile=None):
  """Use stream 7's audible AP1 profile, only for settings never stored.

  Existing user choices belong to the settings/migration owner (stream 5).
  No legacy mute profile is copied into vehicle/runtime code.
  """
  if CP.carFingerprint != AP1:
    return []
  if profile is None:
    from openpilot.common.bogpilot_alert_volumes import AP1_VOLUME_PROFILE
    profile = AP1_VOLUME_PROFILE
  if store is None:
    from openpilot.common.bogpilot_store import ParamStore
    store = ParamStore(params)
  changed = []
  for key, value in profile.items():
    if store.raw(key) is None:
      store.put(key, value)
      changed.append(key)
  return changed
