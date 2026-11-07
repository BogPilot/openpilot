"""BogPilot submenu: only registered, implemented leaf factories; no import-time Params writes."""
from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import Page, build_layout
from openpilot.system.ui.widgets import Widget


def _vehicle_info_layout():
  from openpilot.selfdrive.ui.bogpilot.phase2_vehicle_info import INFO_KEYS, refresh_info_items
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets.list_view import text_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  class VehicleInfoLayout(Widget):
    def __init__(self):
      super().__init__()
      self.items = {key: text_item(lambda key=key: tr(key), "") for key in INFO_KEYS}
      self.scroller = Scroller(list(self.items.values()), line_separator=True, spacing=0)

    def _render(self, rect):
      # UI CP is persisted. It does NOT prove a currently attached vehicle.
      refresh_info_items(self.items, ui_state.CP, current=False, translate=tr)
      self.scroller.render(rect)

    def show_event(self):
      super().show_event()
      self.scroller.show_event()

  return VehicleInfoLayout()


def working_pages():
  from openpilot.selfdrive.ui.bogpilot.phase2_alerts import ACTIVE_ALERT_KEYS, create_alerts_layout
  from openpilot.selfdrive.ui.bogpilot.phase2_sounds import VOLUME_KEYS, create_volume_layout
  from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import TITLES, create_vehicle_settings_layout
  return {
    "alerts_sounds": (Page("volume", "Alert Volume Controller", create_volume_layout, ("AlertVolumeControl", *VOLUME_KEYS)),
                      Page("alerts", "BogPilot Alerts", create_alerts_layout, tuple(ACTIVE_ALERT_KEYS))),
    "vehicle": (Page("vehicle_controls", "Vehicle Controls", create_vehicle_settings_layout, tuple(TITLES)),
                Page("vehicle_info", "Vehicle Info", _vehicle_info_layout, ("read-only CarParams",))),
  }


class BogPilotLayout(Widget):
  def __init__(self):
    super().__init__()
    self.content = build_layout(working_pages())

  def show_event(self):
    super().show_event()
    self.content.show_event()

  def hide_event(self):
    self.content.hide_event()
    super().hide_event()

  def _render(self, rect):
    self.content.render(rect)
