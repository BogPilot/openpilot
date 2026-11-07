"""BogPilot: tools route/file resolution works locally with no comma Connect/account API."""
import json
import os
import socket
import subprocess
import sys
import pathlib

import pytest

ROUTE = "a2a0ccea32023010|2023-07-27--13-01-19"
LIB = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def no_network(monkeypatch):
  def deny(*a, **k):
    raise AssertionError("network access attempted")
  monkeypatch.setattr(socket.socket, "connect", deny)
  monkeypatch.setattr(socket, "create_connection", deny)


def _make_local_route(root: pathlib.Path, segs=(0, 1, 2)):
  for n in segs:
    d = root / f"{ROUTE}--{n}"
    d.mkdir(parents=True)
    for fn in ("rlog.zst", "qlog.zst", "fcamera.hevc", "qcamera.ts"):
      (d / fn).write_bytes(b"x")
  return root


def test_connect_modules_removed():
  assert not (LIB / "api.py").exists() and not (LIB / "auth_config.py").exists()
  for rel in ("route.py", "file_sources.py", "logreader.py", "file_downloader.py"):
    s = (LIB / rel).read_text()
    for tok in ("CommaApi", "get_token", "auth_config", "comma_api_source", "commadotai", "v1/route", "v1/me", "v1/devices"):
      assert tok not in s, (rel, tok)


def test_local_route_reading(tmp_path, no_network):
  from openpilot.tools.lib.route import Route
  r = Route(ROUTE, data_dir=str(_make_local_route(tmp_path)))
  assert r.max_seg_number == 2
  assert all(p and p.endswith("rlog.zst") for p in r.log_paths())
  assert all(p and p.endswith("qlog.zst") for p in r.qlog_paths())


def test_route_without_local_dir_is_rejected_without_network(no_network):
  from openpilot.tools.lib.route import Route
  with pytest.raises(ValueError, match="data_dir is required"):
    Route(ROUTE)


def test_open_ended_range_needs_no_connect(no_network):
  from openpilot.tools.lib.route import SegmentRange, get_max_seg_number_cached
  with pytest.raises(ValueError, match="open-ended"):
    get_max_seg_number_cached(SegmentRange(ROUTE))
  assert SegmentRange(f"{ROUTE}/0:3").seg_idxs == [0, 1, 2]


def test_default_logreader_sources_exclude_connect():
  import openpilot.tools.lib.logreader as lr
  import inspect
  assert "comma_api_source" not in inspect.getsource(lr.LogReader.__init__)


def _downloader(*args, env=None):
  e = dict(os.environ, **(env or {}))
  return subprocess.run([sys.executable, "-m", "openpilot.tools.lib.file_downloader", *args],
                        capture_output=True, text=True, env=e, timeout=60)


@pytest.mark.parametrize("args", [["route-files", ROUTE], ["devices"], ["device-routes", "a2a0ccea32023010"]])
def test_connect_subcommands_are_inert_json(args):
  out = _downloader(*args)
  assert out.returncode == 0
  assert "Connect" in json.loads(out.stdout.strip().splitlines()[-1])["error"]


def test_resolve_route_files_from_local_storage(tmp_path):
  base = tmp_path / "data"
  seg_root = base / ROUTE.split("|")[0] / ROUTE.split("|")[1]
  for n in (0, 1):
    (seg_root / str(n)).mkdir(parents=True)
    (seg_root / str(n) / "rlog.zst").write_bytes(b"x")
    (seg_root / str(n) / "qlog.zst").write_bytes(b"x")
  out = _downloader("resolve-route-files", ROUTE, "--begin", "0", "--end", "1", "--selector", "r",
                    env={"DATA_ENDPOINT": str(base) + "/"})
  res = json.loads(out.stdout.strip().splitlines()[-1])
  assert "error" not in res, (res, out.stderr[-500:])
  assert sorted(res) == ["0", "1"] and res["0"]["rlog"].endswith("0/rlog.zst")
