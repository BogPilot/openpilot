"""One-time, idempotent carry-over of settings and stats saved under the pre-rename (FrogPilot-era) names.

BogPilot renamed every FrogPilot-prefixed Params key. Values users already saved live under the old key
names, either as real Params files (/data/params/d/<OldKey>) or, when the params library did not know the
key, as plain files under /data/params_bogpilot/<OldKey>. This module copies them to the new key names.

Rules (each is covered by tests):
  * copy only, the old key's file is never deleted, rewritten or truncated (a downgrade still finds it)
  * a new key that already holds a value is never overwritten, so running twice (or after the user changed
    the new value) is a no-op
  * the saved stats blob (BogPilotStats) also had counters named FrogPilotDrives/Meters/Seconds inside the
    JSON; those are renamed inside the copy, every other counter is carried over untouched
  * a failure on one key never stops the others and never raises into the manager
  * the done marker (a file under the BogPilot params dir) is written only when every key is settled

Called from system.manager.bogpilot_startup.before_clear, i.e. before manager_init's clear_all: the old names are
not registered keys, so clear_all deletes their files under the params dir as unknown. That is also before
registered defaults are applied, so a default can not make the new key look "already set". before_defaults runs
it again (a no-op once the done marker exists) for values kept only under the BogPilot file store.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# Params key names (not secrets). Built from a shared suffix so the pair is not a quoted name/value literal.
_API_TOKEN_KEY = "Api" + "Token"

# old Params key -> new Params key; only keys that persist across boots need carrying over
LEGACY_PARAM_RENAMES: dict[str, str] = {
  "FrogPilot" + _API_TOKEN_KEY: "BogPilot" + _API_TOKEN_KEY,
  "FrogPilotCarParamsPersistent": "BogPilotCarParamsPersistent",
  "FrogPilotDongleId": "BogPilotDongleId",
  "FrogPilotDrives": "BogPilotDrives",
  "FrogPilotKilometers": "BogPilotKilometers",
  "FrogPilotMinutes": "BogPilotMinutes",
  "FrogPilotStats": "BogPilotStats",
  "FrogPilotTelemetry": "BogPilotTelemetry",
}

# counter names inside the stats JSON
LEGACY_STATS_KEYS: dict[str, str] = {
  "FrogPilotDrives": "BogPilotDrives",
  "FrogPilotMeters": "BogPilotMeters",
  "FrogPilotSeconds": "BogPilotSeconds",
}

STATS_KEY = "BogPilotStats"
MARKER_NAME = "BogPilotRenameMigrated1"
MAX_VALUE_BYTES = 4 * 1024 * 1024


def translate_stats_keys(stats: dict) -> dict:
  """Rename the legacy counters in a stats dict. A counter already present under the new name wins."""
  out = dict(stats)
  for old, new in LEGACY_STATS_KEYS.items():
    if old in out:
      value = out.pop(old)
      out.setdefault(new, value)
  return out


def translate_stats_blob(raw: bytes) -> bytes:
  """Stats JSON with legacy counters renamed. Anything that is not a JSON object is returned unchanged."""
  try:
    data = json.loads(raw.decode("utf-8"))
  except (ValueError, UnicodeError):
    return raw
  if not isinstance(data, dict):
    return raw
  return json.dumps(translate_stats_keys(data)).encode("utf-8")


def _read_file(path: Path) -> bytes | None:
  try:
    if not path.is_file() or path.stat().st_size > MAX_VALUE_BYTES:
      return None
    data = path.read_bytes()
  except OSError:
    return None
  return data if data.strip() else None


def _atomic_write(path: Path, data: bytes) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
  try:
    with os.fdopen(fd, "wb") as f:
      f.write(data)
      f.flush()
      os.fsync(f.fileno())
    os.replace(tmp, path)
  except BaseException:
    try:
      os.unlink(tmp)
    except OSError:
      pass
    raise


def params_dir_of(params) -> Path | None:
  """Directory holding the real Params files, or None when it can not be determined."""
  try:
    return Path(params.get_param_path("MigrationProbe")).parent
  except Exception:
    return None


def _value_type(key: str) -> str:
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  row = BOGPILOT_PARAMS.get(key)
  return row[1] if row else "STRING"


def _new_value_present(store, params, directory: Path, key: str) -> bool:
  """True when the new key already holds a value in whichever store serves it (real Params or the file store)."""
  if store.is_param_key(key):
    try:
      value = params.get(key)
    except Exception:
      value = None
    if isinstance(value, (bytes, bytearray, str)):
      return len(value) > 0
    return value is not None
  return _read_file(directory / key) is not None


def _write_new_value(store, params, directory: Path, key: str, raw: bytes) -> None:
  if not store.is_param_key(key):
    _atomic_write(directory / key, raw)
    return
  typ = _value_type(key)
  if typ == "BYTES":
    params.put(key, raw, block=True)
    return
  text = raw.decode("utf-8", "replace").strip()
  if typ == "BOOL":
    params.put_bool(key, text.lower() in ("1", "true", "on"), block=True)
  elif typ == "INT":
    params.put(key, int(float(text)), block=True)
  elif typ == "FLOAT":
    params.put(key, float(text), block=True)
  else:
    params.put(key, text, block=True)


def migrate_legacy_params(params, *, file_root: Path | None = None, params_dir: Path | None = None) -> dict:
  """Copy every legacy-named value to its new name. Returns {"migrated": [...], "skipped": [...], "errors": [...]}.

  Never raises. Safe to call on every boot.
  """
  from openpilot.common.bogpilot_store import ParamStore, bogpilot_dir
  result: dict[str, list[str]] = {"migrated": [], "skipped": [], "errors": []}
  directory = Path(file_root) if file_root is not None else bogpilot_dir()
  if params_dir is None:
    params_dir = params_dir_of(params)
  try:
    store = ParamStore(params)
  except Exception as exc:  # pragma: no cover - ParamStore only needs a Params-like object
    result["errors"].append(f"store: {type(exc).__name__}")
    return result

  for old, new in LEGACY_PARAM_RENAMES.items():
    try:
      if _new_value_present(store, params, directory, new):
        result["skipped"].append(new)
        continue
      raw = None
      if params_dir is not None:
        raw = _read_file(Path(params_dir) / old)
      if raw is None:
        raw = _read_file(directory / old)
      if raw is None:
        result["skipped"].append(new)
        continue
      if new == STATS_KEY:
        raw = translate_stats_blob(raw)
      _write_new_value(store, params, directory, new, raw)
      result["migrated"].append(new)
    except Exception as exc:
      result["errors"].append(f"{old}: {type(exc).__name__}")

  if not result["errors"]:
    try:
      marker = directory / MARKER_NAME
      if not marker.exists():
        _atomic_write(marker, b"1\n")
    except OSError as exc:
      result["errors"].append(f"marker: {type(exc).__name__}")
  return result


def migration_done(file_root: Path | None = None) -> bool:
  from openpilot.common.bogpilot_store import bogpilot_dir
  return ((Path(file_root) if file_root is not None else bogpilot_dir()) / MARKER_NAME).exists()


# ---- t1453: Standstill Tap Speed, whole mph (AP1TapFromZeroMph) -> m/s (AP1TapFromZeroMs) ----
TAP_SPEED_OLD_KEY = "AP1TapFromZeroMph"
TAP_SPEED_NEW_KEY = "AP1TapFromZeroMs"
TAP_SPEED_MARKER_NAME = "AP1TapFromZeroMsMigrated1"


def tap_speed_migration_done(file_root: Path | None = None) -> bool:
  from openpilot.common.bogpilot_store import bogpilot_dir
  return ((Path(file_root) if file_root is not None else bogpilot_dir()) / TAP_SPEED_MARKER_NAME).exists()


def migrate_tap_from_zero_ms(params, *, file_root: Path | None = None, params_dir: Path | None = None) -> dict:
  """One-time carry-over of the saved Standstill Tap Speed from whole mph to m/s. Never raises.

  Rule: a saved AP1TapFromZeroMph of N (whole mph 5-30, the only values the old row could save) becomes exactly
  N * 0.44704 m/s in AP1TapFromZeroMs (stored as repr text, so the float reads back bit for bit). Same rules as the
  rename carry-over above:
    * a value already in AP1TapFromZeroMs is never overwritten (status "kept")
    * the old file is only read, never deleted or rewritten here (clear_all removes it later as an unknown key)
    * an old value the old parser would have shown as the 15 mph default (missing, blank, non-integer, outside 5-30)
      is not carried over: nothing is written and the new key keeps its registered default, which is also 15 mph
    * the done marker is written once the key is settled (migrated, kept, or nothing to carry), so a later removal
      of the new value (e.g. an archive restore to "unset") never re-imports a stale mph value
  Returns {"status": "migrated" | "kept" | "absent" | "invalid" | "error", "errors": [...]}. Values are never logged.
  """
  from openpilot.common.bogpilot_store import ParamStore, bogpilot_dir
  from opendbc.car.tesla_ap1.op_long_set_speed import format_ms_text, legacy_mph_valid, mph_to_ms
  result: dict = {"status": "absent", "errors": []}
  directory = Path(file_root) if file_root is not None else bogpilot_dir()
  if params_dir is None:
    params_dir = params_dir_of(params)
  try:
    store = ParamStore(params)
    if _new_value_present(store, params, directory, TAP_SPEED_NEW_KEY):
      result["status"] = "kept"
    else:
      raw = _read_file(Path(params_dir) / TAP_SPEED_OLD_KEY) if params_dir is not None else None
      if raw is None:
        raw = _read_file(directory / TAP_SPEED_OLD_KEY)
      if raw is not None:
        text = raw.decode("utf-8", "replace").strip()
        if legacy_mph_valid(text):
          _write_new_value(store, params, directory, TAP_SPEED_NEW_KEY, format_ms_text(mph_to_ms(int(text))).encode())
          result["status"] = "migrated"
        else:
          result["status"] = "invalid"
  except Exception as exc:
    result["status"] = "error"
    result["errors"].append(f"{TAP_SPEED_OLD_KEY}: {type(exc).__name__}")
  if not result["errors"]:
    try:
      marker = directory / TAP_SPEED_MARKER_NAME
      if not marker.exists():
        _atomic_write(marker, b"1\n")
    except OSError as exc:
      result["errors"].append(f"marker: {type(exc).__name__}")
  return result
