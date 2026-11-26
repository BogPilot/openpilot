"""AP1 0x488 restart after a control stall. No CAN, no parser.

The panda forwards the stock DAS 0x488 to the EPAS again once openpilot has not sent an accepted frame for 100 ms
(tesla_ap1.h, TESLA_AP1_STEER_SUBSTITUTE_TIMEOUT_US). If card stalls for that long (a system-wide hiccup, recorded
on the bench comma when the on-device screen recorder started), the EPAS gets stock frames, and when card wakes up
it works through the queued CAN. Before this module it then sent at once from the stale stock counter it had just read, so:
  - its first frame reused a counter the panda had just forwarded from the stock DAS (both ctr 9, about 0.5 ms apart),
  - frames went out 5 to 13 ms apart while the backlog drained (nominal 20 ms),
  - ANGLE resumed at the old target while the EPAS had just dropped from ACTIVE to AVAILABLE on the stock NONE frames.
The EPAS answered with INHIBITED + EAC_ERROR_HIGH_ANGLE_RATE_REQ (7) 40 ms later and kept code 7 latched.

What this does (openpilot side only):
  1. Stall detection, either sign is enough, but only while openpilot owns the stream (it sent a 0x488 on the previous
     control step or within OWNED_FRAMES):
       - wall clock: more than STALL_NS since the last 0x488 openpilot built (now_nanos is card's monotonic clock; a
         value that does not move forward is ignored so replays and fixed-time tests only use the counter sign), or
       - stock stream: STALL_STOCK_BURST or more stock 0x488 counters drained in one control step, or the newest stock
         counter jumping by STALL_STOCK_BURST or more since the last step. At 50 Hz stock and 100 Hz control a live
         step sees 0 or 1 counter (2 at most with jitter); 3 is a backlog of 40 ms or more.
  2. While resyncing openpilot sends no 0x488 at all, so the EPAS only sees the stock stream the panda forwards and
     nothing can clash with it (no duplicate or backward counter, no mixed NONE/ANGLE pair).
  3. Resume needs RESYNC_LIVE_FRAMES control steps in a row that each bring exactly one stock counter, newest + 1
     modulo 16 from the previous one, so the backlog is gone and the counter sync (steer_counter.py) is fresh. When
     now_nanos moves forward, those steps also need at least LIVE_SPACING_NS between them (a drained backlog arrives in
     steps a few ms apart). The counter sync forgets openpilot's last counter, so the next frame is stock + 2 exactly
     as at a normal engage.
  4. `resumed` is true on the step the block ends; the controller restarts the measured-wheel soft-start from there,
     so the EPAS is commanded from the current angle and the engage ramp blends to the planner, like a new engage.
  5. If the stock stream is missing for STOCK_GONE_FRAMES after the stall there is nothing to clash with: resume on
     the stale-stock cadence of steer_counter.py, still through the soft-start.
"""

STALL_NS = 60_000_000          # 60 ms. Logged openpilot 0x488 gaps outside the stall: max 32 ms.
STALL_STOCK_BURST = 3
OWNED_FRAMES = 6               # same window as steer_counter.OWNED_FRAMES
RESYNC_LIVE_FRAMES = 3         # three live stock frames in a row, about 60 ms
LIVE_SPACING_NS = 8_000_000    # 8 ms between live steps (stock 0x488 is 20 ms; a drained backlog came 5 ms apart)
STOCK_GONE_FRAMES = 30         # 0.3 s of control steps with no stock 0x488 at all
COUNTER_MOD = 16


class Ap1SteerResync:
  def __init__(self):
    self.reset()

  def reset(self):
    self.active = False
    self.resumed = False
    self.stalls = 0
    self.live = 0
    self.no_stock = 0
    self.last_send_nanos = None
    self.last_send_frame = None
    self.last_stock = None
    self.last_live_nanos = None
    self.last_now = None
    self.last_reason = None

  def _owned(self, frame):
    return self.last_send_frame is not None and frame - self.last_send_frame <= OWNED_FRAMES

  def _clock_ok(self, now_nanos):
    return now_nanos is not None and self.last_now is not None and now_nanos > self.last_now

  def update(self, stock_counters, frame, now_nanos):
    """One call per control step, before the 0x488 for this step is built. Returns True while 0x488 must not be sent."""
    self.resumed = False
    stock = [int(c) % COUNTER_MOD for c in (stock_counters or ())]
    clock_ok = self._clock_ok(now_nanos)

    jump = None
    if stock and self.last_stock is not None:
      jump = (stock[-1] - self.last_stock) % COUNTER_MOD

    if not self.active and self._owned(frame):
      reason = None
      if clock_ok and self.last_send_nanos is not None and now_nanos - self.last_send_nanos > STALL_NS:
        reason = "clock"
      elif len(stock) >= STALL_STOCK_BURST or (jump is not None and jump >= STALL_STOCK_BURST):
        reason = "stock_burst"
      if reason is not None:
        self.active = True
        self.stalls += 1
        self.live = 0
        self.no_stock = 0
        self.last_live_nanos = None
        self.last_reason = reason

    if self.active:
      if len(stock) == 1 and jump == 1 and (not clock_ok or self.last_live_nanos is None or
                                            now_nanos - self.last_live_nanos >= LIVE_SPACING_NS):
        self.live += 1
        self.last_live_nanos = now_nanos if clock_ok else None
      elif stock:
        self.live = 0
        self.last_live_nanos = None
      self.no_stock = 0 if stock else self.no_stock + 1
      if self.live >= RESYNC_LIVE_FRAMES or self.no_stock >= STOCK_GONE_FRAMES:
        self.active = False
        self.resumed = True
        self.live = 0

    if stock:
      self.last_stock = stock[-1]
    if now_nanos is not None and (self.last_now is None or now_nanos > self.last_now):
      self.last_now = now_nanos
    return self.active

  def sent(self, frame, now_nanos):
    """A 0x488 was built this step."""
    self.last_send_frame = frame
    self.last_send_nanos = now_nanos
