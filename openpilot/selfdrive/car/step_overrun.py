"""card's 100 Hz step overrun counter (no messaging imports, so it is testable anywhere)."""


class StepOverrunCounter:
  """card step overruns (a step longer than its 10 ms slot): counted, worst kept, logged at most every LOG_S."""
  SLOT_S = 0.01
  LOG_S = 10.0

  def __init__(self, log_fn):
    self.log_fn = log_fn
    self.overruns = 0
    self.worst_s = 0.0
    self._window = 0
    self._window_worst = 0.0
    self._last_log: float | None = None

  def record(self, dt: float, now: float) -> None:
    if dt > self.SLOT_S:
      self.overruns += 1
      self._window += 1
      self.worst_s = max(self.worst_s, dt)
      self._window_worst = max(self._window_worst, dt)
    if self._window and (self._last_log is None or now - self._last_log >= self.LOG_S):
      self.log_fn(f"card: {self._window} step overrun(s) > {self.SLOT_S * 1000:.0f} ms, worst {self._window_worst * 1000:.0f} ms "
                  f"({self.overruns} total)")
      self._window, self._window_worst, self._last_log = 0, 0.0, now
