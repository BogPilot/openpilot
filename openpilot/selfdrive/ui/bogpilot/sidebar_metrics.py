"""Read-only BogPilot sidebar readings from genuine deviceState telemetry.

Display semantics come from 568fea Sidebar: maxTempC (the user's Fahrenheit units),
mean CPU load and RAM usage with 70/85 percent warning/danger thresholds.
Missing/stale/malformed telemetry is unavailable, never an invented zero.

The two metric slots follow 0.9.7: the chip slot shows CPU or GPU, the memory slot shows RAM, storage left or storage
used (one at a time, the first enabled in that order).

The upper box is Temp (status / the one unit set by Metric Units: °C when metric, °F when not) by default and can show Power instead (SidebarUpperSlot, a file choice saved
by tapping it). Power is read from /sys/class/hwmon/hwmon1/power1_input (microwatts / 1e6, displayed as ``%.2f W``),
with a fallback existence scan of hwmon*/power1_input when that path is missing or unreadable. A missing or unreadable
file shows "--". The same choice applies offroad and onroad. Power is opt-in; a missing file keeps the current temp mode.

Onroad the chip slot is replaced by the vehicle status box. That box can show CPU, then GPU, instead (SidebarVehicleSlot, a file
choice saved by tapping it): the same CPU reading and colours as the offroad CPU box. Vehicle status is the default, and
it always comes back while the panda is not seen ("NO PANDA"), whatever was chosen.
"""
from __future__ import annotations

import math
import time
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

  Defaults match shipping registry (CPU/RAM/NumericalTemp ON). The temperature unit follows the Metric Units toggle
  (IsMetric): fahrenheit is True only when metric is off. The older Fahrenheit param is kept stored but no longer read.
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

  return b("ShowCPU", True), b("ShowMemoryUsage", True), b("NumericalTemp", True), not b("IsMetric", False)


# --- Sidebar slots: CPU / GPU and memory / storage left / storage used ---
CHIP_KEYS = ("ShowCPU", "ShowGPU")
# The MODELD chip is a third content of the chip slot. It has no Params key (a new key needs a native rebuild), so it is a file
# choice like the vehicle slot: "modeld" selects it, anything else (or no file) leaves ShowCPU / ShowGPU in charge, so saved
# values from older builds behave exactly as before.
CHIP_FILE_KEY = "SidebarChipSlot"
MEMORY_KEYS = ("ShowMemoryUsage", "ShowStorageLeft", "ShowStorageUsed")


def _truthy(raw) -> bool:
  if isinstance(raw, bool):
    return raw
  if isinstance(raw, (bytes, bytearray)):
    raw = raw.decode("utf-8", "replace")
  return raw is not None and str(raw).strip().lower() in ("1", "true", "yes", "on")


def slot_flags(read_bool, read_raw=None, read_file=None) -> dict:
  """Stored choice per slot key. ShowGPU registers ON by default next to ShowCPU, so GPU counts only when it was
  explicitly stored (read_raw returns None for an unset key); otherwise CPU keeps the slot, as it always has."""
  flags = {k: bool(read_bool(k)) for k in (*CHIP_KEYS, *MEMORY_KEYS)}
  if read_raw is not None:
    try:
      flags["ShowGPU"] = _truthy(read_raw("ShowGPU"))
    except Exception:
      flags["ShowGPU"] = False
  flags["ModeldChip"] = False
  if read_file is not None:
    try:
      flags["ModeldChip"] = read_file(CHIP_FILE_KEY) == "modeld"
    except Exception:
      pass
  return flags


def slot_choices(flags: dict) -> tuple:
  """(chip, memory): chip is 'cpu', 'gpu' or 'modeld'; memory is 'memory', 'storage_left' or 'storage_used'.

  A tap on a box cycles its contents (0.9.7 sidebar) and there is no empty step, so a slot that an older build saved as off
  (or that has nothing stored) shows its default, CPU and RAM, rather than vanishing with nothing left to tap."""
  chip = "cpu" if flags.get("ShowCPU") or not flags.get("ShowGPU") else "gpu"
  if flags.get("ModeldChip"):
    chip = "modeld"
  memory = ("storage_left" if flags.get("ShowStorageLeft") and not flags.get("ShowMemoryUsage")
            else "storage_used" if flags.get("ShowStorageUsed") and not flags.get("ShowMemoryUsage") else "memory")
  return chip, memory


# --- tap-to-cycle (0.9.7 sidebar.cc:75-120): each tap on a metric box moves that slot to its next content ---
CHIP_CYCLE = ("cpu", "gpu", "modeld")
MEMORY_CYCLE = ("memory", "storage_left", "storage_used")
TEMP_UNITS = ("celsius", "fahrenheit")


def unit_mode(fahrenheit: bool) -> str:
  """The one temperature unit shown: Celsius when Metric Units is on, Fahrenheit when it is off."""
  return "fahrenheit" if fahrenheit else "celsius"


def temp_cycle(fahrenheit: bool) -> tuple:
  return ("status", unit_mode(fahrenheit))


def fahrenheit_from_metric() -> bool:
  """True when Metric Units is off. Unreadable: Fahrenheit (the IsMetric default is off)."""
  try:
    from openpilot.common.params import Params
    return not Params().get_bool("IsMetric")
  except Exception:
    return True


def _next(cycle: tuple, current) -> str:
  return cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else cycle[0]


def chip_writes(choice: str) -> dict:
  """Param values that make `choice` ('cpu' or 'gpu') the chip slot. ShowGPU is stored explicitly (unset means CPU).
  'modeld' clears both; the file choice (write_chip_file) is what selects it."""
  return {"ShowCPU": choice == "cpu", "ShowGPU": choice == "gpu"}


def next_chip(chip: str) -> str:
  return _next(CHIP_CYCLE, chip)


def chip_file_value(choice: str) -> str:
  return "modeld" if choice == "modeld" else "auto"


def read_chip_file() -> str:
  try:
    from openpilot.common.bogpilot_toggles import read_choice
    return read_choice(CHIP_FILE_KEY)
  except Exception:
    return "auto"


def write_chip_file(choice: str) -> bool:
  """Save whether the chip slot shows MODELD ("modeld") or follows ShowCPU / ShowGPU ("auto")."""
  try:
    from openpilot.common.bogpilot_toggles import write_choice
    write_choice(CHIP_FILE_KEY, chip_file_value(choice))
    return True
  except Exception:
    return False


def memory_writes(choice: str) -> dict:
  return {"ShowMemoryUsage": choice == "memory", "ShowStorageLeft": choice == "storage_left",
          "ShowStorageUsed": choice == "storage_used"}


def temp_mode(numerical: bool, fahrenheit: bool) -> str:
  return "status" if not numerical else "fahrenheit" if fahrenheit else "celsius"


def temp_writes(mode: str) -> dict:
  """Only NumericalTemp is stored; the unit comes from Metric Units, and the old Fahrenheit param is left untouched."""
  return {"NumericalTemp": mode != "status"}


def cycle_chip(chip: str) -> dict:
  return chip_writes(_next(CHIP_CYCLE, chip))


def cycle_memory(memory: str) -> dict:
  return memory_writes(_next(MEMORY_CYCLE, memory))


def cycle_temp(mode: str, fahrenheit: "bool | None" = None) -> dict:
  if fahrenheit is None:
    fahrenheit = fahrenheit_from_metric()
  cycle = temp_cycle(fahrenheit)
  return temp_writes(_next(cycle, cycle[1] if mode in TEMP_UNITS else mode))


# --- onroad middle box: vehicle status or CPU (SidebarVehicleSlot) ---
VEHICLE_SLOT_KEY = "SidebarVehicleSlot"
VEHICLE_CYCLE = ("vehicle", "cpu", "gpu", "modeld")


def vehicle_slot_choice(text) -> str:
  """'cpu', 'gpu' or 'modeld' only when exactly that is stored; anything else (nothing stored, junk, unreadable) is the vehicle status."""
  if isinstance(text, (bytes, bytearray)):
    text = text.decode("utf-8", "replace")
  return text.strip() if isinstance(text, str) and text.strip() in ("cpu", "gpu", "modeld") else "vehicle"


def vehicle_slot_shown(choice: str, panda_seen: bool) -> str:
  """What the onroad middle box shows: CPU or GPU only when chosen AND the panda is seen. A missing panda is a warning the
  driver must not lose, so "NO PANDA" always takes the box back."""
  return choice if choice in ("cpu", "gpu", "modeld") and panda_seen else "vehicle"


def cycle_vehicle_slot(choice: str) -> str:
  return _next(VEHICLE_CYCLE, choice)


def read_vehicle_slot() -> str:
  try:
    from openpilot.common.bogpilot_toggles import read_choice
    return vehicle_slot_choice(read_choice(VEHICLE_SLOT_KEY))
  except Exception:
    return "vehicle"


def write_vehicle_slot(choice: str) -> bool:
  try:
    from openpilot.common.bogpilot_toggles import write_choice
    write_choice(VEHICLE_SLOT_KEY, choice)
    return True
  except Exception:
    return False


# --- upper box: temp modes or Power (SidebarUpperSlot); the same choice offroad and onroad ---
UPPER_SLOT_KEY = "SidebarUpperSlot"
UPPER_STORED = ("status", "celsius", "fahrenheit", "power")   # values an older save may hold; the unit now follows Metric Units


def upper_cycle(fahrenheit: bool) -> tuple:
  """status -> the one unit chosen by Metric Units -> power -> status."""
  return (*temp_cycle(fahrenheit), "power")


POWER_PATH = "/sys/class/hwmon/hwmon1/power1_input"
POWER_SCAN_GLOB = "/sys/class/hwmon/hwmon*/power1_input"
_POWER_CACHE: list = [None]


def clear_power_path_cache() -> None:
  _POWER_CACHE[0] = None


def _power_text(raw) -> Reading:
  if isinstance(raw, (bytes, bytearray)):
    raw = raw.decode("utf-8", "replace")
  if not isinstance(raw, str):
    return Reading()
  text = raw.strip()
  if not text:
    return Reading()
  try:
    microwatts = int(text, 10)
  except ValueError:
    return Reading()
  if microwatts < 0:
    return Reading()
  try:
    watts = microwatts / 1e6
  except OverflowError:
    return Reading()
  if not math.isfinite(watts):
    return Reading()
  return Reading(f"{watts:.2f} W", "good")


def _open_power_file(path: str, read):
  if read is not None:
    return read(path)
  with open(path, encoding="utf-8") as f:
    return f.read()


def _try_power_path(path: str, read) -> Reading | None:
  """A Reading if the path could be opened (including a '--' parse), or None if it could not."""
  try:
    raw = _open_power_file(path, read)
  except (OSError, TypeError, ValueError):
    return None
  return _power_text(raw)


def _scan_power_paths(scan_glob: str) -> list:
  import glob
  return sorted(p for p in glob.glob(scan_glob) if p)


def power_reading(read=None, path: str = POWER_PATH, *, scan_glob: str = POWER_SCAN_GLOB, cache=None) -> Reading:
  """Current power draw from sysfs microwatts, or '--' when unreadable.

  Tries `path` first (hwmon1, the same path as hardware.get_current_power_draw). If that path is missing or
  unreadable, scans scan_glob for the first readable power1_input (existence only; no chip name). The resolved
  path is cached in `cache` (a one-element list; the module cache is used when cache is None). A later failure
  of the cached path clears it and scans once more. Does not use read_param_file's default of 0, and does not
  read deviceState.powerDrawW.
  """
  store = _POWER_CACHE if cache is None else cache
  tried: set = set()

  def from_path(candidate: str):
    if not candidate or candidate in tried:
      return None
    tried.add(candidate)
    got = _try_power_path(candidate, read)
    if got is None:
      return None
    store[0] = candidate
    return got

  cached = store[0] if store else None
  if cached:
    got = from_path(cached)
    if got is not None:
      return got
    store[0] = None

  got = from_path(path)
  if got is not None:
    return got

  if scan_glob:
    for candidate in _scan_power_paths(scan_glob):
      got = from_path(candidate)
      if got is not None:
        return got

  if store:
    store[0] = None
  return Reading()


def upper_slot_choice(text):
  """Exact stored value, or None when nothing usable is stored (missing, junk, unreadable)."""
  if isinstance(text, (bytes, bytearray)):
    text = text.decode("utf-8", "replace")
  if isinstance(text, str) and text.strip() in UPPER_STORED:
    return text.strip()
  return None


def upper_slot_shown(choice, numerical: bool, fahrenheit: bool) -> str:
  """What the upper box shows. Power only when that exact value is stored; otherwise the temp params."""
  return "power" if choice == "power" else temp_mode(numerical, fahrenheit)


def cycle_upper_slot(choice: str, fahrenheit: "bool | None" = None) -> str:
  if fahrenheit is None:
    fahrenheit = fahrenheit_from_metric()
  cycle = upper_cycle(fahrenheit)
  return _next(cycle, cycle[1] if choice in TEMP_UNITS else choice)


def read_upper_slot():
  try:
    from openpilot.common.bogpilot_toggles import toggle_path
    path = toggle_path(UPPER_SLOT_KEY)
    text = path.read_text(encoding="utf-8") if path.is_file() else None
    return upper_slot_choice(text)
  except Exception:
    return None


def write_upper_slot(choice: str) -> bool:
  try:
    from openpilot.common.bogpilot_toggles import write_choice
    write_choice(UPPER_SLOT_KEY, choice)
    return True
  except Exception:
    return False



def slot_flags_from_params(params) -> dict:
  def read_bool(key):
    try:
      v = params.get_bool(key)
    except Exception:
      return False
    return bool(v)

  def read_raw(key):
    return params.get(key) if hasattr(params, "get") else read_bool(key)

  return slot_flags(read_bool, read_raw, lambda key: read_chip_file())


GPU_CLOCK_STATS_PATH = "/sys/class/kgsl/kgsl-3d0/gpu_clock_stats"   # Adreno (comma 3X and comma 4): busy microseconds per power level
GPU_MIN_SAMPLE_US = 200_000   # a repeat read sooner than this (a tap redraw) keeps the last value instead of a tiny noisy window


def parse_clock_stats(raw) -> "int | None":
  """Total GPU busy microseconds: the sum of the per-power-level counters in gpu_clock_stats; None if unreadable."""
  if isinstance(raw, (bytes, bytearray)):
    raw = raw.decode("utf-8", "replace")
  if not isinstance(raw, str):
    return None
  parts = raw.split()
  if not parts:
    return None
  try:
    values = [int(p, 10) for p in parts]
  except ValueError:
    return None
  return None if any(v < 0 for v in values) else sum(values)


class GpuClockStats:
  """GPU busy percent from deltas of gpu_clock_stats over monotonic wall time. The old gpubusy counter only refreshes under a
  load-sampling devfreq governor, and comma pins the governor to performance, so it is frozen at 0. gpu_clock_stats keeps
  counting whatever the governor is. None (a dash) on the first sample, a missing or malformed file, or a counter reset
  or wrap; the next read starts a new window."""

  def __init__(self, path: str = GPU_CLOCK_STATS_PATH, clock_us=None):
    import time
    self.path = path
    self._clock_us = clock_us or (lambda: time.monotonic_ns() // 1000)
    self._prev = None   # (wall_us, busy_us)
    self._last = None

  def percent(self) -> "float | None":
    try:
      with open(self.path, encoding="utf-8") as f:
        busy = parse_clock_stats(f.read())
    except (OSError, ValueError):
      busy = None
    if busy is None:
      self._prev = self._last = None
      return None
    now = self._clock_us()
    prev = self._prev
    if prev is None:
      self._prev = (now, busy)
      return None
    wall = now - prev[0]
    if wall <= 0 or busy < prev[1]:           # clock went backwards or counter reset / wrapped
      self._prev, self._last = (now, busy), None
      return None
    if wall < GPU_MIN_SAMPLE_US:
      return self._last
    self._last = max(0.0, min(100.0, 100.0 * (busy - prev[1]) / wall))
    self._prev = (now, busy)
    return self._last


_GPU_READER = GpuClockStats()


def read_gpu_percent(reader: "GpuClockStats | None" = None) -> "float | None":
  """Busy percent since the previous call (shared reader); None (shown as a dash) when it cannot be known. Never a made-up zero."""
  return (reader or _GPU_READER).percent()


def chip_reading(device_state, which: str, *, fresh: bool, gpu_percent=None) -> Reading:
  """CPU (mean per-core load) or GPU usage; unavailable on stale / malformed data. GPU comes from kgsl gpu_clock_stats deltas
  (read_gpu_percent), not the frozen gpubusy counter."""
  if not fresh or device_state is None:
    return Reading()
  try:
    if which == "gpu":
      value = read_gpu_percent() if gpu_percent is None else gpu_percent()
      return Reading() if value is None else _usage(_number(value, 0, 100))
    loads = [_number(v, 0, 100) for v in device_state.cpuUsagePercent]
    return _usage(sum(loads) / len(loads)) if loads else Reading()
  except (AttributeError, ValueError, TypeError, OverflowError):
    return Reading()


# --- Modeld load: replaces the GPU% display. The kgsl gpubusy counter is frozen at 0 on comma 3X because comma pins the
# GPU governor to "performance" (common/hardware/comma/hardware.py), so the GPU slot shows how much of the 50 ms (20 Hz)
# model frame budget the model runs use instead. The ShowGPU param key and the slot cycle are unchanged; only the display is. ---
MODELD_BUDGET_S = 0.050
MODELD_WARNING_PERCENT = 80      # white below, yellow from here
MODELD_DANGER_PERCENT = 100      # red above (100 itself is still yellow), or on any modelV2.frameDropPerc
MODELD_EMA_TAU_S = 1.0           # smoothing time constant, so the 2 Hz sidebar redraw does not flicker
MODELD_DROP_HOLD_S = 1.0         # a frame drop keeps the pill red this long
MODELD_STALE_S = 1.0             # no modelV2 for this long means modeld is not publishing: grey dash


def modeld_load_level(percent: int, frame_drop: bool = False) -> str:
  if frame_drop or percent > MODELD_DANGER_PERCENT:
    return "danger"
  return "warning" if percent >= MODELD_WARNING_PERCENT else "good"


def modeld_load_reading(percent, frame_drop: bool, *, live: bool) -> Reading:
  """'NN%' of the 50 ms budget. Grey dash when modeld is not publishing or the value is unusable (never a made-up zero)."""
  if not live or percent is None:
    return Reading()
  try:
    value = int(_number(percent, 0, 1e6))
  except (ValueError, TypeError, OverflowError):
    return Reading()
  return Reading(f"{value}%", modeld_load_level(value, frame_drop))


def _exec_percent(seconds) -> "float | None":
  """Execution time in seconds as percent of the frame budget; None when absent or not a sane number (0 to 1 s)."""
  try:
    return 100.0 * _number(seconds, 0, 1.0) / MODELD_BUDGET_S
  except (ValueError, TypeError, OverflowError):
    return None


class ModeldLoad:
  """Cheap smoothed modeld load. update() takes the numbers from the modelV2 message the UI SubMaster already receives
  (no extra subscription); reading() is a pure read. Value = max(modelV2, driverStateV2 modelExecutionTime) / 50 ms."""

  def __init__(self, clock=time.monotonic):
    self._clock = clock
    self._value = None
    self._last = None
    self._drop_until = -math.inf

  def update(self, model_exec_s, driver_exec_s, frame_drop_perc, now=None) -> None:
    now = self._clock() if now is None else now
    seen = [p for p in (_exec_percent(model_exec_s), _exec_percent(driver_exec_s)) if p is not None]
    try:
      if _number(frame_drop_perc, 0, 100) > 0:
        self._drop_until = now + MODELD_DROP_HOLD_S
    except (ValueError, TypeError, OverflowError):
      pass
    if not seen:
      return
    instant = max(seen)
    if self._value is None or self._last is None or now - self._last > MODELD_STALE_S:
      self._value = instant
    else:
      alpha = 1.0 - math.exp(-max(0.0, now - self._last) / MODELD_EMA_TAU_S)
      self._value += alpha * (instant - self._value)
    self._last = now

  def reading(self, now=None) -> Reading:
    now = self._clock() if now is None else now
    live = self._last is not None and now - self._last <= MODELD_STALE_S
    return modeld_load_reading(self._value, now < self._drop_until, live=live)


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
