"""Which BogPilot settings can change while the car is on: FrogPilot 0.9.7 onroad parity.

0.9.7 (bogpilot-tesla 04d560f3) has no global onroad lock on its settings panels. What it does have:

* stock `<Param>Lock` and the stock offroad-only Device / Software actions (settings.cc:99-100, 275-278, 298):
  Power Off, the calibration / driver camera / training buttons, and Install stay offroad only;
* a "Reboot required to take effect." prompt (Reboot Now / Reboot Later) after a change while `started` on the
  Lateral, Model and Vehicle panels and on Disable openpilot Longitudinal (lateral_settings.cc:183-196,
  model_settings.cc:273-277, vehicle_settings.cc:132-145 and 338-352);
* downloads (models, themes, maps, software) only while `!started || parked` (model_settings.cc:388,
  software_settings.cc:165-169);
* sound settings that stay live onroad (sounds_settings.cc:144-146 test-plays through the alert path while started).

This module is the one place that says, per BogPilot menu page (and the few rows inside a page that differ), which of
four classes it is in, and answers "may this be edited now?" for each. It is pure (no raylib, no Params at import); the
UI passes `editor(page)` wherever a page used to pass `ui_state.is_offroad`.

Classes
  ONROAD  editable while driving, no prompt (Alert Volume, Alerts, Appearance / Navigation, Device screen settings,
          the non-destructive Data / Utilities actions).
  REBOOT  editable while driving; the first change on the page while the car is on shows the 0.9.7 reboot prompt
          (Steering / Lane Changes = Lateral, Driving Model, Car Selection, Vehicle Controls incl. Disable Longitudinal,
          Wheel / Stalk Controls).
  PARKED  only with the car off or in Park (downloads, pedal calibration, radar VIN read).
  LOCKED  only with the car off (Tuning Level, Gas / Brake, destructive Data / Utilities actions, Disable Logging and
          the Device Settings master, and every stock offroad-only action, which keeps its own stock gate).

Disable openpilot Longitudinal Control is the one REBOOT row whose consumers also read it live (the planners through
common/bogpilot_onroad_toggles and phase3_long_stopping). While the car is on its change is staged here and applied
when the car turns off, at the next UI start with the car off, or just before Reboot Now, so a drive never runs half
with and half without openpilot longitudinal control. Nothing here touches the Alert Volume floors.
"""
from __future__ import annotations

import json
from collections.abc import Callable

ONROAD = "onroad"
REBOOT = "reboot"
PARKED = "parked"
LOCKED = "locked"
CLASSES = (ONROAD, REBOOT, PARKED, LOCKED)

REBOOT_PROMPT = "Reboot required to take effect."           # 0.9.7 FrogPilotConfirmationDialog::toggleReboot
REBOOT_NOW = "Reboot Now"
REBOOT_LATER = "Reboot Later"
DISENGAGE_TO_REBOOT = "Disengage to Reboot"                  # stock settings.cc DevicePanel::reboot
NOTE = {
  ONROAD: "",
  REBOOT: "While the car is on, changes here take effect after a reboot",
  PARKED: "Put the car in Park to change these",
  LOCKED: "Locked while the car is on",
}

# ---- per page (menu page keys from layouts/settings/bogpilot.py) ---------------------------------------------------
PAGE_CLASS: dict[str, str] = {
  # Alerts and Sounds
  "volume": ONROAD,
  "alerts": ONROAD,
  # Appearance / Navigation (bogpilot_visuals never had an offroad gate)
  "navigation_widgets": ONROAD,
  "appearance": ONROAD,
  # System Settings: page is ONROAD, the rows in ROW_CLASS below stay PARKED / LOCKED
  "system_data": ONROAD,
  "system_device": ONROAD,
  "system_utilities": ONROAD,
  # Driving Controls
  "steering_tuning": REBOOT,     # 0.9.7 Lateral
  "lane_changes": REBOOT,        # 0.9.7 Lateral (lane change rows sit in lateral_settings.cc)
  "driving_model": REBOOT,       # 0.9.7 Model
  "gas_brake": LOCKED,           # 0.9.7 Longitudinal was live; kept offroad only here (see ONROAD_CAVEATS)
  # Vehicle Settings
  "car_selection": REBOOT,       # 0.9.7 Vehicles: Car Make / Model
  "vehicle_controls": REBOOT,    # 0.9.7 Vehicles: tweaks + Disable openpilot Longitudinal
  "stalk_controls": REBOOT,      # 0.9.7 Wheel Controls (vehicle tweak)
  "vehicle_info": ONROAD,        # read only
}

# Home-page controls that are not pages.
MENU_CLASS: dict[str, str] = {
  "tuning_level": LOCKED,        # 0.9.7 allowed it; kept offroad only (see ONROAD_CAVEATS)
}

# Rows inside an ONROAD / REBOOT page that are stricter than their page.
ROW_CLASS: dict[str, str] = {
  # Device Controls > Device Settings
  "DeviceManagement": LOCKED,    # master: turning it off re-enables logging mid-drive when Disable Logging is on
  "NoLogging": LOCKED,           # manager would stop loggerd / encoderd mid-route
  # Data
  "data:delete": LOCKED,         # Delete Driving Data / Error Logs / Screen Recordings / Toggle Backups
  "data:rename": LOCKED,
  "data:restore": LOCKED,        # Toggle Backups RESTORE / Apply Preview changes driving preferences
  "data:stats_reset": LOCKED,
  # Utilities
  "BogPilotDefaultsReset": LOCKED,
  "DoToggleResetStock": LOCKED,
  "ClearCaches": LOCKED,
  # Vehicle Controls rows that keep their own (stricter) gate
  "PedalCalibrate": PARKED,      # vehicle_settings.calibrate_allowed (parked / not moving)
  "TeslaRadarReadVin": PARKED,   # read_vin_blocked: car on, in Park, not engaged
  # Downloads (0.9.7: !started || parked)
  "downloads": PARKED,
}

# Groups 0.9.7 allowed onroad that this build keeps stricter, and why (reported with the patch).
ONROAD_CAVEATS: dict[str, str] = {
  "gas_brake": "Gas / Brake (0.9.7 Longitudinal) changes follow distance, personalities, acceleration and stopping live "
               "in the planner; kept offroad only until Bardo opts in.",
  "tuning_level": "Tuning Level decides which saved values the live consumers honour, so a mid-drive change can "
                  "silently swap tuned values for defaults; kept offroad only.",
  "NoLogging": "Disable Logging (and the Device Settings master above it) makes the manager stop loggerd and encoderd "
               "mid-route; kept offroad only.",
  "data:delete": "Delete / rename / restore / stats reset in Data and the reset / clear actions in Utilities are "
                 "destructive (0.9.7 allowed them onroad); kept offroad only.",
}


def page_class(page_key: str) -> str:
  """Class of a menu page; an unknown page is LOCKED (fail closed)."""
  return PAGE_CLASS.get(page_key, LOCKED)


def row_class(row_key: str, page_key: str | None = None) -> str:
  """Class of a row: its own entry, else its page's class, else LOCKED."""
  if row_key in ROW_CLASS:
    return ROW_CLASS[row_key]
  if row_key in MENU_CLASS:
    return MENU_CLASS[row_key]
  return page_class(page_key) if page_key is not None else LOCKED


def allowed(cls: str, started: bool, parked: bool = False) -> bool:
  """May a control of class `cls` be edited now?"""
  if not started:
    return True
  if cls in (ONROAD, REBOOT):
    return True
  if cls == PARKED:
    return bool(parked)
  return False


def downloads_allowed(started: bool, parked: bool) -> bool:
  """0.9.7 model_settings.cc:388 / software_settings.cc:166: `!started || parked`."""
  return allowed(ROW_CLASS["downloads"], started, parked)


def needs_reboot_prompt(cls: str, started: bool) -> bool:
  return bool(started) and cls == REBOOT


def note(cls: str, started: bool, parked: bool = False) -> str:
  """Header text for a page of class `cls` (empty when nothing is restricted right now)."""
  if not started:
    return ""
  if cls == PARKED and parked:
    return ""
  return NOTE.get(cls, NOTE[LOCKED])


# ---- live state -----------------------------------------------------------------------------------------------------
class DriveState:
  """started / parked / engaged, read from ui_state unless the callables are given (tests)."""

  def __init__(self, started: Callable[[], bool] | None = None, parked: Callable[[], bool] | None = None,
               engaged: Callable[[], bool] | None = None):
    self._started, self._parked, self._engaged = started, parked, engaged

  @staticmethod
  def _ui():
    from openpilot.selfdrive.ui.ui_state import ui_state
    return ui_state

  def started(self) -> bool:
    try:
      if self._started is not None:
        return bool(self._started())
      return not self._ui().is_offroad()          # the same source the pages used before (tests patch it)
    except Exception:
      return True                                  # cannot tell: treat as driving (fail closed)

  def parked(self) -> bool:
    if not self.started():
      return True
    try:
      if self._parked is not None:
        return bool(self._parked())
      from openpilot.cereal import car
      cs = self._ui().sm["carState"]
      return cs.gearShifter == car.CarState.GearShifter.park
    except Exception:
      return False

  def engaged(self) -> bool:
    try:
      return bool(self._engaged()) if self._engaged is not None else bool(self._ui().engaged)
    except Exception:
      return True


_state = DriveState()


def set_state(state: DriveState | None) -> None:
  """Tests: swap the live state source (None restores ui_state)."""
  global _state
  _state = state if state is not None else DriveState()


def state() -> DriveState:
  return _state


def can_edit(cls: str) -> bool:
  s = _state
  started = s.started()
  return allowed(cls, started, s.parked() if started else True)


def editor(page_key: str, row_key: str | None = None) -> Callable[[], bool]:
  """The callable a page passes where it used to pass `ui_state.is_offroad`."""
  cls = row_class(row_key, page_key) if row_key is not None else page_class(page_key)
  return lambda: can_edit(cls)


def is_started() -> bool:
  return _state.started()


# ---- reboot prompt (once per page visit while the car is on) ----------------------------------------------------------
_prompted: set[str] = set()
_prompt_ui: Callable[[str], None] | None = None


def new_visit() -> None:
  """menu_097 calls this whenever the open page changes, so the next change on a REBOOT page prompts again."""
  _prompted.clear()


def set_prompt_ui(show: Callable[[str], None] | None) -> None:
  """Tests: replace the dialog with a recorder. None restores the raylib dialog."""
  global _prompt_ui
  _prompt_ui = show


def changed(page_key: str) -> bool:
  """A REBOOT-class page saved a change. Shows the reboot prompt once per page visit while the car is on.
  Returns True when the prompt was shown."""
  if not needs_reboot_prompt(page_class(page_key), is_started()) or page_key in _prompted:
    return False
  _prompted.add(page_key)
  (_prompt_ui or _show_reboot_dialog)(page_key)
  return True


def on_change(page_key: str) -> Callable[..., None]:
  return lambda *_args, **_kw: changed(page_key)


def reboot_now(put_bool: Callable[[str, bool], object] | None = None,
               alert: Callable[[str], object] | None = None) -> bool:
  """Reboot Now pressed. Refused while engaged (stock DevicePanel rule, stricter than 0.9.7's instant reboot). Applies
  the staged changes first, then asks the manager to reboot (DoReboot, as stock)."""
  if _state.engaged():
    if alert is not None:
      alert(DISENGAGE_TO_REBOOT)
    return False
  apply_pending()
  if put_bool is None:
    from openpilot.common.params import Params
    put_bool = Params().put_bool
  put_bool("DoReboot", True)
  return True


def _show_reboot_dialog(_page_key: str) -> None:
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import DialogResult
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog

  def done(result):
    if result == DialogResult.CONFIRM:
      reboot_now(alert=lambda text: gui_app.push_widget(alert_dialog(tr(text))))

  gui_app.push_widget(ConfirmDialog(tr(REBOOT_PROMPT), tr(REBOOT_NOW), tr(REBOOT_LATER), callback=done))


# ---- staged changes (applied with the car off) ------------------------------------------------------------------------
PENDING_KEY = "OnroadPendingChanges"     # file store (/data/params_bogpilot), JSON {key: value}
STAGED_KEYS = ("DisableOpenpilotLongitudinal",)
_appliers: dict[str, Callable[[object], bool]] = {}


def register_applier(key: str, apply: Callable[[object], bool] | None) -> None:
  """Tests: replace (or with None, restore) the writer used for a staged key."""
  if apply is None:
    _appliers.pop(key, None)
  else:
    _appliers[key] = apply


def _default_applier(key: str):
  if key == "DisableOpenpilotLongitudinal":
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import apply_staged_long
    return apply_staged_long
  return None


def _read_all() -> dict:
  from openpilot.common.bogpilot_store import read_text
  try:
    value = json.loads(read_text(PENDING_KEY) or "{}")
  except (TypeError, ValueError):
    return {}
  return value if isinstance(value, dict) else {}


def _write_all(values: dict) -> bool:
  from openpilot.common.bogpilot_store import remove_file, write_text
  if not values:
    remove_file(PENDING_KEY)
    return True
  return bool(write_text(PENDING_KEY, json.dumps(values, sort_keys=True)))


def stage(key: str, value) -> bool:
  if key not in STAGED_KEYS:
    raise KeyError(key)
  values = _read_all()
  values[key] = value
  return _write_all(values)


def pending(key: str, default=None):
  return _read_all().get(key, default)


def has_pending(key: str | None = None) -> bool:
  values = _read_all()
  return bool(values) if key is None else key in values


def clear_pending(key: str) -> None:
  values = _read_all()
  if key in values:
    values.pop(key)
    _write_all(values)


def apply_pending() -> dict:
  """Write every staged change through its registered applier. Only with the car off or right before a reboot (the
  caller checks). Returns {key: applied?}. A key without an applier stays staged; a refused write is dropped (the car
  or its capability changed, as a stale offroad confirmation would be)."""
  values = _read_all()
  if not values:
    return {}
  out, keep = {}, {}
  for key, value in values.items():
    apply = _appliers.get(key) or _default_applier(key)
    if apply is None:
      keep[key] = value
      continue
    try:
      out[key] = bool(apply(value))
    except Exception:
      out[key] = False
  _write_all(keep)
  return out


_installed = False


def install(ui_state=None) -> None:
  """Apply staged changes on every switch to offroad (and right away when the car is already off). Idempotent."""
  global _installed
  if _installed:
    return
  if ui_state is None:
    from openpilot.selfdrive.ui.ui_state import ui_state as _ui
    ui_state = _ui

  def on_transition():
    if not ui_state.started:
      apply_pending()
    new_visit()

  ui_state.add_offroad_transition_callback(on_transition)
  _installed = True
  if not ui_state.started:
    apply_pending()


__all__ = ["ONROAD", "REBOOT", "PARKED", "LOCKED", "CLASSES", "PAGE_CLASS", "MENU_CLASS", "ROW_CLASS", "ONROAD_CAVEATS",
           "page_class", "row_class", "allowed", "downloads_allowed", "needs_reboot_prompt", "note", "DriveState",
           "set_state", "state", "can_edit", "editor", "is_started", "new_visit", "set_prompt_ui", "changed", "on_change",
           "reboot_now", "stage", "pending", "has_pending", "clear_pending", "apply_pending", "register_applier", "install"]
