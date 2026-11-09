"""Pure Device Controls consumers for proposed UI/power hooks; never writes Params or hardware.

Absent/disabled parent masters preserve the caller's stock behavior. Malformed saved
values fail closed to stock. Integration hooks live in PROPOSED_shared.patch only.
"""
from __future__ import annotations

import math

DEVICE_MASTER = "DeviceManagement"
SCREEN_MASTER = "ScreenManagement"


def _number(store, key, default, lo, hi):
  try:
    raw = store.raw(key)
    value = float(raw) if raw is not None else float(default)
    return min(hi, max(lo, value)) if math.isfinite(value) else default
  except (TypeError, ValueError):
    return default


def device_enabled(store) -> bool:
  return store.get_bool(DEVICE_MASTER, False)


def screen_enabled(store) -> bool:
  return store.get_bool(SCREEN_MASTER, False)


def screen_timeout(store, onroad: bool, stock: int) -> int:
  """Effective interactive timeout seconds. Parent OFF -> stock."""
  if not screen_enabled(store):
    return int(stock)
  key = "ScreenTimeoutOnroad" if onroad else "ScreenTimeout"
  return int(_number(store, key, stock, 5, 60))


def screen_brightness(store, onroad: bool, stock: float, attention: bool = False) -> float:
  """Manual brightness percent, or stock when Auto (101). Alerts force >= 30 onroad."""
  if not screen_enabled(store):
    return stock
  key = "ScreenBrightnessOnroad" if onroad else "ScreenBrightness"
  lo = 0 if onroad else 1
  selected = _number(store, key, 101, lo, 101)
  value = stock if selected == 101 else selected
  if onroad and attention:
    return max(30.0, float(value))
  return float(value)


def screen_awake(store, ignition: bool, timed_out: bool, pc: bool, attention: bool = False) -> bool:
  """Standby Mode may sleep while ignition is on after interactive timeout; alerts/PC always wake."""
  if pc or attention or not timed_out:
    return True
  if ignition:
    return not (screen_enabled(store) and store.get_bool("StandbyMode", False))
  return False


def shutdown_time(store, stock: float) -> float:
  """Seconds offroad before shutdown. Never extends stock MAX_TIME_OFFROAD_S protection."""
  if not device_enabled(store):
    return float(stock)
  value = int(_number(store, "DeviceShutdown", 33, 0, 33))
  seconds = 300 if value == 0 else value * 900 if value <= 3 else (value - 3) * 3600
  return float(min(stock, seconds))


def voltage_cutoff(store, stock: float) -> float:
  """LPF car-battery volts threshold. Never lowers existing protection floor (stock)."""
  if not device_enabled(store):
    return float(stock)
  return float(_number(store, "LowVoltageShutdown", stock, max(11.8, float(stock)), 12.5))


def shutdown_label(value) -> str:
  value = int(value)
  if value == 0:
    return "5 mins"
  if value <= 3:
    return f"{value * 15} mins"
  hours = value - 3
  return f"{hours} hour" + ("" if hours == 1 else "s")
