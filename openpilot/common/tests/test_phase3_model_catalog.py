"""Native stdlib tests; no model execution, device, road or UI required."""
import dataclasses
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from openpilot.common import phase3_model_catalog as mc

ROOT = Path(__file__).resolve().parents[3]


class Response(io.BytesIO):
  def __init__(self, url, data, length=None, status=200):
    super().__init__(data)
    self.url = url
    self.status = status
    self.headers = {} if length is None else {"Content-Length": str(length)}

  def geturl(self):
    return self.url


class TestCatalog(unittest.TestCase):
  def setUp(self):
    self.entry = mc.load_catalog(ROOT).entries[0]
    self.temp = tempfile.TemporaryDirectory(prefix="phase3-catalog-test-")
    self.tmp = Path(self.temp.name).resolve()
    self.addCleanup(self.temp.cleanup)

  def stage(self, opener, **kwargs):
    # Networking/ABI fixture only: fake entries are never exposed by real catalog.
    with patch.object(mc, "verify_runtime"), patch.object(mc, "_open_url", side_effect=opener):
      return mc.download_bundle(self.entry, self.tmp / "cache", root=ROOT, **kwargs)

  def test_only_stock_and_honest_blocker(self):
    c = mc.load_catalog(ROOT)
    self.assertEqual([e.id for e in c.entries], [mc.STOCK_ID])
    self.assertIn("No verified alternate", c.blockers[0])
    self.assertEqual(self.entry.name, "Default (stock)")
    self.assertEqual(len(self.entry.assets), 6)
    self.assertEqual(sum(a.size for a in self.entry.assets), 91403700)

  def test_urls_are_public_full_commit_pins(self):
    for a in self.entry.assets:
      self.assertIn("/" + mc.STOCK_COMMIT + "/", a.url)
      self.assertTrue(a.url.startswith("https://raw.githubusercontent.com/commaai/openpilot/"))
      self.assertEqual(len(a.sha256), 64)

  def test_all_six_existing_stock_assets_verify(self):
    mc.verify_bundle(self.entry, ROOT / mc.MODEL_DIR, root=ROOT)

  def test_manifest_tampering_is_rejected(self):
    p = self.tmp / mc.MANIFEST
    p.parent.mkdir(parents=True)
    p.write_text("{}")
    with self.assertRaisesRegex(mc.CatalogError, "integrity"):
      mc.load_catalog(self.tmp)

  def test_manifest_symlink_rejected(self):
    p = self.tmp / mc.MANIFEST
    p.parent.mkdir(parents=True)
    p.symlink_to(ROOT / mc.MANIFEST)
    with self.assertRaisesRegex(mc.CatalogError, "symlink"):
      mc.load_catalog(self.tmp)

  def test_legacy_model_is_not_trusted(self):
    for changed in ({"id": "dark-souls"}, {"version": "0.9.7"}, {"backend": "METAL"},
                    {"architecture": "x86_64"}, {"format": "thneed"}):
      with self.assertRaisesRegex(mc.CatalogError, "pinned compatible"):
        mc.verify_bundle(dataclasses.replace(self.entry, **changed), ROOT / mc.MODEL_DIR, root=ROOT)

  def test_url_or_hash_injection_rejected_before_network(self):
    for asset in (dataclasses.replace(self.entry.assets[0], url="http://localhost/model"),
                  dataclasses.replace(self.entry.assets[0], sha256="0" * 64)):
      entry = dataclasses.replace(self.entry, assets=(asset, *self.entry.assets[1:]))
      with patch.object(mc, "_open_url") as opener:
        with self.assertRaises(mc.CatalogError):
          mc.download_bundle(entry, self.tmp / "cache", root=ROOT)
        opener.assert_not_called()

  def test_architecture_backend_rejected(self):
    for arch, backend in (("darwin_arm64", "METAL"), ("comma_arm64", "USB+AMD"), ("x86_64", "QCOM")):
      with self.assertRaisesRegex(mc.CatalogError, "comma_arm64/QCOM"):
        mc.verify_runtime(ROOT, arch, backend)

  def test_runtime_dependency_drift_only_the_attested_lock_files(self):
    import hashlib
    m = json.loads((ROOT / mc.MANIFEST).read_bytes())
    drift = {rel for rel, pin in m["inputs"].items() if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != pin["sha256"]}
    self.assertLessEqual(drift, set(mc.ATTESTABLE))
    mc.verify_runtime(ROOT)  # real tree: stock pins + the two hash-attested lock files

  def _gate_with(self, wrong=None, **supplement_patch):
    import hashlib
    m = json.loads((ROOT / mc.MANIFEST).read_bytes())
    att = mc._supplement(ROOT)
    def fake(path):
      rel = Path(path).relative_to(ROOT).as_posix()
      if rel in (wrong or {}):
        return wrong[rel]
      return att.get(rel) or m["inputs"][rel]["sha256"]
    with patch.object(mc, "_digest", side_effect=fake):
      mc.verify_runtime(ROOT)

  def test_supplement_accepts_only_exact_attested_hashes(self):
    att = mc._supplement(ROOT)
    self.assertEqual(set(att), set(mc.ATTESTABLE))
    self._gate_with()
    for rel in mc.ATTESTABLE:
      with self.assertRaisesRegex(mc.CatalogError, "ABI drift: " + rel.replace(".", r"\.")):
        self._gate_with({rel: "0" * 64})

  def test_supplement_cannot_widen_beyond_lock_files_or_when_tampered(self):
    import hashlib
    sup = json.loads((ROOT / mc.SUPPLEMENT).read_bytes())
    sup["attestations"]["openpilot/selfdrive/modeld/get_model_metadata.py"] = {"sha256": "1" * 64}
    root = self.tmp / "r"; (root / mc.SUPPLEMENT).parent.mkdir(parents=True)
    raw = json.dumps(sup).encode()
    (root / mc.SUPPLEMENT).write_bytes(raw)
    self.assertEqual(mc._supplement(root), {})  # sha not pinned in code -> ignored entirely
    with patch.object(mc, "SUPPLEMENT_SHA256", hashlib.sha256(raw).hexdigest()):
      self.assertNotIn("openpilot/selfdrive/modeld/get_model_metadata.py", mc._supplement(root))  # only ATTESTABLE paths
    (root / mc.SUPPLEMENT).unlink(); (root / mc.SUPPLEMENT).symlink_to(ROOT / mc.SUPPLEMENT)
    self.assertEqual(mc._supplement(root), {})  # symlink refused
    self.assertEqual(mc._supplement(self.tmp / "nowhere"), {})  # missing -> stock pins only

  def test_missing_truncated_and_symlinked_assets(self):
    with self.assertRaises(mc.CatalogError):
      mc.verify_bundle(self.entry, self.tmp, root=ROOT)
    p = self.tmp / self.entry.assets[0].name
    p.write_bytes(b"truncated")
    with self.assertRaises(mc.CatalogError):
      mc.verify_bundle(self.entry, self.tmp, root=ROOT)
    p.unlink()
    p.symlink_to(ROOT / mc.MODEL_DIR / p.name)
    with self.assertRaises(mc.CatalogError):
      mc.verify_bundle(self.entry, self.tmp, root=ROOT)

  def test_same_size_corruption_rejected(self):
    a = self.entry.assets[0]
    with (self.tmp / a.name).open("wb") as f:
      f.truncate(a.size)
    with self.assertRaisesRegex(mc.CatalogError, "integrity"):
      mc.verify_bundle(self.entry, self.tmp, root=ROOT)

  def test_cancel_before_download_has_no_side_effects(self):
    cancel = threading.Event()
    cancel.set()
    with patch.object(mc, "_open_url") as opener:
      with self.assertRaises(mc.DownloadCancelled):
        self.stage(opener, cancel_event=cancel)
      opener.assert_not_called()
    self.assertFalse((self.tmp / "cache").exists())

  def test_invalid_timeouts(self):
    for timeout in (0, -1, 181):
      with self.assertRaises(mc.CatalogError):
        self.stage(lambda *_: None, timeout=timeout)

  def test_repository_cache_rejected(self):
    with patch.object(mc, "verify_runtime"):
      for cache in (ROOT, ROOT / "models", ROOT.parent):
        with self.assertRaisesRegex(mc.CatalogError, "overlap"):
          mc.download_bundle(self.entry, cache, root=ROOT)

  def test_symlink_cache_rejected(self):
    (self.tmp / "link").symlink_to(self.tmp, target_is_directory=True)
    with patch.object(mc, "verify_runtime"), self.assertRaisesRegex(mc.CatalogError, "symlink"):
      mc.download_bundle(self.entry, self.tmp / "link" / "cache", root=ROOT)

  def test_wrong_content_length_cleans_only_own_attempt(self):
    cache = self.tmp / "cache"
    cache.mkdir()
    (cache / "unrelated").write_text("keep")
    with self.assertRaises(mc.CatalogError):
      self.stage(lambda url, timeout: Response(url, b"x", length=1))
    self.assertEqual([p.name for p in cache.iterdir()], ["unrelated"])

  def test_http_error_and_redirect_rejected(self):
    for status, altered in ((404, False), (200, True)):
      def opener(url, timeout):
        return Response(url + "/redirect" if altered else url, b"", status=status)
      with self.assertRaises(mc.CatalogError):
        self.stage(opener)
      self.assertEqual(list((self.tmp / "cache").iterdir()), [])

  def test_early_eof_and_network_failure_cleanup(self):
    with self.assertRaisesRegex(mc.CatalogError, "integrity/size"):
      self.stage(lambda url, timeout: Response(url, b"x"))
    with self.assertRaisesRegex(mc.CatalogError, "no bundle published"):
      self.stage(lambda *_: (_ for _ in ()).throw(TimeoutError("socket deadline")))
    self.assertEqual(list((self.tmp / "cache").iterdir()), [])

  def test_existing_bad_cache_is_never_overwritten(self):
    target = self.tmp / "cache" / mc.STOCK_ID
    target.mkdir(parents=True)
    (target / "keep").write_text("do not replace")
    with self.assertRaises(mc.CatalogError):
      self.stage(lambda *_: self.fail("must not network"))
    self.assertEqual((target / "keep").read_text(), "do not replace")

  def test_cancel_midstream_cleanup(self):
    cancel = threading.Event()
    with self.assertRaises(mc.DownloadCancelled):
      self.stage(lambda url, timeout: Response(url, b"x" * 4096), cancel_event=cancel,
                 progress=lambda *_: cancel.set())
    self.assertEqual(list((self.tmp / "cache").iterdir()), [])

  def test_no_disk_space_has_no_network(self):
    with patch.object(mc.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(0, 0, 0)):
      with self.assertRaisesRegex(mc.CatalogError, "space"):
        self.stage(lambda *_: self.fail("must not network"))

  def test_valid_six_file_staging_and_cache_reuse(self):
    # Real source bytes, mocked transport only. No fake model hashes.
    def opener(url, timeout):
      name = url.rsplit("/", 1)[1]
      data = (ROOT / mc.MODEL_DIR / name).read_bytes()
      return Response(url, data, len(data))
    progress = []
    target = self.stage(opener, progress=lambda done, total: progress.append((done, total)))
    mc.verify_bundle(self.entry, target, root=ROOT)
    self.assertEqual(progress[-1][0], progress[-1][1])
    self.assertEqual(target, self.stage(lambda *_: self.fail("must reuse valid cache")))
    self.assertEqual(len(list(target.iterdir())), 6)
    self.assertEqual(list((self.tmp / "cache").iterdir()), [target])

  def test_hash_mismatch_and_oversized_body(self):
    # Transport lies about the length; cap at pinned size+1, never publish.
    a = self.entry.assets[0]
    for size in (a.size, a.size + 1):
      with self.assertRaises(mc.CatalogError):
        self.stage(lambda url, timeout: Response(url, b"x" * size))
      self.assertEqual(list((self.tmp / "cache").iterdir()), [])

  def test_encoded_and_invalid_length_rejected(self):
    for headers in ({"Content-Encoding": "gzip"}, {"Content-Length": "not-a-number"}):
      def opener(url, timeout):
        response = Response(url, b"x")
        response.headers.update(headers)
        return response
      with self.assertRaises(mc.CatalogError):
        self.stage(opener)
      self.assertEqual(list((self.tmp / "cache").iterdir()), [])

  def test_deadline_exceeded_cleans_staging(self):
    clock = [0.0]
    def opener(url, timeout):
      clock[0] = 2.0
      return Response(url, b"x")
    with patch.object(mc.time, "monotonic", side_effect=lambda: clock[0]):
      with self.assertRaisesRegex(mc.CatalogError, "deadline"):
        self.stage(opener, timeout=1)
    self.assertEqual(list((self.tmp / "cache").iterdir()), [])

  def test_progress_callback_failure_cleans_attempt(self):
    with self.assertRaisesRegex(RuntimeError, "callback"):
      self.stage(lambda url, timeout: Response(url, b"x"),
                 progress=lambda *_: (_ for _ in ()).throw(RuntimeError("callback")))
    self.assertEqual(list((self.tmp / "cache").iterdir()), [])

  def test_actual_redirect_handler_refuses_new_target(self):
    with self.assertRaisesRegex(mc.CatalogError, "redirect"):
      mc._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://localhost/private")

  def test_corrupt_cached_directory_is_not_used_after_cancel(self):
    target = self.tmp / "cache" / mc.STOCK_ID
    target.mkdir(parents=True)
    cancel = threading.Event()
    cancel.set()
    with self.assertRaises(mc.DownloadCancelled):
      self.stage(lambda *_: self.fail("must not network"), cancel_event=cancel)
    self.assertTrue(target.exists())

  def test_inspection_adapter_does_not_infer_active_or_compatibility(self):
    facts = mc.inspect_entry(self.entry, root=ROOT)
    self.assertTrue(facts.downloaded)
    self.assertTrue(facts.protected)
    self.assertFalse(hasattr(facts, "active_id"))
    self.assertFalse(hasattr(facts, "pending_id"))
    with patch.object(mc, "verify_runtime", side_effect=mc.CatalogError("test ABI drift")):
      rejected = mc.inspect_entry(self.entry, root=ROOT)
    self.assertFalse(rejected.compatible)
    self.assertTrue(rejected.downloaded)
    self.assertIn("test ABI drift", rejected.reason)
    self.assertNotEqual(facts.revision, rejected.revision)

  def test_inspection_revision_changes_with_missing_artifacts(self):
    with patch.object(mc, "verify_runtime"):
      good = mc.inspect_entry(self.entry, root=ROOT)
      missing = mc.inspect_entry(self.entry, directory=self.tmp, root=ROOT)
    self.assertTrue(good.compatible)
    self.assertFalse(missing.downloaded)
    self.assertTrue(missing.compatible)
    self.assertNotEqual(good.revision, missing.revision)


if __name__ == "__main__":
  unittest.main()
