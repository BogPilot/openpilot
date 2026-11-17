"""Atomic replace of /data/params_bogpilot files: a concurrent reader never sees a torn write.

07e8bd68f's StepCache writes these files from a background thread. Path.write_text truncates
first, so a reader can see empty text and fall back to the default. _write_text_file now
writes a tmp in the same directory, fsyncs, and os.replace.
"""
import os
from pathlib import Path
import stat
import tempfile
import threading
import time

import pytest

from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401

KEY = K.PEDAL_CALIB_MESSAGE   # default ""
VALUES = ("alpha", "bravo")
STRESS_WRITES = 200
STRESS_ROUNDS = 80
MUTANT_ROUNDS = 80


def _inplace_write(key: str, text: str) -> None:
  """The 07e8bd68f in-place write: truncate, then write (mutant)."""
  params._params_dir.mkdir(parents=True, exist_ok=True)
  params._path(key).write_text(text, encoding="utf-8")


def _race(write_fn, n_writes=STRESS_WRITES) -> list[str]:
  """Writer alternates known values; the reader hammers _read_text_file. Returns bad reads."""
  bad = []
  stop = threading.Event()
  write_fn(KEY, VALUES[0])

  def reader():
    while not stop.is_set():
      text = params._read_text_file(KEY)
      if text not in VALUES:
        bad.append(text)
        return

  t = threading.Thread(target=reader, name="params_stress_reader")
  t.start()
  try:
    for i in range(n_writes):
      write_fn(KEY, VALUES[i % 2])
  finally:
    stop.set()
    t.join(timeout=2.0)
  text = params._read_text_file(KEY)
  if text not in VALUES:
    bad.append(text)
  leftovers = [n for n in os.listdir(params._params_dir) if n.endswith(".tmp") or (KEY + ".") in n and n != KEY]
  if leftovers:
    bad.append("leftover:" + ",".join(sorted(leftovers)))
  return bad


def test_atomic_write_reader_never_sees_empty_or_default(_params_dir):
  bads = []
  for i in range(STRESS_ROUNDS):
    bad = _race(params._write_text_file)
    if bad:
      bads.append((i, bad[:5]))
  assert bads == [], f"atomic write leaked empty/default or left tmp in {len(bads)}/{STRESS_ROUNDS} rounds: {bads[:3]}"


def test_mutant_inplace_write_is_caught_with_high_probability(_params_dir):
  kills = 0
  for _ in range(MUTANT_ROUNDS):
    if _race(_inplace_write):
      kills += 1
  rate = kills / MUTANT_ROUNDS
  # The in-place truncate-then-write must be visible to a hammering reader often
  # enough that this test is not a coin flip. Report the measured kill rate.
  assert rate >= 0.25, f"inplace mutant kill rate {rate:.2f} ({kills}/{MUTANT_ROUNDS}) is too low to trust"
  print(f"inplace_mutant_kill_rate={rate:.3f} kills={kills} rounds={MUTANT_ROUNDS}")


def test_failed_write_removes_only_the_tmp(_params_dir, monkeypatch):
  params._write_text_file(KEY, VALUES[0])
  dest = params._path(KEY)
  real_replace = os.replace

  def boom(src, dst):
    raise OSError("replace failed")

  monkeypatch.setattr(os, "replace", boom)
  with pytest.raises(OSError, match="replace failed"):
    params._write_text_file(KEY, VALUES[1])
  assert dest.read_text(encoding="utf-8") == VALUES[0]     # destination unchanged
  leftovers = list(params._params_dir.iterdir())
  assert leftovers == [dest], leftovers


def _write_text_92aa(key: str, text: str) -> None:
  """The 92aa9ee1f in-place write (then `_write_text`): mkdir, then Path.write_text."""
  params._params_dir.mkdir(parents=True, exist_ok=True)
  params._path(key).write_text(text, encoding="utf-8")


def test_panda_firmware_bytes_and_mode_match_92aa(_params_dir):
  """AP1: pandad writes PandaFirmwareVersion through this helper. Bytes and mode must
  match the 92aa in-place write for a new file and for an existing file."""
  key = K.PANDA_FIRMWARE
  text_new = "board.panda version-test\n"
  text_upd = "board.panda version-test-2\n"
  base = params._params_dir
  saved_dir = base

  def snap(path):
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)

  try:
    # New file: old helper in one dir, new helper in another.
    old_dir, new_dir = base / "ref_new", base / "atomic_new"
    params._params_dir = old_dir
    _write_text_92aa(key, text_new)
    params._params_dir = new_dir
    params._write_text_file(key, text_new)
    old_b, old_m = snap(old_dir / key)
    new_b, new_m = snap(new_dir / key)
    assert old_b == new_b == text_new.encode("utf-8")
    assert old_m == new_m
    assert old_m == 0o644

    # Existing 0o644 file, then a second write of new contents.
    old_ex, new_ex = base / "ref_ex", base / "atomic_ex"
    for d, write in ((old_ex, _write_text_92aa), (new_ex, params._write_text_file)):
      params._params_dir = d
      _write_text_92aa(key, text_new)
      os.chmod(d / key, 0o644)
      write(key, text_upd)
    old_b, old_m = snap(old_ex / key)
    new_b, new_m = snap(new_ex / key)
    assert old_b == new_b == text_upd.encode("utf-8")
    assert old_m == new_m == 0o644

    # Existing non-default mode must be kept (Path.write_text does not change it).
    old_k, new_k = base / "ref_600", base / "atomic_600"
    for d, write in ((old_k, _write_text_92aa), (new_k, params._write_text_file)):
      params._params_dir = d
      _write_text_92aa(key, text_new)
      os.chmod(d / key, 0o600)
      write(key, text_upd)
    old_b, old_m = snap(old_k / key)
    new_b, new_m = snap(new_k / key)
    assert old_b == new_b == text_upd.encode("utf-8")
    assert old_m == new_m == 0o600
  finally:
    params._params_dir = saved_dir


def test_mkstemp_dir_is_the_key_directory(_params_dir, monkeypatch):
  """The tmp must be created in the key's directory so os.replace cannot raise EXDEV.
  set_* swallow OSError, so a tmp on another filesystem would silently not save."""
  key = K.PANDA_FIRMWARE
  dest = params._path(key)
  recorded = {}
  real = tempfile.mkstemp

  def wrap(*args, **kwargs):
    fd, name = real(*args, **kwargs)
    recorded["dir"] = kwargs.get("dir")
    recorded["name"] = name
    recorded["parent"] = str(Path(name).parent)
    return fd, name

  monkeypatch.setattr(tempfile, "mkstemp", wrap)
  params._write_text_file(key, "firmware-dir-check")
  assert recorded["dir"] == str(dest.parent)
  assert recorded["parent"] == str(dest.parent)
  assert dest.read_text(encoding="utf-8") == "firmware-dir-check"


def test_fsync_is_called_on_the_tmp_file_and_the_key_directory(_params_dir, monkeypatch):
  """os.fsync must run on the tmp file and on the key directory. A missing call is a silent durability gap."""
  key = K.PANDA_FIRMWARE
  dest = params._path(key)
  opened = {}
  calls = []
  real_fsync = os.fsync
  real_open = os.open
  real_mkstemp = tempfile.mkstemp

  def wrap_mkstemp(*args, **kwargs):
    fd, name = real_mkstemp(*args, **kwargs)
    opened[fd] = name
    return fd, name

  def wrap_open(path, flags, *args, **kwargs):
    fd = real_open(path, flags, *args, **kwargs)
    opened[fd] = os.fspath(path)
    return fd

  def wrap_fsync(fd):
    path = opened.get(fd)
    if path is None:
      for cand in (f"/proc/self/fd/{fd}", f"/dev/fd/{fd}"):
        try:
          path = os.readlink(cand)
          break
        except OSError:
          continue
    calls.append(path)
    return real_fsync(fd)

  monkeypatch.setattr(tempfile, "mkstemp", wrap_mkstemp)
  monkeypatch.setattr(os, "open", wrap_open)
  monkeypatch.setattr(os, "fsync", wrap_fsync)

  params._write_text_file(key, "fsync-record")
  assert dest.read_text(encoding="utf-8") == "fsync-record"
  assert calls, "os.fsync was not called"
  dest_parent = dest.parent.resolve()
  tmp_hits = [p for p in calls if p and Path(p).name.startswith(dest.name + ".") and str(p).endswith(".tmp")]
  dir_hits = []
  for p in calls:
    if not p:
      continue
    try:
      if Path(p).resolve() == dest_parent:
        dir_hits.append(p)
    except OSError:
      if os.path.abspath(p) == os.path.abspath(str(dest.parent)):
        dir_hits.append(p)
  assert tmp_hits, f"no tmp-file fsync in {calls}"
  assert dir_hits, f"no directory fsync in {calls}"
