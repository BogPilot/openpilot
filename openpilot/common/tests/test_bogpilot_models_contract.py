"""The "fits the 0.11.2 driving code" check (compat.check_driving_abi) against real candidate model interfaces.

The interfaces in bogpilot_model_candidate_abis.json were read from the candidate ONNX files with
tools/bogpilot/onnx_io_abi.py (no weights loaded). Set BOGPILOT_MODEL_CANDIDATES to the research folder that holds
the ONNX files (onnx_compat/ and candidates/) to re-read them and compare.
"""
import copy
import json
import os
import sys
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, compat, installer, source
from openpilot.common.bogpilot_models.stock import STOCK_DRIVING_ABI

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = json.loads((HERE / "bogpilot_model_candidate_abis.json").read_text())["models"]
CHEDDAR_SHA = "350a47ea36e554fb71634c7361b2c2a2a3da07ecb211a4c6cff3d2c3013d1d82"
SUNNYPILOT_CUSTOM = ("sp_fully_e2e_feaf52c1f", "sp_lag_derived_da6f2ead1", "sp_no_dynamo_5ebc89b3e",
                     "sp_no_floor_98fb0138f", "sp_fix_instagram_746207852", "sp_fast_greens_1d728da40")


def abi_of(key: str) -> dict:
  a = copy.deepcopy(DATA[key]["abi"])
  a["classes"] = list(STOCK_DRIVING_ABI["classes"])
  a["run"] = STOCK_DRIVING_ABI["run"]
  return a


def cheddar(**edits) -> dict:
  a = abi_of("cheddar_b3ab22efe")
  for dotted, value in edits.items():
    d, parts = a, dotted.split(".")
    for p in parts[:-1]:
      d = d[p]
    if value is None:
      d.pop(parts[-1])
    else:
      d[parts[-1]] = value
  return a


class TestCandidates(unittest.TestCase):
  def test_fixture_hashes(self):
    self.assertEqual(DATA["cheddar_b3ab22efe"]["onnx_sha256"], CHEDDAR_SHA)
    self.assertEqual(DATA["stock_v0112"]["onnx_sha256"], "65a08adc31d5c456219687d99b7bf5e44d61dae2d49ea67850e76105c7248cce")
    self.assertEqual(DATA["cheddar_nov05_875a6b7e1"]["onnx_sha256"],
                     "5520d198bbbe2736b7fbbc432c2d7a97e306db74214aa1677fed70521b9b9eb4")

  def test_stock_onnx_interface_equals_the_pinned_compiled_stock_model(self):
    a = abi_of("stock_v0112")
    for k in ("input_specs", "output_specs", "input_shapes", "output_shapes", "output_slices"):
      self.assertEqual(a[k], STOCK_DRIVING_ABI[k], k)

  def test_stock_fits(self):
    self.assertEqual(compat.check_driving_abi(STOCK_DRIVING_ABI), [])
    self.assertEqual(compat.check_driving_abi(abi_of("stock_v0112")), [])

  def test_cheddar_b3ab22efe_fits(self):
    a = abi_of("cheddar_b3ab22efe")
    self.assertEqual(compat.check_driving_abi(a), [])
    # it is not identical to stock: that is exactly what the old check refused
    self.assertEqual(a["output_specs"]["outputs"][0], [1, 2580])
    self.assertEqual(a["input_specs"]["state_desire_q"][0], [132, 1, 8])
    self.assertEqual(a["input_specs"]["state_feat_q"][0], [128, 1, 512])
    self.assertEqual(a["output_slices"]["action"], [2062, 2066])

  def test_cheddar_nov05_875a6b7e1_fits(self):
    self.assertEqual(compat.check_driving_abi(abi_of("cheddar_nov05_875a6b7e1")), [])

  def test_sunnypilot_custom_models_are_rejected_for_inputs_modeld_never_feeds(self):
    for key in SUNNYPILOT_CUSTOM:
      with self.subTest(key):
        bad = compat.check_driving_abi(abi_of(key))
        self.assertTrue(bad)
        self.assertTrue(any("is not fed by the 0.11.2 modeld" in b for b in bad), bad)
        self.assertTrue(any("speed_limit" in b or "state_curve" in b or "light_img" in b for b in bad), bad)

  def test_comma_pre_queue_model_is_rejected(self):
    bad = compat.check_driving_abi(abi_of("comma_rebel_legion_289534674"))
    self.assertTrue(any("input new_img" in b for b in bad), bad)

  def test_sunnypilot_cheddar_reexport_fits_but_is_excluded_by_source_policy(self):
    self.assertEqual(compat.check_driving_abi(abi_of("sp_chd_ac638611b")), [])
    self.assertTrue(any("sp CHD" in name for name, _ in source.EXCLUDED))
    offered = {i.get("onnx_sha256") for i in source.CATALOG + source.PENDING}
    self.assertNotIn(DATA["sp_chd_ac638611b"]["onnx_sha256"], offered)

  def test_rederive_from_real_onnx_when_available(self):
    base = os.environ.get("BOGPILOT_MODEL_CANDIDATES")
    if not base or not Path(base).is_dir():
      self.skipTest("BOGPILOT_MODEL_CANDIDATES not set")
    sys.path.insert(0, str(ROOT / "tools/bogpilot"))
    from onnx_io_abi import onnx_driving_abi
    for key, item in DATA.items():
      with self.subTest(key):
        a = onnx_driving_abi(Path(base) / item["file"])
        a.pop("classes"), a.pop("run")
        self.assertEqual(a, item["abi"])


class TestContractRules(unittest.TestCase):
  def assertRejected(self, a, needle):
    bad = compat.check_driving_abi(a)
    self.assertTrue(any(needle in b for b in bad), bad)

  def test_extra_input_with_matching_next_output_is_still_rejected(self):
    self.assertRejected(cheddar(**{"input_specs.state_curve": [[1, 1], "float32", "QCOM"],
                                   "output_specs.next_state_curve": [[1, 1], "float32", "QCOM"],
                                   "input_shapes.state_curve": [1, 1], "output_shapes.next_state_curve": [1, 1]}),
                        "state_curve is not fed")

  def test_fed_inputs_must_match_exactly(self):
    self.assertRejected(cheddar(**{"input_specs.desire": [[8], "float16", "QCOM"], "input_shapes.desire": [8]}), "input desire")
    self.assertRejected(cheddar(**{"input_specs.new_img": [[1, 6, 128, 256], "uint8", "QCOM"],
                                   "input_shapes.new_img": [1, 6, 128, 256]}), "input new_img")
    self.assertRejected(cheddar(**{"input_specs.action_t": None, "input_shapes.action_t": None}), "input action_t")

  def test_queue_only_history_axis_may_change(self):
    self.assertRejected(cheddar(**{"input_specs.state_feat_q": [[128, 1, 256], "float32", "QCOM"],
                                   "output_specs.next_state_feat_q": [[128, 1, 256], "float32", "QCOM"],
                                   "input_shapes.state_feat_q": [128, 1, 256], "output_shapes.next_state_feat_q": [128, 1, 256]}),
                        "outside its history axis")
    self.assertRejected(cheddar(**{"input_specs.state_img_q": [[2, 5, 6, 128, 256], "float32", "QCOM"],
                                   "output_specs.next_state_img_q": [[2, 5, 6, 128, 256], "float32", "QCOM"]}),
                        "state input state_img_q")
    longer = [[2, 10, 6, 128, 256], "uint8", "QCOM"]
    self.assertEqual(compat.check_driving_abi(cheddar(**{"input_specs.state_img_q": longer, "output_specs.next_state_img_q": longer,
                                                        "input_shapes.state_img_q": longer[0],
                                                        "output_shapes.next_state_img_q": longer[0]})), [])

  def test_queue_history_length_is_bounded(self):
    huge = [[401, 1, 8], "float32", "QCOM"]
    self.assertRejected(cheddar(**{"input_specs.state_desire_q": huge, "output_specs.next_state_desire_q": huge,
                                   "input_shapes.state_desire_q": huge[0], "output_shapes.next_state_desire_q": huge[0]}),
                        "history length 401")

  def test_queue_needs_its_next_output_and_metadata(self):
    self.assertRejected(cheddar(**{"output_specs.next_state_feat_q": None, "output_shapes.next_state_feat_q": None}),
                        "no matching next_state_feat_q")
    self.assertRejected(cheddar(**{"input_specs.state_feat_q": None, "input_shapes.state_feat_q": None,
                                   "output_specs.next_state_feat_q": None, "output_shapes.next_state_feat_q": None}),
                        "state_feat_q is missing")

  def test_outputs_size_comes_from_metadata_and_must_agree(self):
    self.assertRejected(cheddar(**{"output_shapes.outputs": [1, 2576]}), "metadata output_shapes disagrees")
    self.assertRejected(cheddar(**{"output_specs.outputs": [[2, 2580], "float32", "QCOM"], "output_shapes.outputs": [2, 2580]}),
                        "outputs is")
    self.assertRejected(cheddar(**{"output_specs.surprise": [[1], "float32", "QCOM"], "output_shapes.surprise": [1]}),
                        "unexpected outputs: surprise")

  def test_slices(self):
    self.assertRejected(cheddar(**{"output_slices.action": [2062, 2065]}), "action has 3 values")
    self.assertRejected(cheddar(**{"output_slices.plan": [917, 1900]}), "plan has 983 values")
    self.assertRejected(cheddar(**{"output_slices.lead": None}), "lack lead")
    self.assertRejected(cheddar(**{"output_slices.curve": [0, 1]}), "does not read: curve")
    self.assertRejected(cheddar(**{"output_slices.hidden_state": [2100, 2612]}), "hidden_state")
    no_action = cheddar(**{"output_slices.action": None})
    self.assertEqual(compat.check_driving_abi(no_action), [])

  def test_device_is_the_compile_target(self):
    cpu = cheddar()
    for group in ("input_specs", "output_specs"):
      for spec in cpu[group].values():
        spec[2] = "CPU"
    self.assertTrue(compat.check_driving_abi(cpu))
    self.assertEqual(compat.check_driving_abi(cpu, device="CPU"), [])

  def test_foreign_pickle_class_and_run_still_rejected(self):
    a = cheddar()
    a["classes"] = a["classes"] + ["os.system"]
    self.assertRejected(a, "os.system")
    a = cheddar(run="builtins.eval")
    self.assertRejected(a, "run program")


class TestCheddarPending(unittest.TestCase):
  def item(self):
    return next(i for i in source.PENDING if i["id"] == "cheddar")

  def test_prepared_entry(self):
    c = self.item()
    self.assertEqual(c["onnx_sha256"], CHEDDAR_SHA)
    self.assertEqual(c["license"], "MIT")
    self.assertEqual(c["openpilot"], "0.11.2")
    self.assertIs(c["published"], False)
    self.assertNotEqual(c["id"], STOCK_ID)
    self.assertIn("b3ab22efe", c["credit"])
    for f in c["files"]:
      self.assertTrue(source.allowed_source_url(f["url"]), f["url"])
    self.assertTrue(source.allowed_source_url(c["url"]))

  def test_not_offered_or_fetchable_until_published(self):
    self.assertEqual(source.CATALOG, ())
    self.assertEqual(source.catalog_entries(), ())
    self.assertEqual(source.catalog_entries(source.PENDING), ())
    self.assertIn("not published", installer.screen(self.item()))
    for bad in (False, None, "yes", 1):
      self.assertIn("not published", installer.screen(dict(self.item(), published=bad)))

  def test_pinned_qcom_compile(self):
    f = self.item()["files"][0]
    self.assertEqual((f["role"], f["name"]), ("driving_model", "driving_tinygrad.pkl"))
    self.assertEqual(f["sha256"], "050d74e9dd0c17980f6679f5bdad2eb25e951d58fb73f764de65896107e494cd")
    self.assertEqual(f["size"], 82394323)
    self.assertEqual(len(self.item()["files"]), 1)  # stock warps are reused

  def test_screen_passes_only_once_published(self):
    flipped = dict(self.item(), published=True)
    self.assertEqual(installer.screen(flipped), "")
    self.assertEqual([i["id"] for i in source.catalog_entries((flipped,))], ["cheddar"])

  def test_notice_ships_with_the_tree(self):
    p = ROOT / "openpilot/common/bogpilot_models/notices/cheddar_b3ab22efe_MIT.txt"
    text = p.read_text()
    self.assertIn("b3ab22efe1be5d6c0ad46503f0985b26f8b7a36f", text)
    self.assertIn(CHEDDAR_SHA, text)
    self.assertIn("Copyright (c) 2018, Comma.ai, Inc.", text)
    self.assertIn("cheddar_b3ab22efe_MIT.txt", self.item()["release_assets"])

  def test_cheddar_no_longer_listed_as_incompatible(self):
    self.assertFalse(any(name.startswith("comma.ai Cheddar") for name, _ in source.EXCLUDED))


if __name__ == "__main__":
  unittest.main()
