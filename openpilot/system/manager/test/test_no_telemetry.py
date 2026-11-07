"""BogPilot: no comma cloud telemetry / athena / upload / registration / live-stream integrations."""
import ast
import importlib.util
import pathlib

import pytest

OP = pathlib.Path(__file__).resolve().parents[3]  # .../openpilot
REMOVED_PROCS = {"manage_athenad", "uploader", "webrtcd", "stream_encoderd"}
REMOVED_MODULES = ["openpilot.system.athena.athenad", "openpilot.system.athena.manage_athenad",
                   "openpilot.system.athena.rpc", "openpilot.system.loggerd.uploader", "openpilot.system.webrtc.webrtcd"]
FORBIDDEN_IMPORTS = ("openpilot.system.athena.athenad", "openpilot.system.athena.manage_athenad", "openpilot.system.athena.rpc",
                     "openpilot.system.loggerd.uploader", "openpilot.system.webrtc")
NON_UI_RUNTIME = ["system", "selfdrive/controls", "selfdrive/car", "selfdrive/pandad", "selfdrive/locationd",
                  "selfdrive/modeld", "selfdrive/monitoring", "selfdrive/selfdrived", "common"]


def _runtime_py():
  for sub in NON_UI_RUNTIME:
    for p in (OP / sub).rglob("*.py"):
      if "/test" not in str(p.relative_to(OP)):
        yield p


def _imports(p):
  for node in ast.walk(ast.parse(p.read_text(), str(p))):
    if isinstance(node, ast.Import):
      yield from (a.name for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
      yield node.module


def test_no_cloud_processes():
  src = (OP / "system/manager/process_config.py").read_text()
  for name in REMOVED_PROCS:
    assert f'"{name}"' not in src, name
  assert "IsLiveStreaming" not in src


@pytest.mark.parametrize("mod", REMOVED_MODULES)
def test_executable_modules_removed(mod):
  assert importlib.util.find_spec(mod) is None


def test_no_runtime_imports_of_cloud_modules():
  bad = [(str(p.relative_to(OP)), m) for p in _runtime_py() for m in _imports(p) if m.startswith(FORBIDDEN_IMPORTS)]
  assert bad == []


def test_manager_has_no_registration_or_network():
  src = (OP / "system/manager/manager.py").read_text()
  assert "register(" not in src and "athena" not in src
  ident = (OP / "system/manager/local_identity.py").read_text()
  for tok in ("requests", "api_get", "jwt", "http", "athena", "unlink", "remove("):
    assert tok not in ident, tok


def test_hardwared_has_no_registration_gate():
  src = (OP / "system/hardware/hardwared.py").read_text()
  assert "registered_device" not in src and "athena" not in src


def test_tombstoned_local_only():
  src = (OP / "system/tombstoned.py").read_text()
  assert "is_registered_device" not in src and "athena" not in src and "commaai" not in src


def test_registration_shim_is_inert():
  src = (OP / "system/athena/registration.py").read_text()
  tree = ast.parse(src)
  assert not any(isinstance(n, (ast.FunctionDef, ast.ClassDef)) for n in tree.body)
  assert set(_imports(OP / "system/athena/registration.py")) == {"openpilot.system.manager.local_identity"}


def test_local_dongle_id_reuses_and_never_deletes(tmp_path, monkeypatch):
  import openpilot.system.manager.local_identity as li

  class P:
    def __init__(self, v): self.v = {"DongleId": v} if v else {}
    def get(self, k): return self.v.get(k)
    def put(self, k, v, block=False): self.v[k] = v
  monkeypatch.setattr(li.Paths, "persist_root", staticmethod(lambda: str(tmp_path)))
  assert li.local_dongle_id(P("abc123")) == "abc123"
  assert li.local_dongle_id(P(None)) == li.UNREGISTERED_DONGLE_ID
  (tmp_path / "comma").mkdir(); (tmp_path / "comma/dongle_id").write_text("persist1\n")
  p = P(None); assert li.local_dongle_id(p) == "persist1" and p.v["DongleId"] == "persist1"
  assert (tmp_path / "comma/dongle_id").exists()


def test_deleter_uses_local_route_dirs():
  from openpilot.system.loggerd import deleter, route_dirs
  assert deleter.listdir_by_creation is route_dirs.listdir_by_creation


REPO = OP.parent
NETWORK_TOKENS = ("requests", "urllib", "http.client", "socket", "websocket", "jwt", "api_get", "common.api", "Api(")


@pytest.mark.parametrize("rel", ["system/manager/manager.py", "system/manager/local_identity.py",
                                 "system/manager/process_config.py", "system/tombstoned.py", "system/loggerd/deleter.py",
                                 "system/loggerd/route_dirs.py"])
def test_startup_paths_have_no_network_identity_upload_or_crash_reporting(rel):
  mods = set(_imports(OP / rel))
  assert not any(m.split(".")[0] in ("requests", "urllib", "socket", "websocket", "jwt", "http") for m in mods), mods
  assert "openpilot.common.api" not in mods


def test_pigeond_no_comma_agps_proxy_but_keeps_public_ublox_assist():
  src = (OP / "system/ubloxd/pigeond.py").read_text()
  assert "openpilot.common.api" not in set(_imports(OP / "system/ubloxd/pigeond.py"))
  assert "/assist" not in src and "get_token" not in src and "DongleId" not in src
  assert "online-live2.services.u-blox.com" in src and "AssistNowToken" in src  # user-owned public u-blox service
  assert "save_almanac" in src  # local almanac backup preserved


def test_no_teleoprtc_or_websocket_dependency():
  assert not (REPO / "teleoprtc_repo").exists()
  for rel in ["pyproject.toml", "uv.lock", "SConstruct", "launch_chffrplus.sh", "tools/bogpilot/rc_package.py",
              "tools/bogpilot/rc_build_gate.py"]:
    s = (REPO / rel).read_text()
    assert "teleoprtc" not in s and "websocket" not in s, rel


def test_comma_account_dev_tools_removed():
  for rel in ["openpilot/tools/lib/auth.py", "openpilot/tools/lib/bootlog.py", "tools/scripts/ssh.py"]:
    assert not (REPO / rel).exists(), rel
  op = (REPO / "tools/op.sh").read_text()
  assert "lib/auth.py" not in op and "scripts/ssh.py" not in op


def test_camerad_keeps_onroad_and_driverview():
  from openpilot.system.manager import process_config as pc
  assert pc.driverview(True, None, None) is True  # onroad: started => camera runs
  src = (OP / "system/manager/process_config.py").read_text()
  assert '["./camerad"], driverview,' in src


def test_hardwared_only_registration_gate_removed():
  src = (OP / "system/hardware/hardwared.py").read_text()
  for keep in ('onroad_conditions["ignition"]', "device_temp_good", "device_temp_engageable", "not_flashing_chestnut"):
    assert keep in src, keep
