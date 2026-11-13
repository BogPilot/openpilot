import time
import pyray as rl
from enum import IntEnum
import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import Widget
from openpilot.selfdrive.ui.layouts.sidebar import Sidebar, SIDEBAR_WIDTH
from openpilot.selfdrive.ui.layouts.developer_sidebar import DeveloperSidebar
from openpilot.selfdrive.ui.bogpilot.developer_sidebar_logic import split_rect
from openpilot.selfdrive.ui.layouts.home import HomeLayout
from openpilot.selfdrive.ui.layouts.settings.settings import SettingsLayout, PanelType
from openpilot.selfdrive.ui.onroad.augmented_road_view import AugmentedRoadView
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.selfdrive.ui.layouts.onboarding import OnboardingWindow
from openpilot.selfdrive.ui.body.layouts.onroad import BodyLayout
from openpilot.selfdrive.ui.bogpilot.reverse_camera import ReverseCameraController, enabled_from, is_stock_reverse_gear_screen, read_gear


class MainState(IntEnum):
  HOME = 0
  SETTINGS = 1
  ONROAD = 2


class MainLayout(Widget):
  def __init__(self):
    super().__init__()

    self._pm = messaging.PubMaster(['bookmarkButton', 'userBookmark'])
    self._params = Params()

    self._sidebar = Sidebar()
    self._developer_sidebar = DeveloperSidebar()   # right-hand panel while driving (DeveloperSidebar), display only
    self._current_mode = MainState.HOME
    self._prev_onroad = False

    # Initialize layouts
    self._home_layout = HomeLayout()
    self._home_body_layout = BodyLayout()
    self._layouts: dict[MainState, Widget] = {
      MainState.HOME: self._home_layout,
      MainState.SETTINGS: SettingsLayout(),
      MainState.ONROAD: AugmentedRoadView(),
    }

    # BogPilot: driver camera while reversing (0.9.7 DriverCamera)
    self._reverse = ReverseCameraController()
    self._reverse_view = None
    self._reverse_active = False
    self._visual_store = None

    self._sidebar_rect = rl.Rectangle(0, 0, 0, 0)
    self._content_rect = rl.Rectangle(0, 0, 0, 0)

    # Set callbacks
    self._setup_callbacks()

    gui_app.push_widget(self)

    # Start onboarding if terms or training not completed, make sure to push after self
    self._onboarding_window = OnboardingWindow()
    if not self._onboarding_window.completed:
      gui_app.push_widget(self._onboarding_window)

  def _render(self, _):
    self._handle_onroad_transition()
    self._update_reverse_camera()
    self._render_main_content()

  def _update_reverse_camera(self):
    if self._visual_store is None:
      from openpilot.common.bogpilot_store import ParamStore
      self._visual_store = ParamStore(cache_ttl=2.0)
    in_reverse, fresh = read_gear(ui_state.sm, time.monotonic())
    onroad_view = self._current_mode == MainState.ONROAD and not ui_state.is_body
    active = self._reverse.update(ui_state.started and onroad_view, enabled_from(self._visual_store), in_reverse, fresh)
    if active and not self._reverse_active:
      if self._reverse_view is None:
        from openpilot.selfdrive.ui.onroad.reverse_camera_view import ReverseDriverCameraView
        self._reverse_view = ReverseDriverCameraView()
      self._reverse_view.show_event()
    elif self._reverse_active and not active:
      self._reverse_view.hide_event()
    self._reverse_active = active

  def _setup_callbacks(self):
    self._sidebar.set_callbacks(on_settings=self._on_settings_clicked,
                                on_flag=self._on_bookmark_clicked,
                                open_settings=lambda: self.open_settings(PanelType.TOGGLES))
    self._layouts[MainState.HOME].set_settings_callback(lambda: self.open_settings(PanelType.TOGGLES))
    self._layouts[MainState.SETTINGS].set_callbacks(on_close=self._set_mode_for_state)

    for layout in (self._layouts[MainState.ONROAD], self._home_body_layout):
      layout.set_click_callback(self._on_onroad_clicked)

    device.add_interactive_timeout_callback(self._set_mode_for_state)
    ui_state.add_on_body_changed_callbacks(self._on_body_changed)

  def _update_layout_rects(self):
    self._sidebar_rect = rl.Rectangle(self._rect.x, self._rect.y, SIDEBAR_WIDTH, self._rect.height)

    x_offset = SIDEBAR_WIDTH if self._sidebar.is_visible else 0
    self._content_rect = rl.Rectangle(self._rect.x + x_offset, self._rect.y, self._rect.width - x_offset, self._rect.height)

  def _handle_onroad_transition(self):
    if ui_state.started != self._prev_onroad:
      self._prev_onroad = ui_state.started

      self._set_mode_for_state()

  def _set_mode_for_state(self):
    # Don't go onroad if body, home is onroad
    if ui_state.is_body:
      self._set_current_layout(MainState.HOME)
      self._sidebar.set_visible(not ui_state.ignition)
      return

    if ui_state.started:
      # Don't hide sidebar from interactive timeout. Coming onroad (or back from settings) restores the saved choice.
      if self._current_mode != MainState.ONROAD:
        self._sidebar.set_visible(self._saved_sidebar())
      self._set_current_layout(MainState.ONROAD)
    else:
      self._set_current_layout(MainState.HOME)
      self._sidebar.set_visible(True)

  def _set_current_layout(self, layout: MainState):
    if layout != self._current_mode:
      self._layouts[self._current_mode].hide_event()
      self._current_mode = layout
      self._layouts[self._current_mode].show_event()

  def open_settings(self, panel_type: PanelType):
    self._layouts[MainState.SETTINGS].set_current_panel(panel_type)
    self._set_current_layout(MainState.SETTINGS)
    self._sidebar.set_visible(False)

  def _on_settings_clicked(self):
    self.open_settings(PanelType.DEVICE)

  def _on_bookmark_clicked(self):
    for service in ('bookmarkButton', 'userBookmark'):
      msg = messaging.new_message(service, valid=True)
      self._pm.send(service, msg)

  def _saved_sidebar(self) -> bool:
    try:
      return bool(self._params.get_bool("Sidebar"))
    except Exception:
      return False

  def _on_onroad_clicked(self):
    # A tap on empty screen space shows or hides the sidebar and remembers it (0.9.7 home.cc:124-129).
    self._sidebar.set_visible(not self._sidebar.is_visible)
    try:
      self._params.put_bool("Sidebar", self._sidebar.is_visible)
    except Exception:
      pass

  def _on_body_changed(self):
    self._layouts[MainState.HOME] = self._home_body_layout if ui_state.is_body else self._home_layout
    self._set_mode_for_state()

  def _render_main_content(self):
    if self._reverse_active:
      # 0.9.7: driver view full screen, sidebar hidden, touches ignored; onroad view resumes on exit
      self._reverse_view.render(self._rect)
      # Keep stock visual alerts over the cabin view (audio is soundd, untouched),
      # except the informational reverseGear/permanent full-screen "Reverse Gear"
      # screen the driver camera is meant to replace. 0.9.7 hid the whole onroad
      # widget (and that screen with it) via showDriverView. USER_DISABLE / NO_ENTRY
      # reverseGear alerts and all other visual alerts still render.
      if not is_stock_reverse_gear_screen(ui_state.sm):
        self._layouts[MainState.ONROAD].alert_renderer.render(self._rect)
      return

    # Render sidebar
    if self._sidebar.is_visible:
      self._sidebar.render(self._sidebar_rect)

    content_rect = self._content_rect if self._sidebar.is_visible else self._rect
    developer_rect = None
    if self._current_mode == MainState.ONROAD and not ui_state.is_body and self._developer_sidebar.wanted():
      content, developer = split_rect(content_rect.x, content_rect.y, content_rect.width, content_rect.height, True)
      if developer is not None:
        content_rect, developer_rect = rl.Rectangle(*content), rl.Rectangle(*developer)
    self._layouts[self._current_mode].render(content_rect)
    if developer_rect is not None:
      self._developer_sidebar.render(developer_rect)
