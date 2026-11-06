"""BogPilot shipping defaults + settings visibility (stream 5).

Locked 2026-11-06 for bogpilot-tesla-c3 / bogpilot-tesla-c3x:
  - Border Metrics at Minimal, default ON (BSM side red via BlindSpotMetrics)
  - Developer HUD / Widgets / 300px Sidebar under Developer, default OFF
  - Sidebar Metrics CPU/GPU/RAM ON; those + approved accel-layout toggles at Minimal
  - NudgelessLaneChange OFF; Always On Lateral OFF (toggle available)
  - Fresh-install Tuning Level intentionally unset (TuningLevel=0, Confirmed=0)
  - Model UI widths remain Advanced
  - SwapSpeedGraph file default ON (hide-accel owned by stream 8; must stay Minimal-visible)

Preserves existing user choices: AP1 profile still only writes when a Params value equals
the table default, and file toggles only when the file is absent.
"""
from __future__ import annotations

PARAM_OVERRIDES: dict[str, tuple[str, int]] = {
  'BorderMetrics': ('1', 0),
  'BlindSpotMetrics': ('1', 0),
  'ShowSteering': ('0', 0),
  'SignalMetrics': ('0', 0),
  'DeveloperUI': ('0', 3),
  'DeveloperMetrics': ('1', 3),
  'DeveloperHUD': ('0', 3),
  'DeveloperWidgets': ('0', 3),
  'DeveloperSidebar': ('0', 3),
  'SidebarMetrics': ('1', 0),
  'ShowCPU': ('1', 0),
  'ShowGPU': ('1', 0),
  'ShowMemoryUsage': ('1', 0),
  'ShowIP': ('0', 3),
  'ShowStorageLeft': ('0', 3),
  'ShowStorageUsed': ('0', 3),
  'NudgelessLaneChange': ('0', 0),
  'AlwaysOnLateral': ('0', 0),
  'AlwaysOnLateralLKAS': ('1', 2),
  'AlwaysOnLateralMain': ('1', 2),
  'ModelUI': ('1', 2),
  'PathWidth': ('6.1', 2),
  'RoadEdgesWidth': ('2', 2),
  'AccelerationPath': ('1', 2),
  'DynamicPathWidth': ('0', 2),
  'TuningLevel': ('0', 0),
  'TuningLevelConfirmed': ('0', 0),
}

FILE_TOGGLE_DEFAULTS: dict[str, bool] = {
  'DeveloperHUD': False,
  'SwapSpeedGraph': True,
  'BSMFlameTracks': True,
  'OffroadScreensaver': True,
  'ConfidenceBall': True,
}

REPARENT_TO_CUSTOM_UI: frozenset[str] = frozenset({
  'BorderMetrics',
  'SidebarMetrics',
  'ShowCPU',
  'ShowGPU',
  'ShowMemoryUsage',
  'SwapSpeedGraph',
})

AP1_PARAM_REMOVE: frozenset[str] = frozenset(['TuningLevel', 'TuningLevelConfirmed'])
AP1_PARAM_SET: dict[str, str] = {
  'AlwaysOnLateral': '0',
  'BorderMetrics': '1',
  'DeveloperSidebar': '0',
  'DeveloperWidgets': '0',
  'NudgelessLaneChange': '0',
  'SidebarMetrics': '1',
  'ShowCPU': '1',
  'ShowGPU': '1',
  'ShowMemoryUsage': '1',
  'DeveloperUI': '1',
}
AP1_FILE_SET: dict[str, str] = {
  'DeveloperHUD': '0',
  'SwapSpeedGraph': '1',
}

MINIMAL = 0
STANDARD = 1
ADVANCED = 2
DEVELOPER = 3


def apply_param_overrides(rows: list[tuple] | tuple) -> list[tuple[str, str, int, str]]:
  """Return a new defaults table with shipping value/level overlays applied."""
  out: list[tuple[str, str, int, str]] = []
  seen: set[str] = set()
  for row in rows:
    key, value, level, stock = row[0], str(row[1]), int(row[2]), str(row[3])
    if key in PARAM_OVERRIDES:
      value, level = PARAM_OVERRIDES[key]
      value = str(value)
      level = int(level)
    out.append((key, value, level, stock))
    seen.add(key)
  for key, (value, level) in PARAM_OVERRIDES.items():
    if key not in seen:
      out.append((key, str(value), int(level), "0"))
  return out


def default_map(rows) -> dict[str, str]:
  return {k: str(v) for k, v, _, _ in rows}


def level_map(rows) -> dict[str, int]:
  return {k: int(lvl) for k, _, lvl, _ in rows}


def patch_ap1_param_profile(profile: dict[str, str]) -> dict[str, str]:
  out = dict(profile)
  for k in AP1_PARAM_REMOVE:
    out.pop(k, None)
  out.update(AP1_PARAM_SET)
  return out


def patch_ap1_file_profile(profile: dict[str, str]) -> dict[str, str]:
  out = dict(profile)
  out.update(AP1_FILE_SET)
  return out
