"""Model source policy: only our GitHub releases, only redistributable licenses, no other host is contacted."""
import hashlib
import unittest
from types import SimpleNamespace

from openpilot.common.bogpilot_models import source


OK = "https://github.com/BogPilot/driving-models/releases/download/v1/model.onnx"
OK_LATEST = "https://github.com/BogPilot/driving-models/releases/latest/download/model.onnx"
OK_API = "https://api.github.com/repos/BogPilot/driving-models/releases/assets/123"
BODY = b"onnx-bytes"
SHA = hashlib.sha256(BODY).hexdigest()


class RecordingTransport:
  def __init__(self, mapping):
    self.mapping = dict(mapping)
    self.called = []

  def __call__(self, url):
    self.called.append(url)
    if url not in self.mapping:
      raise AssertionError(f"unexpected fetch of {url}")
    return self.mapping[url]


class TestAllowlist(unittest.TestCase):
  def test_our_github_release_urls_are_allowed(self):
    for url in (OK, OK_LATEST, OK_API,
                "https://api.github.com/repos/BogPilot/driving-models/releases",
                "https://api.github.com/repos/BogPilot/driving-models/releases/latest",
                "https://api.github.com/repos/BogPilot/driving-models/releases/tags/v1.0",
                "https://github.com/BogPilot/models/releases/download/cheddar-b3ab22efe-0.11.2/driving_tinygrad.pkl",
                "https://github.com/BogPilot/openpilot/releases/download/cheddar-b3ab22efe-0.11.2/driving_tinygrad.pkl"):
      with self.subTest(url=url):
        self.assertTrue(source.allowed_source_url(url))

  def test_every_other_host_and_shape_is_refused(self):
    refused = (
      "https://github.com/commaai/openpilot/releases/download/v0.11.2/model.onnx",
      "https://huggingface.co/commaai/openpilot_driving_models/resolve/main/model.onnx",
      "https://objects.githubusercontent.com/github-production-release-asset-2e65be/foo",
      "https://raw.githubusercontent.com/BogPilot/driving-models/main/model.onnx",
      "http://github.com/BogPilot/driving-models/releases/download/v1/model.onnx",
      "https://github.com/BogPilot/driving-models/archive/refs/tags/v1.tar.gz",
      "https://github.com/BogPilot/driving-models/raw/main/model.onnx",
      "https://api.github.com/repos/commaai/openpilot/releases/assets/1",
      "https://github.com/NotBogPilot/models/releases/download/cheddar-b3ab22efe-0.11.2/driving_tinygrad.pkl",
      "https://github.com/BogPilot/models/blob/main/driving_tinygrad.pkl",
      "file:///tmp/model.onnx",
      "https://example.com/model.onnx",
      "",
      None,
    )
    for url in refused:
      with self.subTest(url=url):
        self.assertFalse(source.allowed_source_url(url if isinstance(url, str) else url or ""))

  def test_refused_url_never_calls_the_transport(self):
    tr = RecordingTransport({OK: BODY})
    with self.assertRaises(source.SourceError) as ctx:
      source.fetch_bytes("https://huggingface.co/commaai/openpilot_driving_models/resolve/main/x.onnx", SHA, tr)
    self.assertIn("GitHub releases", str(ctx.exception))
    self.assertEqual(tr.called, [])

  def test_allowed_url_is_fetched_and_pinned(self):
    tr = RecordingTransport({OK: BODY})
    self.assertEqual(source.fetch_bytes(OK, SHA, tr), BODY)
    self.assertEqual(tr.called, [OK])

  def test_pin_mismatch_is_refused(self):
    tr = RecordingTransport({OK: BODY})
    with self.assertRaises(source.SourceError) as ctx:
      source.fetch_bytes(OK, "ab" * 32, tr)
    self.assertIn("hash mismatch", str(ctx.exception))
    self.assertEqual(tr.called, [OK])

  def test_redirect_to_github_asset_host_is_allowed(self):
    asset = "https://objects.githubusercontent.com/github-production-release-asset-2e65be/file"
    tr = RecordingTransport({OK: SimpleNamespace(location=asset), asset: BODY})
    self.assertEqual(source.fetch_bytes(OK, SHA, tr), BODY)
    self.assertEqual(tr.called, [OK, asset])

  def test_redirect_to_any_other_host_is_refused_without_following(self):
    dest = "https://huggingface.co/commaai/openpilot_driving_models/resolve/main/x.onnx"
    tr = RecordingTransport({OK: SimpleNamespace(location=dest), dest: BODY})
    with self.assertRaises(source.SourceError):
      source.fetch_bytes(OK, SHA, tr)
    self.assertEqual(tr.called, [OK])  # dest is never requested

  def test_request_that_starts_on_an_asset_host_is_refused(self):
    asset = "https://objects.githubusercontent.com/github-production-release-asset-2e65be/file"
    tr = RecordingTransport({asset: BODY})
    with self.assertRaises(source.SourceError):
      source.fetch_bytes(asset, SHA, tr)
    self.assertEqual(tr.called, [])


class TestLicenses(unittest.TestCase):
  def test_known_redistributable_names_are_accepted(self):
    for name in source.ALLOWED_LICENSE_NAMES:
      self.assertTrue(source.license_is_redistributable(name), name)

  def test_unclear_or_other_licenses_are_excluded(self):
    for name in (None, "", "  ", "UNKNOWN", "Proprietary", "CC-BY-NC-4.0", "MIT OR GPL-2.0", "custom"):
      with self.subTest(name=name):
        self.assertFalse(source.license_is_redistributable(name))

  def test_catalog_offers_cheddar_and_skips_bad_entries(self):
    self.assertEqual([e["id"] for e in source.catalog_entries()], ["cheddar"])
    offered = source.catalog_entries((
      {"id": "ok", "license": "MIT", "url": OK},
      {"id": "unclear", "license": "", "url": OK},
      {"id": "other-host", "license": "MIT", "url": "https://huggingface.co/x/y"},
      {"id": "community", "license": "see Discord", "url": OK},
    ))
    self.assertEqual([e["id"] for e in offered], ["ok"])


if __name__ == "__main__":
  unittest.main()
