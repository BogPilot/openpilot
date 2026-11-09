"""BogPilot Visuals/theme gap closure (t994 lane visualsTheme).

telemetryAudit found 21 ON-unregistered visuals/theme prefs. This module is the
lane catalog: which keys get a Visuals menu row with a real 0.11.2 raylib
consumer, which stay omitted (with reasons), and the sidebar visibility policy
used by the proposed sidebar.py consumer patch.

Rules (FANOUT): no inert toggles; preserve stored choices; stock lead-box /
IC-only paths untouched; AOL / Model Selector / The Bog / Goat Scream out.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Visuals menu rows this lane adds (parents / peers of already-wired children)
# ---------------------------------------------------------------------------
# Each entry: (param_key, title, description). Titles match 0.9.7 bogpilot-tesla
# where the raylib consumer is a straight port of that feature.

NEW_VISUAL_TOGGLES: tuple[tuple[str, str, str], ...] = (
  ("QOLVisuals", "Quality of Life Visuals",
   "Parent for reverse-camera and the driving personality button. "
   "When off, those Visuals children stay hidden on the driving screen."),
  ("CustomUI", "Driving Screen Widgets",
   "Parent for blind-spot lane fill, pedals, and other custom driving-screen widgets. "
   "When off, those children stay hidden."),
  ("BorderMetrics", "Status Border",
   "Parent for blind-spot (and future torque/signal) status coloring on the screen border. "
   "Required for Blind Spot Border."),
  ("DynamicPedalsOnUI", "Dynamic Pedals",
   "When Pedals on Screen is on, vary pedal opacity with measured acceleration instead of static on/off."),
  ("SwapSpeedGraph", "Accel Graph on Top",
   "Put the acceleration graph above the speed row in the top-left cluster. Display only; file-backed."),
  ("Fahrenheit", "Temperature in Fahrenheit",
   "Show sidebar temperature in Fahrenheit instead of Celsius."),
  ("NumericalTemp", "Numerical Temperature",
   "Show a numeric sidebar temperature instead of only the GOOD/HIGH status label."),
  ("ShowCPU", "Show CPU in Sidebar",
   "Show the CPU usage metric in the offroad sidebar."),
  ("ShowMemoryUsage", "Show Memory in Sidebar",
   "Show the RAM usage metric in the sidebar."),
  ("NavigationUI", "Navigation Widgets",
   "Parent for the posted speed-limit tile on the driving screen."),
  ("ShowSpeedLimits", "Show Speed Limits",
   "Show the posted speed-limit tile (dashboard / plan sources). Requires Navigation Widgets."),
)

NEW_VISUAL_KEYS = tuple(k for k, _, _ in NEW_VISUAL_TOGGLES)

# File-only UI keys (never typed Params). ParamStore already routes these to
# /data/params_bogpilot; consumers use FileToggles / layout_from_toggles.
FILE_ONLY_VISUAL_KEYS = frozenset({"SwapSpeedGraph"})

# ---------------------------------------------------------------------------
# Omissions — ON in preserved prefs, but no honest 0.11.2 raylib consumer yet
# ---------------------------------------------------------------------------
OMITTED: tuple[tuple[str, str], ...] = (
  ("AccelerationPath",
   "0.9.7 colored the path by planned accel; raylib model_renderer has no AccelerationPath reader."),
  ("ModelUI",
   "0.9.7 manage parent for path/lane width knobs; no raylib path-width consumers on feae."),
  ("UnlimitedLength",
   "0.9.7 extended path/lane draw distance; stock/raylib path length not gated by this key."),
  ("RotatingWheel",
   "0.9.7 rotated the HUD wheel icon with steering angle; no wheel-icon render path on raylib C3X."),
  ("RoadNameUI",
   "0.9.7 OSM road-name strip; no OSM/road-name producer or onroad render on feae (cloud/nav fillers removed)."),
  ("PersonalizeOpenpilot",
   "0.9.7 Custom Themes parent (colors/icons/sounds/wheel); theme asset loader / Theme Maker not on raylib; "
   "The Bog restoration not authorized."),
  ("DeveloperUI",
   "Intermediate manage parent only. C3X Adjacent Lead Speed Boxes already have their own Visuals row; "
   "no standalone Developer HUD/sidebar widgets ported to raylib."),
  ("DeveloperWidgets",
   "Intermediate gate for radard adjacent_lead_tracking formula; HUD AdjacentLeadsUI is independent on C3X; "
   "Radar Tracks / stopping-point overlays not ported."),
  ("DeveloperMetrics",
   "Intermediate parent for AdjacentPathMetrics / FPS / LeadInfo; those child renders are absent on raylib feae."),
  ("UseSI",
   "0.9.7 SI formatting for developer metrics; no UseSI reader in raylib UI (developer metric overlays absent)."),
)

OMITTED_KEYS = tuple(k for k, _ in OMITTED)

AUDIT_KEYS = NEW_VISUAL_KEYS + OMITTED_KEYS
assert len(AUDIT_KEYS) == 21, len(AUDIT_KEYS)
assert len(set(AUDIT_KEYS)) == 21


# ---------------------------------------------------------------------------
# Sidebar visibility policy (consumer for ShowCPU / ShowMemoryUsage /
# NumericalTemp / Fahrenheit). Pure; sidebar.py applies via shared patch.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SidebarMetricPolicy:
  show_cpu: bool = True
  show_memory: bool = True
  numerical_temp: bool = True
  fahrenheit: bool = False


def sidebar_metric_policy(store: Any) -> SidebarMetricPolicy:
  """Read preserved prefs; missing keys fall back to ParamStore / registry defaults."""
  def b(key: str, default: bool) -> bool:
    try:
      if hasattr(store, "get_bool"):
        return bool(store.get_bool(key, default))
      raw = store.get(key) if hasattr(store, "get") else None
      if raw is None:
        return default
      if isinstance(raw, bool):
        return raw
      return str(raw).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
      return default

  return SidebarMetricPolicy(
    show_cpu=b("ShowCPU", True),
    show_memory=b("ShowMemoryUsage", True),
    numerical_temp=b("NumericalTemp", True),
    fahrenheit=b("Fahrenheit", False),
  )


def select_sidebar_metrics(
  *,
  started: bool,
  policy: SidebarMetricPolicy,
  offroad_temp,
  onroad_temp_status,
  cpu,
  ram,
  panda,
):
  """Pick which metric widgets to draw. Returns list of metric objects in draw order.

  Offroad: TEMP (numeric or GOOD/HIGH), CPU, RAM — each gated.
  Onroad: TEMP status (GOOD/HIGH always for engagement thermal), VEHICLE, RAM gated.
  Empty slots are omitted (no inert placeholder).
  """
  out = []
  if started:
    out.append(onroad_temp_status)
    out.append(panda)
    if policy.show_memory:
      out.append(ram)
  else:
    out.append(offroad_temp if policy.numerical_temp else onroad_temp_status)
    if policy.show_cpu:
      out.append(cpu)
    if policy.show_memory:
      out.append(ram)
  return out


# ---------------------------------------------------------------------------
# Consumer probes used by UI -> store -> consumer tests
# ---------------------------------------------------------------------------
def consumer_snapshot(store: Any, *, longitudinal: bool = True, has_bsm: bool = True) -> dict[str, bool]:
  """Evaluate the real feae consumers against `store` (no pyray)."""
  from openpilot.selfdrive.ui.bogpilot.reverse_camera import enabled_from as reverse_enabled
  from openpilot.selfdrive.ui.onroad.bogpilot.pedals import policy_from_store as pedal_policy
  from openpilot.selfdrive.ui.onroad.bogpilot.speed_limit_display import policy_from_store as limit_policy
  from openpilot.selfdrive.ui.onroad.bogpilot.cluster_layout import layout_from_toggles

  level = store.tuning_level() if hasattr(store, "tuning_level") else 3
  b = (lambda k: bool(store.toggle_bool(k, level))) if hasattr(store, "toggle_bool") else (lambda k: bool(store.get_bool(k)))

  snap: dict[str, bool] = {}
  snap["QOLVisuals_reverse"] = bool(reverse_enabled(store))
  snap["QOLVisuals_personality"] = bool(b("QOLVisuals") and b("OnroadDistanceButton"))
  snap["CustomUI"] = bool(b("CustomUI"))
  ped = pedal_policy(store, longitudinal)
  snap["CustomUI_pedals"] = bool(ped.show)
  snap["DynamicPedalsOnUI"] = bool(ped.dynamic)
  snap["BorderMetrics"] = bool(b("BorderMetrics") and b("BlindSpotMetrics") and has_bsm)
  lay = layout_from_toggles(lambda k: bool(store.get_bool(k)))
  snap["SwapSpeedGraph"] = bool(lay.swap)
  lim = limit_policy(store, SimpleNamespace_CP(longitudinal=longitudinal))
  snap["NavigationUI_gate"] = bool(b("NavigationUI"))
  snap["ShowSpeedLimits"] = bool(lim.show_speed_limits)
  side = sidebar_metric_policy(store)
  snap["Fahrenheit"] = bool(side.fahrenheit)
  snap["NumericalTemp"] = bool(side.numerical_temp)
  snap["ShowCPU"] = bool(side.show_cpu)
  snap["ShowMemoryUsage"] = bool(side.show_memory)
  return snap


class SimpleNamespace_CP:
  def __init__(self, longitudinal=True):
    self.openpilotLongitudinalControl = longitudinal
    self.radarUnavailable = False
    self.enableBsm = True
    self.carFingerprint = "TESLA_AP1_MODELS"


def decision_table() -> list[dict[str, str]]:
  rows = []
  for key, title, _desc in NEW_VISUAL_TOGGLES:
    rows.append({"key": key, "decision": "IMPLEMENT", "title": title, "note": "Visuals row + real consumer"})
  for key, reason in OMITTED:
    rows.append({"key": key, "decision": "OMIT", "title": "", "note": reason})
  return rows
