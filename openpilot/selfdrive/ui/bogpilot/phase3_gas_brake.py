"""BogPilot > Driving Controls > Gas / Brake.

Composes the two consumer-backed Gas / Brake lanes under ONE page:
  Advanced Longitudinal Tuning   Actuator Delay, Maximum Acceleration, Stop Acceleration, Stopping Rate
  Conditional Experimental Mode  all CEM rows with a real consumer
  Longitudinal Tuning            Acceleration / Deceleration profile, Human-Like Acceleration
  Quality of Life                Force Stop, Increase Stopped Distance, manual weather offsets

Every row writes through the shared ParamStore with a BLOCKING Params write and a read-back before its
internal adoption marker (see common/bogpilot_store.ParamStore.put(block=True)). Importing this module and
opening/closing the page never writes a preference or an adoption marker. Writes are refused unless the
car is offroad AND the live CarParams report openpilot longitudinal control (re-checked on every write).
"""
from __future__ import annotations

from openpilot.selfdrive.ui.bogpilot.phase3_stopping_settings import StoppingCapabilities, StoppingSettingsLayout
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import (
  Capabilities, GROUPS, HISTORICAL_DESCRIPTIONS, make_settings,
)

PAGE_KEY = "gas_brake"
PAGE_TITLE = "Gas / Brake"
# Consumer-backed control IDs (feeds Page.controls so an empty page is omitted by the navigation).
CONTROLS = ("LongitudinalActuatorDelay", "MaxDesiredAcceleration", "StopAccel", "StoppingDecelRate",
            "AccelerationProfile", "DecelerationProfile", "HumanAcceleration",
            "ConditionalExperimental", "ForceStops", "IncreasedStoppedDistance", "WeatherPresets")

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


def root_entries(store):
  """(key, title, description) for the page's top menu; pure data, no widgets."""
  entries = []
  for group in ("advanced", "conditional", "profiles"):
    parent, title, _ack, keys = GROUPS[group]
    if any(store.honoured(key) for key in keys):
      entries.append((group, title, HISTORICAL_DESCRIPTIONS.get(parent, "")))
  if store.honoured("QOLLongitudinal"):
    entries.append(("qol", "Quality of Life", ""))
  return entries


def create_gas_brake_layout(store=None, cp_source=None, can_edit=None):
  """Lazy factory for the phase2 navigation Page. All arguments are injectable for native tests."""
  import pyray as rl
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import button_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import content_bounds
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  if store is None:
    from openpilot.common.bogpilot_store import ParamStore
    store = ParamStore()
  if cp_source is None or can_edit is None:
    from openpilot.selfdrive.ui.ui_state import ui_state
    cp_source = cp_source or (lambda: ui_state.CP)
    can_edit = can_edit or ui_state.is_offroad
  cp = LiveCP(cp_source)

  class GasBrakeLayout(Widget):
    def __init__(self):
      super().__init__()
      self.store, self.cp, self.can_edit = store, cp, can_edit
      self.panel = None
      self.panel_title = ""
      self._shown = False
      self._back = button_item(lambda: self.panel_title or PAGE_TITLE, "BACK", callback=self.close_panel,
                               enabled=lambda: self.panel is not None)
      self._build_root()

    def _build_root(self):
      items = [attach_help(button_item(title, "MANAGE", desc, callback=lambda k=key: self.open_panel(k),
                                       enabled=lambda: self.cp.openpilotLongitudinalControl), "group:" + key)
               for key, title, desc in root_entries(self.store)]
      self.root = Scroller(items, line_separator=True, spacing=0)

    def open_panel(self, key):
      if key == "qol":
        widget = StoppingSettingsLayout(self.store, self.cp, STOPPING_CAPABILITIES, can_edit=self.can_edit, start_page="qol")
      else:
        widget = make_settings(key, self.store, ACCEL_CAPABILITIES, self.cp, self.can_edit)
      title = next(title for k, title, _ in root_entries(self.store) if k == key)
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
      self._back.show_event()
      self._build_root()
      self.root.show_event()
      if self.panel is not None:
        self.panel.show_event()

    def hide_event(self):
      self._shown = False
      if self.panel is not None:
        self.panel.hide_event()
      self.root.hide_event()
      self._back.hide_event()
      super().hide_event()

    def _render(self, rect):
      if self.panel is None:
        self.root.render(rect)
        return
      header, body = content_bounds(rect.x, rect.y, rect.width, rect.height)
      self._back.set_parent_rect(rect)
      self._back.render(rl.Rectangle(*header))
      if body[2] > 0 and body[3] > 0:
        self.panel.render(rl.Rectangle(*body))

  return GasBrakeLayout()
