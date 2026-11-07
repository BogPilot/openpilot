"""Phase-2 eligibility/default contract; no device IO, migration, or control changes.

Source evidence is a review aid, NOT proof of feature behavior. UI lanes must also
supply runtime tests before exposing rows. Never use toggle_metadata as evidence.
"""
from dataclasses import dataclass
from pathlib import Path
import ast

@dataclass(frozen=True)
class Setting:
  storage: str
  default: str | None
  consumer: str | None
  evidence: str = ""
  gate: str = ""

COMMON = "openpilot/common/"
UI = "openpilot/selfdrive/ui/"
AP1 = "opendbc_repo/opendbc/car/tesla_ap1/"
VOLUME_KEYS = ("EngageVolume", "DisengageVolume", "RefuseVolume", "PromptVolume",
               "PromptDistractedVolume", "WarningSoftVolume", "WarningImmediateVolume")
CONTRACT = {
  "AlertVolumeControl": Setting("typed", "0", UI + "soundd.py", "AlertVolumeControl", "controller enabled; immediate warning floor 25"),
  **{k: Setting("typed", "101", UI + "soundd.py", k, "AlertVolumeControl; 101=auto; preserve custom values") for k in VOLUME_KEYS},
  "AlwaysOnLateral": Setting("typed", "0", "openpilot/selfdrive/car/ap1_runtime.py", "AlwaysOnLateral", "AP1 only; existing safety approval required"),
  "AlwaysOnLateralMain": Setting("typed", "1", "openpilot/selfdrive/car/ap1_runtime.py", "AlwaysOnLateralMain", "parent AOL; AP1 only"),
  "NudgelessLaneChange": Setting("typed", "0", None, gate="no live controller consumer in baseline; DO NOT expose"),
  "AdjacentLeadsUI": Setting("typed", "1", UI + "onroad/bogpilot/hud_compose.py", 's.toggle_bool("AdjacentLeadsUI", level)', "radar + tuning level; DebugMode override"),
  "ScreenRecorder": Setting("typed", "1", UI + "onroad/bogpilot/bogpilot_hud.py", 's.toggle_bool("ScreenRecorder", level)', "ScreenManagement + tuning level; DebugMode override"),
  "DeveloperHUD": Setting("file", "0", None, gate="reserved; no live consumer in baseline; DO NOT expose"),
  "OffroadScreensaver": Setting("file", "0", None, gate="reserved; no C3X implementation; DO NOT expose"),
  "EnableICIntegration": Setting("car-file", None, AP1 + "toggles.py", "IC_INTEGRATION_PATH", "AP1 fingerprint default ON, otherwise OFF"),
  "RegenComfortBrake": Setting("car-file", None, AP1 + "regen_brake.py", "REGEN_COMFORT_PATH", "AP1 fingerprint default ON, otherwise OFF"),
  "RegenAwareStop": Setting("car-file", None, AP1 + "regen_aware.py", "_TOGGLE_PATH", "AP1 fingerprint default ON, otherwise OFF"),
  "DisableOpenpilotLongitudinal": Setting("typed+legacy-file", "0", AP1 + "toggles.py", "DISABLE_OP_LONG_PATHS", "legacy file precedence then typed path; restart required"),
}
# Registration alone does NOT make these usable. No new keys or selectors.
# t968u: desired new defaults, NOT supported until lane1b16 behavioral consumer lands.
PENDING_ALERT_DEFAULTS = {"GreenLightAlert": "1", "LeadDepartingAlert": "1"}
PENDING_ALERT_LABELS = {"GreenLightAlert": "Green Light Alert", "LeadDepartingAlert": "Lead Departed Alert"}
EXCLUDED = frozenset({"TeslaEarly", "CarMake", "CarModel", "TeslaLongControl", "TeslaStalkFollow", "AlwaysOnLateralLKAS"})

def eligible(keys):
  """Fail closed; the panel lane still owes behavioral tests for these candidates."""
  return tuple(k for k in keys if k in CONTRACT and CONTRACT[k].consumer is not None and k not in EXCLUDED)

def missing_defaults(saved):
  """Pure missing-only plan. Presence wins even for OFF, zero volume, or empty text.

  Car-dependent and file-backed keys must use their existing stores; this helper
  deliberately cannot invent global AP1 defaults or migrate device values.
  """
  return {k: s.default for k, s in CONTRACT.items()
          if s.storage == "typed" and s.default is not None and k not in saved}

def registry(root):
  tree = ast.parse((Path(root) / COMMON / "bogpilot_params.py").read_text())
  for n in tree.body:
    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "BOGPILOT_PARAMS":
      return ast.literal_eval(n.value)
  raise ValueError("BOGPILOT_PARAMS missing")

def audit(root):
  """Check current source registration/defaults and non-metadata evidence.

  Does not assert that substring evidence proves a feature active. Changes to
  actual consumers must still pass their native focused behavior tests.
  """
  root = Path(root)
  params = registry(root)
  errors = []
  header = (root / COMMON / "params_keys_bogpilot.h").read_text()
  for key, spec in CONTRACT.items():
    if spec.storage.startswith("typed"):
      row = params.get(key)
      if row is None or row[2] != spec.default:
        errors.append(key + ": registry default mismatch")
      if row is not None:
        expected = '{"' + key + '", {' + row[0] + ', ' + row[1] + ', "' + spec.default + '"}}'
        if expected not in header:
          errors.append(key + ": generated header mismatch")
    if spec.storage in ("file", "car-file") and key in params:
      errors.append(key + ": must not become typed")
    if spec.consumer:
      path = root / spec.consumer
      if not path.is_file() or spec.evidence not in path.read_text():
        errors.append(key + ": consumer evidence missing")
  return errors
