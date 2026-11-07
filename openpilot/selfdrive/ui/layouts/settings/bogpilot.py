"""BogPilot settings panel (top-level, replaces Firehose per t962u): Vehicle Settings section.

Organised after bogpilot-tesla 0.9.7 BogPilot > Vehicle Settings (frogpilot/ui/qt/offroad/vehicle_settings.cc),
but only rows backed by active consumers (see selfdrive/ui/bogpilot/vehicle_settings.py). Edits are offroad-only.
"""
from openpilot.common.params import Params
from openpilot.selfdrive.ui.bogpilot import vehicle_settings as vs
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import text_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller

DESC = {
  "long": tr_noop("<b>Disable openpilot longitudinal</b> and use the car's stock ACC instead. Takes effect the next time the car starts."),
  "EnableICIntegration": tr_noop("Show openpilot on the Tesla dash cluster while engaged: the cluster set speed (including curve and "
                                 + "speed limit targets), the Autosteer icon, hands-on reminders, and the path line. Turn off to leave "
                                 + "the dash cluster completely stock. openpilot then sends no cluster messages. Driving is the same "
                                 + "either way. Takes effect right away."),
  "RegenComfortBrake": tr_noop("Start slowing for a car ahead sooner and more gently, sized to what regen alone can do (about "
                               + "1.0 m/s²). Hard braking for cut-ins, collision warnings, and emergencies is unchanged, and so is "
                               + "the stopped distance. Turn off for stock openpilot following. Takes effect when the planner restarts."),
}
AP1_TITLES = {"EnableICIntegration": tr_noop("Tesla AP1: Dash Cluster Integration"),
              "RegenComfortBrake": tr_noop("Tesla AP1: Earlier, Gentler Regen Stops")}
INFO_KEYS = ("Detected", "openpilot Longitudinal Support", "Radar Support", "Stop-and-Go Support")


class BogPilotLayout(Widget):
  def __init__(self, params=None):
    super().__init__()
    self._params = params if params is not None else Params()
    def offroad():
      return ui_state.is_offroad()
    self._long = toggle_item(lambda: tr("Disable openpilot Longitudinal Control"), lambda: tr(DESC["long"]),
                             vs.disable_long_effective(), callback=self._set_long, enabled=offroad)
    self._ap1 = {key: toggle_item(lambda k=key: tr(AP1_TITLES[k]), lambda k=key: tr(DESC[k]), False,
                                  callback=lambda s, k=key: self._set_ap1(k, s), enabled=offroad)
                 for key, (_, write) in vs.ap1_rows().items()}
    self._info = {k: text_item(lambda k=k: tr(k), "") for k in INFO_KEYS}
    self._scroller = Scroller([self._long, *self._ap1.values(), *self._info.values()], line_separator=True, spacing=0)

  def _set_ap1(self, key, state):
    if ui_state.is_offroad():
      vs.ap1_rows()[key][1](bool(state))
    self.refresh()

  def _set_long(self, state):
    if not ui_state.is_offroad():
      self.refresh()
      return
    if not state:
      vs.set_disable_long(self._params, False)
      self.refresh()
      return
    def done(result):
      if result == DialogResult.CONFIRM and ui_state.is_offroad():
        vs.set_disable_long(self._params, True)
      self.refresh()
    gui_app.push_widget(ConfirmDialog(tr("Are you sure you want to completely disable openpilot longitudinal control?"),
                                      tr("Disable"), callback=done))

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self.refresh()

  def refresh(self):
    CP = ui_state.CP
    fp = vs._text(CP.carFingerprint) if CP is not None else ""
    self._long.action_item.set_state(vs.disable_long_effective())
    self._long.set_visible(vs.disable_long_visible(CP))
    for key, (read, _) in vs.ap1_rows().items():
      self._ap1[key].set_visible(fp == vs.AP1_FINGERPRINT)
      self._ap1[key].action_item.set_state(read(fp))
    info = vs.vehicle_info(CP)
    for k, item in self._info.items():
      item.set_visible(k in info)
      item.action_item.set_text(tr(info.get(k, "")))

  def _render(self, rect):
    self._scroller.render(rect)
