"""Background device reads for hardwared's 2 Hz deviceState loop.

hardwared used to make every slow device read inline on the deviceState loop:
thermal zones, free space, memory, CPU and GPU load, screen brightness, power
draw and SoM power draw, plus the boot check. When one of those sysfs/procfs
reads stalls (seconds, not milliseconds, on some devices), deviceState stops
and selfdrived raises commIssue. Pre-AP tester logs showed deviceState gaps of
12.5 s and 14.4 s with pandaStates steady at 10 Hz.

Here the reads run on daemon threads and the loop only takes the latest
cached value, so a stalled read delays fresh values but never deviceState.

Design credit: NAP (NotAutopilot) moved the same reads off its publish loop
(system/hardware/thermal_reader.py, sysfs_reader.py and loop_timing.py, and
hardwared.py, on nap-alpha and nap-dev-0.11.2). NAP's notes record single
thermal and bms power reads blocking for 12.6 to 12.7 s. This file is
BogPilot's own implementation of that design; see
docs/tesla/DIVERGENCES_hardwared_bg_reads.md for the differences.
"""
import threading
import time
from collections.abc import Callable
from dataclasses import fields
from typing import Any

from openpilot.common.realtime import DT_HW
from openpilot.common.swaglog import cloudlog

# A single read slower than this is logged by name.
SLOW_READ_S = 0.25
# No fresh thermal reading for this long marks the temperatures stale.
THERMAL_STALE_S = 10.0
# Once stale, fail hot after this much more time even if the last reading was cool.
THERMAL_FAIL_HOT_S = 60.0
# What stale temperatures do beyond the fan, read once when hardwared starts (stale_thermal_policy). None, the default, picks
# per car: "nap" on a Pre-AP Model S (CarModel, else the persistent fingerprint: bogpilot_ap1_profile.is_preap_slc_platform),
# "strict" on AP1 and every other car, and "strict" while the car is not known yet (first boot, MOCK). Setting "nap" or
# "strict" here overrides that for every car:
#   "nap":    as NAP: thermalStatus goes to at least overheated at once if the held reading was warm, otherwise only after
#             THERMAL_FAIL_HOT_S more of staleness (about 70 s after the last reading). A hung reader with a cool last reading
#             therefore stays engaged up to about 70 s, then soft-disables.
#   "strict": thermalStatus goes to at least overheated as soon as the temperatures are stale (THERMAL_STALE_S), whatever
#             the held reading. Onroad that is selfdrived's overheat event: soft disable (3 s) when engaged, no entry
#             otherwise. Offroad it blocks going onroad. The device does not go offroad (only critical does that).
STALE_THERMAL_POLICY: str | None = None
STALE_THERMAL_POLICIES = ("nap", "strict")
# A non-thermal device read with no success for this long is logged as stale (its last real value is kept).
DEVICE_STALE_S = 10.0
# A loop iteration slower than this logs every step's duration.
SLOW_LOOP_S = 1.0


class BackgroundReads:
  """Runs named read functions on one daemon thread and caches the results.

  get() never touches the device. A read that raises keeps its previous
  value, and a read that hangs only holds up the reads queued behind it on
  this thread, never the caller.
  """

  def __init__(self, name: str, reads: dict[str, Callable[[], Any]], defaults: dict[str, Any],
               period_s: float = DT_HW, slow_s: float = SLOW_READ_S, clock: Callable[[], float] = time.monotonic):
    self.name = name
    self._reads = dict(reads)
    self._period_s = period_s
    self._slow_s = slow_s
    self._clock = clock
    self._lock = threading.Lock()
    self._values: dict[str, Any] = dict(defaults)
    self._fresh_at: dict[str, float] = {}
    self.thread: threading.Thread | None = None

  def get(self, key: str, default: Any = None) -> Any:
    with self._lock:
      return self._values.get(key, default)

  def snapshot(self, key: str, default: Any = None) -> tuple[Any, bool]:
    """(value, whether it came from a real read), taken under one lock so the two always agree."""
    with self._lock:
      return self._values.get(key, default), key in self._fresh_at

  def has_value(self, key: str) -> bool:
    with self._lock:
      return key in self._fresh_at

  def age_s(self, key: str) -> float | None:
    """Seconds since the last successful read of key, or None if it never succeeded."""
    with self._lock:
      t = self._fresh_at.get(key)
    return None if t is None else self._clock() - t

  def run_once(self) -> dict[str, float]:
    """Do every read once. Returns {key: seconds} for the reads slower than slow_s."""
    slow: dict[str, float] = {}
    t_start = self._clock()
    for key, read in self._reads.items():
      t0 = self._clock()
      try:
        value = read()
      except Exception:
        cloudlog.exception(f"hardwared {self.name} read failed: {key}")
      else:
        with self._lock:
          self._values[key] = value
          self._fresh_at[key] = self._clock()
      dt = self._clock() - t0
      if dt > self._slow_s:
        slow[key] = dt
    if slow:
      cloudlog.event("hardwared slow read", error=True, reader=self.name,
                     reads_ms={k: round(v * 1e3, 1) for k, v in slow.items()},
                     total_ms=round((self._clock() - t_start) * 1e3, 1))
    return slow

  def _loop(self, end_event: threading.Event) -> None:
    try:
      while not end_event.is_set():
        t0 = self._clock()
        self.run_once()
        end_event.wait(max(0.0, self._period_s - (self._clock() - t0)))
    except BaseException as e:
      # a dead reader is otherwise silent: its values just stop refreshing
      cloudlog.event("hardwared reader thread died", error=True, reader=self.name, exc=repr(e))
      raise

  def start(self, end_event: threading.Event) -> threading.Thread:
    self.thread = threading.Thread(target=self._loop, args=(end_event,), name=f"hardwared-{self.name}", daemon=True)
    self.thread.start()
    return self.thread


def read_thermal_zones(thermal_config, clock: Callable[[], float] = time.monotonic, slow_s: float = SLOW_READ_S) -> dict:
  """The same dict as ThermalConfig.get_msg(), timing each zone and logging the slow ones by name."""
  temps: dict = {}
  slow: dict[str, float] = {}

  def timed(zone):
    t0 = clock()
    value = zone.read()
    dt = clock() - t0
    if dt > slow_s:
      slow[str(getattr(zone, "name", "?"))] = dt
    return value

  for f in fields(thermal_config):
    v = getattr(thermal_config, f.name)
    if v is None:
      continue
    temps[f.name + "TempC"] = [timed(z) for z in v] if isinstance(v, list) else timed(v)
  if slow:
    cloudlog.event("hardwared slow thermal zone", error=True, zones_ms={k: round(v * 1e3, 1) for k, v in slow.items()})
  return temps


class ThermalStaleness:
  """Tracks how old the cached thermal reading is, as seen by the deviceState loop.

  Before the first reading the age counts from construction, so a reader that
  never returns still goes stale.
  """

  def __init__(self, stale_after_s: float | None = None, clock: Callable[[], float] = time.monotonic):
    self._stale_after_s = THERMAL_STALE_S if stale_after_s is None else stale_after_s
    self._clock = clock
    self._t_created = clock()
    self.stale = False
    self.stale_since: float | None = None

  def update(self, age_s: float | None) -> bool:
    now = self._clock()
    age = (now - self._t_created) if age_s is None else age_s
    stale = age > self._stale_after_s
    if stale and not self.stale:
      self.stale_since = now
      cloudlog.event("hardwared thermal stale", error=True, age_s=round(age, 1))
    elif not stale and self.stale:
      cloudlog.event("hardwared thermal fresh again", error=True, stale_s=round(now - (self.stale_since or now), 1))
      self.stale_since = None
    self.stale = stale
    return stale

  @property
  def stale_s(self) -> float:
    return 0.0 if self.stale_since is None else self._clock() - self.stale_since


class ReadStaleness:
  """Which keys of a background reader have gone without a successful read for stale_after_s.

  Before a key's first read its age counts from construction, so a reader
  that hangs from the start still shows up. Logs the stale set when it
  changes. Values are not touched: the caller keeps the last real value (or a
  fail-closed placeholder before the first read).
  """

  def __init__(self, name: str, stale_after_s: float | None = None, clock: Callable[[], float] = time.monotonic):
    self.name = name
    self._stale_after_s = stale_after_s
    self._clock = clock
    self._t_created = clock()
    self.stale: set[str] = set()

  def update(self, ages: dict[str, float | None]) -> set[str]:
    limit = DEVICE_STALE_S if self._stale_after_s is None else self._stale_after_s
    since_start = self._clock() - self._t_created
    ages_now = {k: (since_start if a is None else a) for k, a in ages.items()}
    stale = {k for k, a in ages_now.items() if a > limit}
    if stale - self.stale:
      cloudlog.warning(f"hardwared {self.name} read stale (no fresh value for {limit:.0f} s): {', '.join(sorted(stale - self.stale))}")
      cloudlog.event("hardwared device reads stale", error=True, reader=self.name, keys=sorted(stale),
                     age_s={k: round(ages_now[k], 1) for k in sorted(stale)}, never_read=sorted(k for k in stale if ages[k] is None))
    if self.stale - stale:
      cloudlog.event("hardwared device reads fresh again", error=True, reader=self.name, keys=sorted(self.stale - stale))
    self.stale = stale
    return stale


# Free space or memory with no fresh value for this long, after its first real read, blocks NEW onroad entry.
ENTRY_STALE_S = 60.0
ENTRY_GATE_KEYS = ("free_space", "memory")


class StaleEntryGate:
  """Startup condition: False while offroad and free space or memory has had no fresh read for ENTRY_STALE_S.

  Only after a key's first real read (before it, the fail-closed placeholders already apply). It never forces
  offroad: while onroad a stale read is logged once and the drive keeps going; the gate only answers whether a new
  onroad entry may start. A fresh read clears it.
  """

  def __init__(self, stale_after_s: float | None = None, keys: tuple[str, ...] = ENTRY_GATE_KEYS):
    self._stale_after_s = ENTRY_STALE_S if stale_after_s is None else stale_after_s
    self._keys = keys
    self.stale: set[str] = set()
    self._logged: tuple[bool, frozenset[str]] | None = None

  def update(self, ages: dict[str, float | None], onroad: bool) -> bool:
    stale = {k for k in self._keys if ages.get(k) is not None and ages[k] > self._stale_after_s}
    state = (bool(onroad), frozenset(stale))
    if stale and state != self._logged:
      if onroad:
        cloudlog.event("hardwared device reads stale while onroad: staying onroad, new entry blocked once offroad",
                       error=True, keys=sorted(stale), age_s={k: round(ages[k], 1) for k in sorted(stale)})
      else:
        cloudlog.event("hardwared device reads stale: onroad entry blocked until a fresh read", error=True,
                       keys=sorted(stale), age_s={k: round(ages[k], 1) for k in sorted(stale)})
    elif not stale and self.stale:
      cloudlog.event("hardwared device reads fresh: onroad entry gate cleared", keys=sorted(self.stale))
    self._logged = state if stale else None
    self.stale = stale
    return onroad or not stale


def stale_thermal_policy(params=None) -> str:
  """STALE_THERMAL_POLICY if set ("strict" if it is not a known policy), else per car from params: "nap" on Pre-AP, "strict"
  on any other car and while the car is unknown (no params, no CarModel / persistent fingerprint, or any read error)."""
  if STALE_THERMAL_POLICY is not None:
    if STALE_THERMAL_POLICY in STALE_THERMAL_POLICIES:
      return STALE_THERMAL_POLICY
    cloudlog.event("hardwared unknown stale thermal policy, using strict", error=True, policy=str(STALE_THERMAL_POLICY))
    return "strict"
  if params is None:
    return "strict"
  try:
    from openpilot.common.bogpilot_ap1_profile import is_preap_slc_platform
    return "nap" if is_preap_slc_platform(params) else "strict"
  except Exception:
    return "strict"


def fail_hot_thermal_status(status: int, stale: bool, stale_s: float, last_temp: float, warm_temp: float,
                            ok: int, overheated: int, fail_hot_s: float | None = None, strict: bool = False) -> int:
  """thermalStatus to publish when the temperatures may be stale.

  Fresh: unchanged. Stale: never cooler than the band logic gave from the
  held temperatures, and at least `overheated` if the last reading was already
  warm (status above ok, or temperature at or above warm_temp) or once stale
  for fail_hot_s. strict: at least `overheated` as soon as stale.
  """
  if not stale:
    return status
  if strict:
    return max(status, overheated)
  if fail_hot_s is None:
    fail_hot_s = THERMAL_FAIL_HOT_S
  if status > ok or last_temp >= warm_temp or stale_s >= fail_hot_s:
    return max(status, overheated)
  return status


class LoopStepTimer:
  """Per-step durations for one hardwared loop iteration."""

  def __init__(self, clock: Callable[[], float] = time.monotonic):
    self._clock = clock
    self._t0 = clock()
    self._prev = self._t0
    self.steps: dict[str, float] = {}

  def mark(self, step: str) -> None:
    now = self._clock()
    self.steps[step] = self.steps.get(step, 0.0) + (now - self._prev)
    self._prev = now

  @property
  def total_s(self) -> float:
    return self._clock() - self._t0

  def report_if_slow(self, limit_s: float | None = None) -> bool:
    """Log every step's duration in ms when the iteration took longer than limit_s (default SLOW_LOOP_S)."""
    limit_s = SLOW_LOOP_S if limit_s is None else limit_s
    total = self.total_s
    if total <= limit_s:
      return False
    cloudlog.event("hardwared slow loop", error=True, total_ms=round(total * 1e3, 1),
                   steps_ms={k: round(v * 1e3, 1) for k, v in self.steps.items()})
    return True
