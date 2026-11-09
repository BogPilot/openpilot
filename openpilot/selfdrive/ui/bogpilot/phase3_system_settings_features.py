"""Versioned nonsecret feature snapshots and explicit current-default plans.

Not code backups, installers, model downloads or a generic Params dump. Scope is
frozen from registry/audit; every mutation requires guards, exact compatibility,
preview digest, validated types/source bounds and a durable pre-change snapshot.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile

from openpilot.selfdrive.ui.bogpilot.phase3_system_settings_backend import (
  PreferenceArchive, SystemPreferences, DIR_FLAGS, MAX_JSON, valid_name,
)
from openpilot.selfdrive.ui.bogpilot.phase3_system_settings_feature_specs import FEATURE_SPECS, PROTECTED_EXCLUSIONS, COMPAT_SOURCE_FILES

FORMAT = "bogpilot-nonsecret-feature-preferences"
VERSION = 2


def digest(value):
  return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def validate_value(key, value, specs=FEATURE_SPECS):
  if key not in specs or key in PROTECTED_EXCLUSIONS:
    raise ValueError("Setting outside audited preference scope")
  if value is None:
    return
  if not isinstance(value, str) or len(value) > 128:
    raise ValueError("Invalid preference encoding")
  spec = specs[key]
  if spec["type"] == "BOOL":
    if value not in {"0", "1"}:
      raise ValueError("Invalid boolean preference")
    return
  if spec["type"] == "INT" and not re.fullmatch(r"-?\d+", value):
    raise ValueError("Invalid integer preference")
  n = float(value)
  if not math.isfinite(n):
    raise ValueError("Nonfinite preference refused")
  # Some source registries have sentinel defaults outside the UI editing range.
  # Preserve only that exact declared sentinel, never an invented tuning value.
  declared=spec.get("declared_default")
  if declared not in (None, ""):
    try:
      if n == float(declared):
        return
    except (TypeError,ValueError):
      pass
  # Only source-defined limits; never invent steering/longitudinal tuning ranges.
  lo, hi = spec.get("min"), spec.get("max")
  if lo is not None and n < float(lo) or hi is not None and n > float(hi):
    raise ValueError("Preference violates source bounds")
  if lo is not None and spec.get("step"):
    steps = (n-float(lo)) / float(spec["step"])
    if abs(steps-round(steps)) > 1e-5:
      raise ValueError("Preference violates source step")


def native_compatibility(store, vehicle, platform):
  """Actual installed source + native schema fingerprint, not stale git_src_commit.

  No credentials, VIN, routes or user values are read into compatibility metadata.
  Vehicle is the detected model/family, never a guessed AP1 default. Unknown
  vehicle permits archival but blocks restore/reset.
  """
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  from openpilot.common.bogpilot_toggles import FILE_TOGGLES, FILE_CHOICES
  root = Path(__file__).resolve().parents[4]
  sources = {}
  for relative in COMPAT_SOURCE_FILES:
    path = root / relative
    if path.is_file() and not path.is_symlink():
      sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
  for required in ("openpilot/common/bogpilot_params.py", "openpilot/common/bogpilot_store.py",
                   "openpilot/selfdrive/ui/bogpilot/phase3_system_settings_features.py"):
    if required not in sources:
      raise ValueError("Cannot identify installed feature source")
  supported = {}
  for key in FEATURE_SPECS:
    if store.is_param_key(key):
      supported[key] = "native:" + str(int(store._params.get_type(key)))
    elif key in BOGPILOT_PARAMS or key in FILE_TOGGLES or key in FILE_CHOICES:
      supported[key] = "file:" + FEATURE_SPECS[key]["type"]
  return {"format": FORMAT, "version": VERSION, "source_sha256": digest(sources),
          "scope_sha256": digest(FEATURE_SPECS), "stores_sha256": digest(supported),
          "platform": str(platform), "vehicle_family": str(vehicle or "unidentified")}


def current_defaults(store, specs=FEATURE_SPECS):
  """Read actual compiled fresh Params defaults + current file registry defaults.

  This creates only a disposable Params fixture, never clears live settings and
  never guesses a vehicle/profile. No historical/AP1 profile option is offered.
  """
  from openpilot.common.params import Params
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  from openpilot.common.bogpilot_toggles import FILE_TOGGLES, FILE_CHOICES
  from openpilot.common.bogpilot_store import registry_default
  result = {}
  with tempfile.TemporaryDirectory(prefix="bogpilot-default-preview-") as directory:
    fresh = Params(str(Path(directory) / "params"))
    for key in specs:
      if key in BOGPILOT_PARAMS or key in FILE_TOGGLES or key in FILE_CHOICES:
        # Current source + shipping registry is the fresh BogPilot policy, not
        # a stale packaged native default and never a detected/AP1 profile.
        default = registry_default(key)
        result[key] = default if default != "" else None
      elif store.is_param_key(key):
        value = fresh.get(key, return_default=True)
        result[key] = None if value is None else ("1" if value else "0") if type(value) is bool else str(value)
  for key, value in result.items():
    validate_value(key, value, specs)
  return result


class FeatureArchive(PreferenceArchive):
  def __init__(self, preferences, compatibility, root="/data/toggle_backups", *, specs=None, defaults=None):
    super().__init__(preferences, root)
    self.specs = dict(FEATURE_SPECS if specs is None else specs)
    if set(self.specs) & set(PROTECTED_EXCLUSIONS):
      raise ValueError("Protected settings may not enter archive scope")
    self.keys = frozenset(self.specs)
    self.compatibility = compatibility
    self.defaults = defaults or (lambda: current_defaults(self.prefs.store, self.specs))

  def list(self):
    self.prefs.guard()
    try:
      with self.directory() as fd:
        return tuple(n for n in sorted(os.listdir(fd)) if n.startswith("feature-") and n.endswith(".json")
                     and stat.S_ISREG(os.stat(n, dir_fd=fd, follow_symlinks=False).st_mode))
    except FileNotFoundError:
      return ()

  def backup(self):
    self.prefs.guard()
    values = {key: self.prefs.store.raw(key) for key in sorted(self.keys)}
    # Absent values are represented explicitly: a same-build restore can return
    # to inheritance without silently synthesizing a saved ON/default value.
    for key, value in values.items():
      validate_value(key, value, self.specs)
    body = {"format": FORMAT, "version": VERSION, "compatibility": self.compatibility(), "values": values}
    doc = {**body, "digest": digest(body)}
    name = "feature-" + doc["digest"] + ".json"
    raw = json.dumps(doc, sort_keys=True).encode()
    if len(raw) > MAX_JSON:
      raise ValueError("Snapshot size limit")
    with self.directory(create=True) as fd:
      try:
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
      except FileExistsError:
        if self._read(fd, name, compatible=False) != doc:
          raise ValueError("Existing archive differs")
      else:
        with os.fdopen(out, "wb") as f:
          f.write(raw)
          f.flush()
          os.fsync(f.fileno())
        os.fsync(fd)
    return name

  def _read(self, fd, name, compatible=True):
    valid_name(name, ".json")
    if not name.startswith("feature-"):
      raise ValueError("Not a compatible feature snapshot")
    src = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(src, "rb") as f:
      if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
        raise ValueError("Nonregular snapshot refused")
      data = f.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
      raise ValueError("Snapshot size limit")
    doc = json.loads(data)
    if set(doc) != {"format", "version", "compatibility", "values", "digest"}:
      raise ValueError("Unknown archive fields")
    if doc["format"] != FORMAT or doc["version"] != VERSION:
      raise ValueError("Unsupported archive format/version")
    body = {k: v for k, v in doc.items() if k != "digest"}
    if digest(body) != doc["digest"] or name != "feature-" + doc["digest"] + ".json":
      raise ValueError("Archive integrity mismatch")
    if not isinstance(doc["values"], dict) or set(doc["values"]) != self.keys:
      raise ValueError("Archive scope mismatch")
    for key, value in doc["values"].items():
      validate_value(key, value, self.specs)
    if compatible:
      current = self.compatibility()
      if current.get("vehicle_family") in {None, "", "unidentified"}:
        raise ValueError("Detected vehicle required; no profile guessed")
      if doc["compatibility"] != current:
        raise ValueError("Build/schema/platform/vehicle compatibility mismatch")
    return doc

  def preview(self, name=None, *, reset=False):
    self.prefs.guard()
    if reset:
      compat = self.compatibility()
      if compat.get("vehicle_family") in {None, "", "unidentified"}:
        raise ValueError("Detected vehicle required; no AP1/default profile guessed")
      target = self.defaults()
      if set(target) - self.keys:
        raise ValueError("Default scope expansion refused")
      for key, value in target.items():
        validate_value(key, value, self.specs)
      reason = "Current BogPilot fresh defaults + shipping registry (not historical/AP1/stock profile)"
    else:
      with self.directory() as fd:
        doc = self._read(fd, name)
      compat, target, reason = doc["compatibility"], doc["values"], "Compatible feature snapshot"
    changes = {key: {"from": self.prefs.store.raw(key), "to": value} for key, value in target.items()
               if self.prefs.store.raw(key) != value}
    plan = {"reason": reason, "compatibility": compat, "changes": changes,
            "protected_exclusions": dict(PROTECTED_EXCLUSIONS)}
    return {**plan, "plan_digest": digest(plan)}

  def apply_preview(self, preview):
    """Only after explicit UI preview + confirmation. No process/reboot actions."""
    self.prefs.guard()
    plan = {k:v for k,v in preview.items() if k != "plan_digest"}
    if digest(plan) != preview.get("plan_digest") or plan["compatibility"] != self.compatibility():
      raise ValueError("Preview stale or compatibility changed")
    if plan["compatibility"].get("vehicle_family") in {None,"", "unidentified"}:
      raise ValueError("Unidentified vehicle")
    changes = plan["changes"]
    for key, entry in changes.items():
      if set(entry) != {"from", "to"}:
        raise ValueError("Invalid preview change")
      validate_value(key, entry["to"], self.specs)
      if self.prefs.store.raw(key) != entry["from"]:
        raise ValueError("Preferences changed since preview")
    receipt = self.backup()  # Must return only after fsync and strict validation.
    applied = []
    consent_flags = {"NoLogging":"LocalLoggingDisableConsent", "HigherBitrate":"HighQualityRecordingConsent"}
    old_consents = {flag:self.prefs.store.raw(flag) for key,flag in consent_flags.items() if key in changes}
    try:
      for flag in old_consents:
        # Restored/stale legacy ON flags require fresh explicit action consent.
        self.prefs.store.put_bool(flag, False)
      # Parent gates last: avoid enabling a group against half-restored values.
      ordered = sorted(changes, key=lambda k: (k.endswith("Management") or k in {"CustomUI", "TuningLevel"}, k))
      for key in ordered:
        self.prefs.guard()
        entry = changes[key]
        if self.prefs.store.raw(key) != entry["from"]:
          raise ValueError("Concurrent preference write")
        applied.append(key)
        value = entry["to"]
        self.prefs.store.remove(key) if value is None else self.prefs.store.put(key, value)
        actual = self.prefs.store.raw(key)
        if value is None and actual is not None or value is not None and not _equivalent(key, actual, value, self.specs):
          raise OSError("Effective preference write not verified")
    except Exception:
      incomplete = False
      for key in reversed(applied):
        value = changes[key]["from"]
        try:
          self.prefs.store.remove(key) if value is None else self.prefs.store.put(key, value)
          if not _equivalent(key, self.prefs.store.raw(key), value, self.specs):
            incomplete = True
        except Exception:
          incomplete = True
      for flag,old_consent in old_consents.items():
        try:
          self.prefs.store.remove(flag) if old_consent is None else self.prefs.store.put(flag,old_consent)
        except Exception:
          incomplete=True
      raise RuntimeError("Change failed; durable original snapshot retained; " +
                         ("rollback incomplete" if incomplete else "rolled back")) from None
    return receipt

  def restore(self, name):
    raise PermissionError("Use preview + explicit apply_preview confirmation")

  def delete(self, name=None):
    self.prefs.guard()
    names = self.list() if name is None else (name,)
    if not names:
      return 0
    with self.directory() as fd:
      for selected in names:
        self._read(fd, selected, compatible=False)
      for selected in names:
        self.prefs.guard()
        os.unlink(selected, dir_fd=fd)
      os.fsync(fd)
    return len(names)


def _equivalent(key, actual, expected, specs):
  if actual is None or expected is None:
    return actual is expected
  try:
    validate_value(key, actual, specs)
    return actual == expected if specs[key]["type"] == "BOOL" else float(actual) == float(expected)
  except (ValueError, TypeError):
    return False
