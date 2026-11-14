"""BogPilot > Driving Controls > Gas / Brake: Driving Personalities (nested Aggressive / Standard / Relaxed with
Following Distance, five smoothness rows, Reset to Defaults), Human-Like Following and Lead Detection Confidence Threshold.

Labels, nesting, ranges and reset semantics: own 0.9.7 04d560f3 bogpilot/ui/qt/offroad/longitudinal_settings.cc
:107-142 (labels), :299-363 (controls/ranges), :689-764 (reset), :966-1050 (visibility). Gas / Brake is only shown
with openpilot longitudinal (bogpilot_settings.cc:447). Writes go through controls.lib.phase3_following.configure /
reset_personality (adoption markers) and are refused unless offroad AND the row is currently editable.
LongitudinalTune (parent of HumanFollowing / LeadDetectionThreshold) is SHARED with the Gas/Brake page; this module only reads it.
Parent integrator: make_layout(CP, ParamStore(), lambda: not ui_state.started, section).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from openpilot.selfdrive.controls.lib.phase3_following import (PROFILES, PROFILE_SUFFIXES, STOCK_LEAD_PROB, configure,
                                                              group_adopted, human_following_default_on,
                                                              reset_personality)


def tr_noop(s):
  return s


@dataclass(frozen=True)
class Row:
  key: str
  kind: str          # manage | value | reset | toggle
  title: str
  desc: str
  parent: str | None
  minimum: float = 0.
  maximum: float = 0.
  step: float = 1.
  unit: str = ""


_P_DESC = {
  "Aggressive": "Designed for assertive driving with tighter gaps.",
  "Standard": "Designed for balanced driving with moderate gaps.",
  "Relaxed": "Designed for smoother, more comfortable driving with larger gaps.",
}
_P_FOLLOW_DEFAULT = {"Aggressive": "1.25", "Standard": "1.45", "Relaxed": "1.75"}
_SUB = (
  ("JerkAcceleration", "Acceleration Smoothness", "<b>How smoothly openpilot accelerates with the \"{p}\" profile.</b> Increase for gentler starts; decrease for faster but more abrupt takeoffs."),
  ("JerkDeceleration", "Braking Smoothness", "<b>How smoothly openpilot brakes with the \"{p}\" profile.</b> Increase for gentler stops; decrease for quicker but sharper braking."),
  ("JerkDanger", "Safety Gap Bias", "<b>How much extra space openpilot keeps from the vehicle ahead with the \"{p}\" profile.</b> Increase for larger gaps and more cautious following; decrease for tighter gaps and closer following."),
  ("JerkSpeedDecrease", "Slowdown Response", "<b>How smoothly openpilot slows down with the \"{p}\" profile.</b> Increase for more gradual deceleration; decrease for faster but sharper slowdowns."),
  ("JerkSpeed", "Speed-Up Response", "<b>How smoothly openpilot speeds up with the \"{p}\" profile.</b> Increase for more gradual acceleration; decrease for quicker but more jolting acceleration."),
)


def _rows():
  rows = [Row("CustomPersonalities", "manage", tr_noop("Driving Personalities"),
              tr_noop("<b>Customize the \"Driving Personalities\"</b> to better match your driving style."), None)]
  for p in PROFILES:
    prof = f"{p}PersonalityProfile"
    rows.append(Row(prof, "manage", tr_noop(p), f"<b>Customize the \"{p}\" personality profile.</b> {_P_DESC[p]}",
                    "CustomPersonalities"))
    rows.append(Row(f"{p}Follow", "value", tr_noop("Following Distance"),
                    f"<b>How many seconds openpilot follows behind lead vehicles when using the \"{p}\" profile.</b> "
                    f"Increase for more space; decrease for tighter gaps.<br><br>Default: {_P_FOLLOW_DEFAULT[p]} seconds.",
                    prof, 1., 3., 0.01, " seconds"))
    for suffix, title, desc in _SUB:
      rows.append(Row(f"{p}{suffix}", "value", tr_noop(title), desc.format(p=p), prof, 25., 200., 1., "%"))
    rows.append(Row(f"Reset{p}Personality", "reset", tr_noop("Reset to Defaults"),
                    f"<b>Reset the \"{p}\" profile to defaults.</b>", prof))
  rows.append(Row("HumanFollowing", "toggle", tr_noop("Human-Like Following"),
                  tr_noop("<b>Following behavior that mimics human drivers</b> by closing gaps behind faster vehicles for "
                          "quicker takeoffs and dynamically adjusting the desired following distance for gentler, more "
                          "efficient braking."), "LongitudinalTune"))
  rows.append(Row("LeadDetectionThreshold", "value", tr_noop("Lead Detection Confidence Threshold"),
                  tr_noop("<b>How sure the driving model must be that an object is a vehicle before it counts as a lead.</b> "
                          "Lower values detect leads sooner and farther away but may react to false leads; higher values "
                          "are more conservative and reduce false detections."), "LongitudinalTune", 25., 50., 1., "%"))
  return tuple(rows)


ROWS = _rows()
BY_KEY = {r.key: r for r in ROWS}
OWNED_KEYS = tuple(r.key for r in ROWS)   # 26 params + 3 reset actions
SHARED_PARENT = "LongitudinalTune"
APPLIES = "Applies next drive (planner/radard read settings at start)."


class FollowingEditor:
  def __init__(self, CP, store, offroad):
    self.CP, self.store, self.offroad = CP, store, offroad

  def op_long(self):
    return bool(getattr(self.CP, "openpilotLongitudinalControl", False)) if self.CP is not None else False

  def on(self, key):
    """What the planner/radard actually do, not just what is stored. Under the default_on policy every group is on, so
    the stored value shows (under the adoption policy an un-adopted group reads OFF). Human-Like Following also reads
    OFF on a Pre-AP Model S that started without the Bosch radar, as the runtime does (human_following_default_on)."""
    if key not in BY_KEY:   # owned by another lane (LongitudinalTune): plain stored value
      return bool(self.store.toggle_bool(key))
    if key == "HumanFollowing" and not human_following_default_on(self.CP):
      return False
    return bool(self.store.toggle_bool(key)) and group_adopted(self.store, key)

  def visible(self, key):
    """04d560f3 updateToggles: tuning level (reset rows have no level -> always), then reachable only through
    an enabled parent (BogPilotManageControl opens the sub panel only while its toggle is on)."""
    row = BY_KEY[key]
    if not self.op_long():
      return False
    if row.kind != "reset" and not self.store.honoured(key):
      return False
    parent = row.parent
    while parent is not None:
      if not self.on(parent):
        return False
      parent = BY_KEY[parent].parent if parent in BY_KEY else None
    return True

  def can_edit(self, key):
    if key == "HumanFollowing" and not human_following_default_on(self.CP):
      return False   # Pre-AP without the Bosch radar at start: shown Off and greyed, nothing to store
    return key in BY_KEY and bool(self.offroad()) and self.visible(key)

  def write(self, key, value):
    if not self.can_edit(key):
      return False
    row = BY_KEY[key]
    if row.kind in ("toggle", "manage"):
      if not isinstance(value, bool):
        return False
    elif row.kind == "value":
      if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
      if not row.minimum <= value <= row.maximum:
        return False
      value = round(float(value), 2) if row.step < 1 else float(round(value))
    else:
      return False
    if not self.offroad():   # re-check at callback time (queued touch after going onroad)
      return False
    configure(self.store, key, value)
    return True

  def reset(self, profile):
    key = f"Reset{profile}Personality"
    if not self.can_edit(key) or not self.offroad():
      return False
    reset_personality(self.store, profile)
    return True

  def value(self, key):
    row = BY_KEY[key]
    if key == "LeadDetectionThreshold" and not group_adopted(self.store, key):
      return min(max(STOCK_LEAD_PROB * 100., row.minimum), row.maximum)   # radard uses the stock 0.5 until adopted
    try:
      v = float(self.store.get_float(key))
    except (TypeError, ValueError):
      v = float("nan")
    if not math.isfinite(v):
      v = float(self.store.default(key))
    return min(max(v, row.minimum), row.maximum)

  def label(self, key):
    row = BY_KEY[key]
    v = self.value(key)
    if row.unit == " seconds":
      # Number only: "1.25 seconds" (~255 px at 40 px Inter Medium) overran the 150 px value pill. The grey hint
      # under the pill keeps the unit ("default: 1.25 seconds", default_shown below).
      return f"{v:.2f}"
    return f"{v:.0f}{row.unit}"

  def default(self, key):
    """The existing default a value row shows as "default: X", or None when there is none to show.

    Following Distance uses the table already in this file (`_P_FOLLOW_DEFAULT`: Aggressive 1.25, Standard 1.45,
    Relaxed 1.75) and the same numbers in bogpilot_defaults.py (AggressiveFollow, StandardFollow, RelaxedFollow),
    unless this car's reset profile sets the key (AP1 Model S: RelaxedFollow 2.0 s from the AP1 profile).
    Jerk rows and Lead Detection use store.default(key), the same source value() already falls back to:
    Aggressive jerks 50 except Danger 100; Standard/Relaxed jerks 100 (bogpilot_defaults.py); Lead Detection 35.
    A missing or non-finite catalog entry is not a default: no hint and no reset for that key.
    """
    row = BY_KEY.get(key)
    if row is None or row.kind != "value":
      return None
    try:
      from openpilot.selfdrive.ui.bogpilot.step_defaults import car_type_reset_values
      text = car_type_reset_values(self.store).get(key)
      v = float(text) if text is not None else float(self.store.default(key))
    except (TypeError, ValueError, KeyError, AttributeError):
      return None
    return v if math.isfinite(v) else None

  def default_shown(self, key):
    """Hint text in the same units as the live value, or None when there is no default."""
    d = self.default(key)
    if d is None:
      return None
    row = BY_KEY[key]
    if row.unit == " seconds":
      return f"{d:.2f}" + (" second" if round(d / 0.01) == 100 else " seconds")
    return f"{d:.0f}{row.unit}" if row.unit == "%" else f"{d:g}{row.unit}"

  def at_default(self, key):
    """True unless the value in effect differs from the existing default. An unknown value is not highlighted."""
    from openpilot.selfdrive.ui.bogpilot.step_defaults import differs_from_default
    d = self.default(key)
    if d is None:
      return True
    try:
      v = self.value(key)
    except (KeyError, TypeError, ValueError):
      return True
    if not math.isfinite(v):
      return True
    return not differs_from_default(v, d)

  def section_defaults(self, keys):
    """Reset table for a section: each of its value keys that can be edited right now, with its existing default.
    A key locked at this moment (onroad, Tuning Level, parent off, no long control) is left alone."""
    return {k: self.default(k) for k in keys if self.default(k) is not None and self.can_edit(k)}


def profile_value_keys(profile):
  """Follow + five jerk keys for one profile (the keys a section reset may write)."""
  return (f"{profile}Follow", *(f"{profile}{s}" for s, _, _ in _SUB))


def visible_rows(editor, section=None):
  """section None = Gas / Brake level rows; 'personalities' = profile list; profile name = that profile."""
  if section is None:
    keys = ("CustomPersonalities",)
  elif section == "longitudinal_tuning":
    # 04d560f3 order: AccelerationProfile, DecelerationProfile, HumanAcceleration, HumanFollowing,
    # HumanLaneChanges (mounted by make_layout), LeadDetectionThreshold, TacoTune (not ported)
    keys = ("HumanFollowing", "LeadDetectionThreshold")
  elif section == "personalities":
    keys = tuple(f"{p}PersonalityProfile" for p in PROFILES)
  elif section in PROFILES:
    keys = (f"{section}Follow", *(f"{section}{s}" for s, _, _ in _SUB), f"Reset{section}Personality")
  else:
    raise ValueError(section)
  return [BY_KEY[k] for k in keys if editor.visible(k)]


def _human_lane_change_item(store, CP, runtime_integrated, offroad):
  """The lane-change page owns HumanLaneChanges; mount its item, never a duplicate."""
  try:
    from openpilot.selfdrive.ui.bogpilot.phase3_lanechange import human_lane_change_item
  except ImportError:
    return None
  try:
    return human_lane_change_item(store, CP, runtime_integrated=runtime_integrated, offroad=offroad)
  except AttributeError:   # a live CarParams proxy with no CarParams yet: no row
    return None


def _manage_toggle_item(title, desc, state, toggle_callback, toggle_enabled, manage_callback, manage_enabled, icon=None):
  """One row with the switch AND the MANAGE button, like the 0.9.7 manage-control widget:
  MANAGE is enabled only while the switch is on. icon: optional section icon (path under selfdrive/assets/icons)."""
  import pyray as rl
  from openpilot.system.ui.widgets.button import Button, ButtonStyle
  from openpilot.system.ui.widgets.list_view import (BUTTON_BORDER_RADIUS, BUTTON_FONT_SIZE, BUTTON_FONT_WEIGHT, BUTTON_HEIGHT,
                                                     BUTTON_WIDTH, ItemAction, ListItem)
  from openpilot.system.ui.widgets.toggle import HEIGHT as TOGGLE_HEIGHT, Toggle, WIDTH as TOGGLE_WIDTH

  gap = 30

  class ManageToggleAction(ItemAction):
    def __init__(self):
      super().__init__(BUTTON_WIDTH + gap + TOGGLE_WIDTH)
      self.toggle_enabled = toggle_enabled
      self.manage_enabled = manage_enabled
      self.toggle = Toggle(initial_state=state, callback=toggle_callback)
      self.manage = Button("MANAGE", font_size=BUTTON_FONT_SIZE, font_weight=BUTTON_FONT_WEIGHT,
                           button_style=ButtonStyle.LIST_ACTION, border_radius=BUTTON_BORDER_RADIUS,
                           click_callback=manage_callback, text_padding=0)
      self.toggle.set_enabled(bool(toggle_enabled()))
      self.manage.set_enabled(bool(manage_enabled()))

    def set_touch_valid_callback(self, touch_callback):
      super().set_touch_valid_callback(touch_callback)
      self.toggle.set_touch_valid_callback(touch_callback)
      self.manage.set_touch_valid_callback(touch_callback)

    def set_state(self, value):
      self.toggle.set_state(value)

    def get_state(self):
      return self.toggle.get_state()

    def _render(self, rect):
      row_on = bool(self.enabled)
      self.toggle.set_enabled(row_on and bool(toggle_enabled()))
      self.manage.set_enabled(row_on and bool(manage_enabled()))
      x = rect.x + rect.width - TOGGLE_WIDTH
      self.toggle.render(rl.Rectangle(x, rect.y + (rect.height - TOGGLE_HEIGHT) / 2, TOGGLE_WIDTH, TOGGLE_HEIGHT))
      self.manage.render(rl.Rectangle(x - gap - BUTTON_WIDTH, rect.y + (rect.height - BUTTON_HEIGHT) / 2, BUTTON_WIDTH, BUTTON_HEIGHT))
      return False

  return ListItem(title=title, description=desc, action_item=ManageToggleAction(), icon=icon)


def build_items(editor, store, CP, section=None, confirm=None, request_confirm=None, lead_items=(),
                runtime_integrated=False, refresh=None):
  """List items for one section (the rows of make_layout). Returns (items, toggles); toggles = {key: item} for the
  rows whose switch state show_event() re-reads.

  confirm(text)->bool is the synchronous reset question; request_confirm(text, on_yes) is the asynchronous form a
  dialog stack needs (the reset runs from on_yes only). refresh() is called after a write (the page rebuilds there).

  section "personalities" is one inline page: each profile switch is followed by its own rows (Following Distance, the five
  smoothness rows, and one Reset section to defaults), indented under it and present only while that profile is on."""
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets.list_view import toggle_item
  from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_value_step_item, reset_section_item, RESET_SECTION_TITLE, MINUS, PLUS
  from openpilot.selfdrive.ui.bogpilot.nesting import indent_under
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  from openpilot.selfdrive.ui.bogpilot import tuning_level

  toggles = {}
  items = list(lead_items) if section == "longitudinal_tuning" else []
  value_items = []

  # Hosts may still pass the older synchronous confirm(text)->bool; wrap it for the shared reset row.
  if request_confirm is None and confirm is not None:
    def request_confirm(text, on_yes, _ask=confirm):
      if _ask(text):
        on_yes()

  def after():
    if refresh is not None:
      refresh()

  def toggle(key, value):
    editor.write(key, bool(value))
    after()

  def must(ok, key):
    # A refused write raises, so the shared reset row stops and tells the user instead of failing silently.
    if not ok:
      raise PermissionError(f"{key} was not reset")

  def stepper(row):
    # One row: [minus] [value] [plus]. Minus is ASCII "-" (the Inter atlas has no U+2212).
    # Grey "default: X" under the value; the value is outlined when it is not the default.
    k = row.key
    item = gated_value_step_item(row.title, row.desc + "<br><br>" + APPLIES,
                                 lambda k=k: editor.label(k),
                                 lambda k=k, r=row: editor.write(k, editor.value(k) - r.step),
                                 lambda k=k, r=row: editor.write(k, editor.value(k) + r.step),
                                 minus=MINUS, plus=PLUS,   # plain -/+; row.step is unchanged
                                 enabled=lambda k=k: editor.can_edit(k),
                                 default_text=lambda k=k: editor.default_shown(k),
                                 is_default=lambda k=k: editor.at_default(k),
                                 translate=tr)
    return attach_help(item, k)

  def add_section_reset(parent, keys, rows, parent_in_section=False):
    # One "Reset section to defaults" row: asks first, then writes these keys back to their existing defaults and, when
    # the section's own switch sits with it (a personality profile), that switch back to its shipped default, last.
    # Shown only while one of its value rows is shown, and also behind the parent toggle's Tuning Level, so it is
    # hidden whenever the rows it resets are hidden. Enabled only while one of those keys can be edited.
    from openpilot.selfdrive.ui.bogpilot.step_defaults import whole_section

    def table(keys=keys, parent=parent):
      from openpilot.selfdrive.ui.bogpilot.step_defaults import car_type_overrides
      ov_keys = list(keys) + ([parent] if parent_in_section and parent is not None else [])
      return whole_section(editor.section_defaults(keys), parent=parent if parent_in_section else None,
                           can_edit=editor.can_edit, overrides=car_type_overrides(editor.store, ov_keys))
    item = reset_section_item(table,
                              lambda k, default: must(editor.write(k, default), k),
                              title=lambda: tr(RESET_SECTION_TITLE),
                              enabled=lambda keys=keys: any(editor.can_edit(k) for k in keys),
                              request_confirm=request_confirm)
    item.set_visible(lambda rows=rows: any(r.is_visible for r in rows))
    item.set_level_gate(lambda p=parent: tuning_level.row_visible(p))
    attach_help(item, "section.reset_defaults")
    items.append(item)
    return item

  for row in visible_rows(editor, section):
    k = row.key
    if row.kind in ("toggle", "manage"):
      item = toggle_item(row.title, row.desc + "<br><br>" + APPLIES, editor.on(k),
                         callback=lambda v, k=k: toggle(k, v), enabled=lambda k=k: editor.can_edit(k))
      attach_help(item, k)
      toggles[k] = item
      items.append(item)
      if section == "personalities":
        profile = k.replace("PersonalityProfile", "")
        children, _ = build_items(editor, store, CP, profile, confirm, request_confirm, refresh=refresh)
        indent_under(item, *children)   # visible only while this profile is on (editor.visible), so the page rebuilds on a toggle
        items.extend(children)
    if k == "HumanFollowing":
      lc_item = _human_lane_change_item(store, CP, runtime_integrated, editor.offroad)
      if lc_item is not None:
        items.append(attach_help(lc_item, "HumanLaneChanges"))
    if row.kind == "value":
      item = stepper(row)
      items.append(item)
      value_items.append((k, item))
    if row.kind == "reset":
      p = k[len("Reset"):-len("Personality")]
      keys = profile_value_keys(p)
      rows = [it for key, it in value_items if key in keys]
      add_section_reset(row.parent, keys, rows, parent_in_section=True)
  if section == "longitudinal_tuning":
    # Lead Detection has no pre-existing RESET row; its parent toggle lives on the Gas / Brake page.
    lead_rows = [it for key, it in value_items if key == "LeadDetectionThreshold"]
    if lead_rows:
      add_section_reset("LongitudinalTune", ("LeadDetectionThreshold",), lead_rows)
  return items, toggles


def shown_keys(editor, section):
  """The row keys the page shows now; the page rebuilds when this changes. 'personalities' includes each shown profile's rows."""
  rows = visible_rows(editor, section)
  keys = [r.key for r in rows]
  if section == "personalities":
    for r in rows:
      keys += [c.key for c in visible_rows(editor, r.key.replace("PersonalityProfile", ""))]
  return tuple(keys)


def make_layout(CP, store, offroad, section=None, confirm=None, lead_items=(), runtime_integrated=False,
                request_confirm=None):
  """Raylib list for one section. Value rows use the shared stepper (grey default hint, highlight when changed).
  Each section has one "Reset section to defaults" row (shared confirm). confirm and request_confirm are accepted
  so a host can still inject the dialog; the shared reset row is the one that asks.
  section "longitudinal_tuning": lead_items = the already-built Acceleration/Deceleration/HumanAcceleration
  items (placed first); the delivered human_lane_change_item is mounted after Human-Like Following
  (runtime_integrated passed through; that helper gates itself until its consumer is integrated)."""
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  class FollowingLayout(Widget):
    def __init__(self):
      super().__init__()
      self.editor = FollowingEditor(CP, store, offroad)
      self._build()

    def _build(self):
      self.shown = shown_keys(self.editor, section)
      items, self.toggles = build_items(self.editor, store, CP, section, confirm, request_confirm, lead_items,
                                        runtime_integrated, refresh=self._refresh)
      self.scroller = Scroller(items, line_separator=True, spacing=0)

    def _refresh(self):
      store.invalidate()
      if shown_keys(self.editor, section) != self.shown:
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

  return FollowingLayout()
