"""Onroad Camera View choices: Auto, Standard and Wide.

The stored CameraView codes are the 367e1fe ones and stay as they are: 0 Auto, 2 Standard, 3 Wide. Code 1 was "Driver"
(the cabin camera as the onroad view); it is no longer offered, and a saved 1, like any other value that is not one of
the three, reads as Auto. Nothing is written back.

Onroad (onroad/augmented_road_view.py _switch_stream_if_needed): Standard always shows the narrow road camera, Wide always
the wide one (narrow when there is no wide stream), Auto is the upstream switching below. The setting is a child of
Quality of Life Visuals (Settings > Visuals); with that off the view is Auto.

Auto is upstream openpilot 0.11.2 (selfdrive/ui/onroad/augmented_road_view.py): in Experimental Mode, with the wide
road stream available, wide below WIDE_CAM_MAX_SPEED (5 m/s, 11 mph), narrow above ROAD_CAM_MIN_SPEED (10 m/s, 22 mph),
the current stream in between; narrow otherwise.

The cabin camera is still shown while reversing (QOLVisuals + DriverCamera, bogpilot/reverse_camera.py) and from
Settings > Device > Cabin Camera; neither reads CameraView.
"""
AUTO, LEGACY_DRIVER, STANDARD, WIDE = 0, 1, 2, 3
OPTIONS: dict[int, str] = {AUTO: "Auto", STANDARD: "Standard", WIDE: "Wide"}


def normalize(raw) -> int:
  """Stored CameraView value -> AUTO, STANDARD or WIDE. Driver (1), junk, None and out-of-range values -> AUTO."""
  try:
    if isinstance(raw, bytes):
      raw = raw.decode()
    value = float(str(raw).strip())
  except (TypeError, ValueError, UnicodeDecodeError):
    return AUTO
  if value != value or value != int(value):
    return AUTO
  value = int(value)
  return value if value in OPTIONS else AUTO


CODES = tuple(OPTIONS)          # button order on the settings row: Auto, Standard, Wide


def selected_view(store) -> int:
  """The onroad Camera View to use now. QOLVisuals off, no store or any read error -> AUTO."""
  try:
    if store is None or not store.get_bool("QOLVisuals"):
      return AUTO
    return normalize(store.get("CameraView"))
  except Exception:
    return AUTO


def button_index(view: int) -> int:
  return CODES.index(view) if view in CODES else 0
