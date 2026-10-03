"""Stored Tesla Early preferences. Not applied to CarParams.

TeslaLongControl and TeslaStalkFollow are params only. CarInterface,
dashcamOnly, panda safety flags, and controlsd do not read them.
There is no TeslaPlatform param. The platform is classify_tesla_platform.
A stored string cannot force preap, ap1_s, ap1_x, or ap2.

The Qt vehicle panel (frogpilot/ui/qt/offroad/vehicle_settings.cc) does not
render frogpilot/ui/layouts/settings/toggle_metadata.py. These keys are the
same default-param list other toggles use. No new settings screen.

Not a product. No warranty. The driver remains responsible. Comply with local law.
"""

TESLA_LONG_CONTROL_VALUES = ("off", "lateral_only", "full")
TESLA_LONG_CONTROL_DEFAULT = "off"
TESLA_STALK_FOLLOW_DEFAULT = True

# Reading these helpers must not change CarParams. This constant is the contract.
APPLIED_TO_CAR_PARAMS = False


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


def _as_text(stored: str | bytes | None) -> str:
  if stored is None:
    return ""
  if isinstance(stored, bytes):
    stored = stored.decode()
  return stored.strip()
