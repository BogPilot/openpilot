"""Synthetic fixtures only: no native build, actual panda key, or device access."""
import base64
import contextlib
import io
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('gate', Path(__file__).resolve().parents[1] / 'rc_firmware_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def synthetic_rsa():
  rng = random.Random(753)
  def prime():
    while True:
      n = rng.getrandbits(512) | (1 << 511) | 1
      d, s = n - 1, 0
      while d % 2 == 0:
        d //= 2
        s += 1
      for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        x = pow(a, d, n)
        if x in (1, n - 1):
          continue
        for _ in range(s - 1):
          x = pow(x, 2, n)
          if x == n - 1:
            break
        else:
          break
      else:
        return n
  while True:
    p, q = prime(), prime()
    if p != q and (p * q).bit_length() == 1024:
      return 65537, p * q, pow(65537, -1, (p - 1) * (q - 1))


class GateTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.e, cls.n, cls.d = synthetic_rsa()

  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.base = Path(self.temp.name)
    self.source = self.base / 'source'
    self.source.mkdir()
    for name in ('SConstruct', 'common/version.h', 'panda/SConscript', 'panda/board/main.c',
                 'opendbc_repo/opendbc/safety/safety.h'):
      p = self.source / name
      p.parent.mkdir(parents=True, exist_ok=True)
      p.write_text('synthetic fixture\n')
    fields = [b'ssh-rsa'] + [x.to_bytes((x.bit_length() + 7) // 8, 'big') for x in (self.e, self.n)]
    wire = b''.join(struct.pack('>I', len(x)) + x for x in fields)
    key = self.source / 'panda/board/crypto/certs/debug.pub'
    key.parent.mkdir(parents=True)
    key.write_bytes(b'ssh-rsa ' + base64.b64encode(wire))
    self.git('init', '-q')
    self.git('add', '.')
    self.git('-c', 'user.name=Synthetic', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'synthetic source')
    self.candidate = self.git('rev-parse', 'HEAD').strip()
    self.policy_patch = patch.object(gate, 'POLICY_BASE', self.candidate)
    self.policy_patch.start()
    self.addCleanup(self.policy_patch.stop)
    files = gate.inventory(self.source)
    self.manifest = dict(schema=1, source_commit=self.candidate, dirty=False, files=files,
                         source_sha256=gate.sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()),
                         version='synthetic fixture')
    (self.source / gate.SOURCE_MANIFEST).write_text(json.dumps(self.manifest))
    self.version = gate.source_identity(self.source, self.manifest, self.candidate)
    self.archive = self.base / 'archive'
    shutil.copytree(self.source, self.archive, ignore=shutil.ignore_patterns('.git'))
    self.first, self.second = self.base / 'first', self.base / 'second'
    for build in (self.first, self.second):
      self.make_build(build)

  def git(self, *args):
    return subprocess.check_output(['git', '-C', str(self.source), *args], stderr=subprocess.DEVNULL).decode()

  def signed(self, suffix):
    payload = b'\0' * 4 + b'synthetic ' + suffix + self.version.encode() + b'\0' + b'VERS' + struct.pack('<I', 2)
    digest = hashlib.sha1(payload[4:]).digest()
    padded = b'\x00\x01' + b'\xff' * 105 + b'\x00' + digest
    sig = pow(int.from_bytes(padded, 'big'), self.d, self.n).to_bytes(128, 'big')
    return struct.pack('<I', len(payload)) + payload[4:] + sig

  def make_build(self, build):
    for i, name in enumerate(gate.OUTPUTS):
      p = build / name
      p.parent.mkdir(parents=True, exist_ok=True)
      p.write_bytes(self.signed(str(i).encode()) if i < 2 else b'\x7fELFsynthetic ' + self.version.encode() + b'\0')
    (build / 'panda/board/obj/version').write_text(self.version)
    commands = [dict(file='board/main.c', arguments=['arm-none-eabi-gcc', '-DALLOW_DEBUG', '-DSTM32H7', '-DSTM32H725xx']),
                dict(file='board/body/main.c', arguments=['arm-none-eabi-gcc', '-DALLOW_DEBUG', '-DSTM32H7', '-DSTM32H725xx', '-DPANDA_BODY'])]
    (build / 'panda/compile_commands.json').write_text(json.dumps(commands))
    self.record(build)

  def record(self, build):
    record = dict(source_commit=self.candidate, source_sha256=self.manifest['source_sha256'], version=self.version,
                  sha256={name: gate.sha((build / name).read_bytes()) for name in gate.OUTPUTS})
    (build / gate.ARTIFACT_MANIFEST).write_text(json.dumps(record))

  def verify(self):
    return gate.verify(self.source, self.archive, self.first, self.second, self.candidate)

  def test_complete_synthetic_evidence(self):
    self.assertEqual(self.verify()['status'], 'pass')

  def test_wrong_candidate(self):
    with self.assertRaisesRegex(ValueError, 'HEAD'):
      gate.verify(self.source, self.archive, self.first, self.second, 'f' * 40)

  def test_abbreviated_candidate(self):
    with self.assertRaises(ValueError):
      gate.source_identity(self.archive, self.manifest, self.candidate[:9])

  def test_dirty_checkout(self):
    (self.source / 'untracked.txt').write_text('change')
    with self.assertRaisesRegex(ValueError, 'dirty'):
      self.verify()

  def test_dirty_claim(self):
    manifest = dict(self.manifest, dirty=True)
    with self.assertRaisesRegex(ValueError, 'cleanliness'):
      gate.source_identity(self.archive, manifest, self.candidate)

  def test_missing_manifest(self):
    (self.archive / gate.SOURCE_MANIFEST).unlink()
    with self.assertRaises(FileNotFoundError):
      self.verify()

  def test_archive_changed(self):
    (self.archive / 'panda/board/main.c').write_text('changed')
    with self.assertRaisesRegex(ValueError, 'inventory'):
      self.verify()

  def test_archive_added_source(self):
    (self.archive / 'panda/board/new.h').write_text('extra')
    with self.assertRaises(ValueError):
      self.verify()

  def test_generated_archive_outputs_excluded(self):
    obj = self.archive / 'panda/board/obj'
    obj.mkdir()
    (obj / 'version').write_text('old generated output')
    (self.archive / 'panda/.sconsign.dblite').write_text('database')
    (self.archive / 'panda/compile_commands.json').write_text('generated')
    self.assertEqual(self.verify()['status'], 'pass')

  def test_fingerprint_tamper(self):
    with self.assertRaisesRegex(ValueError, 'fingerprint'):
      gate.source_identity(self.archive, dict(self.manifest, source_sha256='0' * 64), self.candidate)

  def test_artifact_manifest_tamper(self):
    p = self.first / gate.ARTIFACT_MANIFEST
    record = json.loads(p.read_text())
    record['source_commit'] = '0' * 40
    p.write_text(json.dumps(record))
    with self.assertRaisesRegex(ValueError, 'artifact source'):
      self.verify()

  def test_artifact_bytes_do_not_match_hash_manifest(self):
    p = self.first / gate.OUTPUTS[0]
    p.write_bytes(p.read_bytes() + b'changed')
    with self.assertRaisesRegex(ValueError, 'SHA256'):
      self.verify()

  def test_archive_manifest_mismatch(self):
    p = self.archive / gate.SOURCE_MANIFEST
    data = json.loads(p.read_text())
    data['source_commit'] = 'f' * 40
    p.write_text(json.dumps(data))
    with self.assertRaisesRegex(ValueError, 'archive/source manifest'):
      self.verify()

  def test_source_generated_inventory_excluded(self):
    obj = self.source / 'panda/board/obj'
    obj.mkdir()
    (obj / 'version').write_text('generated output')
    (self.source / 'panda/.sconsign.dblite').write_text('generated database')
    (self.source / 'panda/compile_commands.json').write_text('generated commands')
    self.assertEqual(self.verify()['status'], 'pass')

  def test_missing_body(self):
    (self.first / gate.OUTPUTS[1]).unlink()
    with self.assertRaises(FileNotFoundError):
      self.verify()

  def test_bad_signature(self):
    p = self.first / gate.OUTPUTS[0]
    data = p.read_bytes()
    p.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    self.record(self.first)
    with self.assertRaisesRegex(ValueError, 'signature'):
      self.verify()

  def test_stale_embedded_identity(self):
    p = self.first / gate.OUTPUTS[1]
    p.write_bytes(p.read_bytes().replace(self.candidate.encode(), b'f' * 40))
    self.record(self.first)
    with self.assertRaisesRegex(ValueError, 'embedded'):
      self.verify()

  def test_release_compile_flags(self):
    p = self.first / 'panda/compile_commands.json'
    p.write_text(p.read_text().replace('-DALLOW_DEBUG', '-DRELEASE'))
    with self.assertRaisesRegex(ValueError, 'ALLOW_DEBUG'):
      self.verify()

  def test_repeat_changed(self):
    p = self.second / gate.OUTPUTS[2]
    p.write_bytes(p.read_bytes() + b'different')
    self.record(self.second)
    with self.assertRaisesRegex(ValueError, 'repeat builds differ'):
      self.verify()

  def test_missing_repeat_not_skipped(self):
    shutil.rmtree(self.second)
    with self.assertRaises(FileNotFoundError):
      self.verify()

  def test_same_repeat_directory_rejected(self):
    with self.assertRaisesRegex(ValueError, 'separate'):
      gate.verify(self.source, self.archive, self.first, self.first, self.candidate)

  def test_policy_changed_in_new_commit(self):
    (self.source / 'panda/SConscript').write_text('changed signing policy')
    self.git('add', 'panda/SConscript')
    self.git('-c', 'user.name=Synthetic', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'change')
    with self.assertRaisesRegex(ValueError, 'policy changed'):
      gate.checkout_policy(self.source, self.git('rev-parse', 'HEAD').strip())

  def test_missing_evidence_cli_fails(self):
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
      code = gate.main(['--source', str(self.source), '--archive', str(self.archive), '--artifacts', str(self.first),
                        '--repeat', str(self.second / 'missing'), '--candidate', self.candidate])
    self.assertEqual(json.loads(stderr.getvalue())['status'], 'fail')
    self.assertEqual(code, 1)


if __name__ == '__main__':
  unittest.main()
