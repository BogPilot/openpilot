import os

from openpilot.system.bogpilot.osm.storage import RESERVE_BYTES, OsmStorage, human_size


def make(tmp_path):
  root = tmp_path / "osm"
  (root / "offline" / "38").mkdir(parents=True)
  (root / "offline" / "38" / "-84.bin").write_bytes(b"x" * 1500)
  (root / "tmp").mkdir()
  (root / "tmp" / "part").write_bytes(b"y")
  (root / "mapd").write_bytes(b"bin")
  (root / "mapd_version").write_text("v1.12.0")
  return OsmStorage(root)


def test_human_size_matches_097_format():
  assert human_size(0) == "0 MB"
  assert human_size(1024 * 1024) == "1.00 MB"
  assert human_size(1.5 * 1024 ** 3) == "1.50 GB"
  assert human_size(-5) == "0 MB"


def test_size_and_has_maps(tmp_path):
  st = make(tmp_path)
  assert st.size_bytes() == 1500
  assert st.has_maps()
  assert OsmStorage(tmp_path / "osm_missing").size_bytes() == 0
  assert not OsmStorage(tmp_path / "osm_missing").has_maps()


def test_remove_maps_keeps_binary(tmp_path):
  st = make(tmp_path)
  assert st.remove_maps()
  assert not st.offline_dir.exists() and not st.tmp_dir.exists()
  assert st.mapd_path.exists() and st.version_path.exists()


def test_reset_clears_everything(tmp_path):
  st = make(tmp_path)
  assert st.reset()
  assert st.root.exists() and not any(st.root.iterdir())


def test_deletion_guards(tmp_path):
  bad = tmp_path / "notosm"
  (bad / "offline").mkdir(parents=True)
  st = OsmStorage(bad)
  assert not st.remove_maps() and not st.reset()
  assert (bad / "offline").exists()
  real = tmp_path / "real"
  real.mkdir()
  (real / "keep").write_text("k")
  link = tmp_path / "osm"
  os.symlink(real, link)
  st2 = OsmStorage(link)
  assert not st2.reset() and not st2.remove_maps()
  assert (real / "keep").exists()


def test_symlinked_offline_dir_only_unlinks_the_link(tmp_path):
  root = tmp_path / "osm"
  root.mkdir()
  target = tmp_path / "elsewhere"
  target.mkdir()
  (target / "data").write_text("d")
  os.symlink(target, root / "offline")
  st = OsmStorage(root)
  assert st.remove_maps()
  assert (target / "data").exists() and not (root / "offline").exists()


def test_enough_space_reserve(tmp_path, monkeypatch):
  st = OsmStorage(tmp_path / "osm")
  monkeypatch.setattr(st, "disk_free", lambda: RESERVE_BYTES + 100)
  assert st.enough_space(100)
  assert not st.enough_space(101)


def test_disk_free_walks_to_existing_parent(tmp_path):
  assert OsmStorage(tmp_path / "a" / "b" / "osm").disk_free() > 0
