"""Shared Tesla stalk-tip hold-repeat state machine (AP1 openpilot long and Pre-AP pedal, BogPilot 0.11.2).

One rule for both platforms, driven by the raw SpdCtrlLvr detent (16 up / 32 down = light, 4 up / 8 down = deep):
  light press            -> one +-1 display unit on the press frame
  light held             -> after INITIAL_S (0.35 s) a +-1 every PERIOD_S (0.2 s) while held
  deep press             -> one step to the next / previous 5, never repeats
  light then deep        -> one upgrade to the next / previous 5 (once), never repeats
  release / direction    -> state resets; a re-press starts the delay again

This class is unit-less and only does the timing. The caller owns the speed, its whole-unit rounding and its clamps.
"""

INITIAL_S = 0.35
PERIOD_S = 0.2
_EPS_S = 1e-6        # nine 50 ms ticks sum to 0.44999..; same slack idea as Ap1RaiseHoldoff.TIP_HOLD_EPS_S
_MAX_REPEATS_PER_CALL = 8

LIGHT_UP, LIGHT_DOWN, DEEP_UP, DEEP_DOWN = 16, 32, 4, 8


def lever_to_dir_deep(spd_ctrl_lvr: int) -> tuple[int, bool]:
  """Raw SpdCtrlLvr_Stat -> (direction +1 / -1 / 0, deep)."""
  v = int(spd_ctrl_lvr)
  if v == LIGHT_UP:
    return 1, False
  if v == DEEP_UP:
    return 1, True
  if v == LIGHT_DOWN:
    return -1, False
  if v == DEEP_DOWN:
    return -1, True
  return 0, False


class StalkTipRepeat:
  """update(direction, deep, dt) -> list of events: "press_light", "press_deep", "repeat", "upgrade"."""

  def __init__(self):
    self.reset()

  def reset(self):
    self.dir = 0
    self.held_s = 0.0
    self.next_repeat_s = INITIAL_S
    self.repeats = 0
    self.done = False   # deep reached (press_deep / upgrade): nothing more while held

  def update(self, direction: int, deep: bool, dt: float) -> list[str]:
    direction = int(direction)
    if direction == 0:
      self.reset()
      return []
    if direction != self.dir:
      self.reset()
      self.dir = direction
      if deep:
        self.done = True
        return ["press_deep"]
      return ["press_light"]
    self.held_s += max(float(dt), 0.0)
    if self.done:
      return []
    if deep:
      self.done = True
      return ["upgrade"]
    events: list[str] = []
    while self.held_s >= self.next_repeat_s - _EPS_S and len(events) < _MAX_REPEATS_PER_CALL:
      events.append("repeat")
      self.repeats += 1
      self.next_repeat_s += PERIOD_S
    return events
