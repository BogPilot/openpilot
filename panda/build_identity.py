"""Verified panda source provenance, independent of Git metadata in build archives.

The manifest is a provenance assertion, not a signature or a safety certification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

MANIFEST = '.panda-source.json'
# Complete firmware/build inputs; generated obj outputs are deliberately excluded.
SCOPES = ('panda', 'opendbc_repo/opendbc/safety')
EXTRA = ('SConstruct', 'common/version.h')


def git(root, *args):
  return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


def inventory(root):
  paths = set(EXTRA)
  for scope in SCOPES:
    for p in (root / scope).rglob('*'):
      rel = p.relative_to(root)
      if any(x in rel.parts for x in ('.git', '__pycache__', '.pytest_cache', 'obj')):
        continue
      if p.name in (".sconsign.dblite", "compile_commands.json"):
        continue
      if p.is_file() and not p.name.endswith(('.pyc', '.o', '.so')):
        paths.add(rel.as_posix())
  result = {}
  for name in sorted(paths):
    p = root / name
    if not p.is_file():
      raise ValueError(f'missing source input: {name}')
    result[name] = hashlib.sha256(p.read_bytes()).hexdigest()
  return result


def digest(files):
  return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def checkout(root):
  try:
    return Path(git(root, 'rev-parse', '--show-toplevel')).resolve() == root.resolve()
  except subprocess.CalledProcessError:
    return False


def capture(root):
  if not checkout(root):
    raise ValueError('export requires actual source checkout; never fabricate .git')
  files = inventory(root)
  status = git(root, 'status', '--porcelain', '--untracked-files=all', '--', '.', ':!'+MANIFEST, ':!panda/board/obj',
               ':!panda/.sconsign.dblite', ':!panda/compile_commands.json')
  return dict(schema=1, source_commit=git(root, 'rev-parse', 'HEAD'), dirty=bool(status),
              version=(root / 'common/version.h').read_text().strip(), files=files, source_sha256=digest(files))


def identity(root):
  root = Path(root).resolve()
  path = root / MANIFEST
  if checkout(root):
    current = capture(root)
    if path.exists() and json.loads(path.read_text()) != current:
      raise ValueError('stale or mismatched source manifest in checkout')
    return current
  if not path.exists():
    raise ValueError('archive build requires verified .panda-source.json exported from source checkout')
  data = json.loads(path.read_text())
  if (data.get('schema') != 1 or not re.fullmatch('[0-9a-f]{40}', data.get('source_commit', ''))
      or type(data.get('dirty')) is not bool):
    raise ValueError('invalid source manifest metadata')
  files = inventory(root)
  if data.get('files') != files or data.get('source_sha256') != digest(files):
    raise ValueError('archive source content does not match manifest')
  if data.get('version') != (root / 'common/version.h').read_text().strip():
    raise ValueError('archive version does not match manifest')
  return data


def firmware_version(root, builder, build_type):
  data = identity(root)
  # Full source commit (NOT future output commit), dirty state and content fingerprint.
  # 61 bytes for DEV/DEBUG, within panda's 64-byte USB version response.
  state = 'd' if data['dirty'] else 'c'
  version = f"{builder}-{data['source_commit']}-{state}-{data['source_sha256'][:8]}-{build_type}"
  if len(version.encode()) > 64 or not re.fullmatch('[A-Za-z0-9.-]+', version):
    raise ValueError('invalid/oversized firmware version')
  return version


def main():
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument('command', choices=['export', 'verify'])
  ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
  args = ap.parse_args()
  if args.command == 'export':
    data = capture(args.root.resolve())
    (args.root / MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
  print(firmware_version(args.root, 'DEV', 'DEBUG'))


if __name__ == '__main__':
  main()
