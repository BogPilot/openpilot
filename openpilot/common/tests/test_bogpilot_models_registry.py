"""BogPilot model registry: manifest parsing, hashing, 0.11.2 compatibility checks, and the stock pins."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, STOCK_NAME, abi, compat, registry
from openpilot.common.bogpilot_models.stock import ROLE_STOCK_FILES, STOCK_DRIVING_ABI, STOCK_HASHES, STOCK_WARP_ABI
from openpilot.common.tests import bogpilot_model_fixtures as fx

ROOT = Path(__file__).resolve().parents[3]
STOCK_DIR = ROOT / "openpilot/selfdrive/modeld/models"


def good_manifest(**edits):
  data = fx.driving_pickle_bytes()
  m = {"schema": 1, "id": "m1", "name": "M One", "version": "1", "openpilot": "0.11.2", "license": "MIT",
       "files": [{"role": "driving_model", "name": "d.pkl", "sha256": fx.sha(data), "size": len(data)}]}
  m.update(edits)
  return json.dumps(m).encode()


class TestStockPins(unittest.TestCase):
  def test_six_stock_hashes_unchanged_on_disk(self):
    self.assertEqual(len(STOCK_HASHES), 6)
    for name, want in STOCK_HASHES.items():
      got, _ = abi.sha256_file(STOCK_DIR / name)
      self.assertEqual(got, want, name)

  def test_pins_match_release_stock_manifest_when_present(self):
    p = ROOT / "tools/bogpilot/c3x_stock_models_f7db927.json"
    if not p.exists():
      self.skipTest("release manifest not in this tree")
    assets = json.loads(p.read_text())["assets"]
    for name, want in STOCK_HASHES.items():
      self.assertEqual(assets[f"openpilot/selfdrive/modeld/models/{name}"]["sha256"], want)

  def test_pinned_abi_equals_real_stock_files(self):
    self.assertEqual(abi.read_driving_abi(STOCK_DIR / "driving_tinygrad.pkl"), STOCK_DRIVING_ABI)
    for role, fname in ROLE_STOCK_FILES.items():
      if role != "driving_model":
        self.assertEqual(abi.read_warp_abi(STOCK_DIR / fname), STOCK_WARP_ABI[role])

  def test_stock_is_compatible_with_itself(self):
    self.assertEqual(compat.check_driving_abi(STOCK_DRIVING_ABI), [])
    for role in STOCK_WARP_ABI:
      self.assertEqual(compat.check_warp_abi(STOCK_WARP_ABI[role], role), [])

  def test_stock_entry_is_default_with_license_version_hashes(self):
    e = registry.stock_entry()
    self.assertEqual((e.id, e.name, e.builtin), (STOCK_ID, STOCK_NAME, True))
    self.assertEqual(e.version, "0.11.2")
    self.assertTrue(e.license)
    self.assertEqual(e.model_sha256, STOCK_HASHES["driving_tinygrad.pkl"])
    self.assertEqual({r for r, _, _ in e.file_names}, set(ROLE_STOCK_FILES))
    self.assertTrue(registry.validate_entry(e).ok)

  def test_real_stock_files_pass_the_full_alternate_validation(self):
    with tempfile.TemporaryDirectory() as t:
      d = Path(t) / "copy"
      d.mkdir()
      files = []
      for role, fname in ROLE_STOCK_FILES.items():
        data = (STOCK_DIR / fname).read_bytes()
        (d / fname).write_bytes(data)
        files.append({"role": role, "name": fname, "sha256": fx.sha(data), "size": len(data)})
      (d / "manifest.json").write_text(json.dumps({"schema": 1, "id": "copy", "name": "Copy", "version": "1", "openpilot": "0.11.2",
                                                   "license": "MIT", "files": files}))
      v = registry.validate_entry(registry.get_entry("copy", t))
      self.assertTrue(v.ok, v.reason)
      self.assertEqual(v.abi_digest, abi.digest(STOCK_DRIVING_ABI))


class TestManifest(unittest.TestCase):
  def test_valid(self):
    m = registry.parse_manifest(good_manifest(license={"name": "Apache-2.0"}, description="x"))
    self.assertEqual((m.id, m.name, m.version, m.license, m.openpilot), ("m1", "M One", "1", "Apache-2.0", "0.11.2"))
    self.assertEqual(m.files[0].role, "driving_model")

  def test_rejections(self):
    base = json.loads(good_manifest())
    f0 = base["files"][0]

    def with_(**kw):
      return json.dumps({**base, **kw}).encode()

    def file_(**kw):
      return with_(files=[{**f0, **kw}])

    cases = {
      "not json": b"{nope",
      "not object": b"[]",
      "schema": with_(schema=2),
      "kind": with_(kind="dm"),
      "empty id": with_(id=""),
      "uppercase id": with_(id="Bad"),
      "reserved id": with_(id="default"),
      "path id": with_(id="../x"),
      "no license": json.dumps({k: v for k, v in base.items() if k != "license"}).encode(),
      "empty license": with_(license="  "),
      "license object without name": with_(license={"url": "x"}),
      "no files": with_(files=[]),
      "no driving": with_(files=[{**f0, "role": "driving_warp_1344x760"}]),
      "split vision": with_(files=[{**f0, "role": "vision"}]),
      "split policy": with_(files=[f0, {**f0, "role": "policy", "name": "p.pkl"}]),
      "dup role": with_(files=[f0, {**f0, "name": "o.pkl"}]),
      "dup name": with_(files=[f0, {**f0, "role": "driving_warp_1344x760"}]),
      "traversal": file_(name="../d.pkl"),
      "absolute": file_(name="/etc/passwd"),
      "subdir": file_(name="a/b.pkl"),
      "hidden": file_(name=".d.pkl"),
      "manifest name": file_(name="manifest.json"),
      "bad sha": file_(sha256="XYZ"),
      "uppercase sha": file_(sha256=f0["sha256"].upper()),
      "zero size": file_(size=0),
      "huge size": file_(size=10**10),
      "bool size": file_(size=True),
      "bad abi digest": with_(abi_digest="nope"),
      "name too long": with_(name="x" * 80),
      "control char": with_(version="1\n2"),
      "oversized": b" " * (registry.MAX_MANIFEST_BYTES + 1),
    }
    for label, raw in cases.items():
      with self.subTest(label), self.assertRaises(registry.ManifestError):
        registry.parse_manifest(raw)


class TestRegistryListing(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)

  def tearDown(self):
    self.tmp.cleanup()

  def test_no_directory_means_only_default(self):
    self.assertEqual([e.id for e in registry.list_entries(self.root / "nope")], [STOCK_ID])

  def test_default_first_then_sorted_ids(self):
    fx.install_model(self.root, "zeta")
    fx.install_model(self.root, "alpha")
    self.assertEqual([e.id for e in registry.list_entries(self.root)], [STOCK_ID, "alpha", "zeta"])

  def test_invalid_listed_with_problem_and_unusable(self):
    (self.root / "broken").mkdir()
    (self.root / "broken" / "manifest.json").write_text("{")
    fx.install_model(self.root, "other")
    fx.rewrite_manifest(self.root / "other", id="renamed")
    entries = {e.id: e for e in registry.list_entries(self.root)}
    for k in ("broken", "other"):
      self.assertTrue(entries[k].problem, k)
      self.assertFalse(registry.validate_entry(entries[k]).ok)

  def test_symlink_hidden_and_stray_files_ignored(self):
    fx.install_model(self.root, "real")
    os.symlink(self.root / "real", self.root / "link")
    (self.root / ".staging").mkdir()
    (self.root / "note.txt").write_text("x")
    self.assertEqual([e.id for e in registry.list_entries(self.root)], [STOCK_ID, "real"])

  def test_models_dir_env_override(self):
    os.environ["BOGPILOT_MODELS_DIR"] = str(self.root)
    try:
      self.assertEqual(registry.models_dir(), self.root)
    finally:
      del os.environ["BOGPILOT_MODELS_DIR"]


class TestValidation(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.n = 0

  def tearDown(self):
    self.tmp.cleanup()

  def check(self, mid=None, **kw):
    self.n += 1
    mid = mid or f"t{self.n}"
    fx.install_model(self.root, mid, **kw)
    return registry.validate_entry(registry.get_entry(mid, self.root))

  def test_valid_with_warps(self):
    v = self.check(warps={"driving_warp_1344x760": fx.warp_pickle_bytes("driving_warp_1344x760"),
                          "driving_warp_1928x1208": fx.warp_pickle_bytes("driving_warp_1928x1208")})
    self.assertTrue(v.ok, v.reason)
    self.assertEqual(set(v.paths), {"driving_model", "driving_warp_1344x760", "driving_warp_1928x1208"})
    self.assertEqual(v.abi_digest, abi.digest(STOCK_DRIVING_ABI))

  def test_hash_mismatch_same_size(self):
    good = fx.driving_pickle_bytes()
    bad = bytearray(good)
    bad[-1] ^= 1
    v = self.check(driving=bytes(bad), declared_driving=good)
    self.assertFalse(v.ok)
    self.assertIn("hash mismatch", v.reason)

  def test_size_mismatch_missing_and_symlinked_files(self):
    good = fx.driving_pickle_bytes()
    self.assertIn("size", self.check("a", driving=good + b"x", declared_driving=good).reason)
    d = fx.install_model(self.root, "b")
    (d / "driving.pkl").unlink()
    self.assertIn("missing", registry.validate_entry(registry.get_entry("b", self.root)).reason)
    d = fx.install_model(self.root, "c")
    os.replace(d / "driving.pkl", self.root / "elsewhere.pkl")
    os.symlink(self.root / "elsewhere.pkl", d / "driving.pkl")
    self.assertIn("not a regular file", registry.validate_entry(registry.get_entry("c", self.root)).reason)

  def test_wrong_openpilot_version(self):
    self.assertIn("openpilot 0.10.3", self.check(openpilot="0.10.3").reason)

  def test_abi_digest_pin(self):
    self.assertTrue(self.check(extra_manifest={"abi_digest": abi.digest(STOCK_DRIVING_ABI)}).ok)
    self.assertIn("abi_digest", self.check(extra_manifest={"abi_digest": "0" * 64}).reason)

  def test_incompatible_shapes_and_interfaces(self):
    cases = {
      "new_img shape": fx.stock_abi_variant(**{"input_specs.new_img": [[2, 6, 64, 64], "uint8", "QCOM"]}),
      "desire dtype": fx.stock_abi_variant(**{"input_specs.desire": [[8], "float16", "QCOM"]}),
      "missing required input": fx.stock_abi_variant(**{"input_specs.action_t": None}),
      "outputs shape": fx.stock_abi_variant(**{"output_specs.outputs": [[1, 2580], "float32", "QCOM"]}),
      "state without next": fx.stock_abi_variant(**{"output_specs.next_state_feat_q": None}),
      "state next mismatch": fx.stock_abi_variant(**{"output_specs.next_state_feat_q": [[96, 1, 256], "float32", "QCOM"]}),
      "slice length": fx.stock_abi_variant(**{"output_slices.plan": [1576, 2000]}),
      "slice missing": fx.stock_abi_variant(**{"output_slices.lead": None}),
      "extra slice": fx.stock_abi_variant(**{"output_slices.extra": [0, 4]}),
      "metadata shapes": fx.stock_abi_variant(**{"input_shapes.new_img": [2, 6, 128, 255]}),
      "extra output": fx.stock_abi_variant(**{"output_specs.surprise": [[1], "float32", "QCOM"]}),
      "wrong device": fx.stock_abi_variant(**{"input_specs.new_img": [[2, 6, 128, 256], "uint8", "CPU"]}),
    }
    for label, variant in cases.items():
      with self.subTest(label):
        v = self.check(driving=fx.driving_pickle_bytes(variant))
        self.assertFalse(v.ok, label)
        self.assertTrue(v.problems)

  def test_extra_state_queue_with_matching_next_is_compatible(self):
    v = fx.stock_abi_variant(**{"input_specs.state_extra": [[4, 1, 8], "float32", "QCOM"],
                                "output_specs.next_state_extra": [[4, 1, 8], "float32", "QCOM"],
                                "input_shapes.state_extra": [4, 1, 8], "output_shapes.next_state_extra": [4, 1, 8]})
    self.assertEqual(compat.check_driving_abi(v), [])

  def test_pickle_with_foreign_global_is_rejected_without_running_it(self):
    v = self.check(driving=fx.driving_pickle_bytes(extra_class="os.system"))
    self.assertFalse(v.ok)
    self.assertIn("os.system", v.reason)

  def test_garbage_and_truncated_models(self):
    for label, data in {"garbage": b"not a pickle at all" * 4, "short": b"\x01\x02", "truncated": fx.driving_pickle_bytes()[:40],
                        "huge header": b"\xff" * 8 + b"x" * 32}.items():
      with self.subTest(label):
        v = self.check(driving=data)
        self.assertFalse(v.ok)
        self.assertIn("unreadable", v.reason)

  def test_incompatible_warp(self):
    bad = copy.deepcopy(STOCK_WARP_ABI["driving_warp_1344x760"])
    bad["input_specs"]["input_frame"] = [[2, 123], "|u1", "QCOM"]
    v = self.check(warps={"driving_warp_1344x760": fx.warp_pickle_bytes("driving_warp_1344x760", bad)})
    self.assertFalse(v.ok)
    self.assertIn("warp inputs", v.reason)

  def test_manifest_changed_after_listing(self):
    fx.install_model(self.root, "late")
    e = registry.get_entry("late", self.root)
    fx.rewrite_manifest(self.root / "late", name="Edited")
    self.assertIn("changed", registry.validate_entry(e).reason)

  def test_hash_cache_avoids_rehashing_unchanged_files(self):
    fx.install_model(self.root, "cached")
    e = registry.get_entry("cached", self.root)
    cache, calls, real = {}, [], abi.sha256_file
    abi.sha256_file = lambda p, *a, **k: (calls.append(p), real(p, *a, **k))[1]
    try:
      self.assertTrue(registry.validate_entry(e, cache).ok)
      self.assertTrue(registry.validate_entry(e, cache).ok)
    finally:
      abi.sha256_file = real
    self.assertEqual(len(calls), 1)
    p = self.root / "cached" / "driving.pkl"
    p.write_bytes(p.read_bytes()[:-1] + b"\x07")  # same size, new content: the cache must not hide it
    self.assertFalse(registry.validate_entry(e, cache).ok)

  def test_validate_never_raises(self):
    e = registry.Entry("x", "x", "1", "MIT", False, Path("/definitely/not/here"), registry.parse_manifest(good_manifest(id="x")), ())
    self.assertFalse(registry.validate_entry(e).ok)


if __name__ == "__main__":
  unittest.main()
