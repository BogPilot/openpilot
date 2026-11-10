"""BogPilot > Vehicle Settings: editable active AP1 features only.

Split from ecac1eb56's panel. Vehicle Info belongs to the read-only lane.
No generic make/model overrides or stored-but-unconsumed preferences.
"""
from pathlib import Path

# Model S only. Model X is lateral-only and does not get these toggles.
AP1 = "TESLA_AP1_MODELS"
LONG = "DisableOpenpilotLongitudinal"
CLUSTER = "EnableICIntegration"
REGEN = "RegenComfortBrake"
TITLES = {LONG: "Disable openpilot Longitudinal Control",
          CLUSTER: "Tesla AP1: Dash Cluster Integration",
          REGEN: "Tesla AP1: Earlier, Gentler Regen Stops"}
DESCRIPTIONS = {
  LONG: "Use the car's stock ACC instead of openpilot longitudinal control. Takes effect the next time the car starts.",
  CLUSTER: "Show openpilot information on the Tesla dash cluster. Off leaves the cluster stock. Takes effect immediately.",
  REGEN: "Start slowing for a lead earlier with regen-sized comfort braking. Emergency braking limits and stopped distance are unchanged. "
         "Takes effect the next time the planner starts (normally the next drive).",
}


def supported(cp):
  return (cp is not None and str(cp.carFingerprint) == AP1
          and not getattr(cp, "dashcamOnly", True))


class VehicleSettings:
  """Reads/writes use the consumers themselves; every write rechecks live guards.

  cp and offroad are callables, deliberately not captured snapshots. A confirmation
  may outlive its car or offroad state. Optional paths are for isolated native tests.
  """
  def __init__(self, params, cp, offroad, file_dir=None, params_file=None):
    from opendbc.car.tesla_ap1 import toggles, regen_brake
    self.params, self.cp, self.offroad = params, cp, offroad
    self.toggles, self.regen = toggles, regen_brake
    self.file_dir = Path(file_dir) if file_dir is not None else toggles.IC_INTEGRATION_DIR
    self.params_file = Path(params_file) if params_file is not None else toggles.DISABLE_OP_LONG_PATHS[1]
    self.cluster_path = self.file_dir / CLUSTER if file_dir is not None else toggles._ic_integration_path
    self.regen_path = self.file_dir / REGEN if file_dir is not None else regen_brake._regen_comfort_path

  def visible(self, key):
    cp = self.cp()
    if not supported(cp):
      return False
    if key == LONG:
      # This consumer exists only for tesla_ap1, not generic CP long support.
      return not getattr(cp, "alphaLongitudinalAvailable", False)
    if key == CLUSTER:
      return True
    if key == REGEN:
      return bool(cp.openpilotLongitudinalControl)
    return False

  def enabled(self, key):
    return self.visible(key) and bool(self.offroad())

  def read(self, key):
    if key == LONG:
      return self.toggles.disable_openpilot_long(paths=(self.file_dir / LONG, self.params_file))
    # Missing/unreadable files have the consumer's default-on semantics.
    path = self.cluster_path if key == CLUSTER else self.regen_path
    try:
      stored = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
      stored = ""
    if key == CLUSTER:
      return self.toggles.enable_ic_integration(AP1 if supported(self.cp()) else "", stored=stored)
    if key == REGEN:
      return self.regen.regen_comfort_brake_enabled(AP1 if supported(self.cp()) else "", stored=stored)
    raise KeyError(key)

  def write(self, key, state):
    if not self.enabled(key):
      return False
    state = bool(state)
    if key == LONG:
      # Existing override has priority over Params. Do not create a new override.
      self.params.put_bool(LONG, state, block=True)
      override = self.file_dir / LONG
      if override.is_file():
        override.write_text("1" if state else "0")
    elif key == CLUSTER:
      self.toggles.set_enable_ic_integration(state, path=self.cluster_path)
    elif key == REGEN:
      self.regen.set_regen_comfort_brake(state, path=self.regen_path)
    return True


def create_vehicle_settings_layout(params=None):
  """Lazy UI factory for historical BogPilot -> Vehicle Settings navigation.

  Parent owns the navigation/back button and separate Vehicle Info submenu.
  No top-level settings wiring is changed by this lane.
  """
  from openpilot.common.params import Params
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import DialogResult, Widget
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.list_view import toggle_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

  class VehicleSettingsLayout(Widget):
    def __init__(self):
      super().__init__()
      self.model = VehicleSettings(params if params is not None else Params(), lambda: ui_state.CP, ui_state.is_offroad)
      self.rows = {key: toggle_item(lambda k=key: tr(TITLES[k]), lambda k=key: tr(DESCRIPTIONS[k]), False,
                                   callback=lambda state, k=key: self.set_value(k, state),
                                   enabled=lambda k=key: self.model.enabled(k)) for key in TITLES}
      for key, row in self.rows.items():
        attach_help(row, key)
      self.scroller = Scroller(list(self.rows.values()), line_separator=True, spacing=0)

    def set_value(self, key, state):
      if not self.model.enabled(key):
        self.refresh()
        return
      if key != LONG or not state:
        self.model.write(key, state)
        self.refresh()
        return
      original_cp = ui_state.CP

      def done(result):
        # Reject a stale confirmation even if another supported car is now loaded.
        if result == DialogResult.CONFIRM and ui_state.CP is original_cp:
          self.model.write(key, state)
        self.refresh()
      gui_app.push_widget(ConfirmDialog(tr("Disable openpilot longitudinal control on the next car start?"),
                                        tr("Disable"), callback=done))

    def refresh(self):
      for key, row in self.rows.items():
        row.set_visible(self.model.visible(key))
        row.action_item.set_state(self.model.read(key))

    def show_event(self):
      super().show_event()
      self.scroller.show_event()
      self.refresh()

    def _render(self, rect):
      # CP can arrive/change while the panel stays open.
      self.refresh()
      self.scroller.render(rect)

  return VehicleSettingsLayout()
