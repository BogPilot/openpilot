"""AP1 blind-spot flags from the stock Mobileye AutopilotStatus (0x399).

The stock DAS sends DAS_blindSpotRearLeft / DAS_blindSpotRearRight in 0x399
on bus 2 (cp_cam), the frame the cluster substitution already reads. Values
(tesla_can.dbc VAL_ 921): 0 NO_WARNING, 1 WARNING_LEVEL_1, 2 WARNING_LEVEL_2,
3 SNA.

Fail-closed for lane change: left/right Blindspot is True (OCCUPIED) when
  - WARNING_LEVEL_1/2 is held, OR
  - SNA (3) on a checksum-OK frame, OR
  - garbage/unreadable value on a checksum-OK frame, OR
  - no checksum-OK 0x399 frame within BSM_STALE_S (dropout / bad-checksum skip).
Only a recent checksum-OK NO_WARNING (0) clears that side.

0x399 comes at about 2.4 Hz, so each side holds for BSM_HOLD_S after the last
occupied report. Bad-checksum frames are skipped (no refresh); staleness then
forces OCCUPIED. Read-only: nothing here is sent to the car.
"""
from opendbc.car.tesla_ap1.cluster import (
  AUTOPILOT_STATUS, CHECKSUM_SIGNALS, MSG_NAMES, SIGNALS, pack, tesla_checksum,
)

# Seconds a side stays on after the last occupied report.
BSM_HOLD_S = 1.0
# No checksum-OK frame within this many seconds → OCCUPIED (unknown).
BSM_STALE_S = 1.5

BSM_LEFT = "DAS_blindSpotRearLeft"
BSM_RIGHT = "DAS_blindSpotRearRight"
BSM_DETECTED = (1, 2)  # WARNING_LEVEL_1, WARNING_LEVEL_2
BSM_SNA = 3
BSM_CLEAR = 0

_NAME = MSG_NAMES[AUTOPILOT_STATUS]
_CHECKSUM = CHECKSUM_SIGNALS[AUTOPILOT_STATUS]


def checksum_ok(values):
  """True when DAS_statusChecksum matches the frame rebuilt from its signals."""
  try:
    body = {k: v for k, v in values.items() if k != _CHECKSUM and k in SIGNALS[AUTOPILOT_STATUS]}
    dat = pack(AUTOPILOT_STATUS, SIGNALS[AUTOPILOT_STATUS], body).to_bytes(8, "little")
    return int(values[_CHECKSUM]) == tesla_checksum(AUTOPILOT_STATUS, dat)
  except (KeyError, TypeError, ValueError):
    return False


def detected(value):
  try:
    return int(value) in BSM_DETECTED
  except (TypeError, ValueError):
    return False


def is_sna(value):
  try:
    return int(value) == BSM_SNA
  except (TypeError, ValueError):
    return True  # unreadable → treat as invalid/SNA


def is_clear(value):
  try:
    return int(value) == BSM_CLEAR
  except (TypeError, ValueError):
    return False


def frames_from_vl_all(cp_cam):
  """0x399 frames received this step, oldest first, as {signal: value}."""
  sigs = cp_cam.vl_all.get(_NAME, {}) if hasattr(cp_cam.vl_all, "get") else {}
  n = len(sigs.get(_CHECKSUM, []))
  out = []
  for i in range(n):
    f = {}
    for name, vals in sigs.items():
      if i < len(vals):
        f[name] = vals[i]
    out.append(f)
  return out


class Ap1Blindspot:
  """Per-side hold + staleness: SNA/stale/invalid → OCCUPIED (Blindspot True)."""

  def __init__(self, hold_s=BSM_HOLD_S, stale_s=BSM_STALE_S):
    self.hold_s = hold_s
    self.stale_s = stale_s
    self.left_s = 0.0   # seconds of occupied hold left
    self.right_s = 0.0
    # Age since last checksum-OK frame for that side; start stale → OCCUPIED.
    self.left_age = stale_s + 1.0
    self.right_age = stale_s + 1.0
    self.bad_checksum = 0

  @property
  def left(self):
    return self.left_s > 0.0 or self.left_age > self.stale_s

  @property
  def right(self):
    return self.right_s > 0.0 or self.right_age > self.stale_s

  @property
  def left_valid(self):
    return self.left_age <= self.stale_s

  @property
  def right_valid(self):
    return self.right_age <= self.stale_s

  def _apply_side(self, side: str, value) -> None:
    age_attr = f"{side}_age"
    hold_attr = f"{side}_s"
    setattr(self, age_attr, 0.0)  # fresh checksum-OK observation
    if is_clear(value):
      setattr(self, hold_attr, 0.0)
    else:
      # WARNING, SNA, or garbage → OCCUPIED
      setattr(self, hold_attr, self.hold_s)

  def update(self, frames, dt):
    """Age holds/freshness by dt, then apply this step's frames. Returns (left, right) OCCUPIED."""
    self.left_s = max(0.0, self.left_s - dt)
    self.right_s = max(0.0, self.right_s - dt)
    self.left_age += dt
    self.right_age += dt
    for f in frames:
      if not checksum_ok(f):
        self.bad_checksum += 1
        continue
      self._apply_side("left", f.get(BSM_LEFT))
      self._apply_side("right", f.get(BSM_RIGHT))
    return self.left, self.right
