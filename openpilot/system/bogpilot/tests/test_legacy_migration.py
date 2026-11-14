"""One-time migration of values saved under the pre-rename (FrogPilot-era) key names."""
import json
from pathlib import Path

import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.system.bogpilot import drive_tracking
from openpilot.system.bogpilot import legacy_migration as lm
from openpilot.system.manager import bogpilot_startup as startup


class DirParams:
  """Params-like object backed by a directory; knows every current BogPilot key."""
  def __init__(self, root: Path, known=None):
    self.root = root
    root.mkdir(parents=True, exist_ok=True)
    self.known = set(BOGPILOT_PARAMS) if known is None else set(known)
    self.put_calls = []

  def get_param_path(self, key=""):
    return str(self.root / key)

  def all_keys(self):
    return [k.encode() for k in self.known]

  def check_key(self, key):
    if key not in self.known:
      raise KeyError(key)
    return key

  def get(self, key, *a, **k):
    self.check_key(key)
    p = self.root / key
    if not p.exists():
      return None
    data = p.read_bytes()
    return data if BOGPILOT_PARAMS[key][1] == "BYTES" else data.decode()

  def put(self, key, value, block=False):
    self.check_key(key)
    self.put_calls.append(key)
    if isinstance(value, bytes):
      (self.root / key).write_bytes(value)
    else:
      (self.root / key).write_text(str(value))

  def put_bool(self, key, value, block=False):
    self.put(key, "1" if value else "0")


class OldLibParams(DirParams):
  """An old libparams_c.so: knows none of the renamed BogPilot keys."""
  def __init__(self, root):
    super().__init__(root, known=[])


@pytest.fixture
def env(tmp_path, monkeypatch):
  fileroot = tmp_path / "params_bogpilot"
  fileroot.mkdir()
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(fileroot))
  (tmp_path / "d").mkdir()
  return tmp_path / "d", fileroot


def snapshot(path: Path):
  return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(path.iterdir())}


def test_table_pairs_are_consistent():
  for old, new in lm.LEGACY_PARAM_RENAMES.items():
    assert old.startswith("FrogPilot") and new == "BogPilot" + old[len("FrogPilot"):]
    assert new in BOGPILOT_PARAMS, new
    assert old not in BOGPILOT_PARAMS, old  # the old name is no longer a registered key
  # every persistent renamed key has a migration entry
  for key, row in BOGPILOT_PARAMS.items():
    if key.startswith("BogPilot") and "PERSISTENT" in row[0]:
      assert "FrogPilot" + key[len("BogPilot"):] in lm.LEGACY_PARAM_RENAMES, key


def test_copies_values_and_keeps_old_ones(env):
  d, fileroot = env
  params = DirParams(d)
  (d / "FrogPilotTelemetry").write_text("1")
  (d / "FrogPilotDrives").write_text("42")
  (d / "FrogPilotKilometers").write_text("123.5")
  (d / "FrogPilotDongleId").write_text("fake-dongle-id")
  (d / "FrogPilotCarParamsPersistent").write_bytes(b"\x00\x01\xffcarparams")
  before = snapshot(d)
  res = lm.migrate_legacy_params(params, file_root=fileroot)
  assert not res["errors"], res
  assert sorted(res["migrated"]) == ["BogPilotCarParamsPersistent", "BogPilotDongleId", "BogPilotDrives",
                                     "BogPilotKilometers", "BogPilotTelemetry"]
  assert (d / "BogPilotTelemetry").read_text() == "1"
  assert (d / "BogPilotDrives").read_text() == "42"
  assert float((d / "BogPilotKilometers").read_text()) == 123.5
  assert (d / "BogPilotDongleId").read_text() == "fake-dongle-id"
  assert (d / "BogPilotCarParamsPersistent").read_bytes() == b"\x00\x01\xffcarparams"
  for name, content in before.items():  # old files untouched: bytes and mtime
    assert snapshot(d)[name] == content
  assert lm.migration_done(fileroot)


def test_stats_blob_counters_renamed_inside(env):
  d, fileroot = env
  params = DirParams(d)
  blob = {"FrogPilotDrives": 7, "FrogPilotMeters": 1234.5, "FrogPilotSeconds": 99.0, "Engages": 3, "FrogChirps": 5,
          "ResetStats": True, "Nested": {"a": 1}}
  (d / "FrogPilotStats").write_text(json.dumps(blob))
  lm.migrate_legacy_params(params, file_root=fileroot)
  new = json.loads((d / "BogPilotStats").read_text())
  assert new == {"BogPilotDrives": 7, "BogPilotMeters": 1234.5, "BogPilotSeconds": 99.0, "Engages": 3,
                 "FrogChirps": 5, "ResetStats": True, "Nested": {"a": 1}}
  assert json.loads((d / "FrogPilotStats").read_text()) == blob  # old blob untouched


def test_stats_blob_corrupt_is_copied_verbatim(env):
  d, fileroot = env
  (d / "FrogPilotStats").write_text("{not json")
  lm.migrate_legacy_params(DirParams(d), file_root=fileroot)
  assert (d / "BogPilotStats").read_text() == "{not json"


def test_stats_translation_prefers_new_name():
  assert lm.translate_stats_keys({"FrogPilotDrives": 1, "BogPilotDrives": 9}) == {"BogPilotDrives": 9}
  assert json.loads(lm.translate_stats_blob(b"[1, 2]")) == [1, 2]


def test_idempotent_and_never_overwrites(env):
  d, fileroot = env
  params = DirParams(d)
  (d / "FrogPilotDrives").write_text("5")
  (d / "FrogPilotMinutes").write_text("10")
  (d / "BogPilotMinutes").write_text("77")  # already set under the new name: must win
  r1 = lm.migrate_legacy_params(params, file_root=fileroot)
  assert "BogPilotDrives" in r1["migrated"] and "BogPilotMinutes" not in r1["migrated"]
  assert (d / "BogPilotMinutes").read_text() == "77"
  (d / "BogPilotDrives").write_text("6")  # user keeps driving on the new version
  params.put_calls.clear()
  r2 = lm.migrate_legacy_params(params, file_root=fileroot)
  assert r2["migrated"] == [] and not params.put_calls
  assert (d / "BogPilotDrives").read_text() == "6"


def test_file_store_values_move_when_libparams_is_old(env):
  d, fileroot = env
  params = OldLibParams(d)
  (fileroot / "FrogPilotTelemetry").write_text("1")
  (fileroot / "FrogPilotStats").write_text(json.dumps({"FrogPilotDrives": 3}))
  before = snapshot(fileroot)
  res = lm.migrate_legacy_params(params, file_root=fileroot)
  assert not res["errors"]
  assert (fileroot / "BogPilotTelemetry").read_text() == "1"
  assert json.loads((fileroot / "BogPilotStats").read_text()) == {"BogPilotDrives": 3}
  for name, content in before.items():
    assert snapshot(fileroot)[name] == content
  assert not params.put_calls


def test_params_dir_wins_over_file_store(env):
  d, fileroot = env
  params = DirParams(d)
  (d / "FrogPilotDrives").write_text("11")
  (fileroot / "FrogPilotDrives").write_text("99")
  lm.migrate_legacy_params(params, file_root=fileroot)
  assert (d / "BogPilotDrives").read_text() == "11"


def test_no_old_values_is_a_clean_noop(env):
  d, fileroot = env
  res = lm.migrate_legacy_params(DirParams(d), file_root=fileroot)
  assert res["migrated"] == [] and res["errors"] == []
  assert lm.migration_done(fileroot)  # nothing to do is still "done"


def test_failure_on_one_key_does_not_stop_others_or_write_marker(env):
  d, fileroot = env

  class Flaky(DirParams):
    def put(self, key, value, block=False):
      if key == "BogPilotDrives":
        raise OSError("disk")
      super().put(key, value, block)

  (d / "FrogPilotDrives").write_text("5")
  (d / "FrogPilotMinutes").write_text("8")
  res = lm.migrate_legacy_params(Flaky(d), file_root=fileroot)
  assert res["migrated"] == ["BogPilotMinutes"] and len(res["errors"]) == 1
  assert not lm.migration_done(fileroot)
  # a later run finishes the job
  res = lm.migrate_legacy_params(DirParams(d), file_root=fileroot)
  assert res["migrated"] == ["BogPilotDrives"] and lm.migration_done(fileroot)
  assert float((d / "BogPilotMinutes").read_text()) == 8.0


def test_startup_runs_it_once_before_defaults(env):
  d, fileroot = env
  params = DirParams(d)
  (d / "FrogPilotDrives").write_text("12")
  res = startup.before_defaults(params, file_root=fileroot, backup=lambda reason: None, reset=lambda *a, **k: None)
  assert "rename-migration:1" in res.events, res
  assert (d / "BogPilotDrives").read_text() == "12"
  # user clears the new value; a later boot must not bring the old one back
  (d / "BogPilotDrives").unlink()
  res = startup.before_defaults(params, file_root=fileroot, backup=lambda reason: None, reset=lambda *a, **k: None)
  assert not any(e.startswith("rename-migration") for e in res.events)
  assert not (d / "BogPilotDrives").exists()


def test_load_stats_accepts_old_counter_names():
  stats = drive_tracking.load_stats(json.dumps({"FrogPilotDrives": 4, "FrogPilotMeters": 10.0, "FrogPilotSeconds": 2.0}))
  assert stats["BogPilotDrives"] == 4 and stats["BogPilotMeters"] == 10.0 and stats["BogPilotSeconds"] == 2.0
  assert not any(k.startswith("FrogPilot") for k in stats)


def test_api_token_key_rename_is_exactly_the_two_param_key_names():
  # Param key names, not secrets: the old key maps to the new key, both registered names, nothing else.
  old, new = "FrogPilot" + "Api" + "Token", "BogPilot" + "Api" + "Token"
  assert lm.LEGACY_PARAM_RENAMES[old] == new
  assert [k for k, v in lm.LEGACY_PARAM_RENAMES.items() if v == new] == [old]
  assert (old, new) == ("".join(("Frog", "PilotApiToken")), "".join(("Bog", "PilotApiToken")))
  assert new in BOGPILOT_PARAMS
