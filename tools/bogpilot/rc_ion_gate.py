#!/usr/bin/env python3
"""RC_BUILD_GATE check `ion_visionbuf`: ION-backed VisionBuf must be compiled into the camera stack.

Read-only. Pure python (no nm/binutils), so it also runs where binutils is missing.
Why: msgq_repo/SConscript picks visionbuf_ion.cc only if /dev/ion exists on the BUILD host; otherwise it silently
builds the shm visionbuf.cc, which the comma's camera kernel driver cannot import (cameras never start, camerad SIGABRT).

Usage: rc_ion_gate.py ARTIFACT_ROOT [--json OUT]    exit 0 pass, 2 fail
Required artifacts (relative to ARTIFACT_ROOT):
  openpilot/system/camerad/camerad, openpilot/system/loggerd/encoderd, msgq_repo/msgq/visionipc/visionipc_pyx.so
Per file: contains b"/dev/ion", contains symbol name "_Z6ion_fdv" (ion_fd()), does NOT contain b"msgq_visionbuf".
"""
import json, sys, hashlib
from pathlib import Path

REQUIRED = ["openpilot/system/camerad/camerad", "openpilot/system/loggerd/encoderd",
            "msgq_repo/msgq/visionipc/visionipc_pyx.so"]

def check(root):
    res = []
    for rel in REQUIRED:
        p = Path(root) / rel
        if not p.is_file():
            res.append(dict(path=rel, ok=False, reason="missing")); continue
        b = p.read_bytes()
        d = dict(path=rel, sha256=hashlib.sha256(b).hexdigest(), size=len(b),
                 dev_ion=b"/dev/ion\x00" in b, ion_fd_symbol=b"_Z6ion_fdv" in b,
                 shm_visionbuf=b"msgq_visionbuf" in b, elf=b[:4] == b"\x7fELF")
        d["ok"] = d["elf"] and d["dev_ion"] and d["ion_fd_symbol"] and not d["shm_visionbuf"]
        if not d["ok"]:
            d["reason"] = "built without ION (shm VisionBuf); build host had no /dev/ion" if d["shm_visionbuf"] else "ION markers missing"
        res.append(d)
    return res

if __name__ == "__main__":
    root = sys.argv[1]
    res = check(root)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["path"] + ("" if r["ok"] else "  -> " + r.get("reason", "")))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(dict(gate="ion_visionbuf", ok=all(r["ok"] for r in res), files=res), indent=1))
    sys.exit(0 if all(r["ok"] for r in res) else 2)
