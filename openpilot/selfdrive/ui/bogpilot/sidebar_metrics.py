"""Read-only BogPilot sidebar readings from genuine deviceState telemetry.

Display semantics come from 568fea Sidebar: maxTempC (owner Fahrenheit units),
mean CPU load and RAM usage with 70/85 percent warning/danger thresholds.
Missing/stale/malformed telemetry is unavailable, never an invented zero.
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


# --- t994 visualsTheme: visibility gates for ShowCPU / ShowMemoryUsage / NumericalTemp ---
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
