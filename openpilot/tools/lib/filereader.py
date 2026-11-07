import os
import io
import posixpath
import socket
from functools import cache
from openpilot.common.utils import retry
from urllib.parse import urlparse

from openpilot.tools.lib.url_file import URLFile

# BogPilot: no implicit comma-internal storage. Set DATA_ENDPOINT to a local dir or your own URL to enable.
DATA_ENDPOINT = os.getenv("DATA_ENDPOINT", "")


@cache
@retry(delay=0.0)
def internal_source_available(url: str) -> bool:
  if not url:
    return False
  if os.path.isdir(url):
    return True

  try:
    hostname = urlparse(url).hostname
    port = urlparse(url).port or 80
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
      s.settimeout(0.5)
      s.connect((hostname, port))
    return True
  except (socket.gaierror, ConnectionRefusedError):
    pass
  return False


def resolve_name(fn):
  if fn.startswith("cd:/"):
    if not DATA_ENDPOINT:
      raise ValueError(f"{fn}: cd:/ paths need DATA_ENDPOINT set to a local directory or your own server")
    return posixpath.join(DATA_ENDPOINT, fn[4:])
  return fn


@cache
def file_exists(fn):
  fn = resolve_name(fn)
  if fn.startswith(("http://", "https://")):
    return URLFile(fn).get_length_online() != -1
  return os.path.exists(fn)

class DiskFile(io.BufferedReader):
  def get_multi_range(self, ranges: list[tuple[int, int]]) -> list[bytes]:
    parts = []
    for r in ranges:
      self.seek(r[0])
      parts.append(self.read(r[1] - r[0]))
    return parts

def FileReader(fn):
  fn = resolve_name(fn)
  if fn.startswith(("http://", "https://")):
    return URLFile(fn)
  else:
    return DiskFile(open(fn, "rb"))
