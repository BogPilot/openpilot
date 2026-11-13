"""BogPilot: NoLogging ON records nothing (BogPilot 0.9.7 allow_logging, process_config.py:50-51, :73-82 @568fea947).

Loads the real process_config.py / helpers.py / nologging.py with light stand-ins for the runtime-only modules
(Params, hardware, process classes, mapd supervisor), so it also runs on a checkout without msgq / zstandard.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

OP = Path(__file__).resolve().parents[3]  # .../openpilot
GATED_ONROAD = ("loggerd", "encoderd", "proclogd", "journald")
GATED_ALWAYS = ("logmessaged",)
UNCHANGED = ("deleter", "tombstoned", "camerad", "modeld", "controlsd", "card", "selfdrived", "pandad", "ui", "updated")


class FakeParams:
  store: dict = {}

  def __init__(self, *a, **k):
    pass

  def get(self, key, *a, **k):
    v = self.store.get(key)
    return None if v is None else v.encode()

  def get_bool(self, key, *a, **k):
    return self.store.get(key) == "1"

  def get_int(self, key, default=0, *a, **k):
    v = self.store.get(key)
    return int(v) if v is not None else default

  def put_bool(self, key, val, *a, **k):
    self.store[key] = "1" if val else "0"

  def get_param_path(self):
    return "/tmp/params-not-used"


class _Proc:
  def __init__(self, name, *args, enabled=True, **kw):
    self.name, self.enabled = name, enabled
    self.should_run = next(a for a in args if callable(a))


def _module(name, **attrs):
  m = types.ModuleType(name)
  m.__dict__.update(attrs)
  return m


def _load(name, rel):
  spec = importlib.util.spec_from_file_location(name, OP / rel)
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


@pytest.fixture
def env(monkeypatch):
  FakeParams.store = {}
  stubs = {
    "openpilot.common.params": _module("openpilot.common.params", Params=FakeParams),
    "openpilot.common.hardware": _module("openpilot.common.hardware", PC=False, COMMA_HARDWARE=True),
    # bogpilot_settings imports a name openpilot.common.version does not define (latent, DIVERGENCES_nologging.md):
    # make any import of it fail, so these tests prove the manager never needs it.
    "openpilot.common.bogpilot_settings": None,
    "openpilot.system.manager.process": _module("openpilot.system.manager.process", PythonProcess=_Proc,
                                                NativeProcess=_Proc, DaemonProcess=_Proc),
    "openpilot.system.bogpilot.osm.supervisor": _module("openpilot.system.bogpilot.osm.supervisor",
                                                        manager_condition=lambda *a: False),
  }
  for k, v in stubs.items():
    monkeypatch.setitem(sys.modules, k, v)
  settings = _load("openpilot.system.manager.nologging", "system/manager/nologging.py")
  monkeypatch.setitem(sys.modules, "openpilot.system.manager.nologging", settings)
  pc = _load("_nologging_process_config", "system/manager/process_config.py")
  helpers = _load("_nologging_helpers", "system/manager/helpers.py")
  monkeypatch.setattr(pc.os.path, "exists", lambda p: False)   # ublox probe: no device files here
  return types.SimpleNamespace(pc=pc, helpers=helpers, settings=settings)


CP_CAR = types.SimpleNamespace(notCar=False)


def _running(pc, started, cp=CP_CAR):
  """should_run only (enabled= is platform-dependent, e.g. proclogd/journald are off on macOS)."""
  params = FakeParams()
  return {p.name for p in pc.procs if p.should_run(started, params, cp)}


def _set(**vals):
  FakeParams.store.update({k: str(v) for k, v in vals.items()})


def test_default_off_launches_logging_as_before(env):
  assert env.settings._default("NoLogging") == "0"
  on, off = _running(env.pc, True), _running(env.pc, False)
  for name in GATED_ONROAD + GATED_ALWAYS + UNCHANGED[:8]:
    assert name in on, name
  for name in GATED_ONROAD:
    assert name not in off, name    # onroad only, as before
  assert "logmessaged" in off and "deleter" in off   # always_run, as before


@pytest.mark.parametrize("started", [True, False])
def test_nologging_on_launches_no_recorder(env, started):
  _set(NoLogging=1)
  running = _running(env.pc, started)
  for name in GATED_ONROAD + GATED_ALWAYS:
    assert name not in running, name
  if started:
    for name in UNCHANGED[:8]:   # driving, deleter and crash handling are untouched
      assert name in running, name


def test_explicit_off_equals_default(env):
  default_on, default_off = _running(env.pc, True), _running(env.pc, False)
  _set(NoLogging=0)
  assert _running(env.pc, True) == default_on and _running(env.pc, False) == default_off


def test_nologging_follows_0_9_7_parent_and_tuning_level(env):
  _set(NoLogging=1, DeviceManagement=0)
  assert "loggerd" in _running(env.pc, True)        # parent off: 0.9.7 ignores NoLogging
  _set(DeviceManagement=1, TuningLevelConfirmed=1, TuningLevel=1)
  assert "loggerd" in _running(env.pc, True)        # NoLogging is a level-2 toggle
  _set(TuningLevel=2)
  assert "loggerd" not in _running(env.pc, True)


def test_no_stream_or_qlog_encoder_process_left(env):
  names = {p.name for p in env.pc.procs}
  assert not {"stream_encoderd", "qcamerad", "webrtcd"} & names   # only encoderd writes HEVC/qcamera here


@pytest.mark.parametrize("on", [True, False])
def test_bootlog(env, monkeypatch, on):
  calls = []
  monkeypatch.setattr(env.helpers.shutil, "copytree", lambda *a, **k: calls.append("copytree"))
  monkeypatch.setattr(env.helpers.tempfile, "mkdtemp", lambda: "/tmp/x")
  monkeypatch.setattr(env.helpers.threading, "Thread", lambda *a, **k: types.SimpleNamespace(
    daemon=False, start=lambda: calls.append("bootlog")))
  _set(NoLogging=int(on))
  env.helpers.save_bootlog()
  assert calls == ([] if on else ["copytree", "bootlog"])


def test_default_off_matches_previous_process_config(env, tmp_path):
  """Default OFF: the launch set equals the pre-change process_config (onroad/offroad, car/notCar, DisableLogging)."""
  src = (OP / "system/manager/process_config.py").read_text()
  base = src.replace("from openpilot.system.manager.nologging import no_logging\n", "")
  base = base.replace('["./loggerd"], allow_logging)', '["./loggerd"], logging)')
  base = base.replace("and_(only_onroad, logging_allowed)", "only_onroad").replace("and_(always_run, logging_allowed)", "always_run")
  assert "logging_allowed)" not in base.split("procs = [", 1)[1] and "allow_logging)" not in base.split("procs = [", 1)[1]
  (tmp_path / "base_pc.py").write_text(base)
  spec = importlib.util.spec_from_file_location("_nologging_base_pc", tmp_path / "base_pc.py")
  old = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(old)
  for not_car in (False, True):
    for disable in ("0", "1", None):
      FakeParams.store = {} if disable is None else {"DisableLogging": disable}
      cp = types.SimpleNamespace(notCar=not_car)
      for started in (True, False):
        assert _running(env.pc, started, cp) == _running(old, started, cp), (not_car, disable, started)


@pytest.mark.parametrize("on", [False, True])
def test_manager_imports_and_starts_without_bogpilot_settings(monkeypatch, on):
  """Manager import + first launch-set evaluation with NoLogging OFF and ON, with the real openpilot.common.version
  and the real nologging module, and bogpilot_settings unimportable (an rc9 build crashed here on BOGPILOT_BRANCHES)."""
  FakeParams.store = {"DeviceManagement": "1", "NoLogging": str(int(on))}
  for k, v in {
    "openpilot.common.params": _module("openpilot.common.params", Params=FakeParams),
    "openpilot.common.hardware": _module("openpilot.common.hardware", PC=False, COMMA_HARDWARE=True),
    "openpilot.system.manager.process": _module("openpilot.system.manager.process", PythonProcess=_Proc,
                                                NativeProcess=_Proc, DaemonProcess=_Proc),
    "openpilot.system.bogpilot.osm.supervisor": _module("openpilot.system.bogpilot.osm.supervisor",
                                                        manager_condition=lambda *a: False),
    "openpilot.common.bogpilot_settings": None,
  }.items():
    monkeypatch.setitem(sys.modules, k, v)
  monkeypatch.delitem(sys.modules, "openpilot.system.manager.nologging", raising=False)
  pc = _load("_nologging_start_pc", "system/manager/process_config.py")
  helpers = _load("_nologging_start_helpers", "system/manager/helpers.py")
  monkeypatch.setattr(pc.os.path, "exists", lambda p: False)
  for started in (False, True):
    running = _running(pc, started)
    assert {"pandad", "ui"} <= running
    assert ("loggerd" in running) == (started and not on)
    assert ("logmessaged" in running) == (not on)
  assert callable(helpers.save_bootlog)
  for rel in ("system/manager/process_config.py", "system/manager/helpers.py", "system/manager/nologging.py"):
    assert "bogpilot_settings" not in (OP / rel).read_text().split('"""', 2)[-1], rel
