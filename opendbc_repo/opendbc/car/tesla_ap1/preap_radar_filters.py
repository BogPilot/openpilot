"""Pre-AP Bosch radar retrofit: radar point filters (pure Python, no CAN parsing, no panda change).

Every filter here is used on Pre-AP only (is_preap); AP1 Model S / Model X never construct them. They only withhold radar
points, so the camera lead path is unchanged: a withheld point means a vision-only lead (or none), never an added lead.
Measured basis and references: docs/tesla/DIVERGENCES_preap_radar_filters.md.
"""

# (1) SGUFail hold: camera only once RADC_SGUFail has been set for SGUFAIL_HOLD_S of CAN time; radar points come back
# after it has been clear for SGUFAIL_RELEASE_S. At the slowest measured radar rate (7.4 Hz) 1.0 s is 7 radar cycles.
SGUFAIL_HOLD_S = 1.0
SGUFAIL_RELEASE_S = 1.0


class SguFailHold:
  """update() returns True (camera only) while RADC_SGUFail is held. No fault and no alert: only the points are withheld."""
  def __init__(self, hold_s: float = SGUFAIL_HOLD_S, release_s: float = SGUFAIL_RELEASE_S):
    self.hold_s = hold_s
    self.release_s = release_s
    self.on_since = None
    self.off_since = None
    self.active = False

  def update(self, sgu_fail: bool, t: float) -> bool:
    if sgu_fail:
      self.off_since = None
      if self.on_since is None:
        self.on_since = t
      if t - self.on_since >= self.hold_s:
        self.active = True
    else:
      self.on_since = None
      if self.off_since is None:
        self.off_since = t
      if t - self.off_since >= self.release_s:
        self.active = False
    return self.active
