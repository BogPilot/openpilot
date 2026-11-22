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

# Prepared but NOT offered. A PENDING item is never shown or fetched: catalog_entries() only reads CATALOG and skips
# anything marked "published": False, and installer.screen() refuses an unpublished item. To publish one: upload the
# pkl, the ONNX and the notice to the release below, flip "published", and move it to CATALOG.
CHEDDAR_ONNX_SHA256 = "350a47ea36e554fb71634c7361b2c2a2a3da07ecb211a4c6cff3d2c3013d1d82"
CHEDDAR_ONNX_SIZE = 69671018
# Placeholder release: the repository and tag are not created yet (no push, no publish).
CHEDDAR_RELEASE = f"https://github.com/{RELEASE_ORG}/openpilot/releases/download/cheddar-b3ab22efe-0.11.2"
PENDING: tuple[dict, ...] = (
  {"id": "cheddar", "name": "Cheddar (comma.ai)", "version": "b3ab22efe", "openpilot": "0.11.2", "license": "MIT",
   "onnx_sha256": CHEDDAR_ONNX_SHA256,
   "description": "comma.ai's Cheddar driving model (openpilot b3ab22efe), compiled for 0.11.2. "
                  "It steers and sets speed from its own action output. Not the default.",
   "credit": "comma.ai openpilot b3ab22efe (#39255), MIT; see notices/cheddar_b3ab22efe_MIT.txt",
   "published": False,
   "url": f"{CHEDDAR_RELEASE}/driving_tinygrad.pkl",
   # bench comma 3X QCOM compile, 2026-11-22, tinygrad tree 1a561665 (same pipeline reproduced the stock pkl and both
   # warps bit-for-bit); warps are not shipped because Cheddar uses the stock warp programs unchanged
   "abi_digest": "19cecd0112b85e40fcaecff7084aafe836bd0a8ec87a25f17ce48247a3a20576",
   "files": [
     {"role": "driving_model", "name": "driving_tinygrad.pkl",
      "sha256": "050d74e9dd0c17980f6679f5bdad2eb25e951d58fb73f764de65896107e494cd", "size": 82394323,
      "url": f"{CHEDDAR_RELEASE}/driving_tinygrad.pkl"},
   ],
   # published next to the pkl for provenance; not downloaded by the device (onnx_sha256 pins it)
   "release_assets": ("driving_supercombo.onnx", "cheddar_b3ab22efe_MIT.txt")},
)

# Reviewed 2026-11-22 and NOT offered (names only: nothing below is fetched, copied or hosted).
# Compatibility is the "fits the 0.11.2 driving code" check in compat.check_driving_abi: the four inputs modeld fills
# (new_img, desire, traffic_convention, action_t), only the three history queues (state_img_q, state_desire_q,
# state_feat_q, length from the metadata), one `outputs` vector with the slices the 0.11.2 parser reads (an
# `action` head is allowed). comma.ai Cheddar fits and is prepared above (PENDING).
EXCLUDED: tuple[tuple[str, str], ...] = (
  ("comma.ai models of openpilot 0.11.1 and older",
   "MIT, but not compatible: split driving_vision + driving_policy programs; 0.11.2 runs one fused program"),
  ("comma.ai pre-queue research models (e.g. Rebel Legion, RDF, Terrible Super Fantastic)",
   "MIT, but not compatible: frame/feature buffers outside the ONNX and fp16 inputs (no new_img or history queues)"),
  ("comma.ai big_* (Chestnut) models",
   "MIT, but for the external GPU only; Chestnut setups always keep the stock models"),
  ("sunnypilot custom models (e.g. Fully E2E, Lag Derived, No Dynamo, No Floor, Fix Instagram, Fast Greens)",
   "not compatible: extra inputs the 0.11.2 modeld never feeds (speed_limit, light_img, state_curve, state_calm, "
   "state_lc, state_aux, state_turn, ...), and provenance and license are unclear"),
  ("sunnypilot re-exports of Cheddar (sp CHD, CHD v2)",
   "interface fits, but they are sunnypilot re-exports of comma's weights with no clean provenance; comma's own "
   "Cheddar ONNX is used instead"),
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
    if not isinstance(item, dict) or item.get("published", True) is not True:
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
