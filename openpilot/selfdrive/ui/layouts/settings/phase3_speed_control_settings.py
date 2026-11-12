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

  def priority_options(self, key):
    return PRIORITY1_OPTIONS if key == "SLCPriority1" else PRIORITY_OTHER_OPTIONS

  def priority(self, key):
    opts = self.priority_options(key)
    try:
      v = self.store.get(key)
    except Exception:
      v = None
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
  from openpilot.system.ui.widgets.list_view import toggle_item, text_item, button_item
  from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_dual_button_item, gated_multiple_button_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller

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
                                            callback=lambda i, k=k, ov=ov: self._choose(k, ov[i]),
                                            enabled=lambda k=k: self.editor.can_edit(k),
                                            selected_source=lambda k=k, ov=ov: ov.index(self.editor.choice(k)))
          item.set_enabled(lambda k=k: self.editor.can_edit(k))
          self.choices[k] = item
          items.append(item)
        elif kind == "offset":
          items.append(text_item(lambda k=k: offset_title(k, self.editor.is_metric()),
                                 lambda k=k: f"{self.editor.offset(k):+d} " + ("km/h" if self.editor.is_metric() else "mph"),
                                 APPLIES))
          items.append(gated_dual_button_item("−1", "+1", left_callback=lambda k=k: self._step(k, -1),
                                        right_callback=lambda k=k: self._step(k, +1), enabled=lambda k=k: self.editor.can_edit(k)))
        elif kind == "seconds":
          items.append(text_item(title, lambda k=k: "Off" if self.editor.seconds(k) == 0 else f"{self.editor.seconds(k)} seconds",
                                 (desc or "") + ("<br><br>" if desc else "") + APPLIES))
          items.append(gated_dual_button_item("−1", "+1", left_callback=lambda k=k: self._step(k, -1),
                                        right_callback=lambda k=k: self._step(k, +1), enabled=lambda k=k: self.editor.can_edit(k)))
        elif kind == "priority":
          items.append(text_item(title, lambda k=k: self.editor.priority(k),
                                 (desc or "") + ("<br><br>" if desc else "") + APPLIES))
          items.append(gated_dual_button_item("Prev", "Next", left_callback=lambda k=k: self._step(k, -1),
                                        right_callback=lambda k=k: self._step(k, +1), enabled=lambda k=k: self.editor.can_edit(k)))
      if section is None and open_section is not None:
        for sp in visible_sub_panels(store, CP):
          items.append(button_item(SUB_PANELS[sp], "OPEN", callback=lambda sp=sp: open_section(sp)))
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
