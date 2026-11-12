#!/usr/bin/env python3
"""bogpilot_mapd: installs + keeps the pinned mapd running and feeds it GPS.

Activation (ACTIVATION_POLICY, port-like-0.9.7 policy):
  "default_on" (default): the process exists when the Speed Limit Controller is on (registry default ON, as in 0.9.7)
      AND at least one valid region is selected (the user's own Map Data choice). It then installs the pinned,
      sha256-verified mapd v1.12.0 if missing (0.9.7 downloaded "latest" without any check and ran it) and runs it.
      No region selected -> no process, no download, no network. Saved selections are honoured, never rewritten.
  "adoption": the earlier stock-equivalent mode: additionally requires the Phase3MapDataEnabled marker.
A binary is executed only after verify_installed() (hash + size + aarch64 ELF); a failed install retries with backoff and
never launches anything.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from openpilot.system.bogpilot.osm import installer, regions
from openpilot.system.bogpilot.osm.gps_feed import GpsFeed
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage

ADOPTION_MARKER = "Phase3MapDataEnabled"
ACTIVATION_POLICY = "default_on"
RESTART_BACKOFF_S = (2.0, 5.0, 15.0, 60.0)
INSTALL_RETRY_S = 60.0         # 0.9.7 mapd.py: `while not update_mapd(): time.sleep(60)`


def adopted(store) -> bool:
  """File-store marker; unreadable/absent -> False."""
  try:
    from openpilot.common import bogpilot_store as _bs
    return _bs.parse_bool(_bs.read_text(ADOPTION_MARKER), False)
  except Exception:
    return False


def wanted(selection_text, marker_adopted: bool, storage: OsmStorage, manifest: dict | None = None, cached: bool = False,
           require_binary: bool = True) -> bool:
  """marker_adopted = the policy's activation (marker under "adoption", SLC-on under "default_on")."""
  if not marker_adopted:
    return False
  if regions.parse_selection(selection_text).is_empty():
    return False
  if not require_binary:
    return True
  try:
    return installer.verify_installed(storage, manifest or installer.load_manifest(), cached=cached)
  except Exception:
    return False


def slc_enabled(params) -> bool:
  """Speed Limit Controller toggle (registry default ON, 0.9.7). Any read problem -> False (fail closed)."""
  try:
    from openpilot.common.bogpilot_store import ParamStore
    return bool(ParamStore(params).get_bool("SpeedLimitController"))
  except Exception:
    return False


def activated(params) -> bool:
  if ACTIVATION_POLICY == "default_on":
    return slc_enabled(params)
  return adopted(None)


def manager_condition(started, params, CP) -> bool:
  """process_config predicate (called every manager tick, cheap: one Params read + one file read for the cached check).
  default_on: SLC on + a region selected (the supervisor installs the pinned binary itself). adoption: marker + verified."""
  try:
    sel = params.get("MapsSelected")
    if ACTIVATION_POLICY == "default_on":
      return wanted(sel, slc_enabled(params), OsmStorage(), require_binary=False)
    return wanted(sel, adopted(None), OsmStorage(), cached=True)
  except Exception:
    return False


def backoff(n: int) -> float:
  return RESTART_BACKOFF_S[min(n, len(RESTART_BACKOFF_S) - 1)]


GPS_SERVICES = ("gpsLocation", "gpsLocationExternal")    # qcomgpsd (C3X) / ubloxd


def feed_step(sm, feed: GpsFeed, now: float) -> None:
  """One gps -> LastGPSPosition step. sm is a SubMaster-like (updated/valid/[]); whichever receiver publishes is used."""
  for svc in GPS_SERVICES:
    try:
      if sm.updated[svc] and sm.valid[svc]:
        g = sm[svc]
        feed.update(now, g.latitude, g.longitude, g.hasFix, g.horizontalAccuracy, g.speed, g.bearingDeg)
    except Exception:
      pass
  feed.tick(now)


def run(storage: OsmStorage | None = None, mem: MemParams | None = None, popen=subprocess.Popen, sm=None,
        sleep=time.sleep, monotonic=time.monotonic, max_ticks: int | None = None, fetch=None) -> dict:
  """Supervise mapd + GPS feed. Returns counters (launches, installs, ticks) for tests; loops forever in production."""
  storage = storage or OsmStorage()
  mem = mem or MemParams()
  manifest = installer.load_manifest()
  fetch = fetch or installer.urllib_fetch
  feed = GpsFeed(mem)
  proc, launches, installs, ticks, next_start, next_install = None, 0, 0, 0, 0.0, 0.0
  while max_ticks is None or ticks < max_ticks:
    ticks += 1
    now = monotonic()
    if sm is not None:
      sm.update(100)                         # blocks up to 100 ms on the GPS poll service (no busy loop)
      feed_step(sm, feed, now)
    if proc is None or proc.poll() is not None:
      if now >= next_start:
        if not installer.verify_installed(storage, manifest):
          # never execute an unverified binary: (re)install the pinned one, retry later on any failure
          if now >= next_install:
            next_install = now + INSTALL_RETRY_S
            installs += 1
            try:
              installer.install(storage, manifest, fetch)
            except Exception:
              pass
          if sm is None:
            sleep(0.1)
          continue
        mem.root.mkdir(parents=True, exist_ok=True)
        mem.put("MapdLogLevel", "disabled")
        proc = popen([str(storage.mapd_path)], cwd=str(storage.root))  # mapd v1.12.0 writes ./offline and tmp/ relative to its cwd
        launches += 1
        next_start = now + backoff(launches - 1)
    if sm is None:
      sleep(0.1)
  if proc is not None and proc.poll() is None:
    proc.terminate()
  return {"launches": launches, "installs": installs, "ticks": ticks}


def main():  # pragma: no cover - process entry
  from cereal import messaging
  run(sm=messaging.SubMaster(list(GPS_SERVICES), poll=GPS_SERVICES[0]))


if __name__ == "__main__":
  main()
