"""cell_fetch.py (mapd v2 mode downloader): resume, truncation, corruption, tar-slip, cell swap. Local only, no network."""
import gzip
import http.server
import io
import os
import tarfile
import threading

import pytest

from openpilot.system.bogpilot.osm import cell_fetch as C

CELL = (46, -68)


def archive(files=None, extra=None, lat=46, lon=-68):
  files = files if files is not None else {f"offline/{lat}/{lon}/46.0_-68.0_46.25_-67.75": b"A" * 5000,
                                           f"offline/{lat}/{lon}/46.25_-68.0_46.5_-67.75": b"B" * 7000}
  bio = io.BytesIO()
  with tarfile.open(fileobj=bio, mode="w") as tf:
    d = tarfile.TarInfo(f"offline/{lat}/{lon}/")
    d.type = tarfile.DIRTYPE
    tf.addfile(d)
    for name, data in files.items():
      ti = tarfile.TarInfo(name)
      ti.size = len(data)
      tf.addfile(ti, io.BytesIO(data))
    for ti in extra or ():
      tf.addfile(ti)
  return gzip.compress(bio.getvalue())


def getter(blob, ranges=True, cut=None, status=None):
  calls = []

  def get(url, offset):
    calls.append((url, offset))
    if status is not None:
      return status, None, iter(())
    body = blob[offset:] if (ranges and offset) else blob
    if cut is not None and len(calls) == 1:
      body = body[:cut]
    st = 206 if (ranges and offset) else 200
    return st, len(blob) if st == 200 else len(blob), iter([body[i:i + 1000] for i in range(0, len(body), 1000)])
  get.calls = calls
  return get


def cell_dir(root):
  return root / "offline" / "46" / "-68"


def test_url_and_layout_match_mapd():
  assert C.archive_url(46, -68) == "https://map-data.pfeifer.dev/offline/46/-68.tar.gz"
  assert str(C.part_path("/r", 46, -68)) == "/r/tmp/offline/46/-68.tar.gz.part"


def test_fetch_extracts_whole_cell_and_cleans_up(tmp_path):
  assert C.fetch_cell(tmp_path, *CELL, get=getter(archive())) == 2
  assert sorted(p.name for p in cell_dir(tmp_path).iterdir()) == ["46.0_-68.0_46.25_-67.75", "46.25_-68.0_46.5_-67.75"]
  assert not C.part_path(tmp_path, *CELL).exists() and not (tmp_path / "tmp" / "stage").exists()


def test_truncated_download_keeps_part_and_resumes_with_range(tmp_path):
  blob = archive()
  g = getter(blob, cut=len(blob) // 2)
  with pytest.raises(C.FetchError):
    C.fetch_cell(tmp_path, *CELL, get=g)
  assert C.part_path(tmp_path, *CELL).stat().st_size == len(blob) // 2
  assert not cell_dir(tmp_path).exists()                              # nothing live from a partial archive
  C.fetch_cell(tmp_path, *CELL, get=g)
  assert g.calls[-1][1] == len(blob) // 2 and cell_dir(tmp_path).is_dir()


def test_server_ignoring_range_restarts(tmp_path):
  blob = archive()
  part = C.part_path(tmp_path, *CELL)
  part.parent.mkdir(parents=True)
  part.write_bytes(b"garbage-prefix")
  C.fetch_cell(tmp_path, *CELL, get=getter(blob, ranges=False))
  assert cell_dir(tmp_path).is_dir()


def test_corrupt_archive_is_deleted_and_never_extracted(tmp_path):
  blob = bytearray(archive())
  blob[len(blob) // 2] ^= 0xFF
  with pytest.raises(C.FetchError):
    C.fetch_cell(tmp_path, *CELL, get=getter(bytes(blob)))
  assert not cell_dir(tmp_path).exists() and not C.part_path(tmp_path, *CELL).exists()


def test_missing_gzip_trailer_is_rejected(tmp_path):
  blob = archive()[:-4]
  g = getter(blob)
  with pytest.raises(C.FetchError):
    C.fetch_cell(tmp_path, *CELL, get=g)
  assert not cell_dir(tmp_path).exists()


@pytest.mark.parametrize("name", ["../evil", "offline/46/-68/../../../evil", "/abs/evil", "offline/45/-68/x", "other/x",
                                  "offline/46/-69/x"])
def test_tar_slip_and_foreign_cells_rejected(tmp_path, name):
  with pytest.raises(C.FetchError):
    C.fetch_cell(tmp_path, *CELL, get=getter(archive({name: b"x", "offline/46/-68/ok": b"y"})))
  assert not cell_dir(tmp_path).exists() and not (tmp_path.parent / "evil").exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_links_and_specials_rejected(tmp_path, kind):
  ti = tarfile.TarInfo("offline/46/-68/link")
  ti.type = kind
  ti.linkname = "/etc/passwd"
  with pytest.raises(C.FetchError):
    C.fetch_cell(tmp_path, *CELL, get=getter(archive(extra=[ti])))
  assert not cell_dir(tmp_path).exists()


def test_update_replaces_cell_atomically(tmp_path):
  C.fetch_cell(tmp_path, *CELL, get=getter(archive()))
  (cell_dir(tmp_path) / "stale_tile").write_bytes(b"old")
  C.fetch_cell(tmp_path, *CELL, get=getter(archive({"offline/46/-68/new": b"n"})))
  assert [p.name for p in cell_dir(tmp_path).iterdir()] == ["new"]
  assert not any(p.name.startswith("old_") for p in (tmp_path / "tmp").iterdir())


def test_http_errors_and_size_cap(tmp_path, monkeypatch):
  with pytest.raises(C.FetchError):
    C.fetch_cell(tmp_path, *CELL, get=getter(b"", status=404))
  monkeypatch.setattr(C, "MAX_ARCHIVE_BYTES", 100)
  with pytest.raises(C.FetchError):
    C.fetch_cell(tmp_path, *CELL, get=getter(archive()))


def test_main_exit_codes(tmp_path):
  assert C.main(["x"]) == 2


class _Handler(http.server.BaseHTTPRequestHandler):
  blob = b""
  seen = []

  def do_GET(self):
    rng = self.headers.get("Range")
    _Handler.seen.append((self.path, rng))
    data = _Handler.blob
    if rng:
      start = int(rng.split("=")[1].split("-")[0])
      if start >= len(data):
        self.send_response(416)
        self.end_headers()
        return
      self.send_response(206)
      self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
      body = data[start:]
    else:
      self.send_response(200)
      body = data
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def log_message(self, *a):
    pass


def test_real_http_get_against_local_server_range_and_416(tmp_path, monkeypatch):
  blob = archive()
  _Handler.blob, _Handler.seen = blob, []
  srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
  th = threading.Thread(target=srv.serve_forever, daemon=True)
  th.start()
  try:
    monkeypatch.setattr(C, "HOST", f"http://127.0.0.1:{srv.server_address[1]}/")
    part = C.part_path(tmp_path, *CELL)
    part.parent.mkdir(parents=True)
    half = len(blob) // 2
    part.write_bytes(blob[:half])
    assert C.fetch_cell(tmp_path, *CELL) == 2
    assert _Handler.seen[-1] == ("/offline/46/-68.tar.gz", f"bytes={half}-")
    part.write_bytes(blob)                                                # already complete -> 416 -> validate
    assert C.fetch_cell(tmp_path, *CELL) == 2
    assert _Handler.seen[-1][1] == f"bytes={len(blob)}-"
  finally:
    srv.shutdown()
