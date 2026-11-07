"""Driver camera while in reverse (raylib port of bogpilot-tesla 0.9.7, 04d560f3).

0.9.7 behaviour (frogpilot_ui.cc:93, home.cc:80-86, window.cc:140):
  enabled = QOLVisuals and DriverCamera; while started and gear == reverse a counter grows each UI frame;
  at >= UI_FREQ/2 (0.5 s) the driver camera view replaces the onroad view, the sidebar is hidden and touches
  are ignored; leaving reverse returns to the onroad view immediately.
Port notes: time-based 0.5 s hold instead of a frame count; a stale/invalid carState counts as "not reverse"
(timer resets) so a frozen gear cannot hold the view. No params, processes, recording or uploads are touched:
onroad the cabin stream already runs (camerad/dmonitoringmodeld are started-or-driverview processes).
"""
from __future__ import annotations

import time

HOLD_S = 0.5             # 0.9.7: driver_camera_timer >= UI_FREQ / 2
STALE_S = 0.5            # carState older than this is ignored


def enabled_from(store) -> bool:
  try:
    return bool(store.get_bool("QOLVisuals")) and bool(store.get_bool("DriverCamera"))
  except Exception:
    return False


class ReverseCameraController:
  def __init__(self, clock=time.monotonic):
    self._clock = clock
    self._since: float | None = None

  def reset(self) -> None:
    self._since = None

  def update(self, started: bool, enabled: bool, in_reverse: bool, carstate_fresh: bool) -> bool:
    """Return True while the driver camera should replace the onroad view."""
    if not (started and enabled and in_reverse and carstate_fresh):
      self._since = None
      return False
    now = self._clock()
    if self._since is None:
      self._since = now
    return now - self._since >= HOLD_S


def read_gear(sm, now_mono: float | None = None) -> tuple[bool, bool]:
  """(in_reverse, fresh) from ui_state.sm['carState']."""
  try:
    fresh = bool(sm.alive["carState"]) and bool(sm.valid["carState"])
    if fresh and now_mono is not None and sm.recv_time["carState"] > 0:
      fresh = (now_mono - sm.recv_time["carState"]) <= STALE_S
    from opendbc.car.structs import car
    return sm["carState"].gearShifter == car.CarState.GearShifter.reverse, fresh
  except Exception:
    return False, False
