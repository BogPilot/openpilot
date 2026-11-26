#!/usr/bin/env python3
"""Package-time check: the AP1 EPAS code 4 / code 7 recovery ships only with the panda rule that allows it.

The car-side recovery (opendbc/car/tesla_ap1/epas_gate.py, EpasTmpFaultRecovery) sends ANGLE frames while the EPAS
reports a latched EAC_ERROR_TMP_FAULT (4), or a latched EAC_ERROR_HIGH_ANGLE_RATE_REQ (7) while AVAILABLE. A panda
without the matching AP1 rule (both codes) refuses those frames, and once no
ANGLE frame has been accepted for 100 ms it forwards the stock DAS 0x488 again. So a build that has the recovery
must have the rule in tesla_ap1.h, and the prebuilt panda firmware must be built from that panda source: the 8 hex
identity in panda/board/obj/version (and gitversion.h) must equal the panda source identity of this tree, computed by
panda/build_identity.py from the files (test files excluded). No identity is hardcoded here.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

RECOVERY_FILE = "opendbc_repo/opendbc/car/tesla_ap1/epas_gate.py"
RECOVERY_MARKER = "class EpasTmpFaultRecovery"
PANDA_RULE_FILE = "opendbc_repo/opendbc/safety/modes/tesla_ap1.h"
PANDA_RULE_MARKERS = ("tesla_ap1_epas_tmp_fault_ready", "tesla_ap1_epas_rate_req_ready", "tesla_ap1_rx_all_hook")
BUILD_IDENTITY_FILE = "panda/build_identity.py"
VERSION_FILE = "panda/board/obj/version"
GITVERSION_FILE = "panda/board/obj/gitversion.h"
VERSION_RE = re.compile(r"DEV-([0-9a-f]{40})-([cd])-([0-9a-f]{8})-DEBUG")


def recovery_present(root: Path) -> bool:
  p = Path(root) / RECOVERY_FILE
  return p.is_file() and RECOVERY_MARKER in p.read_text()


def tree_identity(root: Path) -> str:
  """Panda source identity (source_sha256[:8]) computed from the files in this tree."""
  root = Path(root)
  spec = importlib.util.spec_from_file_location("build_identity", root / BUILD_IDENTITY_FILE)
  bi = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(bi)
  return bi.digest(bi.inventory(root))[:8]


def identity_from_manifest(root: Path) -> str:
  data = json.loads((Path(root) / ".panda-source.json").read_text())
  return str(data.get("source_sha256", ""))[:8]


def prebuilt_version(root: Path) -> tuple[str, str, str]:
  """(source commit, clean flag, identity) of the prebuilt panda firmware; raises if missing or inconsistent."""
  root = Path(root)
  version = (root / VERSION_FILE).read_text().strip()
  m = VERSION_RE.fullmatch(version)
  if m is None:
    raise ValueError(f"prebuilt panda version string not recognized: {version!r}")
  gitversion = root / GITVERSION_FILE
  if not gitversion.is_file() or f'"{version}"' not in gitversion.read_text():
    raise ValueError("prebuilt panda gitversion.h does not match panda/board/obj/version")
  return m.group(1), m.group(2), m.group(3)


def check(root: Path, panda_identity: str | None = None) -> str:
  """Return a PASS line or raise ValueError.

  panda_identity defaults to the identity computed from the tree. A packaged tree (some inputs left out on purpose)
  passes the identity from its verified .panda-source.json instead (rc_package.py does).
  """
  root = Path(root)
  if not recovery_present(root):
    return "PASS err4 pairing: no code 4 recovery in this tree"
  rule = root / PANDA_RULE_FILE
  text = rule.read_text() if rule.is_file() else ""
  missing = [m for m in PANDA_RULE_MARKERS if m not in text]
  if missing:
    raise ValueError(f"code 4 recovery present but the panda rule is missing ({', '.join(missing)})")
  ident = panda_identity or tree_identity(root)
  _commit, state, prebuilt = prebuilt_version(root)
  if state != "c":
    raise ValueError("prebuilt panda firmware was built from a dirty source tree")
  if prebuilt != ident:
    raise ValueError(f"code 4 recovery present but the prebuilt panda firmware is {prebuilt} and the panda source is "
                     f"{ident}: rebuild the panda firmware")
  return f"PASS err4 pairing: code 4 recovery with panda {ident}, prebuilt firmware {prebuilt}"


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--root", required=True, type=Path)
  ap.add_argument("--panda-identity", help="8-hex panda identity; default: computed from the tree")
  ap.add_argument("--from-manifest", action="store_true", help="take the identity from <root>/.panda-source.json")
  args = ap.parse_args(argv)
  try:
    ident = args.panda_identity or (identity_from_manifest(args.root) if args.from_manifest else None)
    print(check(args.root, ident))
    return 0
  except Exception as exc:
    print("BLOCKED:", type(exc).__name__, str(exc))
    return 1


if __name__ == "__main__":
  sys.exit(main())
