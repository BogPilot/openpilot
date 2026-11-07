"""Synthetic verifier fixtures, never runtime/inference/model validation."""
import unittest,tempfile,json,pickle,hashlib,importlib.util
from pathlib import Path
from unittest.mock import patch
SPEC=importlib.util.spec_from_file_location('stock_models',Path(__file__).parents[1]/'rc_stock_models.py');M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)
class StockModels(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
  for d in ['tinygrad_repo','openpilot/selfdrive/modeld/models','openpilot/common/transformations','openpilot/system/camerad/cameras','tools/bogpilot']:(self.r/d).mkdir(parents=True,exist_ok=True)
  for name in ['tinygrad_repo/compiler.py','pyproject.toml','uv.lock']:(self.r/name).write_text('synthetic input\n')
  self.base=b"# synthetic default model builder\n";self.builder=self.r/'openpilot/selfdrive/modeld/SConscript';self.builder.write_bytes(self.base+M.BEGIN+b'# synthetic opt-in guard\n'+M.END)
  (self.r/'.panda-source.json').write_text(json.dumps(dict(source_commit='1'*40,dirty=False)))
  self.m=dict(stock_commit=M.STOCK,backend='QCOM',inputs={},assets={},default_builder_sha256=hashlib.sha256(self.base).hexdigest())
  for name in M.inputs(self.r):self.m['inputs'][name]=dict(sha256=M.digest(self.r/name),stock_git_blob='0'*40)
  for name in M.NAMES:
   rel='openpilot/selfdrive/modeld/models/'+name;(self.r/rel).write_bytes(pickle.dumps(dict(device='QCOM',synthetic=True)));self.m['assets'][rel]=dict(sha256=M.digest(self.r/rel),stock_git_blob='0'*40)
 def run_verify(self,arch='comma_arm64'):
  raw=json.dumps(self.m,sort_keys=True).encode();(self.r/'tools/bogpilot/c3x_stock_models_f7db927.json').write_bytes(raw)
  with patch.object(M,'MANIFEST_SHA256',hashlib.sha256(raw).hexdigest()):return M.verify(self.r,arch)
 def test_valid_synthetic_fixture(self):self.assertEqual(self.run_verify()['model_origin'],'PRECOMPILED-STOCK; NOT freshly generated')
 def test_asset_drift(self):
  (self.r/next(iter(self.m['assets']))).write_bytes(b'changed')
  with self.assertRaises(ValueError):self.run_verify()
 def test_missing_asset(self):
  (self.r/next(iter(self.m['assets']))).unlink()
  with self.assertRaises(OSError):self.run_verify()
 def test_compiler_drift(self):
  (self.r/'tinygrad_repo/compiler.py').write_text('changed')
  with self.assertRaises(ValueError):self.run_verify()
 def test_extra_compiler_file(self):
  (self.r/'tinygrad_repo/extra.py').write_text('unknown')
  with self.assertRaises(ValueError):self.run_verify()
 def test_wrong_backend_even_if_fixture_digest_matches(self):
  rel=next(iter(self.m['assets']));(self.r/rel).write_bytes(pickle.dumps(dict(device='METAL')));self.m['assets'][rel]['sha256']=M.digest(self.r/rel)
  with self.assertRaises(ValueError):self.run_verify()
 def test_default_builder_drift(self):
  self.builder.write_bytes(self.builder.read_bytes()+b'# changed default\n')
  with self.assertRaises(ValueError):self.run_verify()
 def test_wrong_arch(self):
  with self.assertRaises(ValueError):self.run_verify('aarch64')
 def test_incomplete_set(self):
  self.m['assets'].pop(next(iter(self.m['assets'])))
  with self.assertRaises(ValueError):self.run_verify()
 def test_wrong_stock(self):
  self.m['stock_commit']='2'*40
  with self.assertRaises(ValueError):self.run_verify()
 def test_untrusted_manifest(self):
  (self.r/'tools/bogpilot/c3x_stock_models_f7db927.json').write_text('{}')
  with self.assertRaises(ValueError):M.verify(self.r)
 def test_missing_candidate_identity(self):
  (self.r/'.panda-source.json').unlink()
  with self.assertRaises(ValueError):self.run_verify()
 def test_dirty_candidate(self):
  (self.r/'.panda-source.json').write_text(json.dumps(dict(source_commit='1'*40,dirty=True)))
  with self.assertRaises(ValueError):self.run_verify()
if __name__=='__main__':unittest.main()
