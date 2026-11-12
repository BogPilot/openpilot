"""tools/bogpilot/settings_row_dump.py refuses to run on a device, and --one refuses a real params store, before any
store or Params write. Pure Python: no window, runs headless."""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

from openpilot.common import hardware

TOOL = Path(__file__).resolve().parents[4] / "tools" / "bogpilot" / "settings_row_dump.py"


@pytest.fixture
def dump(monkeypatch):
  spec = importlib.util.spec_from_file_location("settings_row_dump_under_test", TOOL)
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  calls = []
  monkeypatch.setattr(mod, "run_one", lambda *a: calls.append(a))   # stands in for every store / Params write
  mod.calls = calls
  return mod


def run(mod, monkeypatch, params_dir, *argv):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(params_dir))
  monkeypatch.delenv("PARAMS_ROOT", raising=False)
  monkeypatch.setattr(sys, "argv", ["settings_row_dump.py", *argv])
  return mod.main()


def test_device_is_refused_with_no_write(dump, monkeypatch):
  monkeypatch.setattr(hardware, "PC", False)
  bp = Path(tempfile.mkdtemp(prefix="rowdump-guard-")) / "bp"
  bp.mkdir()
  assert run(dump, monkeypatch, bp, "--one", "ap1", "2", "defaults", str(bp.parent / "out.txt")) == 2
  assert dump.calls == []
  assert list(bp.iterdir()) == []
  assert not (bp.parent / "out.txt").exists()


def test_device_also_refuses_batch_mode(dump, monkeypatch):
  monkeypatch.setattr(hardware, "PC", False)
  out = Path(tempfile.mkdtemp(prefix="rowdump-guard-")) / "out"
  assert run(dump, monkeypatch, out.parent / "bp", "--out", str(out)) == 2
  assert not out.exists()


def test_temp_dir_on_a_pc_is_allowed(dump, monkeypatch):
  monkeypatch.setattr(hardware, "PC", True)
  bp = Path(tempfile.mkdtemp(prefix="rowdump-guard-")) / "bp"
  assert run(dump, monkeypatch, bp, "--one", "ap1", "2", "defaults", "out.txt") == 0
  assert dump.calls == [("ap1", 2, "defaults", "out.txt")]


@pytest.mark.parametrize("real", ["/data/params", "/data/params/d", "/data/params_bogpilot", "PARAMS_ROOT", "HOME"])
def test_real_params_path_is_refused(dump, monkeypatch, real):
  monkeypatch.setattr(hardware, "PC", True)
  if real == "PARAMS_ROOT":
    root = tempfile.mkdtemp(prefix="rowdump-guard-root-")   # a real store even though it is under the temp dir
    monkeypatch.setenv("PARAMS_ROOT", root)
    monkeypatch.setenv("BOGPILOT_PARAMS_DIR", root)
    monkeypatch.setattr(sys, "argv", ["settings_row_dump.py", "--one", "ap1", "2", "defaults", "out.txt"])
    assert dump.main() == 2
  else:
    path = os.path.join(os.path.expanduser("~"), ".comma", "params") if real == "HOME" else real
    assert run(dump, monkeypatch, path, "--one", "ap1", "2", "defaults", "out.txt") == 2
  assert dump.calls == []


def test_outside_temp_is_still_refused(dump, monkeypatch):
  monkeypatch.setattr(hardware, "PC", True)
  assert run(dump, monkeypatch, "/var/lib/somewhere/bp", "--one", "ap1", "2", "defaults", "out.txt") == 2
  assert dump.calls == []
