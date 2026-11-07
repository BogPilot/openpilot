#!/usr/bin/env python3
"""Read-only managerState liveness verdict for a stationary bench startup.

Judges ONLY process state (managerState samples + IsOffroad), never log volume:
quiet manager INFO output is not a stall. It does not start, stop or signal
processes, write params, flash, or prove driving/hardware/road readiness.

Samples file: JSON list of {"t": monotonic_seconds, "managerState_valid": bool,
"offroad": bool, "processes": [{"name","pid","running","shouldBeRunning","exitCode"}]}.
Optional --collect (device-side, read-only SubMaster/Params) writes that file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

DEFAULT_REQUIRED = ("ui", "logmessaged")


def evaluate(samples, required=DEFAULT_REQUIRED, min_seconds=60.0, forbidden=()):
  """Return (verdict, reasons). verdict in PASS / FAIL / INSUFFICIENT."""
  reasons = []
  if len(samples) < 2:
    return "INSUFFICIENT", ["need at least two samples"]
  times = [s.get("t") for s in samples]
  if any(type(t) not in (int, float) for t in times) or times != sorted(times):
    return "INSUFFICIENT", ["sample times missing or non-monotonic"]
  span = times[-1] - times[0]
  first_pid = {}
  for i, s in enumerate(samples):
    if s.get("managerState_valid") is not True:
      reasons.append(f"sample {i}: managerState not valid/fresh")
      continue
    if s.get("offroad") is not True:
      reasons.append(f"sample {i}: not offroad")
    procs = {p.get("name"): p for p in s.get("processes", [])}
    for name in required:
      p = procs.get(name)
      if p is None or p.get("running") is not True or not isinstance(p.get("pid"), int) or p["pid"] <= 0:
        reasons.append(f"sample {i}: {name} not running")
        continue
      if p.get("exitCode", 0) not in (0, None):
        reasons.append(f"sample {i}: {name} exitCode {p.get('exitCode')}")
      if first_pid.setdefault(name, p["pid"]) != p["pid"]:
        reasons.append(f"sample {i}: {name} restarted (pid {first_pid[name]} -> {p['pid']})")
    for name in forbidden:
      if procs.get(name, {}).get("running") is True:
        reasons.append(f"sample {i}: excluded process {name} running")
  if reasons:
    return "FAIL", reasons
  if span < min_seconds:
    return "INSUFFICIENT", [f"stable span {span:.1f}s < {min_seconds:.0f}s"]
  return "PASS", [f"{','.join(required)} stable {span:.1f}s, offroad, no restarts"]


def collect(seconds, interval):  # pragma: no cover - device only, read-only
  import time
  import openpilot.cereal.messaging as messaging
  from openpilot.common.params import Params
  sm, params, out = messaging.SubMaster(["managerState"]), Params(), []
  end = time.monotonic() + seconds
  while time.monotonic() < end:
    sm.update(int(interval * 1000))
    out.append({"t": time.monotonic(), "managerState_valid": sm.valid["managerState"] and sm.alive["managerState"],
                "offroad": params.get_bool("IsOffroad"),
                "processes": [{"name": p.name, "pid": p.pid, "running": p.running,
                               "shouldBeRunning": p.shouldBeRunning, "exitCode": p.exitCode}
                              for p in sm["managerState"].processes]})
  return out


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("samples", type=Path)
  ap.add_argument("--collect", type=float, metavar="SECONDS", help="read-only device sampling, then evaluate")
  ap.add_argument("--interval", type=float, default=2.0)
  ap.add_argument("--require", default=",".join(DEFAULT_REQUIRED))
  ap.add_argument("--forbid", default="", help="comma list, e.g. hardwared,pandad for flash-free bench mode")
  ap.add_argument("--min-seconds", type=float, default=60.0)
  a = ap.parse_args(argv)
  if a.collect:
    if a.samples.exists():
      print("BLOCKED: refuse overwriting samples"); return 2
    a.samples.write_text(json.dumps(collect(a.collect, a.interval)))
  verdict, reasons = evaluate(json.loads(a.samples.read_text()), tuple(filter(None, a.require.split(","))),
                              a.min_seconds, tuple(filter(None, a.forbid.split(","))))
  print(verdict + ":", "; ".join(reasons), "(process state only; not driving/hardware/road validation)")
  return {"PASS": 0, "FAIL": 1}.get(verdict, 2)


if __name__ == "__main__":
  sys.exit(main())
