"""BogPilot submenu: only registered, implemented leaf factories; no import-time Params writes."""
from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import Page, build_layout
from openpilot.system.ui.widgets import Widget


LANE_CHANGE_CONTROLS = ("LaneChanges", "NudgelessLaneChange", "LaneChangeTime", "MinimumLaneChangeSpeed",
                        "LaneDetectionWidth", "OneLaneChange")


def _lane_changes_layout():
  """Lane Changes: consumers are desire_helper/radard (applied in this tree), hence runtime_integrated=True."""
  from openpilot.selfdrive.ui.bogpilot.phase3_lanechange import LaneChangeLayout
  from openpilot.selfdrive.ui.ui_state import ui_state
  return LaneChangeLayout(runtime_integrated=True, offroad=ui_state.is_offroad)


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


def _system_data_layout():
  from openpilot.selfdrive.ui.layouts.settings.phase3_system_settings_data_ui import build_data_layout
  # No export_dir: Stats EXPORT stays hidden until a vetted device directory exists.
  return build_data_layout(show_header=False)


def _system_device_layout():
  from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import create_device_controls_layout
  return create_device_controls_layout(runtime_hooks=True, show_header=False)


def _system_utilities_layout():
  from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities_ui import create_utilities_layout
  return create_utilities_layout()


STALK_CONTROLS = ("twist_follow", "experimental_pull", "pull_hold_s",
                  "experimental_push", "push_hold_s", "standard_engage_cancel_fixed")


def working_pages():
  from openpilot.selfdrive.ui.bogpilot.phase2_alerts import ACTIVE_ALERT_KEYS, create_alerts_layout
  from openpilot.selfdrive.ui.bogpilot.phase2_sounds import VOLUME_KEYS, create_volume_layout
  from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import TITLES, create_vehicle_settings_layout
  from openpilot.selfdrive.ui.bogpilot.phase2_car_selection import create_car_selection_layout
  from openpilot.selfdrive.ui.bogpilot.phase3_stalk_controls import create_stalk_controls_layout
  from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import (
    ACTIVE_CONTROLS as STEER_CONTROLS, PAGE_KEY as STEER_KEY, PAGE_TITLE as STEER_TITLE, create_steering_tuning_layout)
  from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake as gas_brake
  from openpilot.selfdrive.ui.bogpilot import bogpilot_model_selector as model_selector
  return {
    "alerts_sounds": (Page("volume", "Alert Volume Controller", create_volume_layout, ("AlertVolumeControl", *VOLUME_KEYS)),
                      Page("alerts", "BogPilot Alerts", create_alerts_layout, tuple(ACTIVE_ALERT_KEYS))),
    # Driving Controls: ONE tuple (Gas/Brake + Steering Tuning). Gas/Brake, Steering Tuning, Lane Changes, Driving Model.
    "driving": (Page(gas_brake.PAGE_KEY, gas_brake.PAGE_TITLE, gas_brake.create_gas_brake_layout, gas_brake.CONTROLS),
                Page(STEER_KEY, STEER_TITLE, create_steering_tuning_layout, STEER_CONTROLS),
                Page("lane_changes", "Lane Changes", _lane_changes_layout, LANE_CHANGE_CONTROLS),
                Page(model_selector.PAGE_KEY, model_selector.PAGE_TITLE, model_selector.create_driving_model_layout, model_selector.CONTROLS)),
    "vehicle": (Page("car_selection", "Car Selection", create_car_selection_layout,
                     ("CarMake", "CarModel", "CarModelName", "ForceFingerprint")),
                Page("vehicle_controls", "Vehicle Controls", create_vehicle_settings_layout, tuple(TITLES)),
                Page("stalk_controls", "Stalk Controls", create_stalk_controls_layout, STALK_CONTROLS),
                Page("vehicle_info", "Vehicle Info", _vehicle_info_layout, ("read-only CarParams",))),
    "system": (Page("system_data", "Data", _system_data_layout,
                    ("LocalDataActions", "StorageUse", "SystemPreferenceArchives", "BogPilotStats")),
               Page("system_device", "Device Controls", _system_device_layout,
                    ("DeviceManagement", "DeviceShutdown", "LowVoltageShutdown", "ScreenManagement", "ScreenBrightness",
                     "ScreenBrightnessOnroad", "ScreenTimeout", "ScreenTimeoutOnroad", "StandbyMode")),
               Page("system_utilities", "Utilities", _system_utilities_layout,
                    ("DebugMode", "BogPilotDefaultsReset", "DoToggleResetStock", "ClearCaches", "LocalDebugReport"))),
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
