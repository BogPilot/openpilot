"""AP1 brake level from the 0x39D brake booster rod stroke (BrakeBoosterStroke in tesla_ap1_can.dbc).

BogPilot divergence from drive-log evidence (no BogPilot / Tinkla / NAP definition; see DIVERGENCES.md). Display only:
carstate publishes it in the deprecated CarState.brake slot for the onroad decel bar; nothing in controls reads it.
"""
import math

ADDR = 0x39D
# Rest stroke: the mode of unpressed frames (174; a few counts lower, 168, was also seen). Lower reads as 0.
BRAKE_STROKE_REST = 174
# 100 % point: 21 * 256 + 255, the top of a byte-3 reading of 21 (the hardest press logged, stroke 5470, a firm press
# at a standstill). A harder press (panic / ABS stop) pegs at 1.0. May be revised.
BRAKE_STROKE_TOP = 21 * 256 + 255
# 25 Hz frame: older than this (about 12 frames) counts as missing.
BRAKE_LEVEL_MAX_AGE_S = 0.5
# Published when the frame is missing, stale or fails its checksum, so the UI can tell "no level" from "released" (0.0).
BRAKE_LEVEL_MISSING = -1.0


def stroke_checksum(counter: int, stroke: int) -> int:
  """Tesla sum checksum of the frame: address bytes + byte 1 (counter, high nibble 0) + bytes 2-3 (stroke LE)."""
  return ((ADDR & 0xFF) + (ADDR >> 8) + (counter & 0x0F) + (stroke & 0xFF) + ((stroke >> 8) & 0xFF)) & 0xFF


def brake_level(stroke, counter, checksum, fresh: bool) -> float:
  """clamp((stroke - REST) / (TOP - REST), 0, 1) for a fresh frame with a valid checksum, else BRAKE_LEVEL_MISSING."""
  if not fresh:
    return BRAKE_LEVEL_MISSING
  try:
    st, ctr, ck = float(stroke), float(counter), float(checksum)
  except (TypeError, ValueError):
    return BRAKE_LEVEL_MISSING
  if not all(math.isfinite(v) for v in (st, ctr, ck)):
    return BRAKE_LEVEL_MISSING
  if stroke_checksum(int(ctr), int(st)) != int(ck):
    return BRAKE_LEVEL_MISSING
  return min(max((st - BRAKE_STROKE_REST) / (BRAKE_STROKE_TOP - BRAKE_STROKE_REST), 0.0), 1.0)
