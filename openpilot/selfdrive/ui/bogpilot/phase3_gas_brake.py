"""BogPilot > Driving Controls > Gas / Brake.

Composes the two consumer-backed Gas / Brake lanes under ONE page:
  Advanced Longitudinal Tuning   Actuator Delay, Maximum Acceleration, Stop Acceleration, Stopping Rate
  Driving Personalities          switch + MANAGE on this page; Aggressive / Standard / Relaxed on the next
  Longitudinal Tuning            Acceleration / Deceleration profile, Human-Like Acceleration, Human-Like Following,
                                 Human Lane Changes, Lead Detection Confidence Threshold
  Quality of Life                Force Stop, Increase Stopped Distance, manual weather offsets
  Speed Limit Controller         the Speed Limit Controller on AP1 Model S and on Pre-AP with the pedal (fallback,
                                 override, offsets, confirmation, visuals)

Every row writes through the shared ParamStore with a BLOCKING Params write and a read-back before its
internal adoption marker (see common/bogpilot_store.ParamStore.put(block=True)). Importing this module and
opening/closing the page never writes a preference or an adoption marker. Writes are refused unless the
car is offroad AND the live CarParams report openpilot longitudinal control (re-checked on every write).
"""
from __future__ import annotations

from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake_mounts as mounts
from openpilot.selfdrive.ui.bogpilot.phase3_stopping_settings import StoppingCapabilities, StoppingSettingsLayout
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import (
  Capabilities, GROUPS, HISTORICAL_DESCRIPTIONS, make_settings,
)

PAGE_KEY = "gas_brake"
PAGE_TITLE = "Gas / Brake"
TAP_FROM_ZERO_KEY = "AP1TapFromZeroMph"
TAP_FROM_ZERO_TITLE = "Standstill Tap Speed"
TAP_FROM_ZERO_DESC = (
  "AP1: a standstill engage with no known speed limit; the car will drive off to this speed. Pre-AP with the Comma Pedal: "
  "a double pull at a stop sets this speed. Press the accelerator to pull away. Tip the stalk up or down to change it."
)
# Consumer-backed control IDs (feeds Page.controls so an empty page is omitted by the navigation).
CONTROLS = ("LongitudinalActuatorDelay", "MaxDesiredAcceleration", "StopAccel", "StoppingDecelRate",
            "AccelerationProfile", "DecelerationProfile", "HumanAcceleration",
            "CustomPersonalities", "HumanFollowing", "HumanLaneChanges",
            "LeadDetectionThreshold", "ForceStops", "IncreasedStoppedDistance", "WeatherPresets", "SpeedLimitController")

# Capabilities of THIS build. Navigation/SLC/v9-prediction/gears/weather producers are NOT installed, and the
# following/acceleration/curve weather consumers are not wired, so those rows stay hidden.
ACCEL_CAPABILITIES = Capabilities()
STOPPING_CAPABILITIES = StoppingCapabilities(stopped_distance=True, force_stop_inputs=True)


class LiveCP:
  """Always resolves the CURRENT UI CarParams; no CarParams means no openpilot longitudinal control."""
  def __init__(self, source):
    self._source = source

  def _cp(self):
    return self._source()

  @property
  def openpilotLongitudinalControl(self):
    cp = self._cp()
    return bool(cp is not None and cp.openpilotLongitudinalControl)

  def __getattr__(self, name):
    cp = self._cp()
    if cp is None:
      raise AttributeError(name)
    return getattr(cp, name)


_pill_state = None


def pill_visible() -> bool:
  """Whether the GAS / BRAKE pill is on the menu now (see menu_locks.gas_brake_pill_visible). Re-read twice a second at most."""
  global _pill_state
  if _pill_state is None:
    from openpilot.selfdrive.ui.bogpilot import menu_locks

    def read():
      try:
        from openpilot.selfdrive.ui.ui_state import ui_state
        return menu_locks.gas_brake_pill_visible(ui_state.CP, menu_locks.effective_disable_toggle())
      except Exception:
        return True   # when in doubt show it, as 0.9.7 did before it knew the car
    _pill_state = menu_locks.cached(read)
  return bool(_pill_state())


def root_entries(store, cp=None):
  """(key, title, description) for the page's top menu; pure data, no widgets.

  cp: optional CarParams (or the live proxy). The Speed Limit Controller entry is hidden for a car its consumer does not
  drive (no inert row); with no CarParams yet it shows, greyed out, like the other longitudinal entries."""
  entries = []
  for group in ("advanced", "profiles"):   # no "conditional": Conditional Experimental Mode is removed
    parent, title, _ack, keys = GROUPS[group]
    if group == "profiles" and store.honoured(mounts.PERSONALITIES_KEY):
      entries.append(("personalities", mounts.PERSONALITIES_TITLE, mounts.personalities_description()))
    if any(store.honoured(key) for key in keys):
      entries.append((group, title, HISTORICAL_DESCRIPTIONS.get(parent, "")))
  if store.honoured("QOLLongitudinal"):
    entries.append(("qol", "Quality of Life", ""))
  if store.honoured(mounts.SLC_KEY) and mounts.slc_page_supported(cp) is not False:
    entries.append(("slc", mounts.SLC_TITLE, mounts.slc_description()))   # 0.9.7 order: last
  return entries


def tap_from_zero_visible(store, cp=None) -> bool:
  """Show the AP1 standstill tap-speed row under Gas / Brake (hidden on a known non-AP1 car)."""
  if not store.honoured(TAP_FROM_ZERO_KEY):
    return False
  return mounts.slc_supported(cp) is not False


def tap_from_zero_value_text(store) -> str:
  from opendbc.car.tesla_ap1.op_long_set_speed import format_tap_from_zero_display, parse_tap_from_zero_mph
  return format_tap_from_zero_display(parse_tap_from_zero_mph(store.raw(TAP_FROM_ZERO_KEY)),
                                      store.get_bool("IsMetric", False))


def tap_from_zero_default_mph() -> int:
  """The existing default: what the row shows while nothing is saved. TAP_FROM_ZERO_DEFAULT_MPH = 15
  (opendbc/car/tesla_ap1/op_long_set_speed.py:50), returned by parse_tap_from_zero_mph() for an unsaved key; the
  registry row is "15" (openpilot/common/bogpilot_params.py:38). No new number."""
  from opendbc.car.tesla_ap1.op_long_set_speed import parse_tap_from_zero_mph
  return parse_tap_from_zero_mph(None)


def tap_from_zero_default_text(store) -> str:
  from opendbc.car.tesla_ap1.op_long_set_speed import format_tap_from_zero_display
  return format_tap_from_zero_display(tap_from_zero_default_mph(), store.get_bool("IsMetric", False))


def tap_from_zero_is_default(store) -> bool:
  """The shown (parsed) value is the default. A stored value the parser rejects is shown as the default, so it is too."""
  from opendbc.car.tesla_ap1.op_long_set_speed import parse_tap_from_zero_mph
  return parse_tap_from_zero_mph(store.raw(TAP_FROM_ZERO_KEY)) == tap_from_zero_default_mph()


def reset_tap_from_zero(store, key, value, can_edit=None, long_on=None) -> None:
  """Section-reset writer: only the tap-speed key, only its existing default, under the same guards as the -/+ buttons
  (offroad and openpilot longitudinal). A refused write raises so the reset row reports it instead of failing silently."""
  if key != TAP_FROM_ZERO_KEY or int(value) != tap_from_zero_default_mph():
    raise PermissionError(f"{key} is not in this section")
  if (can_edit is not None and not can_edit()) or (long_on is not None and not long_on()):
    raise PermissionError(f"{key} was not reset")
  store.put(TAP_FROM_ZERO_KEY, str(int(value)), block=True)


def nudge_tap_from_zero(store, direction: int, can_edit=None) -> int:
  """Move the setting by one whole mph if the new value is in 5-30. Returns the stored mph."""
  from opendbc.car.tesla_ap1.op_long_set_speed import (
    parse_tap_from_zero_mph, TAP_FROM_ZERO_MAX_MPH, TAP_FROM_ZERO_MIN_MPH,
  )
  if can_edit is not None and not can_edit():
    return parse_tap_from_zero_mph(store.raw(TAP_FROM_ZERO_KEY))
  mph = parse_tap_from_zero_mph(store.raw(TAP_FROM_ZERO_KEY))
  nxt = mph + int(direction)
  if TAP_FROM_ZERO_MIN_MPH <= nxt <= TAP_FROM_ZERO_MAX_MPH:
    store.put(TAP_FROM_ZERO_KEY, str(nxt), block=True)
    return nxt
  return mph


def create_gas_brake_layout(store=None, cp_source=None, can_edit=None):
  """Lazy factory for the phase2 navigation Page. All arguments are injectable for native tests."""
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import button_item
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.selfdrive.ui.bogpilot.gated_actions import RESET_SECTION_TITLE, gated_value_step_item, reset_section_item
  from openpilot.selfdrive.ui.bogpilot import tuning_level
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot import menu_locks
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  if store is None:
    from openpilot.common.bogpilot_store import ParamStore
    store = ParamStore()
  if cp_source is None or can_edit is None:
    from openpilot.selfdrive.ui.ui_state import ui_state
    cp_source = cp_source or (lambda: ui_state.CP)
    if can_edit is None:
      # onroad_policy "gas_brake" = LOCKED: offroad only (0.9.7 allowed Longitudinal live; see ONROAD_CAVEATS).
      from openpilot.selfdrive.ui.bogpilot import onroad_policy
      can_edit = onroad_policy.editor("gas_brake")
  cp = LiveCP(cp_source)

  class GasBrakeLayout(Widget):
    def __init__(self):
      super().__init__()
      self.store, self.cp, self.can_edit = store, cp, can_edit
      self.panel = None
      self.panel_title = ""
      self._shown = False
      self.lock = menu_locks.cached(lambda: menu_locks.long_lock(self.cp._cp(), menu_locks.effective_disable_toggle()))
      self._lock_row = menu_locks.note_row(self.lock, menu_locks.TITLE)
      self._navigator = None
      # When a setting can unlock the page, a button takes the user straight to it.
      self._jump_row = button_item(lambda: "Open: " + (self.lock().unlock_title if self._can_jump() else ""), "OPEN",
                                   callback=self._jump)
      self._jump_row.set_visible(self._can_jump)
      self._build_root()

    # The settings sidebar owns Back (top left); this page reports its own sub-panel title and steps up on request.
    @property
    def navigation_title(self):
      return self.panel_title

    def navigation_back(self):
      if self.panel is None:
        return False
      inner_back = getattr(self.panel, "navigation_back", None)
      if callable(inner_back) and inner_back():
        return True
      self.close_panel()
      return True

    def set_navigator(self, navigator):
      """The menu navigation (menu_097.MenuNavigation) hands itself over when it creates this page."""
      self._navigator = navigator

    def _can_jump(self):
      lock = self.lock()
      return bool(lock is not None and lock.unlock_toggle and self._navigator is not None
                  and self._navigator.can_open(*menu_locks.JUMP_TARGET))

    def _jump(self):
      if self._can_jump():
        self._navigator.open_page(*menu_locks.JUMP_TARGET)

    def _build_root(self):
      # Locked: say why and which setting (if any) unlocks it. The rows below stay greyed; nothing here enables them.
      from openpilot.selfdrive.ui.bogpilot.phase3_following import FollowingEditor, _manage_toggle_item
      from openpilot.selfdrive.ui.bogpilot.section_icons import GAS_BRAKE_SECTIONS, resolve_icon
      self.lock.refresh()
      items = [self._lock_row, self._jump_row]
      editor = FollowingEditor(self.cp, self.store, self.can_edit)
      for key, title, desc in root_entries(self.store, self.cp):
        if key == "personalities":
          # 0.9.7 longitudinal_settings.cc:299-304: one combined switch + MANAGE row; MANAGE only while the switch is on.
          item = _manage_toggle_item(title, desc, editor.on(mounts.PERSONALITIES_KEY),
                                     lambda v: editor.write(mounts.PERSONALITIES_KEY, bool(v)),
                                     lambda: editor.can_edit(mounts.PERSONALITIES_KEY),
                                     lambda: self.open_panel("personalities"),
                                     lambda: editor.on(mounts.PERSONALITIES_KEY),
                                     icon=resolve_icon(GAS_BRAKE_SECTIONS[key]))
          item.action_item.set_enabled(lambda: self.cp.openpilotLongitudinalControl)
          items.append(attach_help(item, "group:" + key))
        else:
          # 0.9.7 section icon on the MANAGE row (section_icons.GAS_BRAKE_SECTIONS); none on the rows inside.
          items.append(attach_help(button_item(title, "MANAGE", desc, callback=lambda k=key: self.open_panel(k),
                                              enabled=lambda: self.cp.openpilotLongitudinalControl,
                                              icon=resolve_icon(GAS_BRAKE_SECTIONS.get(key, ""))), "group:" + key))
      # AP1 Model S only (mounts.slc_supported(cp) is not False), with the same no-car rule as the Speed Limit Controller
      # entry above: with no CarParams yet the rows show greyed, hidden only on a known non-AP1 car. The buttons are gated (gated_actions.py).
      # One value row [-] [value] [+] (was a text row plus a button row) and its own section reset row: same two rows,
      # same gates. As on the old rows, the row itself stays enabled (its help still opens); its buttons and the reset
      # are locked unless offroad with openpilot longitudinal (the same lock the old button row had).
      if tap_from_zero_visible(self.store, self.cp):
        def tap_enabled():
          return bool(self.can_edit() and self.cp.openpilotLongitudinalControl)

        def long_on():
          return bool(self.cp.openpilotLongitudinalControl)
        tap = gated_value_step_item(TAP_FROM_ZERO_TITLE, TAP_FROM_ZERO_DESC, lambda: tap_from_zero_value_text(self.store),
                                    on_minus=lambda: nudge_tap_from_zero(self.store, -1, self.can_edit),
                                    on_plus=lambda: nudge_tap_from_zero(self.store, 1, self.can_edit),
                                    button_width=200, enabled=tap_enabled,
                                    default_text=lambda: tap_from_zero_default_text(self.store),
                                    is_default=lambda: tap_from_zero_is_default(self.store), translate=tr)
        items.append(attach_help(tap, TAP_FROM_ZERO_KEY))
        # Reset writes only AP1TapFromZeroMph back to its existing default (tap_from_zero_default_mph).
        reset = reset_section_item(lambda: {TAP_FROM_ZERO_KEY: tap_from_zero_default_mph()} if tap_enabled() else {},
                                   lambda k, v: reset_tap_from_zero(self.store, k, v, self.can_edit, long_on),
                                   title=lambda: tr(RESET_SECTION_TITLE), enabled=tap_enabled)
        attach_help(reset, "section.reset_defaults")
        # Shown exactly while the tap-speed row is shown (its car gate above and its Tuning Level gate).
        reset.set_visible(lambda: tap.is_visible)
        reset.set_level_gate(lambda: tuning_level.row_visible(TAP_FROM_ZERO_KEY))
        items.append(reset)
      self.root = Scroller(items, line_separator=True, spacing=0)

    def open_panel(self, key):
      if key == "qol":
        widget = StoppingSettingsLayout(self.store, self.cp, STOPPING_CAPABILITIES, can_edit=self.can_edit, start_page="qol")
      elif key == "personalities":
        widget = mounts.make_personalities_panel(self.store, self.cp, self.can_edit)
      elif key == "slc":
        widget = mounts.make_slc_panel(self.store, self.cp, self.can_edit)
      elif key == "profiles":
        widget = make_settings(key, self.store, ACCEL_CAPABILITIES, self.cp, self.can_edit,
                               extra_items=mounts.longitudinal_tuning_items(self.store, self.cp, self.can_edit))
      else:
        widget = make_settings(key, self.store, ACCEL_CAPABILITIES, self.cp, self.can_edit)
      title = next(title for k, title, _ in root_entries(self.store, self.cp) if k == key)
      self.close_panel()
      self.panel, self.panel_title = widget, title
      if self._shown:
        widget.show_event()

    def close_panel(self):
      if self.panel is not None:
        self.panel.hide_event()
      self.panel, self.panel_title = None, ""

    def show_event(self):
      super().show_event()
      self._shown = True
      self.store.invalidate()
      self._build_root()
      self.root.show_event()
      if self.panel is not None:
        self.panel.show_event()

    def hide_event(self):
      self._shown = False
      if self.panel is not None:
        self.panel.hide_event()
      self.root.hide_event()
      super().hide_event()

    def _render(self, rect):
      if self.panel is None:
        self.root.render(rect)
        return
      if rect.width > 0 and rect.height > 0:
        self.panel.render(rect)

  return GasBrakeLayout()
