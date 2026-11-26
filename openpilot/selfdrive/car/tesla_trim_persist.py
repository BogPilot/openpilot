"""Save the Tesla trim detection the car made this drive (opendbc tesla_ap1/trims.py), for the offroad Vehicle page's
Detected line and Trim list, and as the next drive's rpm per m/s seed.

Runs in card's 10 Hz params thread (never in the 100 Hz step). Writes only when something new is known. A new detection
(chassis, layout, Performance rear, or a first learned rpm per m/s) is written at once, like stock's CarParamsPersistent.
A refinement of an rpm per m/s that is already saved is written only when it moved by more than RPM_CHANGE_FRAC, at most
every REFINE_INTERVAL_S (paramsd LiveParametersV2 cadence), plus once on the edge into Park. That is a handful of tiny writes
per drive at most, and none on a drive where nothing changed.
"""
from __future__ import annotations

import math

from openpilot.common.bogpilot_checkpoint import LEARNED_INTERVAL_S

POLL_S = 1.0
RPM_CHANGE_FRAC = 0.01
REFINE_INTERVAL_S = LEARNED_INTERVAL_S
TESLA_TRIM_FINGERPRINTS = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS")


def _k(x) -> float | None:
  try:
    x = float(x)
  except (TypeError, ValueError):
    return None
  return x if math.isfinite(x) and x > 0.0 else None


def detection_from_car_state(CS, fingerprint):
  """trims.Detected from carState.bogpilot, or None while the layout is still unknown."""
  from opendbc.car.tesla_ap1 import trims
  bp = CS.bogpilot
  layout = int(getattr(bp, "ap1DriveLayout", 0) or 0)
  if layout not in (trims.LAYOUT_SINGLE, trims.LAYOUT_DUAL):
    return None
  perf = int(getattr(bp, "ap1PerfRear", 0) or 0) if layout == trims.LAYOUT_DUAL else trims.PERF_UNKNOWN
  measured = bool(getattr(bp, "ap1RpmPerMsMeasured", False))
  rear = _k(getattr(bp, "ap1RearRpmPerMs", None)) if measured else None
  front = _k(getattr(bp, "ap1FrontRpmPerMs", None)) if (measured and layout == trims.LAYOUT_DUAL and
                                                         perf != trims.PERF_UNKNOWN) else None
  return trims.Detected(trims.chassis_of(fingerprint), layout, perf if perf in (1, 2) else 0,
                        trims.clamp_rpm_per_ms(rear) if rear else None, trims.clamp_rpm_per_ms(front) if front else None)


def _new_detection(a, b) -> bool:
  """Something not known before: no saved detection, another chassis/layout/perf, or a first rpm per m/s."""
  if b is None:
    return True
  if (a.chassis, a.layout, a.perf) != (b.chassis, b.layout, b.perf):
    return True
  return any(x is not None and y is None
             for x, y in ((a.rear_rpm_per_ms, b.rear_rpm_per_ms), (a.front_rpm_per_ms, b.front_rpm_per_ms)))


def _refined(a, b) -> bool:
  """A saved rpm per m/s moved by more than RPM_CHANGE_FRAC."""
  for x, y in ((a.rear_rpm_per_ms, b.rear_rpm_per_ms), (a.front_rpm_per_ms, b.front_rpm_per_ms)):
    if x is None or y is None:
      continue                        # nothing new learned: keep what is saved
    if abs(x - y) > RPM_CHANGE_FRAC * y:
      return True
  return False


def _differs(a, b) -> bool:
  return _new_detection(a, b) or _refined(a, b)


def _parked(CS) -> bool:
  try:
    from opendbc.car.structs import car
    return bool(CS.gearShifter == car.CarState.GearShifter.park)
  except Exception:
    return False


class TrimPersist:
  def __init__(self, fingerprint, path=None):
    self.fingerprint = str(fingerprint or "")
    self.enabled = self.fingerprint in TESLA_TRIM_FINGERPRINTS
    self.path = path
    self.last_poll = None
    self.last_write = None   # time of the last write, or of the first poll (refinements wait a full interval)
    self.was_parked = None
    self.saved = None
    self.writes = 0
    if self.enabled:
      from opendbc.car.tesla_ap1 import trims
      saved = trims.read_detected(path=path)
      self.saved = saved if saved.chassis == trims.chassis_of(self.fingerprint) else None

  def poll(self, CS, now: float) -> bool:
    """Called from the params thread; True when it wrote. Never raises."""
    if not self.enabled or CS is None:
      return False
    if self.last_poll is not None and now - self.last_poll < POLL_S:
      return False
    self.last_poll = now
    if self.last_write is None:
      self.last_write = now
    parked = _parked(CS)
    park_edge = parked and self.was_parked is False
    self.was_parked = parked
    try:
      from opendbc.car.tesla_ap1 import trims
      det = detection_from_car_state(CS, self.fingerprint)
      if det is None:
        return False
      old = self.saved
      same = old is not None and old.layout == det.layout
      # keep what an earlier drive learned until this drive measures it (perf, rpm per m/s)
      merged = trims.Detected(det.chassis, det.layout, det.perf or (old.perf if same else trims.PERF_UNKNOWN),
                              det.rear_rpm_per_ms or (old.rear_rpm_per_ms if same else None),
                              det.front_rpm_per_ms or (old.front_rpm_per_ms if same else None))
      if not _new_detection(merged, old):
        if not _refined(merged, old):
          return False
        if not park_edge and now - self.last_write < REFINE_INTERVAL_S:
          return False
      if trims.write_detected(merged, self.path):
        self.saved = merged
        self.writes += 1
        self.last_write = now
        return True
    except Exception:
      pass
    return False
