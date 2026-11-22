"""The AP1 code 4 recovery may only be packaged with the panda rule that allows it."""
import json
from pathlib import Path
import shutil

import pytest

from tools.bogpilot import err4_panda_pairing as m
from tools.bogpilot import rc_package

ROOT = Path(__file__).resolve().parents[3]


def _tree(tmp_path, recovery=True, rule=True):
  for rel, src in ((m.RECOVERY_FILE, recovery), (m.PANDA_RULE_FILE, rule)):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if src:
      shutil.copyfile(ROOT / rel, p)
    else:
      p.write_text("// no code 4 rule\n" if rel.endswith(".h") else "# no recovery\n")
  return tmp_path


def test_this_tree_passes_with_its_measured_panda_identity():
  """Real measurement of this tree's panda identity.

  A built or packaged tree carries .panda-source.json from a clean checkout and its on-disk files differ on purpose
  (build outputs added, the debug signing cert left out), so there the manifest identity is the one to check.
  On a clean checkout without a manifest, the identity panda/build_identity.py computes from the files is used.
  """
  assert m.recovery_present(ROOT)
  if (ROOT / ".panda-source.json").is_file():
    ident = m.identity_from_manifest(ROOT)
    assert ident == m.ERR4_PANDA_IDENTITY, ident
  else:
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_identity", ROOT / "panda/build_identity.py")
    bi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bi)
    ident = bi.digest(bi.inventory(ROOT))[:8]
  assert m.check(ROOT, ident).startswith("PASS"), ident


def test_identity_mismatch_blocks(tmp_path):
  root = _tree(tmp_path)
  with pytest.raises(ValueError, match="886d9623"):
    m.check(root, "886d9623")       # the panda before the code 4 rule


def test_rule_missing_blocks_even_with_the_expected_identity(tmp_path):
  with pytest.raises(ValueError, match="panda rule is missing"):
    m.check(_tree(tmp_path, rule=False), m.ERR4_PANDA_IDENTITY)


def test_code4_only_rule_blocks(tmp_path):
  """A panda rule with the code 4 exception but not the code 7 one refuses the code 7 requests."""
  root = _tree(tmp_path)
  rule = root / m.PANDA_RULE_FILE
  rule.write_text(rule.read_text().replace("tesla_ap1_epas_rate_req_ready", "x"))
  with pytest.raises(ValueError, match="tesla_ap1_epas_rate_req_ready"):
    m.check(root, m.ERR4_PANDA_IDENTITY)

def test_no_recovery_no_requirement(tmp_path):
  assert m.check(_tree(tmp_path, recovery=False, rule=False), "886d9623").startswith("PASS")


def test_cli_reads_the_identity_from_the_manifest(tmp_path, capsys):
  root = _tree(tmp_path)
  (root / ".panda-source.json").write_text(json.dumps({"source_sha256": "886d9623" + "0" * 56}))
  assert m.main(["--root", str(root)]) == 1
  assert "BLOCKED" in capsys.readouterr().out
  assert m.main(["--root", str(root), "--panda-identity", m.ERR4_PANDA_IDENTITY]) == 0


def test_rc_package_verify_runs_the_pairing_check():
  assert rc_package.check_err4_panda_pairing is m.check
  src = Path(rc_package.__file__).read_text()
  assert src.index("validate_panda(root, candidate, exclusions)\n") < src.index("check_err4_panda_pairing(root,")
