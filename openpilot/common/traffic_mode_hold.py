"""On-screen personality-button hold that toggles Traffic Mode.

0.9.7 used a 2.5 s hold (ONROAD_TRAFFIC_HOLD in the 0.9.7 controls and card code).
BogPilot 0.11.2 restores the same gesture at 1.0 s. A brief tap is handled by
the HUD and still cycles personalities; a hold must not also step.

0.9.7 only let the hold toggle while longitudinal was active (or to leave Traffic
Mode). An earlier build kept that gate and the hold never registered on its drive: the
personality taps (205 to 242 s into the logged drive) all happened while openpilot was
disengaged, and trafficModeEnabled stayed false. The gate is gone: Traffic Mode
is a latch that only the planner and radard read, so toggling it while driving
by hand is harmless, and a hold now always answers (the red Traffic pill).

The AP1 cruise-stalk distance detent 1 still turns Traffic Mode on (and a later
stalk traffic-command change turns it off or on again). The latch is only
updated when that command changes, so a hold can stick until the next stalk
move. 0.9.7 assigned the stalk flag every frame, which would have made the
hold a no-op on AP1 once the stalk was publishing.
"""
from __future__ import annotations

ONROAD_TRAFFIC_HOLD = 1.0  # s, on-screen personality button hold that toggles Traffic Mode


class TrafficModeHold:
  def __init__(self):
    self.enabled = False
    self._press_start = None
    self._fired = False
    self._stalk_traffic = None

  def apply_stalk(self, traffic):
    """traffic is True, False, or None (not ready / leave the latch alone)."""
    if traffic is None:
      return
    traffic = bool(traffic)
    if traffic != self._stalk_traffic:
      self._stalk_traffic = traffic
      self.enabled = traffic

  def update_button(self, pressed, now):
    """pressed is OnroadDistanceButtonPressed. The toggle fires once when the
    hold reaches ONROAD_TRAFFIC_HOLD, not again until release."""
    if pressed:
      if self._press_start is None:
        self._press_start = now
      if not self._fired and now - self._press_start >= ONROAD_TRAFFIC_HOLD:
        self._fired = True
        self.enabled = not self.enabled
    else:
      self._press_start = None
      self._fired = False
    return self.enabled
