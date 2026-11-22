"""Where the model downloader (installer.py) may fetch driving models from, and which licenses we will host.

modeld never imports this module. The settings page offers what CATALOG lists and installer.install fetches it.
Every fetch must start at our own GitHub releases (org BogPilot) over https; any other host is refused before a
transport is used, and redirects may only go to GitHub's release-asset hosts. Models whose license is missing or
not on the redistributable list are excluded.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

RELEASE_ORG = "BogPilot"
ALLOWED_LICENSE_NAMES = frozenset({
  "MIT",
  "MIT (openpilot)",
  "Apache-2.0",
  "BSD-2-Clause",
  "BSD-3-Clause",
  "ISC",
  "CC0-1.0",
})

# Request URL (first hop) only. Asset CDNs are accepted only as a later redirect from one of these.
_REPO = r"[A-Za-z0-9._-]+"
_TAG = r"[A-Za-z0-9._~+-]+"
_FILE = r"[A-Za-z0-9._~+-]+"
_RELEASE_DOWNLOAD = re.compile(
  rf"^https://github\.com/{RELEASE_ORG}/{_REPO}/releases/(?:download/{_TAG}|latest/download)/{_FILE}$"
)
_RELEASE_API = re.compile(
  rf"^https://api\.github\.com/repos/{RELEASE_ORG}/{_REPO}/releases(?:/latest|/tags/{_TAG}|/assets/[0-9]+)?$"
)
GITHUB_ASSET_HOSTS = frozenset({
  "objects.githubusercontent.com",
  "release-assets.githubusercontent.com",
  "github-releases.githubusercontent.com",
})

# No models are published on our GitHub releases yet. An item needs a redistributable license, a pinned sha256 and
# size for every file, and a 0.11.2-compatible interface (checked again after download by registry.validate_entry).
CATALOG: tuple[dict, ...] = ()

# Reviewed 2026-11-22 and NOT offered (names only: nothing below is fetched, copied or hosted).
# Compatibility is against this tree's 0.11.2 modeld: one fused driving program with history queues inside it
# (inputs new_img/desire/traffic_convention/action_t + state_img_q[2,5,6,128,256], state_desire_q[100,1,8],
# state_feat_q[96,1,512]; one 2576-wide `outputs` vector with the stock output_slices).
EXCLUDED: tuple[tuple[str, str], ...] = (
  ("comma.ai Cheddar (openpilot master, Nov 17 2026)",
   "MIT, but not compatible: outputs grow to 2580 with a new `action` slice, every slice moves, and the queues grow "
   "to state_desire_q[132,1,8] / state_feat_q[128,1,512]"),
  ("comma.ai models of openpilot 0.11.1 and older",
   "MIT, but not compatible: split driving_vision + driving_policy programs; 0.11.2 runs one fused program"),
  ("comma.ai big_* (Chestnut) models",
   "MIT, but for the external GPU only; Chestnut setups always keep the stock models"),
  ("sunnypilot QCOM catalog models (e.g. Cheddar, sp chd)",
   "not proven compatible: built for sunnypilot's own model runtime and a different tinygrad pin, and its interface "
   "has not been checked against 0.11.2; the dataset's MIT tag has no per-model provenance yet, and the runtime code "
   "is under a custom permission license"),
  ("FrogPilot Resources models",
   "weight redistribution rights unclear (no license in the models branch) and built for older openpilot "
   "(split/thneed artifacts)"),
)


class SourceError(ValueError):
  pass


def license_is_redistributable(name: str | None) -> bool:
  """True only for a known redistributable license name. Unclear or empty names are excluded."""
  if not isinstance(name, str):
    return False
  return name.strip() in ALLOWED_LICENSE_NAMES


def catalog_entries(entries: tuple[dict, ...] | None = None) -> tuple[dict, ...]:
  """Hosted entries we would offer. Skips any item whose license is unclear or not redistributable."""
  out = []
  for item in (CATALOG if entries is None else entries):
    if not isinstance(item, dict):
      continue
    if license_is_redistributable(item.get("license")) and allowed_source_url(item.get("url") or ""):
      out.append(item)
  return tuple(out)


def allowed_source_url(url: str) -> bool:
  """True if this URL may be requested as the first hop of a model fetch."""
  if not isinstance(url, str) or not url:
    return False
  return _RELEASE_DOWNLOAD.match(url) is not None or _RELEASE_API.match(url) is not None


def _allowed_redirect_url(url: str) -> bool:
  if allowed_source_url(url):
    return True
  try:
    parts = urlparse(url)
  except ValueError:
    return False
  if parts.scheme != "https" or parts.hostname not in GITHUB_ASSET_HOSTS:
    return False
  return bool(parts.path and parts.path != "/")


def _check(url: str, *, redirect: bool) -> None:
  ok = _allowed_redirect_url(url) if redirect else allowed_source_url(url)
  if not ok:
    raise SourceError("refused: models may only be fetched from our GitHub releases")


def fetch_bytes(url: str, expected_sha256: str, transport, *, sha256_fn=None) -> bytes:
  """Fetch `url` with the injected `transport` only after the allowlist accepts it.

  `transport` is `(url) -> bytes` or a response object with `.content` and optional `.location`
  or a `Location` header. It is never called when the URL is not allowed. The body must match
  `expected_sha256`. This tree does not ship a network transport.
  """
  if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
    raise SourceError("expected sha256 must be 64 lowercase hex characters")
  _check(url, redirect=False)

  def body_of(resp):
    if isinstance(resp, (bytes, bytearray)):
      return bytes(resp)
    loc = getattr(resp, "location", None)
    if not loc:
      headers = getattr(resp, "headers", None) or {}
      loc = headers.get("Location") if isinstance(headers, dict) else None
    if loc:
      return ("redirect", loc)
    content = getattr(resp, "content", None)
    if isinstance(content, (bytes, bytearray)):
      return bytes(content)
    raise SourceError("transport returned an unreadable response")

  current, seen, redirect = url, set(), False
  while True:
    if current in seen:
      raise SourceError("refused: redirect loop")
    seen.add(current)
    _check(current, redirect=redirect)
    resp = transport(current)
    got = body_of(resp)
    if isinstance(got, tuple) and got[0] == "redirect":
      current, redirect = got[1], True
      continue
    digest = (sha256_fn or hashlib.sha256)(got).hexdigest()
    if digest != expected_sha256:
      raise SourceError("hash mismatch")
    return got
