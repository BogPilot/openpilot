import time
import pyray as rl
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import Widget


class ExpButton(Widget):
  """Top-right Experimental Mode button, HIDDEN AND INERT by default (BogPilot).

  The stock button drew the comma steering wheel (or the Experimental icon) in the top-right corner. BogPilot shows the
  steering arc instead, but the stock HudRenderer paints this button whenever the arc is not live (every boot, before the
  first controlsState/carState/carControl messages, RedesignUI off, or an arc failure), which flashed the stock wheel.
  Nothing is drawn here in any state (no wheel, no Experimental icon, no backing circle), and the widget is disabled so a
  tap in that corner passes through to the normal screen tap instead of toggling Experimental Mode invisibly.
  ArcTapButton (bogpilot_hud) subclasses this as an invisible tap target and re-enables it; the arc is its visual."""

  def __init__(self, button_size: int, icon_size: int):
    super().__init__()
    self.set_enabled(False)
    self._params = Params()
    self._experimental_mode: bool = False
    self._engageable: bool = False

    # State hold mechanism
    self._hold_duration = 2.0  # seconds
    self._held_mode: bool | None = None
    self._hold_end_time: float | None = None

    self._rect = rl.Rectangle(0, 0, button_size, button_size)

  def set_rect(self, rect: rl.Rectangle) -> None:
    self._rect.x, self._rect.y = rect.x, rect.y

  def _update_state(self) -> None:
    selfdrive_state = ui_state.sm["selfdriveState"]
    self._experimental_mode = selfdrive_state.experimentalMode
    self._engageable = selfdrive_state.engageable or selfdrive_state.enabled

  def _handle_mouse_release(self, _):
    super()._handle_mouse_release(_)
    if self._is_toggle_allowed():
      new_mode = not self._experimental_mode
      self._params.put_bool("ExperimentalMode", new_mode)

      # Hold new state temporarily
      self._held_mode = new_mode
      self._hold_end_time = time.monotonic() + self._hold_duration

  def _render(self, rect: rl.Rectangle) -> None:
    # Intentionally paints nothing: no stock wheel, no Experimental icon, no backing circle.
    return None

  def _held_or_actual_mode(self):
    now = time.monotonic()
    if self._hold_end_time and now < self._hold_end_time:
      return self._held_mode

    if self._hold_end_time and now >= self._hold_end_time:
      self._hold_end_time = self._held_mode = None

    return self._experimental_mode

  def _is_toggle_allowed(self):
    if not self._params.get_bool("ExperimentalModeConfirmed"):
      return False

    # Mirror exp mode toggle using persistent car params
    return ui_state.has_longitudinal_control
