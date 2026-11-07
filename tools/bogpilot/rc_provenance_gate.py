#!/usr/bin/env python3
"""Read-only source/privacy release gate. Never emits file contents or raw paths."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

SCHEMA = 1
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 4 * 1024 * 1024 * 1024
BASE_ASSETS = ("LICENSE", "launch_chffrplus.sh", "launch_openpilot.sh", "SConstruct", "pyproject.toml", "uv.lock",
               "openpilot/selfdrive/modeld/models/driving_tinygrad.pkl",
               "openpilot/selfdrive/modeld/models/dmonitoring_model_tinygrad.pkl",
               "openpilot/selfdrive/modeld/models/driving_warp_1344x760_tinygrad.pkl",
               "openpilot/selfdrive/modeld/models/driving_warp_1928x1208_tinygrad.pkl",
               "openpilot/selfdrive/modeld/models/dm_warp_1344x760_tinygrad.pkl",
               "openpilot/selfdrive/modeld/models/dm_warp_1928x1208_tinygrad.pkl")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PRIVATE_PARTS = {".git", ".ssh", ".aws", ".gnupg", "realdata", "params", "params_backup", "params_backups", "private", "secrets", "node_modules", ".venv", "venv"}
KEY = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
TOKEN = re.compile(rb"(?im)^\s*(?:export\s+)?(?:TAILSCALE_AUTHKEY|BOGPILOT_SSH_KEY|API_KEY|ACCESS_TOKEN|AUTH_TOKEN|SECRET_KEY)\s*[:=]\s*[\"\']?[^\s\"\'$]{12,}")
IDENTITY = re.compile(rb"(?:[0-9a-f]{16}\|[0-9]{4}-[0-9]{2}-[0-9]{2}--[0-9]{2}-[0-9]{2}-[0-9]{2}|(?i:VIN)\s*[:=]\s*[\"\']?[A-HJ-NPR-Z0-9]{17})")


def digest(data):
  return hashlib.sha256(data).hexdigest()


def path_id(path):
  return digest(str(path).encode("utf-8", "surrogateescape"))


def safe_path(value):
  if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
    return False
  p = PurePosixPath(value)
  return not p.is_absolute() and all(x not in ("", ".", "..") for x in value.split("/"))


def private_name(name):
  parts = PurePosixPath(name).parts
  low = [p.lower() for p in parts]
  base = low[-1]
  return (any(p in PRIVATE_PARTS for p in low) or base.startswith((".env", "id_rsa", "id_ed25519"))
          or base.endswith((".rlog", ".qlog", ".pem", ".key", ".p12", ".pfx"))
          or base in ("rlog", "qlog", "rlog.bz2", "rlog.zst", "qlog.bz2", "qlog.zst", "config.json", "authorized_keys", "known_hosts", "compile_commands.json")
          or bool(re.search(r"(?:rlog|qlog)[.\-]", base)))


def git(repo, *args):
  # No remote calls, shell interpolation, source execution or raw stderr output.
  p = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, timeout=30)
  if p.returncode:
    raise ValueError("git_failed")
  return p.stdout


def tree_entries(repo):
  out = {}
  for item in git(repo, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
    if item:
      meta, path = item.split(b"\t", 1)
      mode, kind, sha = meta.decode("ascii").split()
      out[os.fsdecode(path)] = (mode, kind, sha)
  return out


def regular_inside(repo, name):
  """Do not follow any symlink, even one pointing inside the source checkout."""
  if not safe_path(name):
    return None
  p = repo
  try:
    for part in PurePosixPath(name).parts:
      p = p / part
      if stat.S_ISLNK(p.lstat().st_mode):
        return None
    return p if stat.S_ISREG(p.lstat().st_mode) else None
  except OSError:
    return None


def audit(repo, manifest, shipping_root=None):
  result = {"schema_version": SCHEMA, "status": "blocked", "scope": "source_and_explicit_shipping_files",
            "checks": [], "limitations": ["heuristic_content_scan_not_privacy_certification", "no_firmware_or_archive_validation"]}
  checks = result["checks"]
  def fail(code, path=None):
    row = {"code": code}
    if path is not None:
      row["path_id"] = path_id(path)
    checks.append(row)
  try:
    repo = Path(repo).resolve(strict=True)
    # Ensure caller supplied the checkout root, not an arbitrary subdirectory.
    if Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel")).strip()).resolve() != repo:
      raise ValueError("not_repo_root")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    tree = git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    dirty = bool(git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"))
    result["source"] = {"commit": head, "tree": tree, "clean": not dirty}
    if dirty:
      fail("dirty_worktree")
    shipping_root = Path(shipping_root).resolve(strict=True) if shipping_root is not None else repo
    if not shipping_root.is_dir():raise ValueError("shipping_root_not_directory")
    entries = tree_entries(repo)
    notice_sources = {p:(repo,p) for p in entries if PurePosixPath(p).name.lower().startswith(("license", "notice", "copying", "authors", "copyright"))}
    links = {p: e[2] for p,e in entries.items() if e[0] == "160000"}
    result["submodules"] = [{"path_id":path_id(p), "commit":sha} for p,sha in sorted(links.items())]
    # Vendored dependencies are trees, not git submodules: report exact tree OIDs.
    roots = git(repo, "ls-tree", "-z", "HEAD").split(b"\0")
    result["vendored_trees"] = []
    for row in roots:
      if not row: continue
      meta, name = row.split(b"\t",1)
      mode, kind, sha = meta.decode().split()
      if kind == "tree" and (name.endswith(b"_repo") or name == b"panda"):
        result["vendored_trees"].append({"path_id":path_id(os.fsdecode(name)),"tree":sha})
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != SCHEMA:
      fail("manifest_schema");return result
    expected = manifest.get("source_commit")
    if not isinstance(expected,str) or not HEX40.fullmatch(expected) or expected != head:
      fail("source_commit_mismatch")
    if manifest.get("submodules") != links:
      fail("submodule_pin_manifest_mismatch")
    for name,sha in links.items():
      try:
        p = repo/name
        if not safe_path(name) or any((repo / Path(*PurePosixPath(name).parts[:i+1])).is_symlink() for i in range(len(PurePosixPath(name).parts))) or not p.is_dir():
          raise ValueError("submodule_unavailable")
        if git(p,"rev-parse","HEAD").decode().strip() != sha:
          fail("submodule_checkout_mismatch",name)
        if git(p,"status","--porcelain=v1","-z","--untracked-files=all"):
          fail("submodule_dirty",name)
        sub_entries = tree_entries(p)
        for subname,entry in sub_entries.items():
          if entry[1] == "blob" and PurePosixPath(subname).name.lower().startswith(("license", "notice", "copying", "authors", "copyright")):
            full = name + "/" + subname
            notice_sources[full] = (p,subname)
            entries[full] = entry
        # Nested gitlinks require explicit independent audit, not a silent pass.
        if any(e[0] == "160000" for e in sub_entries.values()):
          fail("nested_submodule_audit_required",name)
      except (OSError,ValueError,subprocess.TimeoutExpired):
        fail("submodule_unavailable",name)
    files = manifest.get("files")
    required = manifest.get("required_build_assets")
    notices = manifest.get("license_notices")
    if (not isinstance(files,dict) or not files or not isinstance(required,list) or not required
        or not isinstance(notices,list) or not notices):
      fail("manifest_inventory_required");return result
    if any(not safe_path(p) for p in files) or any(not safe_path(p) for p in required+notices):
      fail("unsafe_manifest_path");return result
    if any(not isinstance(h,str) or not HEX64.fullmatch(h) for h in files.values()):
      fail("invalid_file_digest");return result
    required_notices = set(notice_sources)
    result["license_notices"] = [{"path_id":path_id(p),"source_blob":entries[p][2]} for p in sorted(required_notices)]
    if not required_notices.issubset(set(notices)):
      fail("license_notice_inventory_incomplete")
    for name in set(BASE_ASSETS) | set(required) | set(notices):
      if name not in files:
        fail("required_file_not_shipped",name)
    public_fixtures = manifest.get("reviewed_public_fixtures", {})
    if not isinstance(public_fixtures,dict) or any(p not in files or h != files[p] for p,h in public_fixtures.items()):
      fail("invalid_public_fixture_review");public_fixtures = {}
    total = 0
    count = 0
    for name,expected_hash in sorted(files.items()):
      if private_name(name):
        fail("private_shipping_path",name)
        # Do not open known credential/log/config files, even for hashing.
        continue
      p = regular_inside(shipping_root,name)
      if p is None:
        fail("missing_or_nonregular_shipping_file",name);continue
      try:
        size = p.stat().st_size
        if size > MAX_FILE or total+size > MAX_TOTAL:
          fail("scan_budget_exceeded",name);continue
        if size == 0 and name in (set(required) | set(BASE_ASSETS)):
          fail("empty_build_asset",name)
        total += size
        h = hashlib.sha256()
        tail = b""
        sensitive = identity = False
        first = True
        lfs = False
        with p.open("rb") as f:
          while True:
            block=f.read(65536)
            if not block:break
            if first:
              lfs = block.startswith(b"version https://git-lfs.github.com/spec/v1")
              first = False
            h.update(block)
            data=tail+block
            sensitive = sensitive or bool(KEY.search(data) or TOKEN.search(data))
            identity = identity or bool(IDENTITY.search(data))
            tail=data[-4096:]
        actual=h.hexdigest();count+=1
        if lfs and name in (set(required) | set(BASE_ASSETS)):fail("unresolved_build_asset",name)
        if actual != expected_hash:fail("shipping_digest_mismatch",name)
        if sensitive:fail("credential_content",name)
        if identity and public_fixtures.get(name) != actual:fail("unreviewed_identity_content",name)
        if name in notices and (size == 0 or name not in entries):fail("invalid_license_notice",name)
        if name in notices and name in entries:
          # Do not permit stripping/replacing source notices in the shipping copy.
          origin,relative = notice_sources.get(name,(repo,name))
          original=git(origin,"show","HEAD:"+relative)
          if digest(original) != actual:fail("source_license_notice_changed",name)
      except (OSError,ValueError,subprocess.TimeoutExpired):
        fail("shipping_file_unreadable",name)
    result["shipping"] = {"declared_files":len(files),"scanned_files":count,"scanned_bytes":total,
                          "manifest_sha256":digest(json.dumps(manifest,sort_keys=True,separators=(",",":")).encode())}
    # Snapshot fencing: detect source modifications during a potentially long scan.
    if git(repo,"rev-parse","HEAD").decode().strip()!=head or git(repo,"status","--porcelain=v1","-z","--untracked-files=all","--ignore-submodules=none"):
      fail("source_changed_during_audit")
    result["status"] = "pass" if not checks else "blocked"
  except (OSError,ValueError,TypeError,subprocess.TimeoutExpired):
    fail("audit_input_or_git_error")
  return result


def unique_object(pairs):
  result = {}
  for key,value in pairs:
    if key in result:raise ValueError("duplicate_manifest_key")
    result[key]=value
  return result


def main(argv=None):
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--repo",required=True)
  parser.add_argument("--manifest",required=True)
  parser.add_argument("--shipping-root",help="Explicit staging root for shipping files; defaults to source repo")
  parser.add_argument("--output",help="Write JSON outside source checkout; default stdout")
  args=parser.parse_args(argv)
  try:
    manifest_path=Path(args.manifest)
    if manifest_path.stat().st_size > 16*1024*1024:raise ValueError("manifest_too_large")
    manifest=json.loads(manifest_path.read_text(), object_pairs_hook=unique_object)
    result=audit(args.repo,manifest,args.shipping_root)
  except (OSError,ValueError,TypeError):
    result={"schema_version":SCHEMA,"status":"blocked","checks":[{"code":"manifest_unreadable"}]}
  text=json.dumps(result,sort_keys=True,indent=2)+"\n"
  if args.output:
    try:
      # Never overwrite source/evidence files through the audit output flag.
      output=Path(args.output)
      repo=Path(args.repo).resolve()
      resolved=output.resolve()
      staging=Path(args.shipping_root).resolve() if args.shipping_root else repo
      if any(base == resolved or base in resolved.parents for base in (repo,staging)):raise ValueError("output_inside_repo_or_staging")
      with output.open("x") as f:f.write(text)
    except (OSError,ValueError):
      print(json.dumps({"schema_version":SCHEMA,"status":"blocked","checks":[{"code":"output_not_new_external_file"}]}))
      return 2
  else:print(text,end="")
  return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
  raise SystemExit(main())
