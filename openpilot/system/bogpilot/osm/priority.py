"""CPU / IO priority for the mapd downloader, so a download never competes with controls, logging or the encoders.

mapd is a Go program: many threads, and on Linux nice and ioprio are per thread. So mapd starts with a low priority that
every thread inherits (preexec: nice BASE_NICE, IO best-effort lowest), and while a download runs every thread under
/proc/<pid>/task is moved to DOWNLOAD_NICE. openpilot's controls, planner, camera and logging processes run with
realtime or higher priorities, so a nice 19 SCHED_OTHER thread only gets CPU they leave idle. IO stays best-effort level 7
(not the idle class: loggerd writes to /data all the time while driving, and the idle class could starve the unpack).
Every call fails quietly: priority is best effort and must never stop mapd.

Onroad, download work also stays off the driving cores (MAP_CORES). Read from the 0.11.2 sources
(config_realtime_process / set_core_affinity): core 3 pandad (SCHED_FIFO 54) and encoderd (FIFO 52), core 4 card, controlsd
and selfdrived, core 5 the UI, core 6 camerad, core 7 modeld (FIFO 54), plannerd, radard and dmonitoringmodeld. Cores 0-3
carry loggerd and the locationd family (paramsd, lagd, torqued, calibrationd, dmonitoringd at FIFO 5) and core 1 sensord, all
of which preempt a nice 19 SCHED_OTHER thread. MAP_CORES is 0-2, the same set the screen recorder uses, so the panda and
encoder core 3 is left alone too. Not the idle classes: SCHED_IDLE or IO idle could starve the fetch while it holds an ext4
journal handle, and loggerd's next fsync would then wait behind it.
"""
from __future__ import annotations

import ctypes
import os
import platform

BASE_NICE = 10
DOWNLOAD_NICE = 19
MAP_CORES = (0, 1, 2)
DRIVING_CORES = frozenset({3, 4, 5, 6, 7})
ONROAD_RATE_BYTES_S = 5_000_000 // 8   # 5 Mbit/s while the car is on
ONROAD_MAX_FSYNC_HZ = 10.0             # at most 10 file fsyncs a second while the car is on
IOPRIO_CLASS_BE = 2
IO_LEVEL_LOWEST = 7
_IOPRIO_WHO_PROCESS = 1
_SYS_IOPRIO_SET = {"aarch64": 30, "arm64": 30, "x86_64": 251}


def ioprio_value(cls: int, level: int) -> int:
  return (cls << 13) | level


def set_ioprio(tid: int, cls: int = IOPRIO_CLASS_BE, level: int = IO_LEVEL_LOWEST) -> bool:
  nr = _SYS_IOPRIO_SET.get(platform.machine())
  if nr is None:
    return False
  try:
    libc = ctypes.CDLL(None, use_errno=True)
    return libc.syscall(nr, _IOPRIO_WHO_PROCESS, int(tid), ioprio_value(cls, level)) == 0
  except Exception:
    return False


def set_nice(tid: int, nice: int) -> bool:
  try:
    os.setpriority(os.PRIO_PROCESS, int(tid), int(nice))
    return True
  except (OSError, AttributeError):
    return False


def all_cores() -> tuple[int, ...]:
  try:
    return tuple(range(os.cpu_count() or 1))
  except Exception:
    return (0,)


def set_affinity(tid: int, cores) -> bool:
  try:
    os.sched_setaffinity(int(tid), set(int(c) for c in cores))
    return True
  except (OSError, AttributeError, ValueError):
    return False


def threads(pid: int) -> list[int]:
  try:
    return [int(t) for t in os.listdir(f"/proc/{int(pid)}/task")]
  except (OSError, ValueError):
    return [int(pid)]


def apply(pid: int, nice: int, cls: int = IOPRIO_CLASS_BE, level: int = IO_LEVEL_LOWEST, set_nice_fn=set_nice,
          set_io_fn=set_ioprio, threads_fn=threads, cores=None, set_affinity_fn=set_affinity) -> int:
  """Set nice + IO priority (and the cores, when given) on every thread of `pid`. Returns how many threads took the nice value."""
  ok = 0
  for tid in threads_fn(pid):
    ok += bool(set_nice_fn(tid, nice))
    set_io_fn(tid, cls, level)
    if cores is not None:
      set_affinity_fn(tid, cores)
  return ok


def place_self(onroad: bool, set_nice_fn=set_nice, set_affinity_fn=set_affinity) -> None:
  """The calling (single threaded) fetch process: nice 19 on MAP_CORES while the car is on, nice BASE_NICE on every core off."""
  set_nice_fn(0, DOWNLOAD_NICE if onroad else BASE_NICE)
  set_affinity_fn(0, MAP_CORES if onroad else all_cores())


def preexec_low_priority() -> None:  # pragma: no cover - runs in the child between fork and exec
  try:
    os.nice(BASE_NICE)
  except OSError:
    pass
  set_ioprio(0)
