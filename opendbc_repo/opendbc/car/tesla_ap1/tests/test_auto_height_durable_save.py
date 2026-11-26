"""Auto Height settings save (ride_height.SettingsWriter): stock toggle durability (tmp, fsync, rename, directory fsync) on a
short background thread, latest tap wins, pending values readable at once, nothing lost at a normal exit."""
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time

import pytest

from opendbc.car.tesla_ap1 import ride_height as RH
from opendbc.car.tesla_ap1.preap import params as PP


@pytest.fixture
def writer(monkeypatch):
  def use(write=None):
    w = RH.SettingsWriter(write=write)
    monkeypatch.setattr(RH, "_settings_writer", w)
    return w
  return use


def test_a_tap_is_written_like_a_stock_toggle_in_order(tmp_path, writer, monkeypatch):
  w = writer()
  dest = tmp_path / RH.ENABLE_KEY
  events = []
  real_mkstemp, real_fsync, real_replace, real_open = tempfile.mkstemp, os.fsync, os.replace, os.open
  fd_names = {}

  def mkstemp(*a, **k):
    fd, name = real_mkstemp(*a, **k)
    fd_names[fd] = name
    events.append(("tmp", os.path.basename(name)))
    return fd, name

  def osopen(path, flags, *a, **k):
    fd = real_open(path, flags, *a, **k)
    fd_names[fd] = os.fspath(path)
    return fd

  def fsync(fd):
    name = fd_names.get(fd)
    events.append(("fsync_dir" if name and os.path.isdir(name) else "fsync_file", None))
    return real_fsync(fd)

  def replace(src, dst):
    events.append(("rename", os.path.basename(os.fspath(dst))))
    return real_replace(src, dst)

  monkeypatch.setattr(tempfile, "mkstemp", mkstemp)
  monkeypatch.setattr(os, "fsync", fsync)
  monkeypatch.setattr(os, "replace", replace)
  monkeypatch.setattr(os, "open", osopen)
  RH.set_enabled(True, path=dest)
  assert w.flush(5.0)
  kinds = [e[0] for e in events]
  assert kinds == ["tmp", "fsync_file", "rename", "fsync_dir"], events
  assert events[2][1] == RH.ENABLE_KEY and events[0][1].startswith(RH.ENABLE_KEY + ".") and events[0][1].endswith(".tmp")
  assert dest.read_text() == "1" and (dest.stat().st_mode & 0o777) == 0o644
  assert [p.name for p in tmp_path.iterdir()] == [RH.ENABLE_KEY]          # no tmp left behind
  assert w.writes == 1 and w.errors == 0


def test_the_ui_never_waits_and_reads_the_new_value_at_once(tmp_path, writer):
  gate, started = threading.Event(), threading.Event()

  def slow(path, text):
    started.set()
    gate.wait(5)
    PP.write_file_durable(path, text)

  w = writer(slow)
  dest = tmp_path / RH.ENABLE_KEY
  t0 = time.monotonic()
  RH.set_enabled(True, path=dest)
  assert time.monotonic() - t0 < 0.05                    # returned while the flash write is still blocked
  assert started.wait(5)
  assert not dest.exists() and RH.enabled(path=dest) is True   # this process already sees it
  gate.set()
  assert w.flush(5.0) and dest.read_text() == "1" and w.pending(dest) is None


def test_fast_taps_keep_only_the_latest_value_per_file(tmp_path, writer):
  gate, written = threading.Event(), []

  def slow(path, text):
    gate.wait(5)
    written.append((path.name, text))
    PP.write_file_durable(path, text)

  w = writer(slow)
  park, drive = tmp_path / RH.HEIGHT_KEY, tmp_path / RH.DRIVE_HEIGHT_KEY
  RH.set_height("low", path=park)                         # the thread takes this one and blocks on it
  time.sleep(0.05)
  for h in ("medium", "high", "very_high", "none", "medium", "high"):
    RH.set_height(h, path=park)
  RH.set_drive_height("very_high", path=drive)
  assert RH.height(path=park) == "high" and RH.drive_height(path=drive) == "very_high"
  gate.set()
  assert w.flush(5.0)
  assert written == [(RH.HEIGHT_KEY, "low"), (RH.HEIGHT_KEY, "high"), (RH.DRIVE_HEIGHT_KEY, "very_high")]
  assert park.read_text() == "high" and drive.read_text() == "very_high"


def test_a_failed_write_is_counted_and_the_file_keeps_its_old_value(tmp_path, writer):
  dest = tmp_path / RH.ENABLE_KEY
  dest.write_text("0")

  def broken(path, text):
    raise OSError(28, "No space left on device")

  w = writer(broken)
  RH.set_enabled(True, path=dest)
  assert w.flush(5.0) and w.errors == 1 and w.pending(dest) is None
  assert dest.read_text() == "0" and RH.enabled(path=dest) is False


def test_nothing_is_lost_at_a_normal_exit(tmp_path):
  dest = tmp_path / RH.DRIVE_HEIGHT_KEY
  script = textwrap.dedent(f"""
    import time
    from pathlib import Path
    from opendbc.car.tesla_ap1 import ride_height as RH
    from opendbc.car.tesla_ap1.preap import params as PP
    def slow(path, text):
      time.sleep(0.5)                 # the interpreter is already exiting when this lands
      PP.write_file_durable(path, text)
    RH._settings_writer = RH.SettingsWriter(write=slow)
    RH.set_drive_height("high", path=Path({str(dest)!r}))
    RH.set_drive_height("low", path=Path({str(dest)!r}))
  """)
  r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30, env=dict(os.environ))
  assert r.returncode == 0, r.stderr
  assert dest.read_text() == "low"


def test_air_suspension_detection_is_unchanged_and_synchronous(tmp_path, writer):
  w = writer()
  p = tmp_path / RH.DETECTED_KEY
  assert RH.write_air_suspension_detected(True, path=p) is True
  assert p.read_text() == "1" and w.writes == 0           # card's change only write is not moved to the UI writer
