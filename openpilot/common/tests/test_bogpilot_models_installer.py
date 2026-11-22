"""Model download/verify/install (installer.py) with an injected transport, then page -> store -> modeld wiring."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, installer, launcher, registry, selection, source
from openpilot.common.bogpilot_models.stock import STOCK_HASHES
from openpilot.common.tests import bogpilot_model_fixtures as fx
from openpilot.common.tests.test_bogpilot_model_launcher import STOCK_DIR, FakeModeld

BASE = "https://github.com/BogPilot/openpilot-models/releases/download/v1"
ASSET = "https://release-assets.githubusercontent.com/github-production-release-asset/1/abc"


class Resp:
  def __init__(self, content=None, location=None):
    self.content, self.location = content, location


class Transport:
  """url -> bytes or Resp. Records every requested URL."""

  def __init__(self, table):
    self.table, self.calls = dict(table), []

  def __call__(self, url):
    self.calls.append(url)
    if url not in self.table:
      raise source.SourceError("not found")
    return self.table[url]


def catalog_item(model_id="hosted", name="Hosted", driving=None, warps=None, license="MIT", base=BASE, **extra):
  driving = fx.driving_pickle_bytes() if driving is None else driving
  blobs = {"driving_tinygrad.pkl": ("driving_model", driving)}
  for role, data in (warps or {}).items():
    blobs[f"{role}_tinygrad.pkl"] = (role, data)
  files = [{"role": role, "name": n, "sha256": fx.sha(b), "size": len(b), "url": f"{base}/{n}"} for n, (role, b) in blobs.items()]
  item = {"id": model_id, "name": name, "version": "1.0", "openpilot": "0.11.2", "license": license,
          "onnx_sha256": fx.DEFAULT_ONNX_SHA256, "files": files, "url": files[0]["url"]}
  item.update(extra)
  table = {f"{base}/{n}": b for n, (_, b) in blobs.items()}
  return item, table


def stock_fingerprint():
  return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in registry.stock_models_dir().iterdir() if p.is_file()}


class Base(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name) / "models"
    self.offroad = True
    self.stock_before = stock_fingerprint()

  def gate(self):
    return self.offroad

  def leftovers(self):
    return sorted(p.name for p in self.root.iterdir() if p.name.startswith(".")) if self.root.exists() else []

  def tearDown(self):
    self.assertEqual(stock_fingerprint(), self.stock_before)  # the stock models are never written


class TestInstall(Base):
  def test_success_installs_a_valid_model_and_does_not_select_it(self):
    item, table = catalog_item(warps={"driving_warp_1344x760": fx.warp_pickle_bytes("driving_warp_1344x760")})
    t = Transport(table)
    store = fx.MemStore()
    r = installer.install(item, self.gate, t, self.root)
    self.assertTrue(r.ok, r.message)
    self.assertEqual(sorted(t.calls), sorted(table))
    self.assertEqual(self.leftovers(), [])
    entry = registry.get_entry("hosted", self.root)
    self.assertIsNotNone(entry)
    self.assertTrue(registry.validate_entry(entry).ok)
    manifest = json.loads((self.root / "hosted" / "manifest.json").read_text())
    self.assertNotIn("url", manifest)
    self.assertTrue(all("url" not in f for f in manifest["files"]))
    self.assertIsNone(store.raw(selection.KEY_SELECTION))  # installing never changes the choice

  def test_onroad_refuses_before_any_request(self):
    item, table = catalog_item()
    t = Transport(table)
    self.offroad = False
    r = installer.install(item, self.gate, t, self.root)
    self.assertFalse(r.ok)
    self.assertIn("offroad", r.message)
    self.assertEqual(t.calls, [])
    for bad in (lambda: 1, lambda: None):
      self.assertFalse(installer.install(item, bad, t, self.root).ok)

    def boom():
      raise RuntimeError("no state")
    self.assertFalse(installer.install(item, boom, t, self.root).ok)
    self.assertEqual(t.calls, [])

  def test_going_onroad_mid_download_stops_and_cleans_up(self):
    item, table = catalog_item(warps={"driving_warp_1344x760": fx.warp_pickle_bytes("driving_warp_1344x760")})
    t = Transport(table)
    seen = []

    def gate():
      seen.append(1)
      return len(seen) < 3   # offroad for the screen + first file, then the car turns on
    r = installer.install(item, gate, t, self.root)
    self.assertFalse(r.ok)
    self.assertIsNone(registry.get_entry("hosted", self.root))
    self.assertEqual(self.leftovers(), [])

  def test_other_hosts_and_unclear_licenses_are_never_requested(self):
    for item, table in (catalog_item(base="https://huggingface.co/x/y/resolve/main"),
                        catalog_item(base="https://github.com/someone-else/models/releases/download/v1"),
                        catalog_item(base="http://github.com/BogPilot/m/releases/download/v1"),
                        catalog_item(license="Custom (permission required)"),
                        catalog_item(license="")):
      t = Transport(table)
      r = installer.install(item, self.gate, t, self.root)
      self.assertFalse(r.ok)
      self.assertEqual(t.calls, [], item)
    self.assertEqual(self.leftovers(), [])

  def test_split_vision_policy_items_are_refused(self):
    item, table = catalog_item()
    item["files"][0]["role"] = "vision"
    r = installer.install(item, self.gate, Transport(table), self.root)
    self.assertFalse(r.ok)
    self.assertIn("vision/policy", r.message)

  def test_hash_mismatch_installs_nothing(self):
    item, table = catalog_item()
    url = item["files"][0]["url"]
    table[url] = table[url][:-1] + bytes([table[url][-1] ^ 1])
    r = installer.install(item, self.gate, Transport(table), self.root)
    self.assertFalse(r.ok)
    self.assertIn("hash mismatch", r.message)
    self.assertIsNone(registry.get_entry("hosted", self.root))
    self.assertEqual(self.leftovers(), [])

  def test_redirect_only_to_github_asset_hosts(self):
    item, table = catalog_item()
    url = item["files"][0]["url"]
    good = dict(table)
    good[url], good[ASSET] = Resp(location=ASSET), table[url]
    self.assertTrue(installer.install(item, self.gate, Transport(good), self.root).ok)
    item2, table2 = catalog_item("hosted2")
    url2 = item2["files"][0]["url"]
    evil = "https://evil.example.com/driving_tinygrad.pkl"
    bad = {url2: Resp(location=evil), evil: table2[url2]}
    t = Transport(bad)
    r = installer.install(item2, self.gate, t, self.root)
    self.assertFalse(r.ok)
    self.assertNotIn(evil, t.calls)
    self.assertIsNone(registry.get_entry("hosted2", self.root))

  def test_incompatible_model_is_downloaded_but_never_installed(self):
    slices = dict(fx.stock_abi_variant()["output_slices"])
    slices["action"] = [2576, 2580]   # what upstream's Cheddar adds; 0.11.2 modeld has no such output
    abi = fx.stock_abi_variant(output_slices=slices)
    item, table = catalog_item(driving=fx.driving_pickle_bytes(abi))
    r = installer.install(item, self.gate, Transport(table), self.root)
    self.assertFalse(r.ok)
    self.assertIn("Not installed", r.message)
    self.assertIsNone(registry.get_entry("hosted", self.root))
    self.assertEqual(self.leftovers(), [])

  def test_failed_update_keeps_the_previous_install(self):
    item, table = catalog_item()
    self.assertTrue(installer.install(item, self.gate, Transport(table), self.root).ok)
    before = (self.root / "hosted" / "manifest.json").read_bytes()
    item2, table2 = catalog_item(version="2.0")
    url = item2["files"][0]["url"]
    table2[url] = b"x" * len(table2[url])
    self.assertFalse(installer.install(item2, self.gate, Transport(table2), self.root).ok)
    self.assertEqual((self.root / "hosted" / "manifest.json").read_bytes(), before)
    self.assertTrue(registry.validate_entry(registry.get_entry("hosted", self.root)).ok)
    self.assertEqual(self.leftovers(), [])

  def test_successful_update_replaces_in_place(self):
    item, table = catalog_item()
    self.assertTrue(installer.install(item, self.gate, Transport(table), self.root).ok)
    item2, table2 = catalog_item(version="2.0")
    self.assertTrue(installer.install(item2, self.gate, Transport(table2), self.root).ok)
    self.assertEqual(registry.get_entry("hosted", self.root).version, "2.0")
    self.assertEqual(self.leftovers(), [])

  def test_remove_resets_the_choice_and_refuses_stock(self):
    item, table = catalog_item()
    store = fx.MemStore()
    self.assertTrue(installer.install(item, self.gate, Transport(table), self.root).ok)
    self.assertTrue(selection.select("hosted", self.gate, store, self.root).ok)
    self.assertFalse(installer.remove(STOCK_ID, self.gate, store, self.root).ok)
    self.offroad = False
    self.assertFalse(installer.remove("hosted", self.gate, store, self.root).ok)
    self.offroad = True
    self.assertTrue(installer.remove("hosted", self.gate, store, self.root).ok)
    self.assertIsNone(store.raw(selection.KEY_SELECTION))
    self.assertFalse((self.root / "hosted").exists())

  def test_shipped_catalog_is_empty_and_excluded_list_is_names_only(self):
    self.assertEqual(source.CATALOG, ())
    self.assertTrue(source.EXCLUDED)
    for name, why in source.EXCLUDED:
      self.assertNotIn("http", name + why)

  def test_https_transport_refuses_redirects_itself(self):
    import urllib.request
    calls = []

    class FakeErr(urllib.error.HTTPError):
      pass

    class Opener:
      def open(self, req, timeout=None):
        calls.append(req.full_url)
        raise FakeErr(req.full_url, 302, "Found", {"Location": ASSET}, None)
    orig = urllib.request.build_opener
    urllib.request.build_opener = lambda *a: Opener()
    try:
      resp = installer.https_transport(BASE + "/driving_tinygrad.pkl")
    finally:
      urllib.request.build_opener = orig
    self.assertEqual(resp.location, ASSET)
    self.assertEqual(calls, [BASE + "/driving_tinygrad.pkl"])


class TestDownloadToModeld(Base):
  """Download -> page select -> store -> modeld launcher, with the real validation and the fake modeld."""

  def setUp(self):
    super().setUp()
    old = os.environ.get("BOGPILOT_MODELS_DIR")
    os.environ["BOGPILOT_MODELS_DIR"] = str(self.root)
    self.addCleanup(lambda: os.environ.pop("BOGPILOT_MODELS_DIR") if old is None else os.environ.__setitem__("BOGPILOT_MODELS_DIR", old))
    from openpilot.selfdrive.ui.bogpilot.bogpilot_model_selector import ModelSelectorController
    self.store = fx.MemStore()
    self.item, self.table = catalog_item(name="Hosted Model")
    self.transport = Transport(self.table)
    self.ui = ModelSelectorController(self.gate, self.store, self.root, catalog=(self.item,), transport=self.transport,
                                      download_gate=self.gate)

  def drive(self, **behave):
    m = FakeModeld(**behave)
    launcher.run(m, self.store)
    return m

  def test_download_select_then_next_drive_uses_it_and_falls_back_on_failure(self):
    snap = self.ui.refresh()
    self.assertEqual([d[0] for d in snap.downloads], ["hosted"])
    self.assertTrue(snap.can_download)
    self.assertTrue(self.ui.download("hosted").ok, self.ui.message)
    snap = self.ui.refresh()
    self.assertEqual(snap.downloads, ())
    self.assertEqual([i for i, _ in snap.choices], [STOCK_ID, "hosted"])
    self.assertTrue(self.drive().live.is_stock)           # installed but not chosen: stock
    self.assertTrue(self.ui.select("hosted").ok)
    m = self.drive()
    self.assertEqual(m.live.pkl, self.root / "hosted" / "driving_tinygrad.pkl")
    self.assertEqual(self.ui.refresh().status, "Active: Hosted Model")
    failed = self.drive(fail_load=True)
    self.assertEqual(failed.live.pkl, STOCK_DIR / "driving_tinygrad.pkl")
    self.assertIn("Hosted Model", self.ui.refresh().notice)

  def test_download_refused_while_driving_even_if_selection_gate_is_open(self):
    ui = type(self.ui)(lambda: True, self.store, self.root, catalog=(self.item,), transport=self.transport,
                       download_gate=lambda: False)
    self.assertFalse(ui.refresh().can_download)
    self.assertFalse(ui.download("hosted").ok)
    self.assertEqual(self.transport.calls, [])

  def test_no_download_gate_means_no_download(self):
    ui = type(self.ui)(lambda: True, self.store, self.root, catalog=(self.item,), transport=self.transport)
    self.assertFalse(ui.download("hosted").ok)
    self.assertEqual(self.transport.calls, [])

  def test_corrupt_after_install_falls_back_to_stock(self):
    self.assertTrue(self.ui.download("hosted").ok)
    self.assertTrue(self.ui.select("hosted").ok)
    p = self.root / "hosted" / "driving_tinygrad.pkl"
    b = bytearray(p.read_bytes())
    b[-1] ^= 1
    p.write_bytes(bytes(b))
    self.assertTrue(self.drive().live.is_stock)
    self.assertIn("hash mismatch", self.ui.refresh().notice)

  def test_missing_files_fall_back_to_stock(self):
    self.assertTrue(self.ui.download("hosted").ok)
    self.assertTrue(self.ui.select("hosted").ok)
    (self.root / "hosted" / "driving_tinygrad.pkl").unlink()
    self.assertTrue(self.drive().live.is_stock)
    self.assertIn("missing", self.ui.refresh().notice)

  def test_stock_pins_unchanged(self):
    self.assertEqual(STOCK_HASHES["driving_tinygrad.pkl"][:12], "6398a4b0e474")


if __name__ == "__main__":
  unittest.main()
