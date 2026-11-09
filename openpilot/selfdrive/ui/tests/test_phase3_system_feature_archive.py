import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

BASE = Path(__file__).parents[1]
def load(name, path):
  spec = importlib.util.spec_from_file_location(name, BASE/path)
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module
  spec.loader.exec_module(module)
  return module
b = load('openpilot.selfdrive.ui.bogpilot.phase3_system_settings_backend', 'bogpilot/phase3_system_settings_backend.py')
load('openpilot.selfdrive.ui.bogpilot.phase3_system_settings_feature_specs', 'bogpilot/phase3_system_settings_feature_specs.py')
f = load('openpilot.selfdrive.ui.bogpilot.phase3_system_settings_features', 'bogpilot/phase3_system_settings_features.py')

class Store:
  def __init__(self):
    self.values={'Fahrenheit':'1', 'ScreenTimeout':'30', 'NoLogging':'0', 'SshEnabled':'1', 'CarParams':'fixture-protected', 'CalibrationParams':'fixture-calibration'}
    self.writes=[]
  def raw(self,key): return self.values.get(key)
  def get(self,key,default=''): return self.values.get(key,default)
  def put(self,key,value): self.values[key]=str(value); self.writes.append(key)
  def put_bool(self,key,value): self.put(key,'1' if value else '0')
  def remove(self,key): self.values.pop(key,None); self.writes.append(key)

class FeatureArchiveTests(unittest.TestCase):
  def setUp(self):
    self.tmp=tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root=Path(self.tmp.name).resolve()/'backups'
    self.store=Store()
    self.prefs=b.SystemPreferences(self.store,lambda:True,lambda:True)
    self.compat={'source_sha256':'fixture-exact-source', 'platform':'fixture-device', 'vehicle_family':'fixture-model'}
    self.specs={k:f.FEATURE_SPECS[k] for k in ('Fahrenheit','ScreenTimeout','NoLogging')}
    self.archive=f.FeatureArchive(self.prefs, lambda:dict(self.compat), self.root,
                                  specs=self.specs, defaults=lambda:{'Fahrenheit':'0','ScreenTimeout':'30','NoLogging':'0'})

  def test_full_frozen_scope_not_generic_secret_dump(self):
    self.assertEqual(len(f.FEATURE_SPECS),256)
    self.assertFalse(set(f.FEATURE_SPECS)&set(f.PROTECTED_EXCLUSIONS))
    for key in ('SshEnabled','CarParams','CalibrationParams','SecOCKey','DongleId','ForceFingerprint','AlwaysOnDM','RemoteUIStream'):
      self.assertNotIn(key,f.FEATURE_SPECS)
    name=self.archive.backup()
    doc=json.loads((self.root/name).read_text())
    self.assertEqual(set(doc['values']),set(self.specs))
    self.assertNotIn('fixture-protected',(self.root/name).read_text())
    self.assertEqual(self.store.writes,[])

  def test_preview_is_readonly_then_durable_restore(self):
    name=self.archive.backup()
    self.store.values['Fahrenheit']='0'
    plan=self.archive.preview(name)
    self.assertEqual(self.store.writes,[])
    self.assertEqual(plan['changes']['Fahrenheit'],{'from':'0','to':'1'})
    receipt=self.archive.apply_preview(plan)
    self.assertTrue((self.root/receipt).is_file())
    self.assertEqual(self.store.raw('Fahrenheit'),'1')
    self.assertEqual(self.store.raw('SshEnabled'),'1')
    self.assertEqual(self.store.raw('CalibrationParams'),'fixture-calibration')

  def test_exact_build_platform_vehicle_mismatch_refused(self):
    name=self.archive.backup()
    self.compat['source_sha256']='other-build'
    with self.assertRaises(ValueError): self.archive.preview(name)
    self.assertEqual(self.store.writes,[])

  def test_unknown_vehicle_never_guesses_ap1(self):
    self.compat['vehicle_family']='unidentified'
    name=self.archive.backup()
    with self.assertRaises(ValueError): self.archive.preview(name)
    with self.assertRaises(ValueError): self.archive.preview(reset=True)
    self.assertEqual(self.store.writes,[])

  def test_stale_or_tampered_preview_cannot_apply(self):
    plan=self.archive.preview(reset=True)
    self.store.values['Fahrenheit']='0'
    with self.assertRaises(ValueError): self.archive.apply_preview(plan)
    self.assertEqual(self.store.writes,[])
    plan=self.archive.preview(reset=True)
    plan['reason']='unconfirmed modified plan'
    with self.assertRaises(ValueError): self.archive.apply_preview(plan)

  def test_invalid_type_bounds_nan_and_scope(self):
    for key,value in [('ScreenTimeout','100'),('ScreenTimeout','31'),('ScreenTimeout','nan'),('Fahrenheit','true'),('SshEnabled','0')]:
      with self.assertRaises(ValueError): f.validate_value(key,value)

  def test_restore_requires_preview_not_old_direct_method(self):
    name=self.archive.backup()
    with self.assertRaises(PermissionError): self.archive.restore(name)

  def test_failed_write_rolls_back_with_durable_original(self):
    self.store.values['ScreenTimeout']='60'
    plan=self.archive.preview(reset=True)
    original=dict(self.store.values)
    normal=self.store.put
    failed=[]
    def fail_once(key,value):
      if key=='ScreenTimeout' and not failed:
        failed.append(True); raise OSError('fixture failure')
      normal(key,value)
    self.store.put=fail_once
    with self.assertRaises(RuntimeError): self.archive.apply_preview(plan)
    self.assertEqual(self.store.values,original)
    self.assertTrue(self.archive.list())

  def test_default_preview_exact_named_baseline_no_automatic_changes(self):
    plan=self.archive.preview(reset=True)
    self.assertIn('Current BogPilot fresh defaults',plan['reason'])
    self.assertEqual(self.store.writes,[])
    self.archive.apply_preview(plan)
    self.assertEqual(self.store.raw('Fahrenheit'),'0')

  def test_logging_restore_never_restores_disable_consent(self):
    self.store.values['NoLogging']='1'
    name=self.archive.backup()
    self.store.values['NoLogging']='0'
    self.store.values['LocalLoggingDisableConsent']='1'
    plan=self.archive.preview(name)
    self.archive.apply_preview(plan)
    self.assertEqual(self.store.raw('NoLogging'),'1')
    self.assertEqual(self.store.raw('LocalLoggingDisableConsent'),'0')

  def test_unrelated_archives_survive_delete_all(self):
    self.archive.backup()
    legacy=self.root/'old-system-backup.json'
    legacy.write_text('{}')
    self.archive.delete()
    self.assertTrue(legacy.exists())

if __name__=='__main__': unittest.main()
