"""Synthetic small git repositories only; no account scans/native/device work."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location("rc_provenance",Path(__file__).parents[1]/"rc_provenance_gate.py")
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)


class GateTests(unittest.TestCase):
  def setUp(self):
    self.temp=tempfile.TemporaryDirectory(prefix="synthetic-provenance-")
    self.root=Path(self.temp.name)/"repo";self.root.mkdir()
    self.git("init","-q")
    self.git("config","user.name","Synthetic Fixture")
    self.git("config","user.email","synthetic@example.invalid")
    for name in g.BASE_ASSETS:
      self.write(name,b"synthetic build input\n")
    self.write("vendor/LICENSE.txt",b"Synthetic required notice\n")
    self.write("public.py",b"print('synthetic')\n")
    self.commit()
    self.m=self.manifest()
  def tearDown(self):self.temp.cleanup()
  def git(self,*args):
    return subprocess.check_output(["git","-C",str(self.root),*args],stderr=subprocess.DEVNULL).decode().strip()
  def write(self,name,data):
    p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  def commit(self):self.git("add",".");self.git("commit","-qm","synthetic fixture")
  def manifest(self):
    names=self.git("ls-files").splitlines()
    return dict(schema_version=1,source_commit=self.git("rev-parse","HEAD"),submodules={},
                files={p:g.digest((self.root/p).read_bytes()) for p in names},
                required_build_assets=list(g.BASE_ASSETS),
                license_notices=[p for p in names if Path(p).name.lower().startswith(("license","notice","copying"))])
  def codes(self,result):return {x["code"] for x in result["checks"]}
  def run_gate(self):return g.audit(self.root,self.m)
  def test_clean_pass(self):
    r=self.run_gate();self.assertEqual(r["status"],"pass");self.assertTrue(r['source']['clean'])
    self.assertEqual(r['source']['commit'],self.m['source_commit']);self.assertEqual(r['submodules'],[])
  def test_expected_exact_source(self):
    self.m['source_commit']='0'*40
    self.assertIn('source_commit_mismatch',self.codes(self.run_gate()))
  def test_dirty_and_untracked(self):
    self.write('public.py',b'changed');self.write('extra.txt',b'new')
    codes=self.codes(self.run_gate());self.assertIn('dirty_worktree',codes);self.assertIn('shipping_digest_mismatch',codes)
  def test_missing_required(self):
    self.m['files'].pop('SConstruct')
    self.assertIn('required_file_not_shipped',self.codes(self.run_gate()))
  def test_notice_inventory(self):
    self.m['license_notices']=['LICENSE']
    self.assertIn('license_notice_inventory_incomplete',self.codes(self.run_gate()))
  def test_changed_notice(self):
    self.write('LICENSE',b'replaced');self.m['files']['LICENSE']=g.digest(b'replaced')
    self.assertIn('source_license_notice_changed',self.codes(self.run_gate()))
  def test_missing_file(self):
    (self.root/'public.py').unlink()
    self.assertIn('missing_or_nonregular_shipping_file',self.codes(self.run_gate()))
  def test_bad_manifest(self):
    for manifest in [None,{},dict(self.m,schema_version=True),dict(self.m,files={}),dict(self.m,required_build_assets=[]),dict(self.m,files={'a':'bad'})]:
      self.assertEqual(g.audit(self.root,manifest)['status'],'blocked')
  def test_traversal_paths(self):
    for name in ['../outside','/absolute','a/../b','a//b','a\\b','./x']:
      self.m['files']={name:'0'*64}
      self.assertIn('unsafe_manifest_path',self.codes(self.run_gate()))
  def test_symlink_never_followed(self):
    outside=Path(self.temp.name)/'outside';outside.write_bytes(b'not in scope')
    (self.root/'alias').symlink_to(outside)
    self.m['files']['alias']=g.digest(b'not in scope')
    self.assertIn('missing_or_nonregular_shipping_file',self.codes(self.run_gate()))
    (self.root/'diralias').symlink_to(Path(self.temp.name),target_is_directory=True)
    self.m['files']['diralias/outside']=g.digest(b'not in scope')
    self.assertIn('missing_or_nonregular_shipping_file',self.codes(self.run_gate()))
  def test_private_paths_no_read(self):
    for path in ['.ssh/id_rsa','private/config.json','data/rlog.zst','qlog.bz2','params/CarParams','config.json','x/.env.local']:
      self.m['files'][path]='0'*64
    r=self.run_gate();self.assertIn('private_shipping_path',self.codes(r))
    encoded=json.dumps(r)
    for path in self.m['files']:
      if g.private_name(path):self.assertNotIn(path,encoded)
  def test_credential_marker_redaction(self):
    marker=b'-----BEGIN '+b'OPENSSH PRIVATE KEY-----'
    self.write('public.py',marker+b'\nSYNTHETIC_NEVER_REAL\n')
    self.commit();self.m=self.manifest()
    r=self.run_gate();self.assertIn('credential_content',self.codes(r))
    self.assertNotIn('SYNTHETIC_NEVER_REAL',json.dumps(r));self.assertNotIn('public.py',json.dumps(r))
  def test_token_assignment_redaction(self):
    self.write('public.py',b'AUTH'+b'_TOKEN='+b'SYNTHETIC_VALUE_NOT_A_SECRET')
    self.commit();self.m=self.manifest()
    self.assertIn('credential_content',self.codes(self.run_gate()))
  def test_public_identity_review_digest_bound(self):
    # Deliberately synthetic repeated letters, not a vehicle identifier.
    self.write('public.py',b'VIN'+b'='+b'A'*17)
    self.commit();self.m=self.manifest()
    self.assertIn('unreviewed_identity_content',self.codes(self.run_gate()))
    self.m['reviewed_public_fixtures']={'public.py':self.m['files']['public.py']}
    self.assertEqual(self.run_gate()['status'],'pass')
    self.m['reviewed_public_fixtures']['public.py']='0'*64
    self.assertIn('invalid_public_fixture_review',self.codes(self.run_gate()))
  def test_public_review_cannot_allow_keys(self):
    self.write('public.py',b'-----BEGIN '+b'RSA PRIVATE KEY-----')
    self.commit();self.m=self.manifest();self.m['reviewed_public_fixtures']={'public.py':self.m['files']['public.py']}
    self.assertIn('credential_content',self.codes(self.run_gate()))
  def test_chunk_boundary(self):
    marker=b'-----BEGIN '+b'OPENSSH PRIVATE KEY-----'
    self.write('public.py',b'x'*(65536-10)+marker)
    self.commit();self.m=self.manifest()
    self.assertIn('credential_content',self.codes(self.run_gate()))
  def test_budget_fails_closed(self):
    with mock.patch.object(g,'MAX_FILE',1):
      self.assertIn('scan_budget_exceeded',self.codes(self.run_gate()))
  def test_lfs_unresolved(self):
    name=g.BASE_ASSETS[-1]
    self.write(name,b'version https://git-lfs.github.com/spec/v1\n')
    self.commit();self.m=self.manifest()
    self.assertIn('unresolved_build_asset',self.codes(self.run_gate()))
  def test_submodule_expected_pin_mismatch(self):
    self.m['submodules']={'vendor/module':'0'*40}
    self.assertIn('submodule_pin_manifest_mismatch',self.codes(self.run_gate()))
  def test_real_gitlink_uninitialized(self):
    sha=self.git('rev-parse','HEAD')
    self.git('update-index','--add','--cacheinfo','160000,'+sha+',module')
    self.git('commit','-qm','synthetic gitlink')
    self.m['source_commit']=self.git('rev-parse','HEAD');self.m['submodules']={'module':sha}
    self.assertIn('submodule_unavailable',self.codes(self.run_gate()))
  def test_vendored_tree_pin(self):
    self.write('vendor_repo/file.py',b'synthetic vendor');self.commit();self.m=self.manifest()
    self.assertEqual(len(self.run_gate()['vendored_trees']),1)
  def test_source_not_root(self):
    self.assertEqual(g.audit(self.root/'vendor',self.m)['status'],'blocked')
  def test_missing_repo(self):
    self.assertEqual(g.audit(Path(self.temp.name)/'absent',self.m)['status'],'blocked')
  def test_cli_pass_and_block(self):
    manifest=Path(self.temp.name)/'manifest.json';manifest.write_text(json.dumps(self.m))
    output=Path(self.temp.name)/'result.json'
    args=['--repo',str(self.root),'--manifest',str(manifest),'--output',str(output)]
    self.assertEqual(g.main(args),0);self.assertEqual(json.loads(output.read_text())['status'],'pass')
    with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(g.main(args),2)
  def test_output_inside_repo_rejected(self):
    manifest=Path(self.temp.name)/'manifest.json';manifest.write_text(json.dumps(self.m))
    with contextlib.redirect_stdout(io.StringIO()):
      self.assertEqual(g.main(['--repo',str(self.root),'--manifest',str(manifest),'--output',str(self.root/'result.json')]),2)
    self.assertFalse((self.root/'result.json').exists())
  def test_duplicate_json_rejected(self):
    manifest=Path(self.temp.name)/'manifest.json';manifest.write_text('{"schema_version":1,"schema_version":1}')
    stream=io.StringIO()
    with contextlib.redirect_stdout(stream):self.assertEqual(g.main(['--repo',str(self.root),'--manifest',str(manifest)]),2)
    self.assertEqual(json.loads(stream.getvalue())['checks'][0]['code'],'manifest_unreadable')
  def test_ignored_files_not_account_scanned(self):
    self.write('.gitignore',b'.local/\n');self.commit();self.m=self.manifest()
    self.write('.local/ignored',b'-----BEGIN '+b'RSA PRIVATE KEY-----')
    self.assertEqual(self.run_gate()['status'],'pass') # explicitly outside shipping manifest
    self.m['files']['.local/ignored']=g.digest((self.root/'.local/ignored').read_bytes())
    self.assertIn('credential_content',self.codes(self.run_gate()))

  def test_staged_shipping_separate_source(self):
    import shutil
    stage=Path(self.temp.name)/'stage';stage.mkdir()
    for name in self.m['files']:
      dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.root/name,dest)
    self.assertEqual(g.audit(self.root,self.m,stage)['status'],'pass')
    (stage/'public.py').write_bytes(b'-----BEGIN '+b'RSA PRIVATE KEY-----')
    self.m['files']['public.py']=g.digest((stage/'public.py').read_bytes())
    result=g.audit(self.root,self.m,stage)
    self.assertTrue(result['source']['clean'])
    self.assertIn('credential_content',self.codes(result))
  def test_empty_build_asset(self):
    name=g.BASE_ASSETS[-1];self.write(name,b'');self.commit();self.m=self.manifest()
    self.assertIn('empty_build_asset',self.codes(self.run_gate()))
  def test_initialized_submodule_pin(self):
    module=self.root/'module';module.mkdir()
    def subgit(*args):
      return subprocess.check_output(['git','-C',str(module),*args],stderr=subprocess.DEVNULL).decode().strip()
    subgit('init','-q');subgit('config','user.name','Synthetic Fixture');subgit('config','user.email','synthetic@example.invalid')
    (module/'file').write_bytes(b'synthetic nested source')
    subgit('add','.');subgit('commit','-qm','synthetic module')
    pin=subgit('rev-parse','HEAD')
    self.git('update-index','--add','--cacheinfo','160000,'+pin+',module');self.git('commit','-qm','synthetic gitlink')
    self.m['source_commit']=self.git('rev-parse','HEAD');self.m['submodules']={'module':pin}
    result=self.run_gate();self.assertEqual(result['status'],'pass',result)
    (module/'file').write_bytes(b'changed')
    self.assertIn('submodule_dirty',self.codes(self.run_gate()))

if __name__=='__main__':unittest.main()
