"""AP1 runtime options, with unknown-key-safe file fallback and AOL off by default."""
from pathlib import Path
from opendbc.car.tesla_ap1.aol_gate import AP1AolGate

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


def aol_bit():
  # A missing safety implementation is NOT permission to invent a bit.
  try:
    from opendbc.safety import ALTERNATIVE_EXPERIENCE
  except ImportError:
    return 0
  return int(getattr(ALTERNATIVE_EXPERIENCE, "ALWAYS_ON_LATERAL", 0))


def apply_ap1_alternative_experience(CP, params):
  if CP.carFingerprint == AP1 and read_option(params, "AlwaysOnLateral", "0") in ("1", "true", "on"):
    CP.alternativeExperience |= aol_bit()


class Ap1Lateral:
  def __init__(self, CP, params):
    self.available = CP.carFingerprint == AP1 and bool(CP.alternativeExperience) and bool(CP.alternativeExperience & aol_bit())
    self.main = read_option(params, "AlwaysOnLateralMain", "1") in ("1", "true", "on") if self.available else False
    try:
      self.pause_speed = float(read_option(params, "PauseAOLOnBrake", "0")) if self.available else 0.0
    except ValueError:
      self.pause_speed = 0.0
    self.gate = AP1AolGate()

  def update(self, CS, engaged, calibrated, blocked):
    allowed = (self.available and (self.main or CS.cruiseState.enabled) and CS.cruiseState.available and
               str(CS.gearShifter) == "drive" and CS.canValid and calibrated and not blocked and
               not (CS.brakePressed and CS.vEgo < self.pause_speed and not CS.standstill))
    return self.gate.update(bool(allowed), engaged, CS.vEgo, CS.steeringAngleDeg)


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
