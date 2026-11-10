"""System Settings > Utilities page (sysUtilities lane).

Parent System Settings page is owned by lane sysData. This module only exposes
create_utilities_layout() for the Utilities child. Every destructive action uses
ConfirmDialog; Flash Panda / Force Drive State stay explanatory unavailable rows.
"""
from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import UtilitiesActions, PENDING


def create_utilities_layout(*, params=None, store=None, offroad=None, capable=None,
                            actions=None, show_status=True):
  import pyray as rl
  from openpilot.common.hardware import HARDWARE, PC
  from openpilot.common.params import Params
  from openpilot.common.bogpilot_store import ParamStore
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import Widget, DialogResult
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.list_view import button_item, text_item, toggle_item
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  params = params if params is not None else Params()
  store = store if store is not None else ParamStore(params)
  offroad = offroad or ui_state.is_offroad
  capable = capable or (lambda: not PC and HARDWARE.get_device_type() in {"tici", "tizi", "mici"})
  actions = actions or UtilitiesActions(offroad, capable, params=params, store=store)

  class UtilitiesLayout(Widget):
    def __init__(self):
      super().__init__()
      self.status = ""
      self.busy = False
      self._dirty = False
      self._visible = False
      self._scroller = self._make_scroller()

    def allowed(self):
      return (not self.busy) and bool(offroad()) and bool(capable())

    def unavailable(self, title):
      return text_item(lambda t=title: tr(t), lambda: tr("Unavailable"), lambda t=title: tr(PENDING[t]))

    def attempt(self, callback):
      if not self.allowed():
        self.status = "Offroad supported device required; no changes made."
        self._dirty = True
        return
      try:
        outcome = callback()
        if isinstance(outcome, str):
          self.status = outcome
          self._dirty = True
      except Exception as exc:
        self.status = f"Action refused or failed ({type(exc).__name__}); no success claimed."
        self._dirty = True

    def confirm(self, message, action, confirm_label):
      if not self.allowed():
        self.status = "Offroad supported device required; no changes made."
        self._dirty = True
        return

      def on_result(result: DialogResult):
        if result != DialogResult.CONFIRM:
          self.status = "Cancelled; no changes made."
          self._dirty = True
          return
        # Re-check guards after the dialog (engagement / capability may have changed).
        self.attempt(action)

      dialog = ConfirmDialog(tr(message), tr(confirm_label), callback=on_result)
      gui_app.push_widget(dialog)

    def on_debug_mode(self, enabled):
      self.attempt(lambda: actions.set_debug_mode(bool(enabled)))

    def _make_scroller(self):
      items = []
      items.append(attach_help(toggle_item(
        lambda: tr("Debug Mode"),
        lambda: tr("Show BogPilot developer metrics on the next drive. Clears automatically on the following offroad transition (not a permanent preference). Existing onroad HUD/BSM/lead consumers honor this while set."),
        actions.get_debug_mode(),
        callback=self.on_debug_mode,
        enabled=self.allowed,
      ), "DebugMode"))
      items.append(self.unavailable("Flash Panda"))
      items.append(self.unavailable("Force Drive State"))
      items.append(attach_help(button_item(
        lambda: tr("Reset BogPilot Settings to Defaults"),
        lambda: tr("RESET"),
        lambda: tr("Restore audited BogPilot shipping defaults. A durable local backup is written first. Vehicle identity, calibration and cloud credentials are kept. No reboot."),
        callback=lambda: self.confirm(
          "Reset BogPilot settings to shipping defaults? A durable backup is written first. Driving preferences change. Identity/calibration/secrets stay. No reboot.",
          actions.reset_bogpilot_defaults,
          "Reset",
        ),
        enabled=self.allowed,
      ), "BogPilotDefaultsReset"))
      items.append(attach_help(button_item(
        lambda: tr("Reset Toggles to Stock openpilot"),
        lambda: tr("RESET"),
        lambda: tr("Queue stock openpilot toggle reset for the NEXT manager restart. Existing audited lifecycle writes a durable backup first. No reboot now."),
        callback=lambda: self.confirm(
          "Queue stock openpilot toggle reset for the NEXT manager restart? Driving preferences change. Durable backup is mandatory. No reboot happens now.",
          actions.queue_stock_reset,
          "Queue Reset",
        ),
        enabled=self.allowed,
      ), "DoToggleResetStock"))
      items.append(attach_help(button_item(
        lambda: tr("Clear Caches"),
        lambda: tr("CLEAR"),
        lambda: tr("Delete allowlisted download/model caches and soft API cache params. Settings backups, /cache/params and OS/boot slots are never touched."),
        callback=lambda: self.confirm(
          "Clear allowlisted download/model caches and soft API cache params? Settings backups and device identity stay. No OS or boot-slot changes.",
          actions.clear_caches,
          "Clear",
        ),
        enabled=self.allowed,
      ), "ClearCaches"))
      items.append(attach_help(button_item(
        lambda: tr("Save Debug Report Locally"),
        lambda: tr("SAVE"),
        lambda: tr("Write a local diagnostics JSON under /data/bogpilot_debug_reports. Nothing is uploaded."),
        callback=lambda: self.confirm(
          "Save a local debug report on this device? Nothing is uploaded or shared.",
          actions.save_debug_report,
          "Save",
        ),
        enabled=self.allowed,
      ), "LocalDebugReport"))
      if show_status:
        items.append(text_item(lambda: tr("Status"), lambda: tr(self.status or "Ready; no changes made")))
      return Scroller(items, line_separator=True, spacing=0)

    def rebuild(self):
      self._scroller = self._make_scroller()
      self._dirty = False

    def show_event(self):
      super().show_event()
      if not self._visible:
        self.rebuild()
        self._visible = True
        self._scroller.show_event()

    def hide_event(self):
      if self._visible:
        self._scroller.hide_event()
        self._visible = False
      super().hide_event()

    def _render(self, rect):
      if self._dirty:
        self.rebuild()
      if rect.width > 0 and rect.height > 0:
        self._scroller.render(rect)

  return UtilitiesLayout()
