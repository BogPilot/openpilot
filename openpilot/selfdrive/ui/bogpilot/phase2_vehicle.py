"""BogPilot > Vehicle Settings: editable active AP1 features only.

Split from ecac1eb56's panel. Vehicle Info belongs to the read-only lane.
No generic make/model overrides or stored-but-unconsumed preferences.
"""
from pathlib import Path

# Model S only. Model X is lateral-only and does not get these toggles.
AP1 = "TESLA_AP1_MODELS"
PREAP = "TESLA_PREAP_MODELS"
DOUBLE_PULL = "TeslaPreApDoublePull"
PEDAL_STATUS = "PedalStatus"
PEDAL_CALIBRATE = "PedalCalibrate"
BUILD_INFO = "PreApBuild"
PANDA_FIRMWARE = "PreApPandaFirmware"
LONG = "DisableOpenpilotLongitudinal"
CLUSTER = "EnableICIntegration"
REGEN = "RegenComfortBrake"
RADAR = "TeslaRadarEnabled"
RADAR_NOSECONE = "TeslaRadarBehindNosecone"
TITLES = {LONG: "Disable openpilot Longitudinal Control",
          CLUSTER: "Tesla AP1: Dash Cluster Integration",
          REGEN: "Tesla AP1: Earlier, Gentler Regen Stops",
          DOUBLE_PULL: "Pre-AP: Double Pull to Engage Pedal Longitudinal",
          RADAR: "Pre-AP: Bosch Radar",
          RADAR_NOSECONE: "Pre-AP: Radar Behind Nosecone"}
# Pre-AP wording for the shared Disable row (AP1 keeps the stock text).
PREAP_LONG_TITLE = "Disable Pedal Longitudinal"
PREAP_LONG_DESCRIPTION = ("Turn on to disable Comma Pedal longitudinal (steering only). Leave it off so BogPilot can control your speed through a "
                          "detected, calibrated Comma Pedal. Takes effect the next time the car starts.")
PEDAL_STATUS_TITLE = "Comma Pedal"
PEDAL_STATUS_DESCRIPTION = ("Not detected: the car has not heard the pedal. Needs calibration: pedal heard, run Calibrate before "
                            "longitudinal. Recalibrate: the saved pedal scale is out of range, calibrate again. Calibrated: detected and calibrated.")
BUILD_TITLE = "Software"
BUILD_DESCRIPTION = ("The BogPilot version and the commit this build was made from. Quote both when reporting a problem.")
PANDA_FIRMWARE_TITLE = "Panda Firmware"
PANDA_FIRMWARE_DESCRIPTION = ("The firmware version the panda reported when the car last started. Quote it when reporting a problem. "
                              "Not reported yet: the panda has not answered since this build started.")
PANDA_FIRMWARE_UNKNOWN = "Not reported yet"
PEDAL_CALIBRATE_TITLE = "Calibrate Pedal"
PEDAL_CALIBRATE_DESCRIPTION = ("Guided calibration. Put the car in Park with the ignition on. Keep your foot off the accelerator and brake pedals, then follow the screen. "
                               "Cancel leaves the current calibration unchanged.")
DESCRIPTIONS = {
  LONG: "Use the car's stock ACC instead of openpilot longitudinal control. Takes effect the next time the car starts.",
  CLUSTER: "Show openpilot information on the Tesla dash cluster. Off leaves the cluster stock. Takes effect immediately.",
  REGEN: "Start slowing for a lead earlier with regen-sized comfort braking. Emergency braking limits and stopped distance are unchanged. "
         "Takes effect the next time the planner starts (normally the next drive).",
  DOUBLE_PULL: "Needs Always On Lateral. On: the first pull of the cruise stalk starts Always On Lateral steering only (openpilot is not engaged); a second pull "
               "within 400 ms engages openpilot with pedal longitudinal, and a pull or the brake while engaged drops back to steering only. Off: one pull "
               "engages steering and pedal longitudinal. Takes effect immediately.",
  RADAR: "Turn on only if a Tesla Bosch radar is fitted on the radar bus and the panda firmware supports it. Radar leads then feed "
         "pedal longitudinal and Human-Like Following. If the radar does not answer, openpilot will not engage and shows an alert. "
         "Takes effect the next time the car starts.",
  RADAR_NOSECONE: "Turn on if the radar is mounted behind the nosecone. Shown while Bosch Radar is on. "
                  "Takes effect the next time the car starts.",
}


def supported(cp):
  return (cp is not None and str(cp.carFingerprint) in (AP1, PREAP)
          and not getattr(cp, "dashcamOnly", True))


def is_preap(cp):
  return supported(cp) and str(cp.carFingerprint) == PREAP


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
      # This consumer exists only for tesla_ap1 (AP1 and Pre-AP), not generic CP long support.
      return not getattr(cp, "alphaLongitudinalAvailable", False)
    if key == CLUSTER:
      return not is_preap(cp)          # AP1 cluster frames: Pre-AP never sends them
    if key == REGEN:
      return bool(cp.openpilotLongitudinalControl) and not is_preap(cp)
    if key == DOUBLE_PULL:
      # Hidden (never an inert switch) while Always On Lateral is unavailable: the first pull is an AOL lateral intent, as on 0.9.7.
      from opendbc.car.tesla_ap1.preap import params as preap_params
      from openpilot.selfdrive.car import preap_aol
      if not (is_preap(cp) and bool(cp.openpilotLongitudinalControl)):
        return False
      preap_aol.install(cp)
      return preap_params.aol_available()
    if key == RADAR:
      return is_preap(cp)              # Pre-AP retrofit only; AP1 has its own radar and never shows the row
    if key == RADAR_NOSECONE:
      # Sub-option: shown only while the main radar toggle is On (NotAutopilot nap.py:160-175@e99f4dc75 has both rows).
      from opendbc.car.tesla_ap1.preap import params as preap_params
      return is_preap(cp) and preap_params.get_bool(RADAR)
    if key in (BUILD_INFO, PANDA_FIRMWARE):
      return is_preap(cp)              # read-only support info: shown for every Pre-AP car, pedal longitudinal on or off
    if key in (PEDAL_STATUS, PEDAL_CALIBRATE):
      # Pedal rows matter only while pedal longitudinal is on for this car.
      return is_preap(cp) and bool(cp.openpilotLongitudinalControl)
    return False

  def enabled(self, key):
    if key == PEDAL_CALIBRATE:
      return self.visible(key) and self.calibrate_allowed()
    return self.visible(key) and bool(self.offroad())

  # ---- Pre-AP pedal rows ----
  def calibrate_allowed(self):
    """Parked (or offroad with the pedal still heard). Moving blocks it; an unheard pedal blocks it with a message."""
    from openpilot.selfdrive.ui.bogpilot import preap_pedal_cal as cal
    return not cal.blocked_reason(cal.read_snapshot(self.wall()).live, self.moving())

  def wall(self):
    import time
    return getattr(self, "wall_fn", time.time)()

  def moving(self):
    mv = getattr(self, "moving_fn", None)
    return bool(mv()) if mv is not None else False

  def pedal_status(self):
    from openpilot.selfdrive.ui.bogpilot import preap_pedal_cal as cal
    return cal.status_text(cal.read_snapshot(self.wall()))

  def build_text(self):
    """"<version> (<commit>)" of the running build; "+ local edits" when the tree was modified; "unknown" if it cannot be read."""
    cached = getattr(self, "_build_text", None)
    if cached is None:
      try:
        from openpilot.common.version import get_build_metadata
        meta = get_build_metadata().openpilot
        cached = f"{meta.version} ({str(meta.git_commit)[:9]})" + (" + local edits" if getattr(meta, "is_dirty", False) else "")
      except Exception:
        cached = "unknown"
      self._build_text = cached
    return cached

  def panda_firmware_text(self):
    from opendbc.car.tesla_ap1.preap import params as preap_params
    return preap_params.get_str(preap_params.PreApParamKeys.PANDA_FIRMWARE) or PANDA_FIRMWARE_UNKNOWN

  def title(self, key):
    return PREAP_LONG_TITLE if (key == LONG and is_preap(self.cp())) else TITLES[key]

  def description(self, key):
    return PREAP_LONG_DESCRIPTION if (key == LONG and is_preap(self.cp())) else DESCRIPTIONS[key]

  def read(self, key):
    if key == LONG:
      return self.toggles.disable_openpilot_long(paths=(self.file_dir / LONG, self.params_file))
    if key in (DOUBLE_PULL, RADAR, RADAR_NOSECONE):
      from opendbc.car.tesla_ap1.preap import params as preap_params
      return preap_params.get_bool(key)
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
    if key in (DOUBLE_PULL, RADAR, RADAR_NOSECONE):
      from opendbc.car.tesla_ap1.preap import params as preap_params
      preap_params.set_bool(key, state)
      return True
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


def _safe(fn):
  try:
    return bool(fn())
  except Exception:
    return False


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
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
  from openpilot.system.ui.widgets.list_view import toggle_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  from openpilot.system.ui.widgets.list_view import button_item, text_item
  from openpilot.selfdrive.ui.bogpilot import preap_pedal_cal as cal

  class VehicleSettingsLayout(Widget):
    def __init__(self):
      super().__init__()
      self.model = VehicleSettings(params if params is not None else Params(), lambda: ui_state.CP, ui_state.is_offroad)
      self.model.moving_fn = lambda: bool(ui_state.started and not getattr(ui_state.sm["carState"], "standstill", True))
      self._status_cache = (0.0, "")
      self.rows = {key: toggle_item(lambda k=key: tr(self.model.title(k)), lambda k=key: tr(self.model.description(k)), False,
                                   callback=lambda state, k=key: self.set_value(k, state),
                                   enabled=lambda k=key: self.model.enabled(k)) for key in TITLES}
      for key, row in self.rows.items():
        attach_help(row, key)
      # Pre-AP pedal rows: a live status (refreshed every frame from the car's published state) and the guided Calibrate button.
      self.status_row = text_item(lambda: tr(PEDAL_STATUS_TITLE), lambda: tr(self._status()), lambda: tr(PEDAL_STATUS_DESCRIPTION))
      self.calibrate_row = button_item(lambda: tr(PEDAL_CALIBRATE_TITLE), lambda: tr("CALIBRATE"), lambda: tr(PEDAL_CALIBRATE_DESCRIPTION),
                                       callback=self.start_calibration, enabled=lambda: self.model.enabled(PEDAL_CALIBRATE))
      self.build_row = text_item(lambda: tr(BUILD_TITLE), lambda: self.model.build_text(), lambda: tr(BUILD_DESCRIPTION))
      self.panda_row = text_item(lambda: tr(PANDA_FIRMWARE_TITLE), lambda: self._panda_firmware(), lambda: tr(PANDA_FIRMWARE_DESCRIPTION))
      attach_help(self.build_row, BUILD_INFO)
      attach_help(self.panda_row, PANDA_FIRMWARE)
      attach_help(self.status_row, PEDAL_STATUS)
      attach_help(self.calibrate_row, PEDAL_CALIBRATE)
      self.rows[PEDAL_STATUS] = self.status_row
      self.rows[PEDAL_CALIBRATE] = self.calibrate_row
      self.rows[BUILD_INFO] = self.build_row
      self.rows[PANDA_FIRMWARE] = self.panda_row
      # An empty or short page says why (no car / wrong car / longitudinal control off) instead of showing nothing.
      from openpilot.selfdrive.ui.bogpilot import menu_locks
      from openpilot.selfdrive.ui.bogpilot.vehicle_settings import disable_long_effective
      note = menu_locks.cached(lambda: menu_locks.page_note(ui_state.CP, "vehicle_controls", _safe(disable_long_effective)))
      self.note_row = menu_locks.note_row(note, "Not all rows are shown")
      self.scroller = Scroller([self.note_row, *self.rows.values()], line_separator=True, spacing=0)

    def _status(self):
      import time
      t, text = self._status_cache
      if time.monotonic() - t > 0.5:
        text = self.model.pedal_status()
        self._status_cache = (time.monotonic(), text)
      return text

    def _panda_firmware(self):
      import time
      t, text = getattr(self, "_fw_cache", (0.0, ""))
      if time.monotonic() - t > 1.0:
        text = self.model.panda_firmware_text()
        self._fw_cache = (time.monotonic(), text)
      return text

    def start_calibration(self):
      """Calibrate pressed: blocked reasons show as an alert; otherwise the full intro, then the guided screen."""
      snap = cal.read_snapshot(self.model.wall())
      reason = cal.blocked_reason(snap.live, self.model.moving())
      if reason or not self.model.visible(PEDAL_CALIBRATE):
        gui_app.push_widget(alert_dialog(tr(reason or "Calibration is not available for this car.")))
        return

      def started(result):
        if result == DialogResult.CONFIRM:
          session = cal.PedalCalSession(moving=self.model.moving)
          gui_app.push_widget(cal.create_calibration_screen(session))
      gui_app.push_widget(cal.create_intro_dialog(started))

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
      question = "Disable pedal longitudinal control on the next car start?" if is_preap(ui_state.CP) else "Disable openpilot longitudinal control on the next car start?"
      gui_app.push_widget(ConfirmDialog(tr(question),
                                        tr("Disable"), callback=done))

    def refresh(self):
      for key, row in self.rows.items():
        row.set_visible(self.model.visible(key))
        if key in TITLES:                      # toggles; the Pre-AP status / calibrate rows read live and have no switch
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
