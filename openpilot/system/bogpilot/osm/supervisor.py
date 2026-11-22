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
from openpilot.system.bogpilot.osm.downloads import DownloadController
from openpilot.system.bogpilot.osm.gps_feed import GpsFeed
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage

ADOPTION_MARKER = "Phase3MapDataEnabled"
ACTIVATION_POLICY = "default_on"
RESTART_BACKOFF_S = (2.0, 5.0, 15.0, 60.0)
INSTALL_RETRY_S = 60.0         # 0.9.7 mapd.py: `while not update_mapd(): time.sleep(60)`
SCHEDULE_TICK_S = 60.0


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


ENGINE_POLL_S = 2.0          # how often the MapdV2 toggle is re-read (switching engines takes effect within this)
HEARTBEAT_S = 2.0            # BogPilotMapdHeartbeat refresh: the Map Data page tells a stopped downloader from a busy one
CRASH_RETRY_S = 5.0          # main(): run() raised; run it again after this (the manager never restarts a dead process)


def run(storage: OsmStorage | None = None, mem: MemParams | None = None, popen=subprocess.Popen, sm=None,
        sleep=time.sleep, monotonic=time.monotonic, max_ticks: int | None = None, fetch=None, scheduler=None,
        resumer=None, prioritize=None, preexec=None, engine=None, fetcher_factory=None, write_settings=None) -> dict:
  """Supervise mapd + GPS feed. Returns counters (launches, installs, ticks, restarts) for tests; loops forever in production.

  Map downloads run whether the car is parked or driving (pick a state at a charger, the download continues on the
  road over the hotspot). They are kept out of the way instead:
  scheduler: optional object with tick() (scheduler.UpdateScheduler): the "Automatically Update Maps" consumer, asked once a minute.
  resumer: optional resume.Resumer, stepped once a second: fills the cells a download missed, and returns "stalled" /
    "no_space" when mapd has to be restarted (a hung download, or free space under the floor).
  prioritize: optional callable(pid, downloading) that sets mapd's CPU / IO priority (priority.apply), called when the
    download state changes. preexec: popen preexec_fn (priority.preexec_low_priority in production).
  engine: optional callable -> bool, True = mapd v2 (param MapdV2, re-read every ENGINE_POLL_S). None = always v1.
    v2: the pinned v2 binary (osm/mapd_v2) runs with BogPilot's MapdSettings (mapd_v2.write_settings) and is never stopped
    for a download: the resumer gets fetcher_factory() (a resume.FetchProcess) and fetches cells out of process, and a
    stalled / no-space download only stops that fetch. Switching engines stops the running mapd and starts the other."""
  storage = storage or OsmStorage()
  mem = mem or MemParams()
  v2 = False
  if engine is not None:
    try:
      v2 = bool(engine())
    except Exception:
      v2 = False
  manifest = installer.load_engine_manifest(v2)
  next_engine = 0.0
  fetch = fetch or installer.urllib_fetch
  feed = GpsFeed(mem)
  proc, launches, installs, ticks, next_start, next_install, next_schedule = None, 0, 0, 0, 0.0, 0.0, 0.0
  restarts, next_resume, downloading, next_beat = 0, 0.0, None, 0.0
  dl = DownloadController(mem, storage)

  def set_fetcher(on):
    if resumer is None:
      return
    cur = getattr(resumer, "fetcher", None)
    if on and cur is None and fetcher_factory is not None:
      resumer.fetcher = fetcher_factory()
    elif not on and cur is not None:
      cur.stop()
      resumer.fetcher = None
  try:
    set_fetcher(v2)
    while max_ticks is None or ticks < max_ticks:
      ticks += 1
      now = monotonic()
      if now >= next_beat:
        next_beat = now + HEARTBEAT_S
        mem.put("BogPilotMapdHeartbeat", "1")     # the Map Data page reads the file age (MemParams.age_s), not the value
      if engine is not None and now >= next_engine:
        next_engine = now + ENGINE_POLL_S
        try:
          want = bool(engine())
        except Exception:
          want = False                         # unreadable toggle: the existing engine (v1)
        if want != v2:
          v2 = want
          manifest = installer.load_engine_manifest(v2)
          set_fetcher(v2)
          if proc is not None and proc.poll() is None:
            proc.terminate()                   # switch engines: the other binary starts right away
            try:
              proc.wait(timeout=5)
            except Exception:
              try:
                proc.kill()
              except Exception:
                pass
          proc, next_start, next_install, downloading = None, 0.0, 0.0, None
      if sm is not None:
        sm.update(100)                         # blocks up to 100 ms on the GPS poll service (no busy loop)
        feed_step(sm, feed, now)
      if scheduler is not None and now >= next_schedule:
        next_schedule = now + SCHEDULE_TICK_S
        try:
          scheduler.tick()
        except Exception:
          pass                                 # a scheduling problem must never stop mapd or the GPS feed
      if resumer is not None and now >= next_resume:
        next_resume = now + 1.0
        try:
          r = resumer.step()
        except Exception:
          r = "error"
        if r in ("stalled", "no_space") and not v2 and proc is not None and proc.poll() is None:
          proc.terminate()                     # mapd v1.12.0 has no cancel and no HTTP timeout: restart it without the request
          restarts += 1
        if prioritize is not None and not v2 and proc is not None and proc.poll() is None:
          try:
            busy = dl.progress().active
            if busy != downloading:
              downloading = busy
              prioritize(proc.pid, busy)
          except Exception:
            pass
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
          kw = {"preexec_fn": preexec} if (preexec is not None and not v2) else {}   # v2 never downloads: normal priority
          if v2:
            from openpilot.system.bogpilot.osm.mapd_v2 import launch_env
            kw["env"] = launch_env()           # openpilot msgq paths (/dev/shm/msgq_*) even before logmessaged is up
          if v2 and write_settings is not None:
            try:
              write_settings()                 # every mapd control off, BogPilot decides (mapd_v2.settings_json)
            except Exception:
              pass
          # mapd v1.12.0 writes ./offline and tmp/ relative to its cwd; v2 uses /data/media/0/osm, the same directory
          proc = popen([str(installer.binary_path(storage, manifest))], cwd=str(storage.root), **kw)
          downloading = None
          launches += 1
          next_start = now + backoff(launches - 1)
      if sm is None:
        sleep(0.1)
  finally:
    # also on an exception: never leave an orphan mapd / fetch behind (main() runs run() again)
    if proc is not None and proc.poll() is None:
      proc.terminate()
    f = getattr(resumer, "fetcher", None)
    if f is not None:
      try:
        f.stop()
      except Exception:
        pass
    g = getattr(resumer, "_gap", None)
    if g is not None:
      try:
        g.stop()
      except Exception:
        pass
    mem.remove("BogPilotMapdHeartbeat")
  return {"launches": launches, "installs": installs, "ticks": ticks, "restarts": restarts}


def main():  # pragma: no cover - process entry
  from openpilot.cereal import messaging
  from openpilot.common.bogpilot_store import ParamStore
  from openpilot.system.bogpilot.osm import priority
  from openpilot.system.bogpilot.osm.resume import Resumer
  from openpilot.system.bogpilot.osm.scheduler import UpdateScheduler
  from openpilot.system.bogpilot.osm.map_data_controller import downloads_allowed
  storage, mem = OsmStorage(), MemParams()
  store = ParamStore()

  def prioritize(pid, downloading):
    priority.apply(pid, priority.DOWNLOAD_NICE if downloading else priority.BASE_NICE)

  from openpilot.system.bogpilot.osm import mapd_v2
  from openpilot.system.bogpilot.osm.resume import FetchProcess
  sm = messaging.SubMaster(list(GPS_SERVICES), poll=GPS_SERVICES[0])
  while True:
    # The manager never restarts a process that died (process.py start() returns while proc is set), so one exception here
    # used to leave Map Data on "Waiting for the map downloader..." until a reboot. Log it and run again instead.
    try:
      run(storage=storage, mem=mem, sm=sm,
          scheduler=UpdateScheduler(store, mem=mem, storage=storage),
          resumer=Resumer(mem, storage, allowed=lambda: downloads_allowed(store),
                          gap_fetcher=FetchProcess(storage, preexec=priority.preexec_low_priority)),
          prioritize=prioritize, preexec=priority.preexec_low_priority,
          engine=lambda: mapd_v2.engine_v2(store),
          fetcher_factory=lambda: FetchProcess(storage, preexec=priority.preexec_low_priority),
          write_settings=mapd_v2.write_settings)
    except Exception:
      try:
        from openpilot.common.swaglog import cloudlog
        cloudlog.exception("bogpilot_mapd: supervisor loop failed, restarting")
      except Exception:
        pass
      time.sleep(CRASH_RETRY_S)


if __name__ == "__main__":
  main()
