"""Pre-push guard: the prebuilt panda firmware must be built from the pushed tree's panda source."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tools.bogpilot import panda_prebuilt_guard as g

ROOT = Path(__file__).resolve().parents[3]
SYNTH_EMAIL = "@".join(("test", "example.invalid"))


def git(root, *args):
  return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


def commit(root, msg="change"):
  git(root, "add", "-A")
  git(root, "-c", "user.name=Synthetic", "-c", "user.email=" + SYNTH_EMAIL, "commit", "-qm", msg)
  return git(root, "rev-parse", "HEAD")


def stamp(root, source, ident, state="c"):
  version = f"DEV-{source}-{state}-{ident}-DEBUG"
  obj = root / "panda/board/obj"
  obj.mkdir(parents=True, exist_ok=True)
  (obj / "version").write_text(version)
  (obj / "gitversion.h").write_text(f'const uint8_t gitversion[{len(version) + 1}] = "{version}";\n')


@pytest.fixture
def repo(tmp_path):
  root = tmp_path / "repo"
  for rel in ("SConstruct", "openpilot/common/version.h", "panda/board/main.c", "panda/SConscript",
              "opendbc_repo/opendbc/safety/modes/tesla_ap1.h", "opendbc_repo/opendbc/safety/tests/test_tesla_ap1.py",
              "panda/tests/libpanda/panda.c"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"fixture {rel}\n")
  (root / "common").mkdir()
  os.symlink("../openpilot/common/version.h", root / "common/version.h")
  shutil.copyfile(ROOT / g.BUILD_IDENTITY_FILE, root / g.BUILD_IDENTITY_FILE)
  git(root.parent, "init", "-q", str(root))
  source = commit(root, "source")
  ident = g.load_build_identity(root)
  ident = ident.digest(ident.inventory(root))[:8]
  stamp(root, source, ident)
  out = commit(root, "prebuilt")
  return root, source, out, ident


def git_check(root, rev="HEAD"):
  return g.check_git(root / ".git", rev)


def test_pass_root_and_git(repo):
  root, source, out, ident = repo
  assert ident in g.check_root(root)
  assert source[:12] in git_check(root)


def test_git_inventory_equals_filesystem_inventory(repo):
  root, *_ = repo
  bi = g.load_build_identity(root)
  assert g.git_inventory(root / ".git", "HEAD", bi) == bi.inventory(root)


def test_panda_source_change_without_rebuild_refused(repo):
  root, *_ = repo
  (root / "opendbc_repo/opendbc/safety/modes/tesla_ap1.h").write_text("changed rule\n")
  commit(root)
  with pytest.raises(ValueError, match="rebuild the panda firmware"):
    git_check(root)
  assert g.main(["--git-dir", str(root / ".git"), "--rev", "HEAD"]) == 1


def test_version_header_change_refused(repo):
  root, *_ = repo
  (root / "openpilot/common/version.h").write_text("new version\n")   # reached through the common/version.h symlink
  commit(root)
  with pytest.raises(ValueError, match="rebuild"):
    git_check(root)


def test_test_only_change_passes(repo):
  root, *_ = repo
  (root / "opendbc_repo/opendbc/safety/tests/test_tesla_ap1.py").write_text("edited test\n")
  (root / "panda/tests/libpanda/panda.c").write_text("edited test library\n")
  commit(root)
  assert git_check(root)
  assert g.main(["--root", str(root)]) == 0


def test_source_commit_not_an_ancestor_refused(repo):
  root, source, out, ident = repo
  stamp(root, "f" * 40, ident)
  commit(root)
  with pytest.raises((ValueError, subprocess.CalledProcessError)):
    git_check(root)
  assert g.main(["--git-dir", str(root / ".git")]) == 1


def test_source_commit_with_other_identity_refused(repo):
  root, source, out, ident = repo
  (root / "panda/board/main.c").write_text("older source\n")
  other = commit(root, "other source")
  (root / "panda/board/main.c").write_text(f"fixture panda/board/main.c\n")
  stamp(root, other, ident)
  commit(root)
  with pytest.raises(ValueError, match="has panda identity"):
    git_check(root)


def test_dirty_build_refused(repo):
  root, source, out, ident = repo
  stamp(root, source, ident, state="d")
  commit(root)
  with pytest.raises(ValueError, match="dirty"):
    git_check(root)


def test_gitversion_mismatch_refused(repo):
  root, *_ = repo
  (root / g.GITVERSION_FILE).write_text('const uint8_t gitversion[4] = "old";\n')
  commit(root)
  with pytest.raises(ValueError, match="gitversion.h"):
    git_check(root)


def test_real_tree_passes():
  assert g.main(["--root", str(ROOT)]) == 0
