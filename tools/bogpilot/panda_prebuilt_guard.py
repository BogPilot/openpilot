#!/usr/bin/env python3
"""Pre-push guard: refuse a commit whose prebuilt panda firmware was not built from its own panda source.

Checks, on a checkout (--root) or straight from git objects (--git-dir/--rev, so a bare repository works):
- the 8 hex identity in panda/board/obj/version equals the panda source identity of the tree
  (panda/build_identity.py inventory: panda, opendbc safety, SConstruct, common/version.h; test files excluded),
- gitversion.h carries the same version string and the build was clean (c),
- in git mode, the version's source commit is the pushed commit or one of its ancestors, with that same identity.
Read only; writes nothing. Exit 0 PASS, 1 REFUSED.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
import types

BUILD_IDENTITY_FILE = "panda/build_identity.py"
VERSION_FILE = "panda/board/obj/version"
GITVERSION_FILE = "panda/board/obj/gitversion.h"
VERSION_RE = re.compile(r"DEV-([0-9a-f]{40})-([cd])-([0-9a-f]{8})-DEBUG")


def _git(git_dir, *args, data=None):
  return subprocess.run(["git", "--git-dir", str(git_dir), *args], input=data, capture_output=True, check=True).stdout


def load_build_identity_from_git(git_dir, rev):
  module = types.ModuleType("build_identity")
  exec(compile(_git(git_dir, "show", f"{rev}:{BUILD_IDENTITY_FILE}").decode(), BUILD_IDENTITY_FILE, "exec"), module.__dict__)
  return module


def load_build_identity(root):
  spec = importlib.util.spec_from_file_location("build_identity", Path(root) / BUILD_IDENTITY_FILE)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def git_inventory(git_dir, rev, bi):
  """Same result as bi.inventory() on a checkout of rev, computed from git objects."""
  out = _git(git_dir, "ls-tree", "-r", "-z", "--full-tree", rev)
  entries = {}
  for item in out.split(b"\0"):
    if not item:
      continue
    meta, path = item.split(b"\t", 1)
    mode, _kind, obj = meta.split()
    entries[path.decode()] = (mode.decode(), obj.decode())

  def blob_of(path, depth=0):
    if path not in entries or depth > 8:
      raise ValueError(f"missing source input: {path}")
    mode, obj = entries[path]
    if mode == "120000":   # symlink: hash the target file, as the filesystem walk does
      target = _git(git_dir, "cat-file", "blob", obj).decode()
      return blob_of(posixpath.normpath(posixpath.join(posixpath.dirname(path), target)), depth + 1)
    if mode == "160000":
      raise ValueError(f"submodule inside the panda source scope: {path}")
    return obj

  # Older build_identity.py (before test files were excluded) has only _is_build_output.
  is_input = getattr(bi, "is_input", None) or (lambda rel: not bi._is_build_output(rel))
  names = set(bi.EXTRA)
  for path in entries:
    if any(path.startswith(scope + "/") for scope in bi.SCOPES) and is_input(PurePosixPath(path)):
      names.add(path)
  objs = {name: blob_of(name) for name in sorted(names)}
  batch = _git(git_dir, "cat-file", "--batch", data="".join(o + "\n" for o in objs.values()).encode())
  contents, pos = {}, 0
  for obj in objs.values():
    header_end = batch.index(b"\n", pos)
    size = int(batch[pos:header_end].split()[2])
    contents[obj] = batch[header_end + 1:header_end + 1 + size]
    pos = header_end + 1 + size + 1
  return {name: hashlib.sha256(contents[obj]).hexdigest() for name, obj in objs.items()}


def parse_version(version, gitversion):
  m = VERSION_RE.fullmatch(version.strip())
  if m is None:
    raise ValueError(f"prebuilt panda version string not recognized: {version.strip()!r}")
  if f'"{version.strip()}"' not in gitversion:
    raise ValueError("prebuilt gitversion.h does not match panda/board/obj/version")
  if m.group(2) != "c":
    raise ValueError("prebuilt panda firmware was built from a dirty source tree")
  return m.group(1), m.group(3)


def check_root(root):
  root = Path(root)
  bi = load_build_identity(root)
  ident = bi.digest(bi.inventory(root))[:8]
  _commit, prebuilt = parse_version((root / VERSION_FILE).read_text(), (root / GITVERSION_FILE).read_text())
  if prebuilt != ident:
    raise ValueError(f"panda source identity {ident} differs from the prebuilt firmware {prebuilt}: rebuild the panda firmware")
  return f"panda source {ident} matches the prebuilt firmware"


def check_git(git_dir, rev):
  rev = _git(git_dir, "rev-parse", "--verify", f"{rev}^{{commit}}").decode().strip()
  bi = load_build_identity_from_git(git_dir, rev)
  ident = bi.digest(git_inventory(git_dir, rev, bi))[:8]
  source, prebuilt = parse_version(_git(git_dir, "show", f"{rev}:{VERSION_FILE}").decode(),
                                   _git(git_dir, "show", f"{rev}:{GITVERSION_FILE}").decode())
  if prebuilt != ident:
    raise ValueError(f"panda source identity {ident} differs from the prebuilt firmware {prebuilt}: rebuild the panda firmware")
  if subprocess.run(["git", "--git-dir", str(git_dir), "merge-base", "--is-ancestor", source, rev],
                    capture_output=True).returncode != 0:
    raise ValueError(f"prebuilt firmware source commit {source[:12]} is not this commit or an ancestor")
  source_ident = bi.digest(git_inventory(git_dir, source, bi))[:8]
  if source_ident != prebuilt:
    raise ValueError(f"prebuilt firmware source commit {source[:12]} has panda identity {source_ident}, not {prebuilt}")
  return f"{rev[:12]}: panda source {ident} matches the prebuilt firmware built from {source[:12]}"


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--root", type=Path)
  ap.add_argument("--git-dir", type=Path)
  ap.add_argument("--rev", default="HEAD")
  args = ap.parse_args(argv)
  try:
    line = check_git(args.git_dir, args.rev) if args.git_dir else check_root(args.root or Path.cwd())
    print("PANDA_GUARD PASS " + line)
    return 0
  except subprocess.CalledProcessError:
    print("PANDA_GUARD REFUSED git lookup failed (missing panda file or commit)")
    return 1
  except Exception as exc:   # fail closed
    print(f"PANDA_GUARD REFUSED {type(exc).__name__}: {exc}")
    return 1


if __name__ == "__main__":
  sys.exit(main())
