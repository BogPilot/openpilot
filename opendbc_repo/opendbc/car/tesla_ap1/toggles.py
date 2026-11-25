"""Stored Tesla Early preferences. Not applied to CarParams.

TeslaLongControl and TeslaStalkFollow are params only. CarInterface,
dashcamOnly, panda safety flags, and controlsd do not read them.
There is no TeslaPlatform param. The platform is classify_tesla_platform.
A stored string cannot force preap, ap1_s, ap1_x, or ap2.

EnableICIntegration gates AP1 instrument-cluster substitution. July
prebuilt params_pyx.so has no Tesla* keys (same constraint as
TeslaLongControl / TeslaStalkFollow): putting a new key in
bogpilot_default_params raises UnknownKeyName at boot. So this toggle
is file-backed under /data/params_bogpilot/EnableICIntegration, not a
Params key. Absent file + AP1 fingerprint => on. Explicit 0/false/off
=> off. Non-AP1 => always off.

The Qt vehicle panel (bogpilot/ui/qt/offroad/vehicle_settings.cc) does
not render bogpilot/ui/layouts/settings/toggle_metadata.py, and the
device runs a July prebuilt UI binary, so this toggle is not shown in
Settings. Change it on device with:
  echo 0 > /data/params_bogpilot/EnableICIntegration   # off
  echo 1 > /data/params_bogpilot/EnableICIntegration   # on
then restart openpilot (or reboot). See docs/tesla/DIVERGENCES.md.

Not a product. No warranty. The driver remains responsible. Comply with local law.
"""

from pathlib import Path

TESLA_LONG_CONTROL_VALUES = ("off", "lateral_only", "full")
TESLA_LONG_CONTROL_DEFAULT = "off"
TESLA_STALK_FOLLOW_DEFAULT = True

# Reading these helpers must not change CarParams. This constant is the contract.
APPLIED_TO_CAR_PARAMS = False

# File-backed: July params_pyx.so cannot store EnableICIntegration.
IC_INTEGRATION_DIR = Path("/data/params_bogpilot")
IC_INTEGRATION_PATH = IC_INTEGRATION_DIR / "EnableICIntegration"
# Tests may override the path via this module attribute.
_ic_integration_path = IC_INTEGRATION_PATH


def tesla_long_control(stored: str | bytes | None) -> str:
  """Return off, lateral_only, or full.

  Unknown, empty, and integer ButtonParamControl indexes ("0", "1", "2")
  are off. Not applied to CarParams, dashcamOnly, or safety flags.
  """
  text = _as_text(stored)
  if text in TESLA_LONG_CONTROL_VALUES:
    return text
  return TESLA_LONG_CONTROL_DEFAULT


def tesla_stalk_follow(stored: str | bytes | None) -> bool:
  """Stored TeslaStalkFollow preference.

  Unset is on. That default is only a stored preference for early Tesla.
  Explicit off is 0, false, or off. Any other text is off.
  controlsd does not call this. Car state may still parse the stalk on its own.
  """
  if stored is None:
    return TESLA_STALK_FOLLOW_DEFAULT
  text = _as_text(stored)
  if text == "":
    return TESLA_STALK_FOLLOW_DEFAULT
  if text in ("1", "true", "on"):
    return True
  if text in ("0", "false", "off"):
    return False
  return False


def enable_ic_integration(fingerprint: str | None, stored: str | bytes | None = None) -> bool:
  """Whether AP1 cluster substitution runs.

  Non-AP1 fingerprints are always off (control hidden / inert).
  AP1: default on when the file is absent. Explicit off stops all cluster
  TX immediately so the panda forwards stock 0x399 / 0x389 / 0x239.
  `stored` overrides the file when not None (tests). Not applied to CarParams.
  """
  from opendbc.car.tesla_ap1.values import CAR
  if fingerprint != CAR.TESLA_AP1_MODELS:
    return False
  if stored is not None:
    text = _as_text(stored)
  else:
    text = _read_ic_integration_file()
  if text == "":
    return True
  if text in ("1", "true", "on"):
    return True
  if text in ("0", "false", "off"):
    return False
  return True


def set_enable_ic_integration(enabled: bool, path: Path | None = None) -> None:
  """Write the file-backed EnableICIntegration preference."""
  target = path if path is not None else _ic_integration_path
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text("1" if enabled else "0")


def _read_ic_integration_file() -> str:
  try:
    if _ic_integration_path.is_file():
      return _ic_integration_path.read_text(encoding="utf-8", errors="replace").strip()
  except OSError:
    pass
  return ""


def _as_text(stored: str | bytes | None) -> str:
  if stored is None:
    return ""
  if isinstance(stored, bytes):
    stored = stored.decode()
  return stored.strip()


# AP1 standstill-engage experiment (Tinkla standby DAS_control). File-backed,
# default ON on this test branch: /data/params_bogpilot/AP1StandstillEngage ("0"/"off" = off). Read once
# at car init (interface.py) and turned into panda TESLA_FLAG_AP1_STANDSTILL.
AP1_STANDSTILL_PATH = IC_INTEGRATION_DIR / "AP1StandstillEngage"
_ap1_standstill_path = AP1_STANDSTILL_PATH


def ap1_standstill_engage(fingerprint: str | None, stored: str | bytes | None = None) -> bool:
  """AP1 only. Test branch: on unless the file (or `stored`) says 0/false/off."""
  from opendbc.car.tesla_ap1.values import CAR
  if fingerprint != CAR.TESLA_AP1_MODELS:
    return False
  if stored is None:
    try:
      stored = _ap1_standstill_path.read_text(encoding="utf-8", errors="replace") if _ap1_standstill_path.is_file() else "1"
    except OSError:
      stored = "1"
  return _as_text(stored) not in ("0", "false", "off")


# 0.9.7 FrogPilot DisableOpenpilotLongitudinal (default "0": openpilot long ON).
# opendbc cannot read Params, so this reads the stored value as a file:
# /data/params_bogpilot/DisableOpenpilotLongitudinal first, then the 0.9.7
# params store. Missing or unreadable means the default (long ON).
DISABLE_OP_LONG_PATHS = (IC_INTEGRATION_DIR / "DisableOpenpilotLongitudinal",
                         Path("/data/params/d/DisableOpenpilotLongitudinal"))


def disable_openpilot_long(stored: str | bytes | None = None, paths=None) -> bool:
  if stored is None:
    stored = ""
    for p in (paths if paths is not None else DISABLE_OP_LONG_PATHS):
      try:
        if p.is_file():
          stored = p.read_text(encoding="utf-8", errors="replace")
          break
      except OSError:
        continue
  return _as_text(stored).lower() in ("1", "true", "on")


# AP1 stalk tip rounding (AP1TipRoundSet). Originally developed on the 0.9.7 line (archived and removed). File-backed, default ON:
# /data/params_bogpilot/AP1TipRoundSet. A missing, empty or unreadable file means ON; only an explicit 0/false/off turns it off, so a
# value saved earlier (either way) is preserved and a fresh install is on. When on, Ap1RaiseHoldoff rounds the software set to a whole
# display unit (km/h when IsMetric, else mph) before a +-1 / next-5 / prev-5 tip, so a 14.8 mph tip-engage latch + full tip up gives
# 20, not 15. Settings > Vehicle > Stalk Controls > Round Set Speed Tips writes the same file (offroad only).
# AP1 Model S and AP1 Model X. The rounding lives in the openpilot set-speed path, which the X only uses with openpilot
# longitudinal (AP1XOpenpilotLong); with stock cruise the X set speed is the car's own and nothing is rounded.
AP1_TIP_ROUND_PATH = IC_INTEGRATION_DIR / "AP1TipRoundSet"
_ap1_tip_round_path = AP1_TIP_ROUND_PATH


def ap1_tip_round_set(fingerprint: str | None, stored: str | bytes | None = None) -> bool:
  """AP1 Model S and Model X. Off only when the file (or `stored`) says 0/false/off. Missing, empty, unreadable, or any other
  text = on."""
  from opendbc.car.tesla_ap1.values import CAR
  if fingerprint not in (CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX):
    return False
  if stored is None:
    try:
      stored = _ap1_tip_round_path.read_text(encoding="utf-8", errors="replace") if _ap1_tip_round_path.is_file() else ""
    except OSError:
      stored = ""
  return _as_text(stored).lower() not in ("0", "false", "off")


def set_ap1_tip_round(enabled: bool, path: Path | None = None) -> None:
  """Write the file-backed AP1TipRoundSet preference (the Stalk Controls row)."""
  target = path if path is not None else _ap1_tip_round_path
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text("1" if enabled else "0")


# AP1 Model X openpilot longitudinal (AP1XOpenpilotLong). EXPERIMENTAL. File-backed, default ON for a detected AP1 Model X:
# /data/params_bogpilot/AP1XOpenpilotLong. Only an explicit 0/false/off turns it off (the user's choice for stock TACC); a missing,
# empty, unreadable or any other value is on. A one-time migration (openpilot/common/bogpilot_ap1_profile.py
# force_ap1x_op_long_on_once) writes 1 once on a detected X, even over a saved 0, and never again. There is no row for it any more:
# the UI's Disable openpilot Longitudinal Control row is the Model X's single longitudinal row and writes 1 here, and a saved 0 is
# carried over to Disable on at start (merge_ap1x_long_into_disable). Read once at car init
# (interface.py): it makes the strictly detected AP1 Model X use openpilot longitudinal (CarParams.openpilotLongitudinalControl
# plus the AP1 safety LONG_CONTROL flag). Never applies to any other car; the panda and safety limits are the Model S ones.
AP1X_OP_LONG_PATH = IC_INTEGRATION_DIR / "AP1XOpenpilotLong"
_ap1x_op_long_path = AP1X_OP_LONG_PATH
AP1X_OP_LONG_DEFAULT = True
AP1X_OP_LONG_OFF = ("0", "false", "off")


def ap1x_op_long(fingerprint: str | None, stored: str | bytes | None = None) -> bool:
  """AP1 Model X only. On unless the file (or `stored`) says 0/false/off. Every other car is off."""
  from opendbc.car.tesla_ap1.values import CAR
  if fingerprint != CAR.TESLA_AP1_MODELX:
    return False
  if stored is None:
    try:
      stored = _ap1x_op_long_path.read_text(encoding="utf-8", errors="replace") if _ap1x_op_long_path.is_file() else ""
    except OSError:
      stored = ""
  return _as_text(stored).lower() not in AP1X_OP_LONG_OFF


def set_ap1x_op_long(enabled: bool, path: Path | None = None) -> None:
  """Write the file-backed AP1XOpenpilotLong preference (the Vehicle row)."""
  target = path if path is not None else _ap1x_op_long_path
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text("1" if enabled else "0")
