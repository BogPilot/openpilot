"""mapd v2 plumbing (mapd_v2.py, the v2 manifest, installer install_name, cereal): pure, no mapd binary needed."""
import json
from types import SimpleNamespace

import pytest

from openpilot.system.bogpilot.osm import installer as I
from openpilot.system.bogpilot.osm import mapd_v2 as M
from openpilot.system.bogpilot.osm.storage import OsmStorage
from openpilot.system.bogpilot.osm.tests.test_installer import elf, fetcher, manifest_for


def test_v2_manifest_pinned_and_installs_beside_v1():
  m = I.load_engine_manifest(True)
  assert m["version"] == "v2.4.0" and m["license"] == "MIT" and m["install_name"] == "mapd_v2"
  assert m["sha256"] == "0bc3564ec634486d11e95b76e884fd37b783c66933405cec1bd59f179fa09e94" and m["size"] == 21933040
  assert m["asset_url"] == "https://github.com/pfeiferj/mapd/releases/download/v2.4.0/mapd"
  assert I.load_engine_manifest(False)["version"] == "v1.12.0" and "install_name" not in I.load_engine_manifest(False)
  assert (I.V2_MANIFEST_PATH.parent / m["license_file"]).read_text().startswith("Copyright")


def test_binary_path_and_side_by_side_install(tmp_path):
  st = OsmStorage(tmp_path / "osm")
  b1, b2 = elf(n=4096), elf(n=8192)
  m1, m2 = manifest_for(b1), dict(manifest_for(b2), version="v2.4.0", install_name="mapd_v2")
  assert I.binary_path(st, m1) == st.mapd_path and I.binary_path(st, m2) == st.root / "mapd_v2"
  I.install(st, m1, fetcher(b1))
  I.install(st, m2, fetcher(b2))
  assert I.verify_installed(st, m1) and I.verify_installed(st, m2)
  assert st.version_path.read_text() == "v1.12.0" and (st.root / "mapd_v2_version").read_text() == "v2.4.0"
  for bad in ("../mapd", "/bin/sh", "sh", "mapd/../x"):
    with pytest.raises(I.InstallError):
      I.binary_path(st, dict(m2, install_name=bad))
    assert I.verify_installed(st, dict(m2, install_name=bad)) is False


def test_settings_turn_every_mapd_control_off():
  s = json.loads(M.settings_json())
  assert s["settings_version"] == 2
  for k, v in s.items():
    if k.endswith("_enabled"):
      assert v is False, k
  assert all(p["map_curve_target_lat_a"] == M.MAP_CURVE_LAT_A for p in s["personalities"].values())
  assert s["speed_limit"]["speed_limit_offset"] == 0


def test_curve_lookahead_setting_matches_the_planner_and_leaves_speed_limits_alone():
  from openpilot.selfdrive.controls.lib import curve_speed_planner as C
  s = json.loads(M.settings_json())
  for p in s["personalities"].values():
    assert p["curve_target_speed_time_offset"] == M.MAP_CURVE_TIME_OFFSET == C.MAPD_TIME_OFFSET
    assert M.MAP_HORIZON_M == C.MAP_HORIZON_M
    assert p["target_speed_accel"] == C.MAPD_ACCEL and p["target_speed_jerk"] == C.MAPD_JERK
    assert p["speed_limit_increase_target_speed_time_offset"] == 1.5
    assert p["speed_limit_decrease_target_speed_time_offset"] == 0.75


def test_write_settings_atomic(tmp_path):
  assert M.write_settings(tmp_path)
  assert json.loads((tmp_path / "MapdSettings").read_text())["settings_version"] == 2
  assert [p.name for p in tmp_path.iterdir()] == ["MapdSettings"]


def test_launch_env_forces_openpilot_msgq_paths():
  env = M.launch_env({"PATH": "/bin", "USE_MSGQ_PREFIX": "false"})
  assert env == {"PATH": "/bin", "USE_MSGQ_PREFIX": "true"}


def test_engine_toggle_fails_closed():
  assert M.engine_v2(SimpleNamespace(get_bool=lambda k: k == "MapdV2")) is True
  assert M.engine_v2(SimpleNamespace(get_bool=lambda k: False)) is False
  assert M.engine_v2(SimpleNamespace(get_bool=lambda k: (_ for _ in ()).throw(OSError()))) is False


def out(**kw):
  d = dict(tileLoaded=True, speedLimit=20.0, nextSpeedLimit=15.0, nextSpeedLimitDistance=300.0, mapCurveSpeed=12.0, roadName="Main")
  d.update(kw)
  return SimpleNamespace(**d)


def test_parse_bounds():
  assert M.parse(out()) == M.MapdV2Data(True, 20.0, 15.0, 300.0, 12.0, "Main")
  assert M.parse(out(tileLoaded=False)) == M.MapdV2Data(fresh=True)
  d = M.parse(out(speedLimit=float("nan"), nextSpeedLimit=0.0, mapCurveSpeed=1e9))
  assert (d.speed_limit, d.next_speed_limit, d.next_distance, d.curve_speed) == (0.0, 0.0, 0.0, 0.0)
  assert M.parse(object()) == M.NO_V2


class FakeSM:
  def __init__(self):
    self.msg, self.valid_flag, self.new = out(), True, False
    self.updated, self.valid = {"mapdOut": False}, {"mapdOut": True}

  def update(self, _t):
    self.updated["mapdOut"], self.valid["mapdOut"], self.new = self.new, self.valid_flag, False

  def __getitem__(self, k):
    return self.msg


def test_reader_freshness_and_invalid():
  sm, t = FakeSM(), [0.0]
  r = M.MapdOutReader(sm_factory=lambda: sm, mono=lambda: t[0])
  assert r.update() == M.NO_V2
  sm.new = True
  assert r.update().speed_limit == 20.0
  t[0] += M.FRESH_S - 0.01
  assert r.update().fresh
  t[0] += 0.02
  assert r.update() == M.NO_V2                                # stale
  sm.new, sm.valid_flag = True, False
  assert r.update() == M.NO_V2
  assert M.MapdOutReader(sm_factory=lambda: (_ for _ in ()).throw(RuntimeError())).update() == M.NO_V2


def test_shared_tick_reads_once_per_period():
  calls, t = [], [0.0]
  r = SimpleNamespace(update=lambda: calls.append(1) or M.NO_V2, data=M.NO_V2)
  tick = M.SharedTick(r, mono=lambda: t[0])
  tick.get()
  tick.get()
  t[0] += 0.05
  tick.get()
  assert len(calls) == 2


def test_cereal_mapd_v2_round_trip():
  from openpilot.cereal import custom, log, messaging
  from openpilot.cereal.services import SERVICE_LIST
  assert SERVICE_LIST["mapdOut"].frequency == 20.0 and "mapdIn" in SERVICE_LIST and "mapdExtendedOut" in SERVICE_LIST
  assert "mapdCli" not in SERVICE_LIST
  from openpilot.cereal.services import QueueSize
  for svc in ("mapdOut", "mapdExtendedOut", "mapdIn"):            # mapd v2.4.0 settings/const.go: QUEUE_SIZE_MEDIUM
    assert SERVICE_LIST[svc].queue_size == QueueSize.MEDIUM == 2 * 1024 * 1024
  for svc in ("carState", "selfdriveState", "gpsLocation", "gpsLocationExternal"):   # QUEUE_SIZE_SMALL in mapd
    assert SERVICE_LIST[svc].queue_size == QueueSize.SMALL == 250 * 1024
  assert SERVICE_LIST["modelV2"].queue_size == QueueSize.BIG
  m = messaging.new_message("mapdOut")
  m.mapdOut.speedLimit, m.mapdOut.mapCurveSpeed, m.mapdOut.tileLoaded, m.mapdOut.roadName = 20.0, 12.0, True, "Main"
  b = m.to_bytes()
  with log.Event.from_bytes(b) as e:
    assert e.which() == "mapdOut"
    assert M.parse(e.mapdOut) == M.MapdV2Data(True, 20.0, 0.0, 0.0, 12.0, "Main")
  assert custom.MapdOut.schema.node.id == 0xa4f1eb3323f5f582
  assert custom.MapdIn.schema.node.id == 0xc86a3d38d13eb3ef
  assert custom.MapdExtendedOut.schema.node.id == 0xa30662f84033036c
  fields = log.Event.schema.fields
  assert fields["mapdOut"].proto.ordinal.explicit == 145 and fields["mapdIn"].proto.ordinal.explicit == 144
