"""Read-only BogPilot sidebar readings from genuine deviceState telemetry.

Display semantics come from 568fea Sidebar: maxTempC (owner Fahrenheit units),
mean CPU load and RAM usage with 70/85 percent warning/danger thresholds.
Missing/stale/malformed telemetry is unavailable, never an invented zero.

The two metric slots follow 0.9.7: the chip slot shows CPU or GPU, the memory slot shows RAM, storage left or storage
used (one at a time, the first enabled in that order).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Reading:
  value: str = "--"
  level: str = "unknown"


def _number(value: Any, lower: float, upper: float) -> float:
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    raise ValueError("invalid telemetry")
  number = float(value)
  if not math.isfinite(number) or not lower <= number <= upper:
    raise ValueError("invalid telemetry")
  return number


def _usage(value: float) -> Reading:
  return Reading(f"{int(value)}%", "danger" if value >= 85 else "warning" if value >= 70 else "good")


def device_readings(device_state: Any, *, fresh: bool, fahrenheit: bool = False) -> tuple[Reading, Reading, Reading]:
  if not fresh or device_state is None:
    return Reading(), Reading(), Reading()
  temp = cpu = ram = Reading()
  try:
    celsius = int(_number(device_state.maxTempC, -40, 150))
    thermal = device_state.thermalStatus
    severity = getattr(thermal, "raw", thermal)
    # Retain CURRENT upstream thermal alarm coloring: anything other than ok is danger.
    if type(severity) is not int or severity not in (0, 1, 2):
      raise ValueError("invalid thermal status")
    number = int(celsius * 9 / 5) + 32 if fahrenheit else celsius
    temp = Reading(f"{number}°{'F' if fahrenheit else 'C'}", "good" if severity == 0 else "danger")
  except (AttributeError, ValueError, TypeError, OverflowError):
    pass
  try:
    loads = [_number(v, 0, 100) for v in device_state.cpuUsagePercent]
    if loads:
      cpu = _usage(sum(loads) / len(loads))
  except (AttributeError, ValueError, TypeError, OverflowError):
    pass
  try:
    ram = _usage(_number(device_state.memoryUsagePercent, 0, 100))
  except (AttributeError, ValueError, TypeError, OverflowError):
    pass
  return temp, cpu, ram


# --- visualsTheme: visibility gates for ShowCPU / ShowMemoryUsage / NumericalTemp ---
def metric_visibility_from_params(params) -> "tuple[bool, bool, bool, bool]":
  """(show_cpu, show_memory, numerical_temp, fahrenheit) from a Params-like object.

  Defaults match shipping registry (CPU/RAM/NumericalTemp ON, Fahrenheit OFF) so a
  missing key preserves prior on-screen behaviour.
  """
  def b(key: str, default: bool) -> bool:
    try:
      if hasattr(params, "get_bool"):
        v = params.get_bool(key)
        if v is None:
          return default
        return bool(v)
    except Exception:
      pass
    try:
      raw = params.get(key) if hasattr(params, "get") else None
    except Exception:
      raw = None
    if raw is None:
      return default
    if isinstance(raw, bool):
      return raw
    if isinstance(raw, (bytes, bytearray)):
      raw = raw.decode("utf-8", "replace")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")

  return b("ShowCPU", True), b("ShowMemoryUsage", True), b("NumericalTemp", True), b("Fahrenheit", False)


# --- Sidebar slots: CPU / GPU and memory / storage left / storage used ---
CHIP_KEYS = ("ShowCPU", "ShowGPU")
MEMORY_KEYS = ("ShowMemoryUsage", "ShowStorageLeft", "ShowStorageUsed")


def _truthy(raw) -> bool:
  if isinstance(raw, bool):
    return raw
  if isinstance(raw, (bytes, bytearray)):
    raw = raw.decode("utf-8", "replace")
  return raw is not None and str(raw).strip().lower() in ("1", "true", "yes", "on")


def slot_flags(read_bool, read_raw=None) -> dict:
  """Stored choice per slot key. ShowGPU registers ON by default next to ShowCPU, so GPU counts only when it was
  explicitly stored (read_raw returns None for an unset key); otherwise CPU keeps the slot, as it always has."""
  flags = {k: bool(read_bool(k)) for k in (*CHIP_KEYS, *MEMORY_KEYS)}
  if read_raw is not None:
    try:
      flags["ShowGPU"] = _truthy(read_raw("ShowGPU"))
    except Exception:
      flags["ShowGPU"] = False
  return flags


def slot_choices(flags: dict) -> tuple:
  """(chip, memory): chip is 'cpu' or 'gpu'; memory is 'memory', 'storage_left' or 'storage_used'.

  A tap on a box cycles its contents (0.9.7 sidebar) and there is no empty step, so a slot that an older build saved as off
  (or that has nothing stored) shows its default, CPU and RAM, rather than vanishing with nothing left to tap."""
  chip = "cpu" if flags.get("ShowCPU") or not flags.get("ShowGPU") else "gpu"
  memory = ("storage_left" if flags.get("ShowStorageLeft") and not flags.get("ShowMemoryUsage")
            else "storage_used" if flags.get("ShowStorageUsed") and not flags.get("ShowMemoryUsage") else "memory")
  return chip, memory


# --- tap-to-cycle (0.9.7 sidebar.cc:75-120): each tap on a metric box moves that slot to its next content ---
CHIP_CYCLE = ("cpu", "gpu")
MEMORY_CYCLE = ("memory", "storage_left", "storage_used")
TEMP_CYCLE = ("status", "celsius", "fahrenheit")


def _next(cycle: tuple, current) -> str:
  return cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else cycle[0]


def chip_writes(choice: str) -> dict:
  """Param values that make `choice` ('cpu' or 'gpu') the chip slot. ShowGPU is stored explicitly (unset means CPU)."""
  return {"ShowCPU": choice == "cpu", "ShowGPU": choice == "gpu"}


def memory_writes(choice: str) -> dict:
  return {"ShowMemoryUsage": choice == "memory", "ShowStorageLeft": choice == "storage_left",
          "ShowStorageUsed": choice == "storage_used"}


def temp_mode(numerical: bool, fahrenheit: bool) -> str:
  return "status" if not numerical else "fahrenheit" if fahrenheit else "celsius"


def temp_writes(mode: str) -> dict:
  return {"NumericalTemp": mode != "status", "Fahrenheit": mode == "fahrenheit"}


def cycle_chip(chip: str) -> dict:
  return chip_writes(_next(CHIP_CYCLE, chip))


def cycle_memory(memory: str) -> dict:
  return memory_writes(_next(MEMORY_CYCLE, memory))


def cycle_temp(mode: str) -> dict:
  return temp_writes(_next(TEMP_CYCLE, mode))


def slot_flags_from_params(params) -> dict:
  def read_bool(key):
    try:
      v = params.get_bool(key)
    except Exception:
      return False
    return bool(v)

  def read_raw(key):
    return params.get(key) if hasattr(params, "get") else read_bool(key)

  return slot_flags(read_bool, read_raw)


def chip_reading(device_state, which: str, *, fresh: bool) -> Reading:
  """CPU (mean per-core load) or GPU usage; unavailable on stale / malformed data."""
  if not fresh or device_state is None:
    return Reading()
  try:
    if which == "gpu":
      return _usage(_number(device_state.gpuUsagePercent, 0, 100))
    loads = [_number(v, 0, 100) for v in device_state.cpuUsagePercent]
    return _usage(sum(loads) / len(loads)) if loads else Reading()
  except (AttributeError, ValueError, TypeError, OverflowError):
    return Reading()


def storage_reading(device_state, which: str, usage, *, fresh: bool) -> Reading:
  """Storage left / used in GB for /data. `usage` is (free_gb, used_gb) or None. Colour follows the free-space
  percent from deviceState (warning under 25 percent, danger under 10), as 0.9.7 did."""
  if not fresh or device_state is None or usage is None:
    return Reading()
  try:
    free_percent = _number(device_state.freeSpacePercent, 0, 100)
    gb = usage[0] if which == "storage_left" else usage[1]
    gb = int(_number(gb, 0, 1e9))
  except (AttributeError, ValueError, TypeError, OverflowError, IndexError):
    return Reading()
  return Reading(f"{gb} GB", "danger" if free_percent < 10 else "warning" if free_percent < 25 else "good")


def data_usage_gb(path: str = "/data"):
  """(free_gb, used_gb) from statvfs, or None when it cannot be read."""
  import os
  try:
    st = os.statvfs(path)
  except OSError:
    return None
  return (st.f_bavail * st.f_frsize / 1e9, (st.f_blocks - st.f_bfree) * st.f_frsize / 1e9)


# --- Wi-Fi address (ShowIP) ---
def wifi_ipv4(ifname: str = "wlan0") -> str:
  """IPv4 address of the Wi-Fi interface, or "" when it has none or cannot be read. A local ioctl: sends nothing."""
  try:
    import fcntl
    import socket
    import struct
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
      packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", ifname[:15].encode()))[20:24]   # SIOCGIFADDR
    return socket.inet_ntoa(packed)
  except (OSError, ImportError, ValueError):
    return ""


class IpReader:
  """Cached (5 s) address read, so the sidebar never makes a system call every frame."""

  def __init__(self, read=wifi_ipv4, clock=None, ttl: float = 5.0):
    import time
    self._read, self.clock, self.ttl = read, clock or time.monotonic, ttl
    self._next = -1.0
    self._value = ""

  def get(self) -> str:
    now = self.clock()
    if now >= self._next:
      self._next = now + self.ttl
      try:
        self._value = str(self._read() or "")
      except Exception:
        self._value = ""
    return self._value
