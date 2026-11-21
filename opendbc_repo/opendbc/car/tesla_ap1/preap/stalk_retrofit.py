"""Pre-AP auto-detect for an AP1 follow-distance stalk retrofit (no menu row, no saved setting).

Stock Pre-AP cruise stalks have no follow-distance twist. The one stock Pre-AP rlog we have carries DTR_Dist_Rq
as a constant 0 (ACC_DIST_1) on every STW_ACTN_RQ frame, never SNA and never another detent. Detection must not
latch on any number of copies of a single value: that would turn the dial on for a stock car.

The detector latches for the rest of the drive (one CarState instance, nothing persisted) only after two
distinct valid non-SNA detents have each been held for DETECT_FRAMES consecutive STW_ACTN_RQ frames
(2.5 s at the 10 Hz frame rate). Frames are counted from the CAN frame timestamp, so the 100 Hz carState
loop calling update() repeatedly with the same frame does not shorten the hold. SNA, a missing sample and any
non-detent value reset the current run and are never confirmed.

The first latch is saved once (PreApParamKeys.STALK_RETROFIT_DETECTED, written by carstate through the params snapshot thread);
a saved 1 makes the next start begin latched. Reset Hardware Settings clears it.
"""
from __future__ import annotations

# 25 consecutive new frames = 2.5 s at the 10 Hz STW_ACTN_RQ rate, counted from CAN timestamps. Detection runs once: the first latch is
# saved (PreAPStalkRetrofitDetected) and later starts skip it, so the slower, safer hold costs the driver one 2.5 s wait ever.
DETECT_FRAMES = 25
VALID_DETENTS = frozenset({0, 33, 66, 100, 133, 166, 200})
SNA = 255


def _as_detent(raw):
  if isinstance(raw, float) and raw.is_integer():
    raw = int(raw)
  if isinstance(raw, bool) or not isinstance(raw, int):
    return None
  if raw == SNA or raw not in VALID_DETENTS:
    return None
  return raw


class StalkRetrofitDetector:
  """Per-drive latch. Construct one on CarState; it is not persisted."""

  def __init__(self):
    self.latched = False
    self._run_val = None
    self._run_len = 0
    self._confirmed = set()
    self._last_ts = None

  def latch(self) -> None:
    """Start latched (the retrofit was detected on an earlier drive and saved): no detection, the dial is read from frame one."""
    self.latched = True

  def wants(self, frame_ts) -> bool:
    """True only when observe() has work: not latched yet and a new, real frame timestamp (10 Hz, not the 100 Hz loop).

    carstate checks this before it reads or decodes anything, so after a latch (or a saved flag) and on every repeat step of
    one frame the detection path is a couple of comparisons. A missing frame (None / 0) has nothing to count."""
    return (not self.latched) and bool(frame_ts) and frame_ts != self._last_ts

  def observe(self, raw, frame_ts=None) -> None:
    """Feed the current DTR_Dist_Rq sample (None if the message has not been seen).

    frame_ts is the CAN timestamp of that signal. A repeat of the same timestamp is the same frame and is
    ignored; None means every call is a new frame (unit tests, no timestamp source). Once latched this does nothing.
    """
    if self.latched:
      return
    if frame_ts is not None and frame_ts == self._last_ts:
      return
    detent = _as_detent(raw)
    if detent is None:
      self._run_val = None
      self._run_len = 0
      self._last_ts = frame_ts
      return
    if frame_ts is not None:
      self._last_ts = frame_ts
    if detent == self._run_val:
      self._run_len += 1
    else:
      self._run_val = detent
      self._run_len = 1
    if self._run_len >= DETECT_FRAMES:
      self._confirmed.add(detent)
      if len(self._confirmed) >= 2:
        self.latched = True
