"""The AP1 code 4 recovery may only be packaged with the panda rule that allows it, and with prebuilt panda firmware
built from that panda source (identity computed from the tree, never a hardcoded value)."""
import json
from pathlib import Path
import shutil

import pytest

from tools.bogpilot import err4_panda_pairing as m
from tools.bogpilot import rc_package

ROOT = Path(__file__).resolve().parents[3]
COMMIT = "a" * 40


def _write_prebuilt(root, ident, state="c", gitversion=True):
  version = f"DEV-{COMMIT}-{state}-{ident}-DEBUG"
  obj = root / "panda/board/obj"
  obj.mkdir(parents=True, exist_ok=True)
  (obj / "version").write_text(version)
  if gitversion:
    (obj / "gitversion.h").write_text(f'#pragma once\n\nconst uint8_t gitversion[{len(version) + 1}] = "{version}";\n')


def _tree(tmp_path, recovery=True, rule=True, prebuilt="match"):
  """Small tree with the real build_identity.py, the recovery and the rule; prebuilt version matching its identity."""
  for rel, src in ((m.RECOVERY_FILE, recovery), (m.PANDA_RULE_FILE, rule)):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if src:
      shutil.copyfile(ROOT / rel, p)
    else:
      p.write_text("// no code 4 rule\n" if rel.endswith(".h") else "# no recovery\n")
  for rel in (m.BUILD_IDENTITY_FILE, "SConstruct", "common/version.h", "panda/board/main.c",
              "opendbc_repo/opendbc/safety/tests/test_tesla_ap1.py"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if rel == m.BUILD_IDENTITY_FILE:
      shutil.copyfile(ROOT / rel, p)
    else:
      p.write_text(f"fixture {rel}\n")
  if prebuilt == "match":
    _write_prebuilt(tmp_path, m.tree_identity(tmp_path))
  elif prebuilt:
    _write_prebuilt(tmp_path, prebuilt)
  return tmp_path


def test_this_tree_passes_with_its_computed_panda_identity():
  """Real tree: the prebuilt panda firmware was built from this tree's panda source."""
  assert m.recovery_present(ROOT)
  ident = m.tree_identity(ROOT)
  assert m.prebuilt_version(ROOT)[2] == ident
  assert m.check(ROOT).startswith("PASS"), ident


def test_no_hardcoded_identity():
  assert not hasattr(m, "ERR4_PANDA_IDENTITY")


def test_fixture_passes(tmp_path):
  assert m.check(_tree(tmp_path)).startswith("PASS")


def test_panda_source_change_without_rebuild_blocks(tmp_path):
  root = _tree(tmp_path)
  rule = root / m.PANDA_RULE_FILE
  rule.write_text(rule.read_text() + "\n// changed rule\n")
  with pytest.raises(ValueError, match="rebuild the panda firmware"):
    m.check(root)


def test_test_only_edit_keeps_the_pairing(tmp_path):
  root = _tree(tmp_path)
  (root / "opendbc_repo/opendbc/safety/tests/test_tesla_ap1.py").write_text("edited test\n")
  (root / "opendbc_repo/opendbc/safety/tests/test_new.py").write_text("new test\n")
  assert m.check(root).startswith("PASS")


def test_identity_mismatch_blocks(tmp_path):
  root = _tree(tmp_path)
  with pytest.raises(ValueError, match="886d9623"):
    m.check(root, "886d9623")       # the panda before the code 4 rule


def test_stale_prebuilt_blocks(tmp_path):
  with pytest.raises(ValueError, match="prebuilt panda firmware is 886d9623"):
    m.check(_tree(tmp_path, prebuilt="886d9623"))


def test_dirty_prebuilt_blocks(tmp_path):
  root = _tree(tmp_path)
  _write_prebuilt(root, m.tree_identity(root), state="d")
  with pytest.raises(ValueError, match="dirty"):
    m.check(root)


def test_gitversion_mismatch_blocks(tmp_path):
  root = _tree(tmp_path)
  (root / m.GITVERSION_FILE).write_text('const uint8_t gitversion[9] = "DEV-old";\n')
  with pytest.raises(ValueError, match="gitversion.h"):
    m.check(root)


def test_missing_prebuilt_blocks(tmp_path):
  with pytest.raises(FileNotFoundError):
    m.check(_tree(tmp_path, prebuilt=None))


def test_rule_missing_blocks(tmp_path):
  with pytest.raises(ValueError, match="panda rule is missing"):
    m.check(_tree(tmp_path, rule=False, prebuilt="00000000"))


def test_code4_only_rule_blocks(tmp_path):
  """A panda rule with the code 4 exception but not the code 7 one refuses the code 7 requests."""
  root = _tree(tmp_path)
  rule = root / m.PANDA_RULE_FILE
  rule.write_text(rule.read_text().replace("tesla_ap1_epas_rate_req_ready", "x"))
  with pytest.raises(ValueError, match="tesla_ap1_epas_rate_req_ready"):
    m.check(root)


def test_no_recovery_no_requirement(tmp_path):
  assert m.check(_tree(tmp_path, recovery=False, rule=False, prebuilt=None), "886d9623").startswith("PASS")


def test_cli(tmp_path, capsys):
  root = _tree(tmp_path)
  assert m.main(["--root", str(root)]) == 0
  (root / ".panda-source.json").write_text(json.dumps({"source_sha256": "886d9623" + "0" * 56}))
  assert m.main(["--root", str(root), "--from-manifest"]) == 1
  assert "BLOCKED" in capsys.readouterr().out
  assert m.main(["--root", str(root), "--panda-identity", m.tree_identity(root)]) == 0


def test_rc_package_verify_runs_the_pairing_check():
  assert rc_package.check_err4_panda_pairing is m.check
  src = Path(rc_package.__file__).read_text()
  assert src.index("validate_panda(root, candidate, exclusions)\n") < src.index("check_err4_panda_pairing(root,")
