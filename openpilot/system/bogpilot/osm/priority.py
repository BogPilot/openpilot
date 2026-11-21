"""CPU / IO priority for the mapd downloader, so a download never competes with controls, logging or the encoders.

mapd is a Go program: many threads, and on Linux nice and ioprio are per thread. So mapd starts with a low priority that
every thread inherits (preexec: nice BASE_NICE, IO best-effort lowest), and while a download runs every thread under
/proc/<pid>/task is moved to DOWNLOAD_NICE. openpilot's controls, planner, camera and logging processes run with
realtime or higher priorities, so a nice 19 SCHED_OTHER thread only gets CPU they leave idle. IO stays best-effort level 7
(not the idle class: loggerd writes to /data all the time while driving, and the idle class could starve the unpack).
Every call fails quietly: priority is best effort and must never stop mapd.
"""
from __future__ import annotations

import ctypes
import os
import platform

BASE_NICE = 10
DOWNLOAD_NICE = 19
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


def threads(pid: int) -> list[int]:
  try:
    return [int(t) for t in os.listdir(f"/proc/{int(pid)}/task")]
  except (OSError, ValueError):
    return [int(pid)]


def apply(pid: int, nice: int, cls: int = IOPRIO_CLASS_BE, level: int = IO_LEVEL_LOWEST, set_nice_fn=set_nice,
          set_io_fn=set_ioprio, threads_fn=threads) -> int:
  """Set nice + IO priority on every thread of `pid`. Returns how many threads took the nice value."""
  ok = 0
  for tid in threads_fn(pid):
    ok += bool(set_nice_fn(tid, nice))
    set_io_fn(tid, cls, level)
  return ok


def preexec_low_priority() -> None:  # pragma: no cover - runs in the child between fork and exec
  try:
    os.nice(BASE_NICE)
  except OSError:
    pass
  set_ioprio(0)
