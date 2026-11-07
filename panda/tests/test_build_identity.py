import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('identity', Path(__file__).resolve().parents[1] / 'build_identity.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class IdentityTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name) / 'source'
    self.root.mkdir()
    for name in ('panda/board/main.c', 'opendbc_repo/opendbc/safety/safety.h', *m.EXTRA):
      p = self.root / name
      p.parent.mkdir(parents=True, exist_ok=True)
      p.write_text('test source\n')
    self.run_git('init', '-q')
    self.run_git('add', '.')
    self.run_git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'source')

  def run_git(self, *args):
    return subprocess.check_output(['git', '-C', str(self.root), *args])

  def export(self):
    data = m.capture(self.root)
    (self.root / m.MANIFEST).write_text(json.dumps(data))
    return data

  def archive(self):
    dest = Path(self.tmp.name) / 'archive'
    shutil.copytree(self.root, dest, ignore=shutil.ignore_patterns('.git'))
    return dest

  def test_checkout_clean_full_commit(self):
    data = m.identity(self.root)
    version = m.firmware_version(self.root, 'DEV', 'DEBUG')
    self.assertIn(data['source_commit'], version)
    self.assertFalse(data['dirty'])
    self.assertLessEqual(len(version), 64)
    self.assertTrue(version.endswith('-DEBUG'))

  def test_archive_missing_manifest(self):
    with self.assertRaisesRegex(ValueError, 'requires verified'):
      m.identity(self.archive())

  def test_correct_archive_reproducible(self):
    self.export()
    archive = self.archive()
    self.assertEqual(m.identity(self.root), m.identity(archive))
    self.assertEqual(m.firmware_version(self.root, 'DEV', 'DEBUG'), m.firmware_version(archive, 'DEV', 'DEBUG'))
    self.assertEqual(m.firmware_version(archive, 'DEV', 'DEBUG'), m.firmware_version(archive, 'DEV', 'DEBUG'))

  def test_archive_mismatch(self):
    self.export()
    archive = self.archive()
    (archive / 'panda/board/main.c').write_text('changed')
    with self.assertRaisesRegex(ValueError, 'content'):
      m.identity(archive)

  def test_archive_extra_source(self):
    self.export()
    archive = self.archive()
    (archive / 'panda/board/extra.h').write_text('extra')
    with self.assertRaises(ValueError):
      m.identity(archive)

  def test_dirty_source_preserved(self):
    (self.root / 'panda/board/main.c').write_text('dirty')
    data = self.export()
    self.assertTrue(data['dirty'])
    self.assertIn('-d-', m.firmware_version(self.archive(), 'DEV', 'DEBUG'))

  def test_untracked_source_dirty(self):
    (self.root / 'panda/new.h').write_text('new')
    self.assertTrue(m.capture(self.root)['dirty'])

  def test_stale_checkout_manifest(self):
    self.export()
    (self.root / 'panda/board/main.c').write_text('changed')
    with self.assertRaisesRegex(ValueError, 'stale'):
      m.identity(self.root)

  def test_invalid_claim_rejected(self):
    self.export()
    archive = self.archive()
    data = json.loads((archive / m.MANIFEST).read_text())
    data['source_commit'] = 'unknown'
    (archive / m.MANIFEST).write_text(json.dumps(data))
    with self.assertRaises(ValueError):
      m.identity(archive)

  def test_generated_outputs_excluded(self):
    before = m.capture(self.root)
    p = self.root / 'panda/board/obj/version'
    p.parent.mkdir()
    p.write_text('old build output')
    self.assertEqual(before, m.capture(self.root))


if __name__ == '__main__':
  unittest.main()
