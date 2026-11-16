"""Pre-AP Bosch radar retrofit: radar point filters (pure Python, no CAN parsing, no panda change).

Every filter here is used on Pre-AP only (is_preap); AP1 Model S / Model X never construct them. They only withhold radar
points, so the camera lead path is unchanged: a withheld point means a vision-only lead (or none), never an added lead.
Measured basis and references: docs/tesla/DIVERGENCES_preap_radar_filters.md.
"""
from collections import deque

# (4) Bosch point gate: Tinkla/BogGyver selfdrive/car/tesla/radar_interface.py:12-13,129-135 @ 501c7de
# (BOSCH_MAX_DIST, OBJECT_MIN_PROBABILITY) and NotAutopilot opendbc car/tesla/radar_interface.py:105-109 @ cc39c7fa.
BOSCH_MAX_DIST = 250.0         # m, RadarPoint LongDist
OBJECT_MIN_PROBABILITY = 50.0  # %, RadarPoint ProbExist

# (2) Stuck track: a point whose range does not move while ego speed changes is not a road object.
STUCK_WINDOW_S = 5.0
STUCK_MAX_SPAN_M = 0.2      # max - min dRel over the window
STUCK_MAX_ABS_VREL = 0.13   # m/s on every sample (two LongSpeed steps of 0.0625)
STUCK_MIN_EGO_DV = 3.0      # m/s, ego speed change over the window
STUCK_RELEASE_SPAN_M = 0.5  # a flagged track is released once its range moves this much in the window


def bosch_point_valid(long_dist: float, prob_exist: float) -> bool:
  return 0.0 < long_dist <= BOSCH_MAX_DIST and prob_exist >= OBJECT_MIN_PROBABILITY


class StuckTrackFilter:
  """Per trackId: flag a track whose dRel moves <= STUCK_MAX_SPAN_M with |vRel| <= STUCK_MAX_ABS_VREL over a full
  STUCK_WINDOW_S while ego speed changed by >= STUCK_MIN_EGO_DV. update() returns True while the track is flagged."""
  def __init__(self, window_s: float = STUCK_WINDOW_S, max_span_m: float = STUCK_MAX_SPAN_M,
               max_abs_vrel: float = STUCK_MAX_ABS_VREL, min_ego_dv: float = STUCK_MIN_EGO_DV,
               release_span_m: float = STUCK_RELEASE_SPAN_M):
    self.window_s = window_s
    self.max_span_m = max_span_m
    self.max_abs_vrel = max_abs_vrel
    self.min_ego_dv = min_ego_dv
    self.release_span_m = release_span_m
    self.hist: dict[int, deque] = {}
    self.flagged: set[int] = set()

  def update(self, track_id: int, d_rel: float, v_rel: float, v_ego: float, t: float) -> bool:
    h = self.hist.setdefault(track_id, deque())
    h.append((t, d_rel, v_rel, v_ego))
    while t - h[0][0] > self.window_s:
      h.popleft()
    ds = [x[1] for x in h]
    span = max(ds) - min(ds)
    if track_id in self.flagged:
      if span > self.release_span_m:
        self.flagged.discard(track_id)
    elif t - h[0][0] >= 0.95 * self.window_s and span <= self.max_span_m and all(abs(x[2]) <= self.max_abs_vrel for x in h):
      ves = [x[3] for x in h]
      if max(ves) - min(ves) >= self.min_ego_dv:
        self.flagged.add(track_id)
    return track_id in self.flagged

  def prune(self, live_ids) -> None:
    for k in list(self.hist):
      if k not in live_ids:
        del self.hist[k]
        self.flagged.discard(k)
