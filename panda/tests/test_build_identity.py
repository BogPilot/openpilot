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

  def test_scons_state_excluded(self):
    before = m.capture(self.root)
    (self.root / 'panda/.sconsign.dblite').write_text('database')
    (self.root / 'panda/compile_commands.json').write_text('commands')
    self.assertEqual(before, m.capture(self.root))

  def test_generated_outputs_excluded(self):
    before = m.capture(self.root)
    p = self.root / 'panda/board/obj/version'
    p.parent.mkdir()
    p.write_text('old build output')
    self.assertEqual(before, m.capture(self.root))

  def test_untracked_os_objects_do_not_change_identity(self):
    """A built clone must hash the same as a clean checkout.

    scons writes panda/tests/libpanda/panda.os; libsafety writes tmp*.os
    under tests/libsafety. Those are gitignored, but inventory walks the
    filesystem and previously counted *.os (it already skipped *.o / *.so).
    """
    before_files = m.inventory(self.root)
    before = m.digest(before_files)
    (self.root / 'panda/tests/libpanda').mkdir(parents=True, exist_ok=True)
    (self.root / 'panda/tests/libpanda/panda.os').write_text('libpanda obj')
    (self.root / 'panda/tests/libpanda/libpanda.so').write_bytes(b'\x00so')
    safety = self.root / 'opendbc_repo/opendbc/safety/tests/libsafety'
    safety.mkdir(parents=True, exist_ok=True)
    (safety / 'tmpTEST123.os').write_text('libsafety obj')
    (self.root / 'panda/coverage.gcda').write_text('gcda')
    (self.root / 'panda/coverage.gcno').write_text('gcno')
    (self.root / 'opendbc_repo/opendbc/safety/foo.d').write_text('dep')
    (self.root / 'opendbc_repo/opendbc/safety/foo.a').write_bytes(b'ar')
    after_files = m.inventory(self.root)
    self.assertEqual(before_files, after_files)
    self.assertEqual(before, m.digest(after_files))
    for name in after_files:
      self.assertFalse(name.endswith(('.os', '.o', '.so', '.d', '.a', '.tmp', '.gcda', '.gcno')), name)

  def test_misra_outputs_do_not_change_identity(self):
    """A tree after panda/safety MISRA must hash the same as a clean checkout.

    panda/tests/misra/test_misra.sh tees cppcheck into .output.log (gitignored
    there). cppcheck also writes *.*.ctu-info and cppcheck-addon-ctu-file-list;
    coverage runs write coverage-out/. Those sit under identity SCOPES, so
    inventory must skip them (the test directories are left out as a whole too).
    """
    before_files = m.inventory(self.root)
    before = m.digest(before_files)
    misra = self.root / 'panda/tests/misra'
    misra.mkdir(parents=True, exist_ok=True)
    (misra / '.output.log').write_text('cppcheck misra log')
    (misra / 'checkers.txt.tmp').write_text('checkers tmp')
    (misra / 'new_table').write_text('generated table')
    (misra / 'cppcheck' / 'bin').mkdir(parents=True)
    (misra / 'cppcheck' / 'bin' / 'cppcheck').write_text('extracted tool')
    (self.root / 'panda' / 'board' / 'main.c.ctu-info').write_text('ctu')
    (self.root / 'panda' / 'cppcheck-addon-ctu-file-list').write_text('ctu list')
    (self.root / 'panda' / 'other.log').write_text('generic log')
    (self.root / 'panda' / 'board' / 'foo.dump').write_text('dump')
    cov = self.root / 'opendbc_repo/opendbc/safety/tests/coverage-out'
    cov.mkdir(parents=True)
    (cov / 'index.html').write_text('coverage')
    (self.root / 'opendbc_repo/opendbc/safety/tests/coverage.info').write_text('lcov')
    (self.root / 'opendbc_repo/opendbc/safety/tests/misra').mkdir(parents=True, exist_ok=True)
    (self.root / 'opendbc_repo/opendbc/safety/tests/misra' / 'safety.ctu-info').write_text('ctu')
    after_files = m.inventory(self.root)
    self.assertEqual(before_files, after_files)
    self.assertEqual(before, m.digest(after_files))
    for name in after_files:
      self.assertFalse(name.endswith(('.log', '.dump', '.ctu-info', '.gcov', '.profraw', '.profdata')), name)
      self.assertNotEqual(Path(name).name, '.output.log')
      self.assertNotIn('coverage-out', Path(name).parts)
      self.assertNotIn('cppcheck', Path(name).parts)


  def test_test_only_edits_do_not_change_identity(self):
    """Test files are not firmware inputs: editing or adding one keeps the identity."""
    for name in ('opendbc_repo/opendbc/safety/tests/test_mode.py', 'panda/tests/libpanda/panda.c',
                 'panda/tests/misra/coverage_table', 'panda/python/test_helpers.py', 'panda/conftest.py'):
      p = self.root / name
      p.parent.mkdir(parents=True, exist_ok=True)
      p.write_text('first\n')
    before = m.inventory(self.root)
    for name in ('opendbc_repo/opendbc/safety/tests/test_mode.py', 'panda/tests/misra/coverage_table'):
      (self.root / name).write_text('edited\n')
    (self.root / 'opendbc_repo/opendbc/safety/tests/test_new.py').write_text('new test\n')
    after = m.inventory(self.root)
    self.assertEqual(before, after)
    for name in after:
      self.assertNotIn('tests', Path(name).parts)
      self.assertFalse(Path(name).name.startswith('test_') and name.endswith('.py'), name)

  def test_source_edit_changes_identity(self):
    before = m.digest(m.inventory(self.root))
    (self.root / 'opendbc_repo/opendbc/safety/safety.h').write_text('changed rule\n')
    self.assertNotEqual(before, m.digest(m.inventory(self.root)))

  def test_is_input_rule(self):
    for name in ('panda/board/main.c', 'opendbc_repo/opendbc/safety/modes/tesla_ap1.h', 'panda/SConscript',
                 'panda/examples/tesla_tester.py', 'panda/scripts/spi_test.py'):
      self.assertTrue(m.is_input(Path(name)), name)
    for name in ('panda/tests/libpanda/panda.c', 'opendbc_repo/opendbc/safety/tests/test_tesla_ap1.py',
                 'panda/board/obj/version', 'panda/python/test_x.py', 'panda/conftest.py'):
      self.assertFalse(m.is_input(Path(name)), name)


if __name__ == '__main__':
  unittest.main()
