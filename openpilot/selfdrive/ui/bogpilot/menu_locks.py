"""Why a BogPilot menu page is locked or empty, and how to unlock it.

Every Gas / Brake group needs openpilot longitudinal control: the live CarParams must report it. When it does not, the rows are
greyed out. In 0.9.7 the GAS / BRAKE button was not there for a car without it (and shown until a CarParams said otherwise);
the pill follows the same rule here. The page still explains a lock (and offers a button to the Disable setting) in case it is
open when the car state changes. Vehicle Controls and Wheel Controls hide their rows for a car they
do not support; they get the same kind of note instead of an empty page. This module only reads; it never changes a setting.

The pure functions need no raylib. Text is ASCII only (the help popup font has no wider glyphs) and has no angle brackets (the
description renderer reads them as tags).
"""
from __future__ import annotations

from dataclasses import dataclass

AP1_X = "TESLA_AP1_MODELX"
AP1_S = "TESLA_AP1_MODELS"
PREAP = "TESLA_PREAP_MODELS"
UNKNOWN_FINGERPRINTS = ("", "MOCK")

TITLE = "Locked: needs longitudinal control"
JUMP_TARGET = ("vehicle_settings", "vehicle_controls")   # menu pill and page that hold the Disable setting
UNLOCK_PATH = "Vehicle Settings, then VEHICLE SETTINGS, then Vehicle Controls"


@dataclass(frozen=True)
class Lock:
  code: str
  short: str          # right-hand value of the lock row
  detail: str         # what is wrong and what to do (the row's description)
  unlock_toggle: str  # param key of the setting that unlocks it, or ""
  unlock_title: str = ""  # that setting's name on screen


NO_CAR = Lock("no_car", "No car detected",
              "BogPilot has not identified a vehicle yet, so it does not know whether this car allows openpilot longitudinal control. "
              "Start the car once with the harness connected and let it finish starting, then open this page again.", "")
DASHCAM = Lock("dashcam", "Dashcam mode",
               "This vehicle is running in dashcam mode, so openpilot does not control the gas or the brake. "
               "Nothing in the BogPilot menus changes that.", "")
STEERING_ONLY = Lock("steering_only", "Steering only",
                     "This vehicle is steering only in this build: the car keeps its own cruise control for speed. "
                     "On a Model X, openpilot longitudinal control is the experimental Model X row in Vehicle Controls: it is "
                     "turned off, or the car has not restarted since it was turned on.", "")
RESTART = Lock("restart", "Restart the car",
               "openpilot longitudinal control is set to on, but the car has not been restarted since it was last off. "
               "Turn the car off and on again, then open this page again.", "")
NOT_SUPPORTED = Lock("not_supported", "Not supported",
                     "This vehicle does not support openpilot longitudinal control, so Gas / Brake has nothing to adjust.", "")


def _toggle_lock(fingerprint: str) -> Lock:
  name = "Disable Pedal Longitudinal" if fingerprint == PREAP else "Disable openpilot Longitudinal Control"
  return Lock("toggle_off", "Turned off",
              f"{name} is on. Turn it off in {UNLOCK_PATH}, then turn the car off and on again so it takes effect. "
              "Until then Gas / Brake stays locked and the car keeps its own cruise control.", "DisableOpenpilotLongitudinal", name)


def _text(value) -> str:
  if value is None:
    return ""
  if isinstance(value, (bytes, bytearray)):
    value = value.decode(errors="replace")
  return str(value).strip()


def _dashcam(cp) -> bool:
  return bool(getattr(cp, "dashcamOnly", False)) or bool(getattr(cp, "passive", False))


def long_lock(cp, disable_toggle_on: bool = False) -> Lock | None:
  """None when openpilot longitudinal control is available; otherwise the reason the Gas / Brake rows are locked.

  cp: the persisted CarParams (None when no car has ever been identified). disable_toggle_on: the effective value of
  Disable openpilot Longitudinal Control, as the car interface will read it at the next start.
  """
  if cp is None or _text(getattr(cp, "carFingerprint", "")) in UNKNOWN_FINGERPRINTS:
    return NO_CAR
  if bool(getattr(cp, "openpilotLongitudinalControl", False)):
    return None
  fingerprint = _text(cp.carFingerprint)
  if _dashcam(cp):
    return DASHCAM
  if fingerprint == AP1_X:
    # Disable openpilot Longitudinal Control wins over the experimental Model X row (tesla_ap1/interface.py).
    return _toggle_lock(fingerprint) if disable_toggle_on else STEERING_ONLY
  if fingerprint in (AP1_S, PREAP):
    return _toggle_lock(fingerprint) if disable_toggle_on else RESTART
  return NOT_SUPPORTED


# Locks for which the GAS / BRAKE pill stays on the menu. Strictly as in 0.9.7: with no car ever identified the pill is shown
# (0.9.7 started with "has longitudinal" true and only hid the pill once a persisted CarParams said otherwise), and once the
# car is known it is hidden whenever the car cannot do openpilot longitudinal control, including when the Disable setting
# is on or a restart is pending. The way back is the Disable toggle in Vehicle Controls, which stays visible for the car.
PILL_STAYS = ("no_car",)


def gas_brake_pill_visible(cp, disable_toggle_on: bool = False) -> bool:
  """0.9.7 rule: shown while no car is known, else only with openpilot longitudinal control and the Disable setting off."""
  lock = long_lock(cp, disable_toggle_on)
  if lock is None:
    return not disable_toggle_on     # 0.9.7: hasLongitudinalControl(CP) && !DisableOpenpilotLongitudinal
  return lock.code in PILL_STAYS


def effective_disable_toggle() -> bool:
  """Disable openpilot Longitudinal Control as the car interface reads it; False when it cannot be read."""
  try:
    from openpilot.selfdrive.ui.bogpilot.vehicle_settings import disable_long_effective
    return bool(disable_long_effective())
  except Exception:
    return False


# ---- Vehicle Controls / Wheel Controls: why the page is empty or short --------------------------------------------------
UNSUPPORTED_VEHICLE = Lock("unsupported_vehicle", "Not available",
                           "These settings are for a detected Tesla Model S with AP1 or Pre-AP. This vehicle has none of them.", "")
NO_CAR_VEHICLE = Lock("no_car", "No car detected",
                      "These settings appear for a detected Tesla Model S with AP1 or Pre-AP. BogPilot has not identified a vehicle yet: "
                      "start the car once with the harness connected, then open this page again.", "")
MODEL_X = Lock("steering_only", "Model X: steering only",
               "Model X runs steering only in this build, so it has no settings on this page.", "")
MODEL_X_VEHICLE = Lock("steering_only", "Model X: steering only",
                       "Model X runs steering only while Disable openpilot Longitudinal Control is on, or while the experimental "
                       "Model X openpilot longitudinal row on this page is off. A change takes effect the next time the car starts.", "")
MODEL_X_WHEEL = Lock("steering_only", "Model X: steering only",
                     "Wheel Controls on a Model X need openpilot longitudinal control. In Vehicle Controls, turn off Disable "
                     "openpilot Longitudinal Control and turn on the experimental Model X longitudinal row; it takes effect the "
                     "next time the car starts.", "")
WHEEL_AP1_ONLY = Lock("unsupported_vehicle", "AP1 only",
                      "Wheel Controls are for a Tesla Model S or Model X with AP1. This vehicle has none of them.", "")


def _supported(cp, fingerprints) -> bool:
  return cp is not None and _text(cp.carFingerprint) in fingerprints and not _dashcam(cp)


def page_note(cp, kind: str, disable_toggle_on: bool = False) -> Lock | None:
  """The note for a page whose rows depend on the car: kind is "vehicle_controls" or "stalk_controls".

  None when every row of the page can be shown. Otherwise why the page is empty (no car / wrong car), or, for a supported car,
  why the rows that need openpilot longitudinal control are hidden.
  """
  if cp is None or _text(getattr(cp, "carFingerprint", "")) in UNKNOWN_FINGERPRINTS:
    return NO_CAR_VEHICLE
  fingerprint = _text(cp.carFingerprint)
  if _dashcam(cp):
    return DASHCAM
  if fingerprint == AP1_X:
    if kind == "vehicle_controls":
      # The experimental Model X row lives here; once openpilot long is on for the X there is nothing to explain.
      return None if bool(getattr(cp, "openpilotLongitudinalControl", False)) else MODEL_X_VEHICLE
    if kind == "stalk_controls":
      return None if bool(getattr(cp, "openpilotLongitudinalControl", False)) else MODEL_X_WHEEL
    return MODEL_X
  allowed = (AP1_S, PREAP) if kind == "vehicle_controls" else (AP1_S,)
  if not _supported(cp, allowed):
    return UNSUPPORTED_VEHICLE if kind == "vehicle_controls" else WHEEL_AP1_ONLY
  if bool(getattr(cp, "openpilotLongitudinalControl", False)):
    return None
  lock = long_lock(cp, disable_toggle_on)
  if lock is None:
    return None
  return Lock(lock.code, "Some rows hidden", "Some rows on this page need openpilot longitudinal control and are hidden. " + lock.detail,
              lock.unlock_toggle)


class _Cached:
  """Evaluate fn at most every ttl seconds (the note is asked for several times a frame; one read of the settings file is enough)."""
  def __init__(self, fn, ttl=0.5):
    self._fn, self._ttl, self._at, self._value = fn, ttl, None, None

  def __call__(self):
    import time
    now = time.monotonic()
    if self._at is None or now - self._at >= self._ttl:
      self._value, self._at = self._fn(), now
    return self._value

  def refresh(self):
    self._at = None


def cached(fn, ttl=0.5):
  return _Cached(fn, ttl)


def note_row(get_note, title):
  """A list row showing get_note() -> Lock | None: title on the left, the short reason on the right and the full explanation
  open below. Hidden while get_note() is None. The widgets are imported here so the functions above stay pure."""
  from openpilot.system.ui.widgets.list_view import ITEM_TEXT_VALUE_COLOR, ListItem, TextAction

  class NoteRow(ListItem):
    def show_event(self):
      super().show_event()
      self._set_description_visible(True)

  def short():
    note = get_note()
    return note.short if note is not None else ""

  def detail():
    note = get_note()
    return note.detail if note is not None else ""

  row = NoteRow(title=title, description=detail, action_item=TextAction(text=short, color=ITEM_TEXT_VALUE_COLOR))
  row.set_visible(lambda: get_note() is not None)
  return row
