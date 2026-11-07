#!/usr/bin/env python3
"""
CLI tool for downloading explicitly supplied files and resolving local/internal-storage routes.
Called by C++ replay/cabana via subprocess. BogPilot: comma Connect API access removed.

Subcommands:
  route-files <route>    - (removed: Connect) prints {"error": ...}
  resolve-route-files <route> - Resolve logs and cameras from DATA_ENDPOINT storage (local dir or URL)
  download <url>         - Download/decompress an explicitly supplied URL to local cache, print local path
  decompress <path>      - Decompress a local log file, print temporary path
  devices                - (removed: Connect) prints {"error": ...}
  device-routes <did>    - (removed: Connect) prints {"error": ...}
"""
import argparse
import bz2
import hashlib
import json
import os
import shutil
import sys
import tempfile
import traceback
from urllib.parse import urlparse

from openpilot.common.hardware.hw import Paths


CONNECT_REMOVED = "comma Connect API access is removed in BogPilot"


def connect_removed(_args=None):
  """Compatibility stub for C++ callers: JSON error, no network."""
  json.dump({"error": CONNECT_REMOVED}, sys.stdout)
  sys.stdout.write("\n")
  sys.stdout.flush()


def cache_file_path(url, compression=None):
  url_without_query = url.split("?")[0]
  if compression:
    url_without_query = f"decompressed-{compression}:{url_without_query}"
  return os.path.join(Paths.download_cache_root(), hashlib.sha256(url_without_query.encode()).hexdigest())


def compression_type(data):
  if data.startswith(b'BZh'):
    return 'bz2'
  if data.startswith(b'\x28\xb5\x2f\xfd'):
    return 'zst'
  return None


def make_decompressor(compression):
  if compression == 'bz2':
    return bz2.BZ2Decompressor()
  if compression == 'zst':
    import zstandard as zstd
    return zstd.ZstdDecompressor().decompressobj()
  raise ValueError(f"Unsupported compression type: {compression}")


def decompress_file(source, destination, compression=None):
  with open(source, 'rb') as src, open(destination, 'wb') as dst:
    header = src.read(4)
    compression = compression or compression_type(header)
    decompressor = make_decompressor(compression)
    dst.write(decompressor.decompress(header))
    while data := src.read(1024 * 1024):
      dst.write(decompressor.decompress(data))
  if not decompressor.eof:
    raise EOFError(f"Compressed {compression} file ended before the end-of-stream marker")


def materialize_cached_file(source, url, compression):
  local_path = cache_file_path(url, compression)
  if os.path.exists(local_path):
    return local_path

  tmp_fd, tmp_path = tempfile.mkstemp(dir=Paths.download_cache_root())
  os.close(tmp_fd)
  try:
    decompress_file(source, tmp_path, compression)
    shutil.move(tmp_path, local_path)
  except Exception:
    try:
      os.unlink(tmp_path)
    except OSError:
      pass
    raise
  return local_path


def resolve_route_files(route_name: str, begin: int = 0, end: int = -1, selector: str = "a") -> dict[int, dict[str, str]]:
  from openpilot.tools.lib.filereader import DATA_ENDPOINT
  from openpilot.tools.lib.file_sources import InternalUnavailableException, internal_source
  from openpilot.tools.lib.route import FileName, SegmentRange

  sr = SegmentRange(route_name)
  api_error = None
  route_files: dict[str, list[str]] = {}  # BogPilot: no Connect route file listing
  fields = {"rlog": FileName.RLOG, "qlog": FileName.QLOG,
            "narrow_road": FileName.FCAMERA, "cabin": FileName.DCAMERA, "wide_road": FileName.ECAMERA, "qcamera": FileName.QCAMERA}
  names = {name: key for key, fns in fields.items() for name in fns}
  names.update({"rlog": "rlog", "qlog": "qlog"})
  api_files: dict[int, dict[str, str]] = {}
  for url in (url for urls in route_files.values() for url in urls):
    _, number, name = urlparse(url).path.rsplit("/", 2)
    if name in names:
      api_files.setdefault(int(number), {})[names[name]] = url
  # Preserve replay's inclusive segment bounds.
  open_ended = end < 0
  local_internal = os.path.isdir(DATA_ENDPOINT)
  if open_ended:
    end = max(begin, max(api_files, default=0))
    if local_internal:
      internal_dir = os.path.join(DATA_ENDPOINT, sr.dongle_id, sr.log_id)
      if os.path.isdir(internal_dir):
        end = max(end, max((int(name) for name in os.listdir(internal_dir) if name.isdigit()), default=0))
  indices = list(range(max(0, begin), end + 1))
  segments: dict[int, dict[str, str]] = {seg: {} for seg in indices}
  internal_errors: dict[str, Exception] = {}

  def resolve(key, requested):
    files = {seg: api_files[seg][key] for seg in requested if key in api_files.get(seg, {})}
    missing = [seg for seg in requested if seg not in files]
    if missing:
      try:
        files.update(internal_source(sr, missing, fields[key]))
      except Exception as e:
        if e is not InternalUnavailableException:
          internal_errors[key] = e
    for seg, path in files.items():
      segments[seg][key] = path

  log_types = ["qlog"] if selector == "q" else ["rlog"]
  if selector == "a":
    log_types.append("qlog")
  for key in log_types:
    resolve(key, [seg for seg in indices if not segments[seg]])
  if open_ended and not local_internal:
    # Remote internal storage exposes individual files, not a segment listing.
    # Probe the contiguous tail beyond the API's last segment until no selected log exists.
    number = end + 1
    while True:
      internal_errors.clear()
      segments[number] = {}
      for key in log_types:
        if not segments[number]:
          resolve(key, [number])
      if not segments[number]:
        if internal_errors:
          print(f"Internal discovery stopped at segment {number}; keeping resolved logs", file=sys.stderr)
          traceback.print_exception(next(iter(internal_errors.values())))
        del segments[number]
        break
      indices.append(number)
      number += 1
  available = [seg for seg in indices if segments[seg]]
  if not available:
    if api_error is not None:
      raise api_error
    raise FileNotFoundError(f"No {selector} logs found for {sr.route_name} in segments {indices} in DATA_ENDPOINT storage")
  for key in ("narrow_road", "cabin", "wide_road", "qcamera"):
    resolve(key, available)
  return {seg: segments[seg] for seg in available}


def cmd_resolve_route_files(args):
  try:
    result = resolve_route_files(args.route, args.begin, args.end, args.selector)
  except Exception as e:
    error = f"{type(e).__name__} resolving {args.route} (begin={args.begin}, end={args.end}, selector={args.selector}): {e}"
    print(error, file=sys.stderr)
    traceback.print_exc()
    result = {"error": error}
  json.dump(result, sys.stdout)
  sys.stdout.write("\n")
  sys.stdout.flush()


def cmd_download(args):
  url = args.url
  use_cache = not args.no_cache

  if use_cache:
    for compression in ('bz2', 'zst'):
      decompressed_path = cache_file_path(url, compression)
      if os.path.exists(decompressed_path):
        sys.stdout.write(decompressed_path + "\n")
        sys.stdout.flush()
        return

    local_path = cache_file_path(url)
    if os.path.exists(local_path):
      with open(local_path, 'rb') as f:
        compression = compression_type(f.read(4))
        if compression:
          local_path = materialize_cached_file(local_path, url, compression)
      sys.stdout.write(local_path + "\n")
      sys.stdout.flush()
      return

  try:
    # Stream the file in a single HTTP request instead of making
    # a separate Range request per chunk (which was very slow).
    from openpilot.tools.lib.url_file import URLFile
    pool = URLFile.pool_manager()
    r = pool.request("GET", url, preload_content=False)
    if r.status not in (200, 206):
      sys.stderr.write(f"ERROR:HTTP {r.status}\n")
      sys.stderr.flush()
      sys.exit(1)

    total = int(r.headers.get('content-length', 0))
    if total <= 0:
      sys.stderr.write("ERROR:File not found or empty\n")
      sys.stderr.flush()
      sys.exit(1)

    os.makedirs(Paths.download_cache_root(), exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=Paths.download_cache_root())
    try:
      downloaded = 0
      chunk_size = 1024 * 1024
      compression = None
      decompressor = None
      with os.fdopen(tmp_fd, 'wb') as f:
        for data in r.stream(chunk_size):
          if downloaded == 0:
            compression = compression_type(data)
            if compression:
              decompressor = make_decompressor(compression)
          f.write(decompressor.decompress(data) if decompressor else data)
          downloaded += len(data)
          sys.stderr.write(f"PROGRESS:{downloaded}:{total}\n")
          sys.stderr.flush()

      if decompressor and not decompressor.eof:
        raise EOFError(f"Compressed {compression} file ended before the end-of-stream marker")

      if decompressor:
        if use_cache:
          output_path = cache_file_path(url, compression)
          shutil.move(tmp_path, output_path)
        else:
          output_path = tmp_path
        sys.stdout.write(output_path + "\n")
      elif use_cache:
        shutil.move(tmp_path, local_path)
        sys.stdout.write(local_path + "\n")
      else:
        sys.stdout.write(tmp_path + "\n")
    except Exception:
      try:
        os.unlink(tmp_path)
      except OSError:
        pass
      raise
    finally:
      r.release_conn()

  except Exception as e:
    sys.stderr.write(f"ERROR:{e}\n")
    sys.stderr.flush()
    sys.exit(1)

  sys.stdout.flush()


def cmd_decompress(args):
  os.makedirs(Paths.download_cache_root(), exist_ok=True)
  output_fd, output_path = tempfile.mkstemp(dir=Paths.download_cache_root())
  os.close(output_fd)
  try:
    decompress_file(args.path, output_path)
  except Exception as e:
    try:
      os.unlink(output_path)
    except OSError:
      pass
    sys.stderr.write(f"ERROR:{e}\n")
    sys.stderr.flush()
    sys.exit(1)
  sys.stdout.write(output_path + "\n")
  sys.stdout.flush()


def main():
  parser = argparse.ArgumentParser(description="File downloader CLI for openpilot tools")
  subparsers = parser.add_subparsers(dest="command", required=True)

  p_rf = subparsers.add_parser("route-files")
  p_rf.add_argument("route")
  p_rf.set_defaults(func=connect_removed)

  p_resolve = subparsers.add_parser("resolve-route-files")
  p_resolve.add_argument("route")
  p_resolve.add_argument("--begin", type=int, default=0)
  p_resolve.add_argument("--end", type=int, default=-1, help="Inclusive last segment; negative means open-ended")
  p_resolve.add_argument("--selector", choices=("a", "r", "q"), default="a")
  p_resolve.set_defaults(func=cmd_resolve_route_files)

  p_dl = subparsers.add_parser("download")
  p_dl.add_argument("url")
  p_dl.add_argument("--no-cache", action="store_true")
  p_dl.set_defaults(func=cmd_download)

  p_dc = subparsers.add_parser("decompress")
  p_dc.add_argument("path")
  p_dc.set_defaults(func=cmd_decompress)

  p_dev = subparsers.add_parser("devices")
  p_dev.set_defaults(func=connect_removed)

  p_dr = subparsers.add_parser("device-routes")
  p_dr.add_argument("dongle_id")
  p_dr.add_argument("--start", type=int, default=None)
  p_dr.add_argument("--end", type=int, default=None)
  p_dr.add_argument("--preserved", action="store_true")
  p_dr.set_defaults(func=connect_removed)

  args = parser.parse_args()
  args.func(args)


if __name__ == "__main__":
  main()
