import hashlib
import json
import os

import pytest

from openpilot.system.bogpilot.osm import installer as I
from openpilot.system.bogpilot.osm.storage import OsmStorage


def elf(machine=0xB7, n=4096):
  h = bytearray(64)
  h[:4] = b"\x7fELF"
  h[4] = 2
  h[18:20] = machine.to_bytes(2, "little")
  return bytes(h) + b"\0" * (n - 64)


def manifest_for(blob, url="https://github.com/pfeiferj/mapd/releases/download/v1.12.0/mapd"):
  return {"version": "v1.12.0", "asset_url": url, "sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob)}


def fetcher(blob, parts=3):
  def f(_url):
    step = max(1, len(blob) // parts)
    for i in range(0, len(blob), step):
      yield blob[i:i + step]
  return f


def test_real_manifest_is_pinned():
  m = I.load_manifest()
  assert m["version"] == "v1.12.0" and m["license"] == "MIT"
  assert len(m["sha256"]) == 64 and int(m["size"]) == 9371832
  assert m["asset_url"].startswith("https://github.com/pfeiferj/mapd/releases/download/v1.12.0/")
  assert m["source_tag"] == "v1.12.0" and len(m["source_commit"]) == 40


def test_install_ok(tmp_path):
  blob = elf()
  st = OsmStorage(tmp_path / "osm")
  assert I.install(st, manifest_for(blob), fetcher(blob))
  assert st.mapd_path.read_bytes() == blob
  assert os.access(st.mapd_path, os.X_OK)
  assert st.version_path.read_text() == "v1.12.0"
  assert I.verify_installed(st, manifest_for(blob))
  assert [p.name for p in st.root.iterdir() if p.name.startswith(".mapd.")] == []


@pytest.mark.parametrize("mutate,msg", [
  (lambda b: b[:-1] + b"\x01", "sha256"),
  (lambda b: b + b"\0", "larger"),
  (lambda b: b[:-5], "size"),
])
def test_install_rejects_tampered(tmp_path, mutate, msg):
  blob = elf()
  man = manifest_for(blob)
  st = OsmStorage(tmp_path / "osm")
  with pytest.raises(I.InstallError, match=msg):
    I.install(st, man, fetcher(mutate(blob)))
  assert not st.mapd_path.exists() and not st.version_path.exists()
  assert [p.name for p in st.root.iterdir() if p.name.startswith(".mapd.")] == []


def test_install_rejects_wrong_arch_and_non_elf(tmp_path):
  st = OsmStorage(tmp_path / "osm")
  for blob in (elf(machine=0x3E), b"#!/bin/sh\n" + b"\0" * 4096):
    with pytest.raises(I.InstallError, match="aarch64"):
      I.install(st, manifest_for(blob), fetcher(blob))
  assert not st.mapd_path.exists()


@pytest.mark.parametrize("url", ["http://github.com/x/mapd", "https://evil.example/mapd", "file:///etc/passwd", "https://github.com.evil.example/mapd"])
def test_install_rejects_urls(tmp_path, url):
  blob = elf()
  with pytest.raises(I.InstallError, match="refusing"):
    I.install(OsmStorage(tmp_path / "osm"), manifest_for(blob, url), fetcher(blob))


def test_failed_install_keeps_previous_good_binary(tmp_path):
  good = elf()
  st = OsmStorage(tmp_path / "osm")
  I.install(st, manifest_for(good), fetcher(good))
  bad = elf(n=5000)
  with pytest.raises(I.InstallError):
    I.install(st, manifest_for(good), fetcher(bad))
  assert st.mapd_path.read_bytes() == good


def test_verify_installed_detects_edits_and_perms(tmp_path):
  blob = elf()
  man = manifest_for(blob)
  st = OsmStorage(tmp_path / "osm")
  assert not I.verify_installed(st, man)
  I.install(st, man, fetcher(blob))
  os.chmod(st.mapd_path, 0o644)
  assert not I.verify_installed(st, man)
  os.chmod(st.mapd_path, 0o755)
  st.mapd_path.write_bytes(blob[:-1] + b"\x07")
  assert not I.verify_installed(st, man)
  os.chmod(st.mapd_path, 0o755)
  os.replace(st.mapd_path, tmp_path / "moved")
  os.symlink(tmp_path / "moved", st.mapd_path)       # a symlink is not a regular file
  assert not I.verify_installed(st, man)


def test_manifest_validation(tmp_path):
  p = tmp_path / "m.json"
  p.write_text(json.dumps({"version": "v", "asset_url": "u", "sha256": "ab", "size": 1}))
  with pytest.raises(I.InstallError):
    I.load_manifest(p)
  p.write_text(json.dumps({"version": "v"}))
  with pytest.raises(I.InstallError):
    I.load_manifest(p)


def test_cached_verify_rehashes_on_change(tmp_path, monkeypatch):
  blob = elf()
  man = manifest_for(blob)
  st = OsmStorage(tmp_path / "osm")
  I.install(st, man, fetcher(blob))
  calls = []
  real = I.sha256_file
  monkeypatch.setattr(I, "sha256_file", lambda p: calls.append(1) or real(p))
  assert I.verify_installed(st, man, cached=True) and I.verify_installed(st, man, cached=True)
  assert len(calls) == 1                                   # second poll did not re-hash
  assert I.verify_installed(st, man) and len(calls) == 2   # uncached (pre-exec) always hashes
  st.mapd_path.write_bytes(blob[:-1] + b"\x09")
  os.chmod(st.mapd_path, 0o755)
  assert not I.verify_installed(st, man, cached=True)      # mtime/inode changed -> re-hashed -> rejected
