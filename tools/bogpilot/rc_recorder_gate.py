#!/usr/bin/env python3
"""Independent recorder acceptance. No singleton, device, screen or native imports.

Run on the authorized Mac/AGNOS VM only. All output uses an owned temporary
sandbox. Fault injections are labelled synthetic. Missing dependencies are
PENDING, not PASS. No third-party packages are required.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import datetime
import errno
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

FRAME = bytes([25, 80, 120, 255]) * (16 * 16)


class Pending(Exception):
  pass


def require(condition, message):
  if not condition:
    raise AssertionError(message)


def wait_for(predicate, timeout=2.0):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    if predicate():
      return
    threading.Event().wait(0.005)
  raise AssertionError("bounded worker wait expired")


def load_recorder(path, source=None):
  path = Path(path).resolve(strict=True)
  spec = importlib.util.spec_from_file_location("_rc_recorder_subject", path)
  module = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = module
  source = path.read_bytes() if source is None else source
  exec(compile(source, str(path), "exec"), module.__dict__)
  # Never call recorder()/capture_hook() here. Logging remains sandbox-local.
  module.log_error = lambda message: None
  return module


@dataclass
class Result:
  name: str
  evidence: str
  status: str
  detail: str = ""


class FakeEncoder:
  """Synthetic I/O fault boundary around the actual threaded RecorderEngine."""
  def __init__(self, path, width, height, *, fault=None):
    self.path, self.width, self.height = path, width, height
    self.error = None
    self.frames = 0
    self.fault = fault
    self.running = False
    self.closed = False

  def open(self):
    if self.fault == "open":
      self.error = "synthetic encoder launch failure"
      return False
    Path(self.path + ".lock").write_text("synthetic")
    Path(self.path).write_bytes(b"synthetic-not-video\n")
    self.running = True
    return True

  def alive(self):
    return self.running

  def write(self, data):
    if self.fault == "enospc" or not self.running:
      self.error = str(OSError(errno.ENOSPC if self.fault == "enospc" else errno.EPIPE, "synthetic write failure"))
      return False
    self.frames += 1
    return True

  def close(self):
    self.closed = True
    self.running = False
    Path(self.path + ".lock").unlink(missing_ok=True)
    if self.fault in ("close", "enospc", "dead") or not self.frames:
      self.error = self.error or "synthetic finalization failure"
      Path(self.path).unlink(missing_ok=True)
      return False
    return True


class Harness:
  def __init__(self, module, directory, fault=None):
    self.module, self.directory, self.fault = module, directory, fault
    self.encoders = []
    self.now = 10.0
    self.free = 1 << 40

  def factory(self, path, width, height):
    require(Path(path).resolve().is_relative_to(self.directory.resolve()), "encoder escaped sandbox")
    encoder = FakeEncoder(path, width, height, fault=self.fault)
    self.encoders.append(encoder)
    return encoder

  @contextmanager
  def engine(self, **kwargs):
    e = self.module.RecorderEngine(directory=str(self.directory), min_free=1024, fps=10,
                                   encoder_factory=self.factory, free_fn=lambda path: self.free,
                                   clock=lambda: self.now, wallclock=lambda: datetime.datetime(2026, 1, 2, 12, 0, 0),
                                   **kwargs)
    try:
      yield e
    finally:
      e.stop()

  def feed(self, engine):
    engine.submit_frame(FRAME, 16, 16, 1)

  def first_frame(self, engine):
    require(engine.start(), "start refused")
    self.feed(engine)
    wait_for(lambda: self.encoders and self.encoders[-1].frames > 0)


def run_gate(path, *, hud_path=None, real=True):
  results = []

  def check(name, evidence, fn):
    try:
      fn()
    except Pending as error:
      results.append(Result(name, evidence, "PENDING", str(error)))
    except Exception as error:
      results.append(Result(name, evidence, "FAIL", f"{type(error).__name__}: {error}"))
    else:
      results.append(Result(name, evidence, "PASS"))

  try:
    source = Path(path).read_bytes()
    module = load_recorder(path, source=source)
  except Exception as error:
    return {"source_sha256": None, "results": [asdict(Result("module_available", "actual API", "PENDING", str(error)))],
            "counts": {"PASS": 0, "FAIL": 0, "PENDING": 1}}

  with tempfile.TemporaryDirectory(prefix="bp-recorder-gate-") as tmp:
    root = Path(tmp)
    snapshot = root / "subject_snapshot.py"
    snapshot.write_bytes(source)

    def sandbox(name, test, fault=None, **kwargs):
      directory = root / name
      harness = Harness(module, directory, fault)
      with harness.engine(**kwargs) as engine:
        test(harness, engine)

    def low_space(h, e):
      h.free = 0
      require(not e.start() and not e.recording and bool(e.last_error), "low space must refuse with error")
    check("low_space_start", "actual API / synthetic disk-space boundary", lambda: sandbox("low", low_space))

    def invalid_path():
      p = root / "not-a-directory"
      p.write_text("fixture")
      h = Harness(module, p)
      with h.engine() as e:
        require(not e.start() and not e.recording and bool(e.last_error), "invalid path must refuse visibly")
    check("invalid_output_path", "actual filesystem sandbox", invalid_path)

    def permissions(h, e):
      with patch.object(module.os, "makedirs", side_effect=PermissionError(errno.EACCES, "synthetic denied")):
        require(not e.start() and not e.recording and bool(e.last_error), "EACCES must refuse with error")
    check("path_permissions", "actual API / synthetic EACCES", lambda: sandbox("permissions", permissions))

    def startup_failure(h, e):
      require(e.start(), "setup start refused")
      h.feed(e)
      wait_for(lambda: not e.recording)
      require(bool(e.last_error) and not e.saved, "launch failure must clear recording and expose error")
    check("encoder_launch_failure", "actual API / synthetic encoder", lambda: sandbox("launch", startup_failure, "open"))

    def indicator_before_encoder(h, e):
      require(e.start(), "start refused")
      rec = module.ScreenRecorder(e)
      active = e.encoder is not None and e.encoder.alive() and e.encoder.frames > 0
      require(not rec.recording or active, "UI recording=true before encoder exists or any frame is accepted")
    check("indicator_before_first_frame", "actual ScreenRecorder property / synthetic encoder", lambda: sandbox("indicator", indicator_before_encoder))

    def stop_finalize(h, e):
      h.first_frame(e)
      e.stop()
      require(not e.recording and len(e.saved) == 1, "stop must finalize exactly one segment")
      require(h.encoders[0].closed and not list(h.directory.glob("*.lock")), "stop left encoder/lock")
      e.stop()
    check("stop_finalization", "actual API / synthetic file writer (not video)", lambda: sandbox("stop", stop_finalize))

    def fault_during_write(h, e):
      require(e.start(), "start refused")
      h.feed(e)
      wait_for(lambda: not e.recording)
      e.stop()
      require(bool(e.last_error) and not e.saved and not list(h.directory.glob("*.mp4*")), "failed partial must be removed with error")
    check("disk_full_write", "actual API / synthetic ENOSPC", lambda: sandbox("full", fault_during_write, "enospc"))

    def close_failure(h, e):
      h.first_frame(e)
      e.stop()
      require(not e.saved and bool(e.last_error) and not list(h.directory.glob("*.mp4*")), "finalize failure must not report saved")
    check("finalization_failure", "actual API / synthetic close failure", lambda: sandbox("close", close_failure, "close"))

    def pressure(h, e):
      h.first_frame(e)
      h.free = 0
      h.now += 6
      h.feed(e)
      wait_for(lambda: not e.recording)
      require(bool(e.last_error), "running low-space stop missing error")
    check("running_low_space", "actual API / synthetic space decrease", lambda: sandbox("pressure", pressure))

    def rotation(h, e):
      h.first_frame(e)
      h.now += 2
      h.feed(e)
      wait_for(lambda: len(h.encoders) == 2 and h.encoders[-1].frames > 0)
      e.stop()
      require(len(e.saved) == 2 and len(set(e.saved)) == 2, "rotation must save distinct finalized segments")
      require(all(enc.closed for enc in h.encoders), "rotation left encoder open")
    check("segment_rotation_collision", "actual API / synthetic encoder + time", lambda: sandbox("rotate", rotation, max_segment_s=1))

    def repeated(h, e):
      rec = module.ScreenRecorder(e)
      for _ in range(4):
        require(rec.toggle(), "toggle on refused")
        h.feed(e)
        wait_for(lambda: h.encoders and h.encoders[-1].frames > 0 and not h.encoders[-1].closed)
        require(not rec.toggle() and not rec.recording, "toggle off left indicator active")
      require(len(e.saved) == 4 and len(set(e.saved)) == 4, "repeated toggles lost/overwrote segments")
    check("repeated_toggle", "actual ScreenRecorder API / synthetic encoder", lambda: sandbox("toggle", repeated))

    def dead_idle(h, e):
      h.first_frame(e)
      h.encoders[-1].running = False
      h.encoders[-1].fault = "dead"
      rec = module.ScreenRecorder(e)
      require(not rec.recording, "UI recording=true after encoder process is dead while no new frames arrive")
    check("dead_process_indicator", "actual UI property / synthetic process death", lambda: sandbox("dead", dead_idle))

    def drive_exit(h, e):
      callbacks, hooks = [], []
      gui = SimpleNamespace(add_frame_hook=hooks.append)
      state = SimpleNamespace(add_offroad_transition_callback=callbacks.append)
      rec = module.ScreenRecorder(e)
      with patch.dict(sys.modules, {
          "openpilot.system.ui.lib.application": SimpleNamespace(gui_app=gui),
          "openpilot.selfdrive.ui.ui_state": SimpleNamespace(ui_state=state)}), \
          patch.object(module, "ScreenRecorder", return_value=rec), patch.object(module, "_recorder", None):
        require(module.recorder() is rec and len(callbacks) == 1 and len(hooks) == 1, "lifecycle registration missing")
        h.first_frame(e)
        callbacks[0]()
        require(not rec.recording and len(e.saved) == 1 and h.encoders[0].closed, "drive exit did not finalize")
    check("drive_exit_callback", "actual singleton registration / synthetic GUI and encoder; capture hook NEVER invoked", lambda: sandbox("drive", drive_exit))

    def shutdown():
      # Exercise normal Python process shutdown with an actual RecorderEngine
      # and a tiny injected writer. No GUI/framebuffer and no real video capture.
      child = r'''
import importlib.util, sys, time
from pathlib import Path
spec=importlib.util.spec_from_file_location("subject",sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.log_error=lambda message: None
root=Path(sys.argv[2])
class Encoder:
 def __init__(self,path,w,h): self.path=path; self.error=None; self.frames=0
 def open(self): return True
 def alive(self): return True
 def write(self,data): self.frames+=1; return True
 def close(self): (root/"finalized").write_text("closed"); return True
e=m.RecorderEngine(directory=str(root),encoder_factory=Encoder,free_fn=lambda p: 1<<40)
e.start(); e.submit_frame(bytes(16*16*4),16,16,1)
deadline=time.monotonic()+2
while (e.encoder is None or e.encoder.frames==0) and time.monotonic()<deadline: time.sleep(.005)
assert e.encoder is not None and e.encoder.frames>0
# Intentionally normal interpreter exit, no explicit stop: lifecycle acceptance.
'''
      directory = root / "shutdown"
      directory.mkdir()
      result = subprocess.run([sys.executable, "-c", child, str(snapshot), str(directory)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6)
      require(result.returncode == 0, "shutdown fixture child failed")
      require((directory / "finalized").exists(), "normal process shutdown did not finalize active engine")
    check("normal_process_shutdown", "actual engine / controlled child + synthetic writer", shutdown)

    def error_ui():
      if hud_path is None:
        raise Pending("supply --hud-module for actual RecordButton error-state audit")
      tree = ast.parse(Path(hud_path).read_text())
      cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RecordButton"), None)
      require(cls is not None, "RecordButton missing")
      # Static audit only: require an error/status input in actual render path;
      # it is not a claim that native error rendering has been verified.
      render = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_render")
      attrs = {n.attr for n in ast.walk(render) if isinstance(n, ast.Attribute)}
      require(bool(attrs & {"last_error", "error", "status", "state", "error_message"}), "actual RecordButton._render consumes recording only; no visible error/status input")
    check("error_ui_input_audit", "actual UI AST only; native error rendering remains unverified", error_ui)

    def actual_process_failure():
      executable = shutil.which("false")
      if executable is None:
        raise Pending("existing false executable unavailable")
      out = root / "failed-process.mp4"
      enc = module.FfmpegEncoder(str(out), 16, 16, 10, 64000, ffmpeg=executable)
      try:
        require(enc.open(), "controlled failure process could not launch")
        wait_for(lambda: not enc.alive())
        require(not enc.close() and bool(enc.error), "nonzero process exit must expose failure")
        require(not out.exists() and not Path(str(out) + ".lock").exists(), "failed process left partial/lock")
      finally:
        if enc.proc is not None:
          enc.close()
    check("actual_encoder_process_failure", "actual FfmpegEncoder / existing false process, NO CAPTURE", actual_process_failure)

    def real_encode():
      if not real:
        raise Pending("real encoder smoke explicitly disabled")
      if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise Pending("existing ffmpeg/ffprobe unavailable; no dependency installed")
      out = root / "real.mp4"
      enc = module.FfmpegEncoder(str(out), 16, 16, 10, 64000)
      try:
        require(enc.open(), "real encoder open failed")
        require(enc.alive(), "real encoder exited before frames")
        for _ in range(3):
          require(enc.write(FRAME), "real encoder write failed")
        require(enc.close(), "real encoder finalization failed: " + str(enc.error))
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                                "-show_entries", "stream=codec_name,width,height,nb_read_frames", "-of", "json", str(out)],
                               capture_output=True, text=True, timeout=5, check=True)
        stream = json.loads(probe.stdout)["streams"][0]
        require((stream["codec_name"], stream["width"], stream["height"], int(stream["nb_read_frames"])) == ("h264", 16, 16, 3), "real finalized media shape/count mismatch")
        require(not Path(str(out) + ".lock").exists(), "real finalized media lock remained")
      finally:
        if enc.proc is not None:
          enc.close()
    check("real_h264_finalization_probe", "actual FfmpegEncoder / 3 tiny sandbox RGBA frames (NO CAPTURE)", real_encode)

  counts = {status: sum(r.status == status for r in results) for status in ("PASS", "FAIL", "PENDING")}
  return {"source_sha256": hashlib.sha256(source).hexdigest(), "results": [asdict(r) for r in results], "counts": counts}


def exit_code(report):
  return 1 if report["counts"]["FAIL"] else 2 if report["counts"]["PENDING"] else 0


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--recorder-module", required=True, type=Path)
  parser.add_argument("--hud-module", type=Path)
  parser.add_argument("--skip-real-encoder", action="store_true", help="reports PENDING, never PASS")
  args = parser.parse_args()
  report = run_gate(args.recorder_module, hud_path=args.hud_module, real=not args.skip_real_encoder)
  print(json.dumps(report, indent=2))
  return exit_code(report)


if __name__ == "__main__":
  raise SystemExit(main())
