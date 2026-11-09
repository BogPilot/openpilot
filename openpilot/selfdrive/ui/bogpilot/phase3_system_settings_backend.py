"""Bounded local System Settings actions; no subprocesses, network or import-time IO.

Caller must provide live offroad/capability guards. Production roots cannot be
chosen by UI input. All file walking is fd-relative, NOFOLLOW, same filesystem.
"""
import errno
import json
import os
import time
import re
import stat
from contextlib import contextmanager
from pathlib import Path

ROOTS = {
  "driving": ("/data/media/0/realdata", "/data/media/0/realdata_HD", "/data/media/0/realdata_konik"),
  "errors": ("/data/error_logs",),
  "recordings": ("/data/media/screen_recordings",),
}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
MAX_ENTRIES = 100000
MAX_DEPTH = 32
MAX_JSON = 4 * 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,159}\Z")


def valid_name(value, suffix=None):
  if not isinstance(value, str) or not NAME.fullmatch(value) or value in {".", ".."}:
    raise ValueError("Invalid local filename")
  if suffix and not value.lower().endswith(suffix):
    raise ValueError("Wrong filename type")
  return value


@contextmanager
def open_directory(path):
  """Reject symlinks in *every* ancestor, not just the selected root."""
  p = Path(path)
  if not p.is_absolute() or ".." in p.parts:
    raise ValueError("Absolute bounded root required")
  fd = os.open("/", DIR_FLAGS)
  try:
    for part in p.parts[1:]:
      new = os.open(part, DIR_FLAGS, dir_fd=fd)
      os.close(fd)
      fd = new
    yield fd
  finally:
    os.close(fd)


def _preserved(fd):
  try:
    return os.getxattr(fd, "user.preserve") == b"1"
  except OSError as exc:
    if exc.errno in {errno.ENODATA, errno.ENOTSUP, getattr(errno, "ENOATTR", errno.ENODATA)}:
      return False
    raise  # Unknown xattr errors must not erase possibly protected drives.


def _scan(fd, dev, depth=0, count=None):
  count = [0] if count is None else count
  if depth > MAX_DEPTH:
    raise ValueError("Directory nesting exceeds safety limit")
  result = []
  for name in sorted(os.listdir(fd)):
    count[0] += 1
    if count[0] > MAX_ENTRIES:
      raise ValueError("Directory entry limit exceeded")
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if st.st_dev != dev or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
      raise ValueError("Symlink, mount or special file refused")
    children = None
    if stat.S_ISDIR(st.st_mode):
      child = os.open(name, DIR_FLAGS, dir_fd=fd)
      try:
        opened = os.fstat(child)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
          raise ValueError("Directory changed during inspection")
        children = _scan(child, dev, depth + 1, count)
      finally:
        os.close(child)
    result.append((name, st.st_ino, children))
  return result


def _remove(fd, entries, dev, guard):
  for name, inode, children in entries:
    guard()
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if st.st_dev != dev or st.st_ino != inode or stat.S_ISLNK(st.st_mode):
      raise ValueError("Contents changed; operation stopped")
    if children is None:
      if not stat.S_ISREG(st.st_mode):
        raise ValueError("File type changed")
      os.unlink(name, dir_fd=fd)
    else:
      child = os.open(name, DIR_FLAGS, dir_fd=fd)
      try:
        if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (dev, inode):
          raise ValueError("Directory changed")
        _remove(child, children, dev, guard)
      finally:
        os.close(child)
      os.rmdir(name, dir_fd=fd)



def _bytes(fd, dev, depth=0, count=None):
  """Sum regular-file sizes under an already-opened directory fd. Read-only."""
  count = [0] if count is None else count
  if depth > MAX_DEPTH:
    raise ValueError("Directory nesting exceeds safety limit")
  total = 0
  for name in os.listdir(fd):
    count[0] += 1
    if count[0] > MAX_ENTRIES:
      raise ValueError("Directory entry limit exceeded")
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if st.st_dev != dev or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
      raise ValueError("Symlink, mount or special file refused")
    if stat.S_ISREG(st.st_mode):
      total += st.st_size
    else:
      child = os.open(name, DIR_FLAGS, dir_fd=fd)
      try:
        opened = os.fstat(child)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
          raise ValueError("Directory changed during inspection")
        total += _bytes(child, dev, depth + 1, count)
      finally:
        os.close(child)
  return total


class LocalData:
  def __init__(self, offroad, capable, *, roots=None, recording=lambda: False):
    self.offroad, self.capable = offroad, capable
    self.roots = ROOTS if roots is None else roots  # fixtures only; UI never supplies this
    self.recording = recording

  def guard(self, category):
    if not self.offroad() or not self.capable():
      raise PermissionError("Offroad supported device required")
    if category not in self.roots:
      raise ValueError("Unknown data category")
    if category == "recordings" and self.recording():
      raise PermissionError("Stop recording before managing recordings")

  def _selected(self, fd, category, selected=None):
    dev = os.fstat(fd).st_dev
    entries = _scan(fd, dev)
    result = []
    for name, inode, children in entries:
      if category == "recordings":
        if name.endswith(".lock") or name.endswith(".part"):
          raise PermissionError("Recorder lock or partial file present")
        if children is not None or not name.lower().endswith(".mp4"):
          continue
      if selected is not None and name != selected:
        continue
      if category == "driving":
        if children is None:
          continue  # Never remove bootlog or unrelated root files.
        child = os.open(name, DIR_FLAGS, dir_fd=fd)
        try:
          if _preserved(child):
            continue
        finally:
          os.close(child)
      result.append((name, inode, children))
    return result

  def list_recordings(self):
    self.guard("recordings")
    try:
      with open_directory(self.roots["recordings"][0]) as fd:
        return tuple(e[0] for e in self._selected(fd, "recordings"))
    except FileNotFoundError:
      return ()

  def storage_use(self):
    """Read-only byte totals per local data category. Never mutates files."""
    if not self.offroad() or not self.capable():
      raise PermissionError("Offroad supported device required")
    report = {}
    for category, roots in self.roots.items():
      if category not in ROOTS and category not in self.roots:
        raise ValueError("Unknown data category")
      total = 0
      present = 0
      for root in roots:
        try:
          with open_directory(root) as fd:
            total += _bytes(fd, os.fstat(fd).st_dev)
            present += 1
        except FileNotFoundError:
          continue
      report[category] = {"bytes": int(total), "roots_present": present}
    return report


  def delete(self, category, selected=None):
    """Explicit invocation only, after UI confirmation; no root itself removed.

    Guard rechecked per root and immediately before mutation. A refusal may leave
    prior completed roots deleted; callers report failure, never claim success.
    """
    self.guard(category)
    if selected is not None:
      if category != "recordings":
        raise ValueError("Individual selection is recordings-only")
      valid_name(selected, ".mp4")
    removed = 0
    for root in self.roots[category]:
      try:
        with open_directory(root) as fd:
          entries = self._selected(fd, category, selected)
          self.guard(category)
          _remove(fd, entries, os.fstat(fd).st_dev, lambda: self.guard(category))
          removed += len(entries)
      except FileNotFoundError:
        continue
    return removed

  def rename_recording(self, old, new):
    self.guard("recordings")
    valid_name(old, ".mp4")
    new = new.strip().replace(" ", "_")
    if not new.lower().endswith(".mp4"):
      new += ".mp4"
    valid_name(new, ".mp4")
    with open_directory(self.roots["recordings"][0]) as fd:
      entries = self._selected(fd, "recordings", old)
      if not entries:
        raise FileNotFoundError(old)
      # No overwrite: same-directory hard link publication fails if dest exists.
      self.guard("recordings")
      os.link(old, new, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
      dst = os.stat(new, dir_fd=fd, follow_symlinks=False)
      if not stat.S_ISREG(dst.st_mode) or dst.st_ino != entries[0][1]:
        os.unlink(new, dir_fd=fd)
        raise ValueError("Recording changed during rename")
      self.guard("recordings")
      current = os.stat(old, dir_fd=fd, follow_symlinks=False)
      if not stat.S_ISREG(current.st_mode) or current.st_ino != entries[0][1]:
        os.unlink(new, dir_fd=fd)
        raise ValueError("Recording changed before source removal")
      os.unlink(old, dir_fd=fd)
      os.fsync(fd)
    return new


# Only feature-owned preferences, never identity/calibration/security/car config.
SYSTEM_KEYS = frozenset({"DeviceManagement", "DeviceShutdown", "LowVoltageShutdown", "ScreenManagement",
                        "ScreenBrightness", "ScreenBrightnessOnroad", "ScreenTimeout", "ScreenTimeoutOnroad",
                        "StandbyMode", "DebugMode", "NoLogging", "HigherBitrate", "OffroadScreensaver"})
RANGES = {"DeviceShutdown": (0, 33, 1), "LowVoltageShutdown": (11.8, 12.5, .1),
          "ScreenBrightness": (1, 101, 1), "ScreenBrightnessOnroad": (0, 101, 1),
          "ScreenTimeout": (5, 60, 5), "ScreenTimeoutOnroad": (5, 60, 5)}


class SystemPreferences:
  def __init__(self, store, offroad, capable, stats_backup_dir=None):
    self.store, self.offroad, self.capable = store, offroad, capable
    # INT t994 (review MAJOR 2): lifetime stats cannot be rebuilt, so RESET needs a durable copy first.
    self.stats_backup_dir = stats_backup_dir

  def guard(self):
    if not self.offroad() or not self.capable():
      raise PermissionError("Offroad supported device required")

  def _backup_stats(self, raw):
    if not self.stats_backup_dir:
      raise PermissionError("Stats backup directory required before reset")
    root = Path(self.stats_backup_dir)
    if not root.is_absolute() or ".." in root.parts or root.is_symlink():
      raise ValueError("Unsafe stats backup directory")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
      raise ValueError("Unsafe stats backup directory")
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    for n in range(1000):
      path = root / f"FrogPilotStats.{stamp}.{n}.json"
      try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        break
      except FileExistsError:
        continue
    else:
      raise OSError("No free stats backup name")
    with os.fdopen(fd, "wb") as f:
      f.write(raw.encode())
      f.flush()
      os.fsync(f.fileno())
    return str(path)

  def set(self, key, value):
    self.guard()
    if key not in SYSTEM_KEYS:
      raise ValueError("Preference outside System Settings scope")
    if key in RANGES:
      lo, hi, step = RANGES[key]
      value = float(value)
      if not lo <= value <= hi or abs((value - lo) / step - round((value - lo) / step)) > 1e-6:
        raise ValueError("Preference outside historical range/step")
      self.store.put(key, str(round(value, 1)) if step < 1 else str(int(value)))
    else:
      if type(value) is not bool:
        raise ValueError("Boolean required")
      self.store.put_bool(key, value)
    # ParamStore may fall back to file storage and suppress write exceptions.
    # Read back the effective store rather than reporting a registered key as working.
    actual = self.store.raw(key)
    if key in RANGES:
      if actual is None or abs(float(actual) - float(value)) > 1e-6:
        raise OSError("Preference write verification failed")
    elif actual != ("1" if value else "0"):
      raise OSError("Preference write verification failed")

  def stats(self):
    raw = self.store.get("FrogPilotStats", "") or "{}"
    if len(raw) > MAX_JSON:
      raise ValueError("Stats exceed display limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
      raise ValueError("Invalid stats object")
    return value

  def reset_stats(self):
    self.guard()
    raw = self.store.raw("FrogPilotStats")
    if raw not in (None, "", "{}"):
      self._backup_stats(raw)  # durable copy first; failure refuses the reset
    self.store.put("FrogPilotStats", "{}")
    if self.store.raw("FrogPilotStats") != "{}":
      raise OSError("Stats reset write verification failed")

  def export_stats(self, destination_dir):
    """Write a bounded FrogPilotStats JSON export into an already-scoped directory.

    destination_dir must be an absolute path supplied by the caller/tests; the UI
    never accepts free-form paths. Overwrite refused. No network upload.
    """
    self.guard()
    dest = Path(destination_dir)
    if not dest.is_absolute() or ".." in dest.parts:
      raise ValueError("Absolute export directory required")
    payload = json.dumps(self.stats(), sort_keys=True, ensure_ascii=True).encode()
    if len(payload) > MAX_JSON:
      raise ValueError("Stats exceed export limit")
    name = "bogpilot-stats-export.json"
    with open_directory(dest) as fd:
      try:
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
      except FileExistsError as exc:
        raise FileExistsError("Export target already exists") from exc
      with os.fdopen(out, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
      os.fsync(fd)
    return str(dest / name)



class PreferenceArchive:
  """System-owned toggle snapshots, not whole Params dumps or executable backups.

  Secrets, car identity, calibration, driving policy and cloud keys never enter
  this format. Restore validates *all* values, writes a durable pre-restore
  snapshot, and rolls back on write failure. No absent/default synthesis.
  """
  def __init__(self, preferences, root="/data/toggle_backups"):
    self.prefs = preferences
    self.root = Path(root)
    self.keys = SYSTEM_KEYS - {"DebugMode"}

  @contextmanager
  def directory(self, create=False):
    with open_directory(self.root.parent) as parent:
      if create:
        try:
          os.mkdir(self.root.name, 0o700, dir_fd=parent)
        except FileExistsError:
          pass
      fd = os.open(self.root.name, DIR_FLAGS, dir_fd=parent)
      try:
        yield fd
      finally:
        os.close(fd)

  def list(self):
    self.prefs.guard()
    try:
      with self.directory() as fd:
        return tuple(n for n in sorted(os.listdir(fd)) if n.startswith("system-") and n.endswith(".json")
                     and stat.S_ISREG(os.stat(n, dir_fd=fd, follow_symlinks=False).st_mode))
    except FileNotFoundError:
      return ()

  def backup(self):
    import hashlib
    self.prefs.guard()
    values = {k: self.prefs.store.raw(k) for k in sorted(self.keys)}
    values = {k: v for k, v in values.items() if v is not None}
    data = json.dumps({"version": 1, "scope": "system-settings", "values": values}, sort_keys=True).encode()
    if len(data) > MAX_JSON:
      raise ValueError("Snapshot exceeds size limit")
    name = "system-" + hashlib.sha256(data).hexdigest() + ".json"
    with self.directory(create=True) as fd:
      try:
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
      except FileExistsError:
        if self._read(fd, name) != json.loads(data):
          raise ValueError("Existing snapshot invalid")
      else:
        with os.fdopen(out, "wb") as f:
          f.write(data)
          f.flush()
          os.fsync(f.fileno())
        os.fsync(fd)
    return name

  def _read(self, fd, name):
    valid_name(name, ".json")
    if not name.startswith("system-"):
      raise ValueError("Not a System Settings snapshot")
    src = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(src, "rb") as f:
      if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
        raise ValueError("Regular snapshot required")
      raw = f.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
      raise ValueError("Snapshot exceeds size limit")
    doc = json.loads(raw)
    if set(doc) != {"version", "scope", "values"} or doc["version"] != 1 or doc["scope"] != "system-settings":
      raise ValueError("Unsupported snapshot schema")
    values = doc["values"]
    if not isinstance(values, dict) or set(values) - self.keys:
      raise ValueError("Snapshot outside preference allowlist")
    for key, value in values.items():
      if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid snapshot value")
      if key in RANGES:
        lo, hi, step = RANGES[key]
        n = float(value)
        if not lo <= n <= hi or abs((n-lo)/step - round((n-lo)/step)) > 1e-6:
          raise ValueError("Invalid numeric preference")
      elif value not in {"0", "1"}:
        raise ValueError("Invalid boolean preference")
    import hashlib
    canonical = json.dumps(doc, sort_keys=True).encode()
    if name != "system-" + hashlib.sha256(canonical).hexdigest() + ".json":
      raise ValueError("Snapshot digest mismatch")
    return doc

  def delete(self, name=None):
    self.prefs.guard()
    names = self.list() if name is None else (name,)
    with self.directory() as fd:
      for selected in names:
        self._read(fd, selected)  # Validate before any removal; never old unknown archives.
      for selected in names:
        self.prefs.guard()
        os.unlink(selected, dir_fd=fd)
      os.fsync(fd)
    return len(names)

  def restore(self, name):
    self.prefs.guard()
    with self.directory() as fd:
      values = self._read(fd, name)["values"]
    receipt = self.backup()  # Mandatory durable pre-restore snapshot.
    original = {k: self.prefs.store.raw(k) for k in values}
    try:
      for key, value in values.items():
        self.prefs.guard()
        self.prefs.set(key, float(value) if key in RANGES else value == "1")
    except Exception:
      # Best-effort rollback, report failures rather than silently applying half.
      failed = False
      for key, value in original.items():
        try:
          self.prefs.store.remove(key) if value is None else self.prefs.store.put(key, value)
        except Exception:
          failed = True
      if failed:
        raise RuntimeError("Restore failed; rollback incomplete; original snapshot retained") from None
      raise RuntimeError("Restore failed; original preferences restored") from None
    return receipt


class DurableStore:
  """Synchronous, verified-store writer; ParamStore's UI queue is not a receipt.

  Native typed writes use block=True. File-only feature writes are atomic and
  fsynced below the validated BogPilot root; no symlink destinations followed.
  """
  def __init__(self, base, allowed=None):
    self.base = base
    self.allowed = frozenset(allowed or (SYSTEM_KEYS | {"FrogPilotStats"}))

  def __getattr__(self, name):
    return getattr(self.base, name)

  def put_bool(self, key, value):
    self.put(key, "1" if value else "0")

  def put(self, key, value):
    if key not in self.allowed:
      raise ValueError("Write outside explicit preference scope")
    if hasattr(self.base, "is_param_key") and self.base.is_param_key(key):
      from openpilot.common.params import ParamKeyType
      native = self.base._params
      kind = native.get_type(key)
      text = str(value)
      if kind == ParamKeyType.BOOL:
        typed = text in {"1", "True", "true"}
      elif kind == ParamKeyType.INT:
        typed = int(float(text))
      elif kind == ParamKeyType.FLOAT:
        typed = float(text)
      elif kind == ParamKeyType.JSON:
        typed = json.loads(text)
      else:
        typed = text
      native.put(key, typed, block=True)
      self.base.invalidate(key)
    elif hasattr(self.base, "is_param_key"):
      import secrets
      from openpilot.common.bogpilot_store import bogpilot_dir
      root = bogpilot_dir()
      with open_directory(root.parent) as parent:
        try:
          os.mkdir(root.name, 0o700, dir_fd=parent)
        except FileExistsError:
          pass
      with open_directory(root) as fd:
        try:
          st = os.stat(key, dir_fd=fd, follow_symlinks=False)
          if not stat.S_ISREG(st.st_mode):
            raise ValueError("Nonregular preference target refused")
        except FileNotFoundError:
          pass
        temp = ".setting-" + secrets.token_hex(12)
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
          with os.fdopen(out, "wb") as f:
            f.write(str(value).encode())
            f.flush()
            os.fsync(f.fileno())
          os.rename(temp, key, src_dir_fd=fd, dst_dir_fd=fd)
          os.fsync(fd)
        finally:
          try:
            os.unlink(temp, dir_fd=fd)
          except FileNotFoundError:
            pass
      self.base.invalidate(key)
    else:
      self.base.put(key, value)  # In-memory native-test fixtures only.

  def remove(self, key):
    if key not in self.allowed:
      raise ValueError("Remove outside explicit preference scope")
    if hasattr(self.base, "is_param_key") and self.base.is_param_key(key):
      self.base._params.remove(key)
      self.base.invalidate(key)
    elif hasattr(self.base, "is_param_key"):
      from openpilot.common.bogpilot_store import bogpilot_dir
      with open_directory(bogpilot_dir()) as fd:
        try:
          st = os.stat(key, dir_fd=fd, follow_symlinks=False)
          if not stat.S_ISREG(st.st_mode):
            raise ValueError("Nonregular preference target refused")
          os.unlink(key, dir_fd=fd)
          os.fsync(fd)
        except FileNotFoundError:
          pass
      self.base.invalidate(key)
    else:
      self.base.remove(key)
    if self.base.raw(key) is not None:
      raise OSError("Preference removal verification failed")
