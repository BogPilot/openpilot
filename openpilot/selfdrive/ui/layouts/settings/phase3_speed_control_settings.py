"""BogPilot > Driving Controls > Gas / Brake > Speed Limit Controller rows (phase 3, 0.9.7 04d560f3e).

Source: bogpilot/ui/qt/offroad/longitudinal_settings.cc/.h (speedLimitController*Keys, labels, option lists,
value ranges, updateToggles visibility). Runtime consumer: selfdrive/controls/lib/phase3_speed_control.py.
Active-only: rows whose key has no AP1 consumer in this tree are in OMITTED with the reason. Nothing is
registered and no default is written here.

gasFollowSpeed: SlcEditor + make_layout turn the row model into a real panel. Every write goes through
phase3_speed_control.configure (value + adoption marker), is refused unless offroad AND the row is currently visible
and valid, and the panel shows the parent toggle as the planner really behaves (OFF until adopted, see
phase3_speed_control docstring). Parent integrator: make_layout(CP, ParamStore(), lambda: not ui_state.started, section).
"""
from __future__ import annotations

import math
import time

from openpilot.selfdrive.controls.lib.phase3_speed_control import (
  LOOKAHEAD_HORIZON_DEFAULT, LOOKAHEAD_HORIZON_MAX, LOOKAHEAD_HORIZON_MIN,
  clamp_lookahead_horizon_s, configure, slc_adopted, slc_supported,
)


def tr_noop(s: str) -> str:
  return s


PANEL_PATH = ("BogPilot", "Driving Controls", "Gas / Brake", "Speed Limit Controller")
PARENT_KEY = "SpeedLimitController"
FALLBACK_EXPERIMENTAL = 1

# key, kind, title, description, parent, sub-panel
ROWS = (
  ("SpeedLimitController", "toggle", tr_noop("Speed Limit Controller"),
   tr_noop("<b>Limit openpilot's maximum driving speed to the current speed limit</b> from the dashboard "
           "(Tesla maps, and Mobileye on AP1). Map data can start an early slowdown toward a lower upcoming limit."),
   None, None),
  ("SLCFallback", "choice", tr_noop("Fallback Speed"),
   tr_noop("<b>The speed used by \"Speed Limit Controller\" when no speed limit is found.</b><br><br>- <b>Set Speed</b>: "
           "Use the cruise set speed<br>- <b>Experimental Mode</b>: Estimate the limit using the driving model<br>- "
           "<b>Previous Limit</b>: Keep using the last confirmed limit"), PARENT_KEY, None),
  ("SLCOverride", "choice", tr_noop("Override Speed"),
   tr_noop("<b>The speed used by \"Speed Limit Controller\" after you manually drive faster than the posted limit.</b>"
           "<br><br>- <b>Set with Gas Pedal</b>: Use the highest speed reached while pressing the gas<br>- <b>Max Set "
           "Speed</b>: Use the cruise set speed<br><br>Overrides clear when openpilot disengages."), PARENT_KEY, None),
  ("SLCPriority1", "priority", tr_noop("Priority 1"),
   tr_noop("<b>The first source used for the current posted limit</b> when Dashboard has no limit. "
           "When the dashboard is reporting a limit, it stays the current-limit authority. "
           "Highest or Lowest picks one of the other present sources and hides Priority 2 and 3."),
   PARENT_KEY, None),
  ("SLCPriority2", "priority", tr_noop("Priority 2"),
   tr_noop("<b>The second source used when Priority 1 has no limit.</b> Choose None to stop here."),
   PARENT_KEY, None),
  ("SLCPriority3", "priority", tr_noop("Priority 3"),
   tr_noop("<b>The third source used when Priority 1 and 2 have no limit.</b>"),
   PARENT_KEY, None),
  ("SLCLookaheadLower", "seconds", tr_noop("Look-ahead"),
   tr_noop("<b>How far ahead openpilot may start easing toward a lower upcoming map limit.</b> "
           "0 seconds turns look-ahead off. The current posted limit still comes from the dashboard; "
           "look-ahead never raises the set speed. Early slowing is capped at 2.0 mph/s and finishes "
           "only when the dashboard confirms the new limit. At 65 mph, 5 seconds is about 480 feet, "
           "enough to ease about 10 mph at 2 mph/s."),
   PARENT_KEY, None),
  *[(f"Offset{i}", "offset", None, None, PARENT_KEY, "SLCOffsets") for i in range(1, 8)],
  ("SLCConfirmation", "toggle", tr_noop("Confirm New Speed Limits"),
   tr_noop("<b>Ask before changing to a new speed limit.</b> To accept, press the Cruise Increase button. To deny, press "
           "the Cruise Decrease button or ignore the prompt for 30 seconds."), PARENT_KEY, "SLCQOL"),
  ("SLCConfirmationLower", "toggle", tr_noop("Lower Limits"), "", "SLCConfirmation", "SLCQOL"),
  ("SLCConfirmationHigher", "toggle", tr_noop("Higher Limits"), "", "SLCConfirmation", "SLCQOL"),
  ("SetSpeedLimit", "toggle", tr_noop("Match Speed Limit on Engage"),
   tr_noop("<b>When openpilot is first enabled, automatically set the max speed to the current posted limit</b> "
           "plus your speed limit offset. Pre-AP with the pedal only. Needs a current dashboard limit; otherwise, "
           "and when engaging at a stop or with the gas pressed, the normal engage speed is used."), PARENT_KEY, "SLCQOL"),
  ("ShowSLCOffset", "toggle", tr_noop("Show Speed Limit Offset"),
   tr_noop("<b>Show the current offset from the posted limit</b> on the driving screen."), PARENT_KEY, "SLCVisuals"),
)
ACTIVE_KEYS = tuple(r[0] for r in ROWS)
SUB_PANELS = {"SLCOffsets": tr_noop("Speed Limit Offsets"), "SLCQOL": tr_noop("Quality of Life"),
              "SLCVisuals": tr_noop("Visual Settings")}
CHOICES = {
  "SLCFallback": (tr_noop("Set Speed"), tr_noop("Experimental Mode"), tr_noop("Previous Limit")),
  "SLCOverride": (tr_noop("None"), tr_noop("Set With Gas Pedal"), tr_noop("Max Set Speed")),
}
# Pill width per SLC choice label: label width at 40 px Inter Medium plus ~50 px, at least 200. "Experimental Mode"
# (~371 px) and "Set With Gas Pedal" (~368 px) overran the old shared 300 px pills; a shared 420 px width would not fit
# the row (3 x 420 + 40 = 1300 px), so each pill is sized to its own label (rows 1030 / 1000 px).
CHOICE_PILL_WIDTHS = {"Set Speed": 250, "Experimental Mode": 420, "Previous Limit": 320,
                      "None": 200, "Set With Gas Pedal": 420, "Max Set Speed": 340}
PRIORITY1_OPTIONS = ("Dashboard", "Map Data", "Navigation", "Highest", "Lowest")
PRIORITY_OTHER_OPTIONS = ("None", "Dashboard", "Map Data", "Navigation")
OFFSET_BANDS = {False: ("0–24", "25–34", "35–44", "45–54", "55–64", "65–74", "75–99"),
                True: ("0–29", "30–49", "50–59", "60–79", "80–99", "100–119", "120–140")}
OFFSET_RANGE = {False: (-99, 99), True: (-150, 150)}

_NO_AP1 = "pcmCruise: 0.9.7 hid it (hasPCMCruise) and bogpilot_variables ignored it on AP1"
_SET_SPEED_LIMIT = (
  "AP1: 0.9.7 hid the row (hasPCMCruise / !pcm_cruise) and initialize_v_cruise returned early "
  "because AP1 keeps pcmCruise=True, so the engage apply never ran. "
  "Pre-AP with pedal (pcmCruise=False): 0.9.7 applied it on engage. "
  "This tree applies it on that engage too (cruise.py initialize_v_cruise), so the row is shown only there."
)
# Rows shown only on cars whose CarParams match (row key -> reason it is hidden elsewhere).
CAR_GATED = {"SetSpeedLimit": _SET_SPEED_LIMIT}
OMITTED = {
  "CustomCruise": _NO_AP1, "CustomCruiseLong": _NO_AP1, "SetSpeedOffset": _NO_AP1,
  "ReverseCruise": "Toyota-only PCM long-press semantics (0.9.7 isToyota); not reverse gear",
  "MapGears": "GM / HKG CAN-FD / Toyota only (0.9.7 visibility); not Tesla",
  "ForceMPHDashboard": "Toyota-only dashboard unit consumer; AP1 units come from the car (tesla_ap1/speed_limit.py)",
  "SLCPriority": "superseded by the Priority 1/2/3 rows; the combined key is unused",
  "SLCLookaheadHigher": "unused: look-ahead never raises the set speed early; saved values are preserved",
  "SLCMapboxFiller": "Mapbox API key + cloud request: prohibited (no API key collection / cloud)",
  "SpeedLimitSources": "no raylib consumer for the source list overlay",
  "SetWeatherKey": "OpenWeatherMap API key collection: prohibited",
  "WeatherPresets": "network weather source: prohibited / no consumer",
}


def experimental_fallback_available(store=None) -> bool:
  """Experimental Mode fallback is offered only once the planner consumes it (shared planner patch:
  Ap1SpeedControl.resolve_experimental); before that the option would be an inactive switch."""
  try:
    from pathlib import Path
    planner = Path(__file__).resolve().parents[3] / "controls/lib/longitudinal_planner.py"
    return "speed_control.resolve_experimental" in planner.read_text()
  except Exception:
    return False


def offset_title(key: str, is_metric: bool) -> str:
  i = int(key[-1]) - 1
  unit = "km/h" if is_metric else "mph"
  return f"Speed Offset ({OFFSET_BANDS[bool(is_metric)][i]} {unit})"


def clamp_offset(value: int, is_metric: bool) -> int:
  lo, hi = OFFSET_RANGE[bool(is_metric)]
  return int(min(max(int(value), lo), hi))


def slc_on(store, level=None) -> bool:
  """What the planner does: stored toggle AND adopted. A registry-default / profile-stored "1" is not active."""
  level = store.tuning_level() if level is None else level
  return bool(store.toggle_bool(PARENT_KEY, level)) and slc_adopted(store)


def car_row_allowed(key, CP) -> bool:
  """CAR_GATED rows: SetSpeedLimit only on Pre-AP with pedal (pcmCruise=False), as 0.9.7 !pcm_cruise. No CP: hidden."""
  if key not in CAR_GATED:
    return True
  return (CP is not None and str(getattr(CP, "carFingerprint", "") or "") == "TESLA_PREAP_MODELS"
          and not bool(getattr(CP, "pcmCruise", True)))


def visible_rows(store, sub_panel=None, CP=None) -> list[tuple]:
  level = store.tuning_level()
  if not slc_on(store, level) and sub_panel is not None:
    return []
  out = []
  for row in ROWS:
    key, _, _, _, parent, panel = row
    if panel != sub_panel and not (sub_panel is None and panel is None):
      continue
    if not store.honoured(key, level) or not car_row_allowed(key, CP):
      continue
    if parent is not None and not (slc_on(store, level) if parent == PARENT_KEY else store.toggle_bool(parent, level)):
      continue
    if key in ("SLCPriority2", "SLCPriority3"):
      p1 = store.get("SLCPriority1")
      if p1 in ("Highest", "Lowest"):
        continue
    out.append(row)
  return out


def visible_sub_panels(store, CP=None) -> list[str]:
  if not slc_on(store):
    return []
  return [p for p in SUB_PANELS if visible_rows(store, p, CP)]


def choice_options(store, key):
  opts = list(enumerate(CHOICES[key]))
  if key == "SLCFallback" and not experimental_fallback_available(store):
    opts = [o for o in opts if o[0] != FALLBACK_EXPERIMENTAL]
  return opts


BY_KEY = {r[0]: r for r in ROWS}
APPLIES = "Applies next drive (the planner reads these settings once per drive)."


# ---- SLC reset profile by car type ----
# A car type listed here gets its SLC section resets (and the row hints) from that profile instead of the general
# table (the registry defaults). Each entry: (car type, detector(store) -> bool, values(store) -> {key: stored text}).
# Today only the AP1 Model S maps, to the one-time AP1 Model S profile (openpilot/common/bogpilot_ap1_profile.py,
# ported from BogPilot 367e1fe selfdrive/car/tesla/ap1_defaults.py), read through the profile's own
# _profile_for_units() so nothing is copied here: Offset1-7 from AP1_SPEED_OFFSETS_MPH (converted and rounded to km/h
# on a metric device, as the profile writes them), SLCOverride, SLCPriority1 / SLCPriority3, SLCLookaheadLower and
# ShowSLCOffset. Its detector is the profile's own is_ap1() (CarModel or CarParamsPersistent TESLA_AP1_MODELS). A key
# the profile does not list keeps its registry default (SLCPriority2 "Map Data").
# Pre-AP Model S maps to the one-time legacy SLC profile (legacy_slc_profile_for_units in the same file): its
# SLCPriority1-3 (Dashboard / Map Data / Navigation) and look-ahead, plus the AP1 profile's Offset1-7 and SLCOverride.
# AP1 Model X and every other car are not listed and keep the general table; another car type is one more entry.
def _ap1_model_s(store) -> bool:
  from openpilot.common.bogpilot_ap1_profile import is_ap1
  return bool(is_ap1(store))


def _ap1_profile_values(store) -> dict[str, str]:
  from openpilot.common.bogpilot_ap1_profile import _profile_for_units
  return _profile_for_units(store)


def _preap_model_s(store) -> bool:
  from openpilot.common.bogpilot_ap1_profile import is_preap_slc_platform
  return bool(is_preap_slc_platform(store))


def _legacy_slc_values(store) -> dict[str, str]:
  from openpilot.common.bogpilot_ap1_profile import legacy_slc_profile_for_units
  return legacy_slc_profile_for_units(store)


SLC_RESET_PROFILES: tuple[tuple, ...] = (
  ("TESLA_AP1_MODELS", _ap1_model_s, _ap1_profile_values),
  ("TESLA_PREAP_MODELS", _preap_model_s, _legacy_slc_values),
)


def slc_reset_profile_entry(store):
  """The SLC_RESET_PROFILES entry for the current car, or None (general table)."""
  for entry in SLC_RESET_PROFILES:
    try:
      if entry[1](store):
        return entry
    except Exception:
      continue
  return None


def slc_reset_profile(store) -> dict[str, str] | None:
  """{key: stored text} of the current car's SLC reset profile, or None when the car uses the general table."""
  entry = slc_reset_profile_entry(store)
  return None if entry is None else dict(entry[2](store))


class SlcEditor:
  def __init__(self, CP, store, offroad):
    self.CP, self.store, self.offroad = CP, store, offroad

  def available(self):
    """The consumer runs on legacy Teslas (AP1 S, AP1 X, Pre-AP) with openpilot longitudinal."""
    return slc_supported(self.CP)

  def is_metric(self):
    return bool(self.store.get_bool("IsMetric", False))

  def visible(self, key):
    if not self.available() or key not in BY_KEY:
      return False
    return any(row[0] == key for sp in (None, *SUB_PANELS) for row in visible_rows(self.store, sp, self.CP))

  def can_edit(self, key):
    return bool(self.offroad()) and self.visible(key)

  def on(self, key):
    if key == PARENT_KEY:
      return slc_on(self.store)
    return bool(self.store.toggle_bool(key)) and slc_adopted(self.store)

  def choice(self, key):
    opts = dict(choice_options(self.store, key))
    try:
      v = int(self.store.get_int(key))
    except (TypeError, ValueError):
      v = 0
    return v if v in opts else min(opts)

  def offset(self, key):
    try:
      v = int(self.store.get_int(key))
    except (TypeError, ValueError):
      v = 0
    return clamp_offset(v, self.is_metric())

  def offset_text(self, value):
    return f"{int(value):+d} " + ("km/h" if self.is_metric() else "mph")

  def priority_options(self, key):
    return PRIORITY1_OPTIONS if key == "SLCPriority1" else PRIORITY_OTHER_OPTIONS

  def priority(self, key):
    try:
      v = self.store.get(key)
    except Exception:
      v = None
    return self._priority_shown(key, v)

  def _priority_shown(self, key, v):
    opts = self.priority_options(key)
    if v in opts:
      return v
    default = "Dashboard" if key == "SLCPriority1" else "None"
    return default if default in opts else opts[0]

  def seconds(self, key):
    try:
      v = self.store.get_int(key)
    except (TypeError, ValueError):
      v = LOOKAHEAD_HORIZON_DEFAULT
    return clamp_lookahead_horizon_s(v, LOOKAHEAD_HORIZON_DEFAULT)

  def seconds_text(self, value):
    return "Off" if value == 0 else f"{value} seconds"

  def reset_profile_values(self):
    """{row key: stored text} of this car's SLC reset profile (see SLC_RESET_PROFILES); {} for the general table."""
    try:
      # car detection may parse CarParamsPersistent; the rows ask every frame, so keep the answer for 1 s
      model, now = self.store.get("CarModel"), time.monotonic()
      cached = getattr(self, "_profile_cache", None)
      if cached is None or cached[0] != model or now - cached[1] > 1.0:
        cached = self._profile_cache = (model, now, slc_reset_profile_entry(self.store))
      if cached[2] is None:
        return {}
      return {k: v for k, v in cached[2][2](self.store).items() if k in BY_KEY}
    except Exception:
      return {}

  # ---- defaults for the value rows: exactly what this panel shows while the key is unsaved (no new number) ----
  # The store returns the registry default for an unsaved key (openpilot/common/bogpilot_params.py), and the readers
  # above parse it. So the default of a row is that same parse of the registry default:
  #   Offset1-4 "5", Offset5-7 "10"            bogpilot_params.py:277-283 (UI catalog bogpilot_defaults.py:198-204)
  #   SLCLookaheadLower "5"                     bogpilot_params.py:366 (UI catalog bogpilot_defaults.py:278),
  #                                             = LOOKAHEAD_HORIZON_DEFAULT (phase3_speed_control.py:64)
  #   SLCPriority1/2/3 Navigation / Map Data / Dashboard   bogpilot_params.py:370-372 (bogpilot_defaults.py:281-283);
  #     priority() shows them as they are because each is one of its row's options ("Dashboard" / "None" above is only
  #     for a stored value that is not an option).
  def default(self, key):
    """The value this row shows while its key is unsaved, or None when the key has no default (never invented).
    On a car with an SLC reset profile (AP1 Model S, Pre-AP) a row the profile writes defaults to that value."""
    from openpilot.common.bogpilot_store import registry_default
    if key not in BY_KEY:
      return None
    text = self.reset_profile_values().get(key)
    if text is None:
      text = registry_default(key)
    if text in (None, ""):
      return None
    kind = BY_KEY[key][1]
    try:
      if kind == "offset":
        return clamp_offset(int(float(text)), self.is_metric())
      if kind == "seconds":
        return clamp_lookahead_horizon_s(float(text), LOOKAHEAD_HORIZON_DEFAULT)
    except (TypeError, ValueError):
      return None
    if kind == "priority":
      return self._priority_shown(key, text)
    return None

  def default_text(self, key):
    d = self.default(key)
    if d is None:
      return None
    kind = BY_KEY[key][1]
    return self.offset_text(d) if kind == "offset" else self.seconds_text(d) if kind == "seconds" else d

  def shown_value(self, key):
    kind = BY_KEY[key][1]
    return self.offset(key) if kind == "offset" else self.seconds(key) if kind == "seconds" else self.priority(key)

  def at_default(self, key):
    from openpilot.selfdrive.ui.bogpilot.step_defaults import differs_from_default
    return not differs_from_default(self.shown_value(key), self.default(key))

  def section_defaults(self, keys):
    """Reset table for one section: each of its keys that has a default and can be edited right now (offroad, row
    shown for this car, Tuning Level and parent), with that default. Anything locked right now is left alone.
    With an SLC reset profile, a toggle or choice row the profile writes (ShowSLCOffset, SLCOverride) is reset too."""
    table = {k: self.default(k) for k in keys if self.default(k) is not None and self.can_edit(k)}
    prof = self.reset_profile_values()
    for k in keys:
      if k in table or k not in prof or not self.can_edit(k):
        continue
      kind = BY_KEY[k][1]
      try:
        if kind == "toggle":
          table[k] = prof[k] == "1"
        elif kind == "choice":
          table[k] = int(float(prof[k]))
      except (TypeError, ValueError):
        pass
    return table

  def profile_reset_rows(self, keys):
    """Toggle / choice row keys among keys that this car's SLC reset profile writes (empty with the general table)."""
    prof = self.reset_profile_values()
    return tuple(k for k in keys if k in prof and BY_KEY[k][1] in ("toggle", "choice"))

  def reset_write(self, key, value):
    """Section-reset writer: the same guarded write as the -/+ buttons; a refused write raises (the row reports it)."""
    if not self.write(key, value):
      raise PermissionError(f"{key} was not reset")

  def write(self, key, value):
    if not self.can_edit(key):
      return False
    kind = BY_KEY[key][1]
    if kind == "toggle":
      if not isinstance(value, bool):
        return False
    elif kind == "choice":
      if isinstance(value, bool) or not isinstance(value, int) or value not in dict(choice_options(self.store, key)):
        return False
    elif kind == "offset":
      if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
      lo, hi = OFFSET_RANGE[self.is_metric()]
      if not lo <= value <= hi:
        return False
      value = int(round(value))
    elif kind == "seconds":
      if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
      if not LOOKAHEAD_HORIZON_MIN <= value <= LOOKAHEAD_HORIZON_MAX:
        return False
      value = int(round(value))
    elif kind == "priority":
      if not isinstance(value, str) or value not in self.priority_options(key):
        return False
    else:
      return False
    if not self.offroad():   # re-check at callback time (queued touch after going onroad)
      return False
    configure(self.store, key, value)
    return True

  def step_offset(self, key, delta):
    return self.write(key, self.offset(key) + delta)

  def step_seconds(self, key, delta):
    return self.write(key, self.seconds(key) + int(delta))

  def step_priority(self, key, delta):
    opts = self.priority_options(key)
    cur = self.priority(key)
    idx = opts.index(cur) if cur in opts else 0
    return self.write(key, opts[(idx + int(delta)) % len(opts)])


def make_layout(CP, store, offroad, section=None, open_section=None):
  """Raylib list for one section. section None = parent + choices + a button per sub panel; a SUB_PANELS key = its rows."""
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import toggle_item, button_item
  from openpilot.selfdrive.ui.bogpilot.gated_actions import (RESET_SECTION_TITLE, gated_multiple_button_item,
                                                             gated_value_step_item, reset_section_item)
  from openpilot.selfdrive.ui.bogpilot import tuning_level
  from openpilot.selfdrive.ui.bogpilot.nesting import indent_under
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  # Shared value row per value kind: (minus, plus, button width). ASCII "-" (the font has no U+2212). Steps unchanged.
  # Plain -/+ on the stepper buttons; the step size is set by _step, not by the label.
  STEP_CHROME = {"offset": ("-", "+", 220), "seconds": ("-", "+", 260), "priority": ("Prev", "Next", 260)}

  class SlcLayout(Widget):
    def __init__(self):
      super().__init__()
      self.editor = SlcEditor(CP, store, offroad)
      self._build()

    def _shown(self):
      if not self.editor.available():
        return ()
      subs = tuple(visible_sub_panels(store, CP)) if section is None else ()
      return (tuple(r[0] for r in visible_rows(store, section, CP)), subs, self.editor.is_metric())

    def _build(self):
      self.toggles, self.choices = {}, {}
      self.shown = self._shown()
      items = []
      values = []   # (key, row) of this section's value rows, for its one reset row
      e = self.editor   # bound once, outside the loop, for the value rows' callbacks
      for row in (visible_rows(store, section, CP) if self.editor.available() else []):
        key, kind, title, desc, _, _ = row
        k = key
        if kind == "toggle":
          item = toggle_item(title, (desc or "") + ("<br><br>" if desc else "") + APPLIES, self.editor.on(k),
                             callback=lambda v, k=k: self._toggle(k, v), enabled=lambda k=k: self.editor.can_edit(k))
          self.toggles[k] = item
          items.append(item)
        elif kind == "choice":
          opts = choice_options(store, k)
          idx = [o[0] for o in opts].index(self.editor.choice(k))
          ov = [o[0] for o in opts]
          # D2: lock the action (not only the ListItem) and show the stored choice, never a refused tap.
          item = gated_multiple_button_item(title, desc + "<br><br>" + APPLIES, [o[1] for o in opts], idx, button_width=300,
                                            button_widths=[CHOICE_PILL_WIDTHS.get(o[1], 300) for o in opts],
                                            callback=lambda i, k=k, ov=ov: self._choose(k, ov[i]),
                                            enabled=lambda k=k: self.editor.can_edit(k),
                                            selected_source=lambda k=k, ov=ov: ov.index(self.editor.choice(k)))
          item.set_enabled(lambda k=k: self.editor.can_edit(k))
          self.choices[k] = item
          items.append(item)
        elif kind in STEP_CHROME:
          # One row: [-] [value] [+] (was a text row plus a red button row). Same steps, same lock, same writes.
          minus, plus, width = STEP_CHROME[kind]
          if kind == "offset":
            row_title, row_desc, shown = (lambda k=k: offset_title(k, e.is_metric())), APPLIES, (lambda k=k: e.offset_text(e.offset(k)))
          elif kind == "seconds":
            row_title, row_desc, shown = title, (desc or "") + ("<br><br>" if desc else "") + APPLIES, (lambda k=k: e.seconds_text(e.seconds(k)))
          else:
            row_title, row_desc, shown = title, (desc or "") + ("<br><br>" if desc else "") + APPLIES, (lambda k=k: e.priority(k))
          item = gated_value_step_item(row_title, row_desc, shown, on_minus=lambda k=k: self._step(k, -1),
                                       on_plus=lambda k=k: self._step(k, +1), minus=minus, plus=plus, button_width=width,
                                       enabled=lambda k=k: e.can_edit(k), default_text=lambda k=k: e.default_text(k),
                                       is_default=lambda k=k: e.at_default(k), translate=tr)
          values.append((k, item))
          items.append(item)
      self.reset = None
      # With an SLC reset profile (AP1 Model S, Pre-AP): toggle / choice rows the profile writes reset with it.
      shown_keys = tuple(r[0] for r in (visible_rows(store, section, CP) if self.editor.available() else []))
      prof_rows = tuple((k, self.toggles.get(k) or self.choices.get(k)) for k in e.profile_reset_rows(shown_keys))
      prof_rows = tuple((k, i) for k, i in prof_rows if i is not None)
      if values or prof_rows:
        # One reset row for the section, right after its value rows: asks first, then writes only those keys back to
        # the defaults above (SlcEditor.default). Locked whenever none of them can be edited; shown only while one of
        # its rows is shown, and behind the Speed Limit Controller's own Tuning Level.
        keys = tuple(k for k, _ in values) + tuple(k for k, _ in prof_rows)
        rows_of_reset = tuple(i for _, i in values) + tuple(i for _, i in prof_rows)
        self.reset = reset_section_item(lambda: self.editor.section_defaults(keys), self.editor.reset_write,
                                        title=lambda: tr(RESET_SECTION_TITLE),
                                        enabled=lambda: any(self.editor.can_edit(k) for k in keys),
                                        on_done=self._after_reset)
        self.reset.set_visible(lambda: any(i.is_visible for i in rows_of_reset))
        self.reset.set_level_gate(lambda: tuning_level.row_visible(PARENT_KEY))
        items.append(self.reset)
      if section is None and open_section is not None:
        for sp in visible_sub_panels(store, CP):
          items.append(button_item(SUB_PANELS[sp], "OPEN", callback=lambda sp=sp: open_section(sp)))
      parent = self.toggles.get(PARENT_KEY)
      if parent is not None:
        # Everything under the switch sits one level in (Appearance style). Visibility already follows the saved values
        # (visible_rows), so this only indents; the OPEN rows keep their behavior.
        indent_under(parent, *(i for i in items if i is not parent))
      self.scroller = Scroller(items, line_separator=True, spacing=0)

    def _toggle(self, key, value):
      self.editor.write(key, bool(value))
      self._refresh()

    def _choose(self, key, value):
      self.editor.write(key, int(value))
      self._refresh()

    def _step(self, key, delta):
      kind = BY_KEY[key][1]
      if kind == "seconds":
        self.editor.step_seconds(key, delta)
      elif kind == "priority":
        self.editor.step_priority(key, delta)
      else:
        self.editor.step_offset(key, delta)
      self._refresh()

    def _after_reset(self):
      store.invalidate()
      self._build()          # a reset can change which rows show (Priority 1 back from Highest / Lowest)
      self.scroller.show_event()

    def _refresh(self):
      store.invalidate()
      if self._shown() != self.shown:
        self._build()
        self.scroller.show_event()

    def show_event(self):
      super().show_event()
      self._refresh()
      for key, item in self.toggles.items():
        item.action_item.set_state(self.editor.on(key))
      self.scroller.show_event()

    def _render(self, rect):
      self.scroller.render(rect)

  return SlcLayout()
