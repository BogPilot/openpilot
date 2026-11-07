#!/usr/bin/env python3
"""Read-only, fail-closed local candidate firmware evidence gate (not certification)."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys

POLICY_BASE = 'f5928f3b168159129bc88b8f65c9f53b3f73039d'
SOURCE_MANIFEST = '.panda-source.json'
ARTIFACT_MANIFEST = 'rc-firmware-artifacts.json'
OUTPUTS = ('panda/board/obj/panda_h7.bin.signed', 'panda/board/obj/body_h7.bin.signed',
           'panda/board/obj/panda_h7/main.elf', 'panda/board/obj/body_h7/main.elf')


def require(condition, message):
  if not condition:
    raise ValueError(message)


def sha(data):
  return hashlib.sha256(data).hexdigest()


def read_json(path):
  return json.loads(path.read_text())


def run_git(root, *args):
  return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


def inventory(root):
  """Independent implementation of the documented firmware source inventory."""
  names = {'SConstruct', 'common/version.h'}
  for directory in ('panda', 'opendbc_repo/opendbc/safety'):
    require((root / directory).is_dir(), f'missing source scope: {directory}')
    for path in (root / directory).rglob('*'):
      name = path.relative_to(root)
      if set(name.parts) & {'.git', '__pycache__', '.pytest_cache', 'obj'}:
        continue
      if path.name in {'.sconsign.dblite', 'compile_commands.json'} or path.suffix in {'.pyc', '.o', '.so'}:
        continue
      if path.is_file():
        names.add(name.as_posix())
  return {name: sha((root / name).read_bytes()) for name in sorted(names)}


def source_identity(root, manifest, candidate):
  require(re.fullmatch('[0-9a-f]{40}', candidate) is not None, 'candidate must be full source SHA')
  require(manifest.get('schema') == 1, 'source manifest schema')
  require(manifest.get('source_commit') == candidate, 'source manifest candidate mismatch')
  require(manifest.get('dirty') is False, 'dirty or missing source cleanliness')
  files = inventory(root)
  fingerprint = sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())
  require(manifest.get('files') == files, 'source inventory mismatch')
  require(manifest.get('source_sha256') == fingerprint, 'source fingerprint mismatch')
  require(manifest.get('version') == (root / 'common/version.h').read_text().strip(), 'source version mismatch')
  return f'DEV-{candidate}-c-{fingerprint[:8]}-DEBUG'


def checkout_policy(root, candidate):
  require(Path(run_git(root, 'rev-parse', '--show-toplevel')).resolve() == root.resolve(), 'not actual source checkout')
  require(run_git(root, 'rev-parse', 'HEAD') == candidate, 'checkout HEAD is not candidate source commit')
  status = run_git(root, 'status', '--porcelain', '--untracked-files=all', '--', '.',
                   ':!' + SOURCE_MANIFEST, ':!panda/board/obj', ':!panda/.sconsign.dblite', ':!panda/compile_commands.json')
  require(not status, 'source checkout dirty (excluding documented generated outputs only)')
  # Never print key material or safety diffs. Baseline is policy, NOT output provenance.
  result = subprocess.run(['git', '-C', str(root), 'diff', '--quiet', POLICY_BASE, '--',
                           'panda/SConscript', 'panda/board', 'opendbc_repo/opendbc/safety', ':!panda/board/obj'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  require(result.returncode == 0, 'firmware safety/signing/build policy changed or baseline unavailable')


def debug_public_key(path):
  pieces = path.read_bytes().split()
  require(len(pieces) >= 2 and pieces[0] == b'ssh-rsa', 'expected public RSA debug key')
  raw = base64.b64decode(pieces[1], validate=True)
  fields = []
  while raw:
    require(len(raw) >= 4, 'truncated public key')
    size = int.from_bytes(raw[:4], 'big')
    require(len(raw) >= 4 + size, 'truncated public key field')
    fields.append(raw[4:4 + size])
    raw = raw[4 + size:]
  require(len(fields) == 3 and fields[0] == b'ssh-rsa', 'malformed RSA public key')
  e, n = (int.from_bytes(x, 'big') for x in fields[1:])
  require(n.bit_length() == 1024 and e > 1, 'unexpected debug public key shape')
  return e, n


def verify_signed(data, version, key):
  require(len(data) > 140, 'signed firmware too short')
  payload_size = len(data) - 128
  require(struct.unpack('<I', data[:4])[0] == payload_size, 'signed firmware length mismatch')
  require(data[payload_size - 8:payload_size] == b'VERS' + struct.pack('<I', 2), 'signed firmware format/version mismatch')
  versions = re.findall(rb'DEV-[A-Za-z0-9.-]+', data[:payload_size])
  require(versions == [version.encode()], 'embedded firmware source identity missing, stale or ambiguous')
  e, n = key
  signature = int.from_bytes(data[payload_size:], 'big')
  require(signature < n, 'signature out of range')
  expected = b'\x00\x01' + b'\xff' * 0x69 + b'\x00' + hashlib.sha1(data[4:payload_size]).digest()
  require(pow(signature, e, n).to_bytes(128, 'big') == expected, 'debug signature verification failed')


def compile_policy(build):
  entries = read_json(build / 'panda/compile_commands.json')
  require(isinstance(entries, list) and entries, 'missing compilation evidence')
  for suffix, body in (('board/main.c', False), ('board/body/main.c', True)):
    matches = [x for x in entries if x.get('file', '').replace('\\', '/').endswith(suffix)]
    require(matches, f'missing compile command for {suffix}')
    for entry in matches:
      tokens = entry.get('arguments') or shlex.split(entry.get('command', ''))
      require(isinstance(tokens, list) and all(isinstance(x, str) for x in tokens), 'invalid compile command')
      require('-DALLOW_DEBUG' in tokens and '-DSTM32H7' in tokens and '-DSTM32H725xx' in tokens,
              'DEBUG/ALLOW_DEBUG or H7 compile evidence missing')
      require(not any(x.startswith(('-UALLOW_DEBUG', '-DALLOW_DEBUG=')) for x in tokens), 'conflicting DEBUG flags')
      require(('-DPANDA_BODY' in tokens) == body, 'body build selection mismatch')


def artifact_evidence(build, source_manifest, version, key):
  record = read_json(build / ARTIFACT_MANIFEST)
  require(record.get('source_commit') == source_manifest['source_commit'], 'artifact source commit mismatch')
  require(record.get('source_sha256') == source_manifest['source_sha256'], 'artifact source fingerprint mismatch')
  require(record.get('version') == version, 'artifact version mismatch')
  hashes = {name: sha((build / name).read_bytes()) for name in OUTPUTS}
  require(record.get('sha256') == hashes, 'artifact SHA256 manifest mismatch')
  require((build / 'panda/board/obj/version').read_text() == version, 'generated version file mismatch')
  compile_policy(build)
  for name in OUTPUTS[:2]:
    verify_signed((build / name).read_bytes(), version, key)
  for name in OUTPUTS[2:]:
    data = (build / name).read_bytes()
    require(data.startswith(b'\x7fELF') and version.encode() + b'\x00' in data, 'ELF source identity missing')
  return hashes


def verify(source, archive, artifacts, repeat, candidate):
  source, archive, artifacts, repeat = (Path(x).resolve() for x in (source, archive, artifacts, repeat))
  require(artifacts != repeat, 'repeat build must be separate preserved evidence directory')
  checkout_policy(source, candidate)
  manifest = read_json(source / SOURCE_MANIFEST)
  version = source_identity(source, manifest, candidate)
  require(read_json(archive / SOURCE_MANIFEST) == manifest, 'archive/source manifest mismatch')
  require(source_identity(archive, manifest, candidate) == version, 'archive identity mismatch')
  key = debug_public_key(source / 'panda/board/crypto/certs/debug.pub')
  first = artifact_evidence(artifacts, manifest, version, key)
  second = artifact_evidence(repeat, manifest, version, key)
  require(first == second, 'native firmware repeat builds differ')
  return dict(status='PASS', source_commit=candidate, source_sha256=manifest['source_sha256'],
              version=version, sha256=first, scope='local evidence only; no hardware or safety certification')


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  for name in ('source', 'archive', 'artifacts', 'repeat'):
    parser.add_argument('--' + name, type=Path, required=True)
  parser.add_argument('--candidate', required=True)
  args = parser.parse_args(argv)
  try:
    result = verify(args.source, args.archive, args.artifacts, args.repeat, args.candidate)
  except (ValueError, OSError, subprocess.SubprocessError, TypeError, KeyError) as exc:
    print(json.dumps(dict(status='FAIL', reason=str(exc))), file=sys.stderr)
    return 1
  print(json.dumps(result, sort_keys=True, indent=2))
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
