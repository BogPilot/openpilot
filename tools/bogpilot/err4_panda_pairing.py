#!/usr/bin/env python3
"""Package-time check: the AP1 EPAS code 4 recovery ships only with the panda rule that allows it.

The car-side recovery (opendbc/car/tesla_ap1/epas_gate.py, EpasTmpFaultRecovery) sends ANGLE frames while the EPAS
reports a latched EAC_ERROR_TMP_FAULT (4). A panda without the matching AP1 rule refuses those frames, and once no
ANGLE frame has been accepted for 100 ms it forwards the stock DAS 0x488 again. So a build that has the recovery
must have the panda firmware source with that rule: the reviewed identity below (source_sha256[:8] of
panda/build_identity.py's inventory) and the rule itself in tesla_ap1.h. Change ERR4_PANDA_IDENTITY only together
with a reviewed panda change.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ERR4_PANDA_IDENTITY = "25e380f4"
RECOVERY_FILE = "opendbc_repo/opendbc/car/tesla_ap1/epas_gate.py"
RECOVERY_MARKER = "class EpasTmpFaultRecovery"
PANDA_RULE_FILE = "opendbc_repo/opendbc/safety/modes/tesla_ap1.h"
PANDA_RULE_MARKERS = ("tesla_ap1_epas_tmp_fault_ready", "tesla_ap1_rx_all_hook")


def recovery_present(root: Path) -> bool:
  p = Path(root) / RECOVERY_FILE
  return p.is_file() and RECOVERY_MARKER in p.read_text()


def check(root: Path, panda_identity: str) -> str:
  """Return a PASS line or raise ValueError."""
  root = Path(root)
  if not recovery_present(root):
    return "PASS err4 pairing: no code 4 recovery in this tree"
  if panda_identity != ERR4_PANDA_IDENTITY:
    raise ValueError(f"code 4 recovery present but panda identity is {panda_identity}, expected {ERR4_PANDA_IDENTITY}")
  rule = root / PANDA_RULE_FILE
  text = rule.read_text() if rule.is_file() else ""
  missing = [m for m in PANDA_RULE_MARKERS if m not in text]
  if missing:
    raise ValueError(f"code 4 recovery present but the panda rule is missing ({', '.join(missing)})")
  return f"PASS err4 pairing: code 4 recovery with panda {panda_identity}"


def identity_from_manifest(root: Path) -> str:
  data = json.loads((Path(root) / ".panda-source.json").read_text())
  return str(data.get("source_sha256", ""))[:8]


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--root", required=True, type=Path)
  ap.add_argument("--panda-identity", help="8-hex panda identity; default: from <root>/.panda-source.json")
  args = ap.parse_args(argv)
  try:
    print(check(args.root, args.panda_identity or identity_from_manifest(args.root)))
    return 0
  except Exception as exc:
    print("BLOCKED:", type(exc).__name__, str(exc))
    return 1


if __name__ == "__main__":
  sys.exit(main())
