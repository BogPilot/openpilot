"""AP1 cluster lane placement (0x239 DAS_lanes C0..C3). Display only.

Ported from BogPilot 0.9.7 bogpilot-tesla-ic-discovery-2 selfdrive/car/tesla/ic_lanes.py
(lane fix only; the 1 Hz shadow log and the lead "snap" log are not ported, they
only logged and needed a radarState SubMaster that opendbc cannot own).

Default ON for AP1, same as the 0.9.7 test branch: a missing
/data/params_bogpilot/ICLanes means "lanes". The file can hold:
  (missing / empty / anything else), 1 / true / on / lanes / snap
              Engaged 0x239 path from openpilot's lane lines, in the cluster's
              own units (see "Mapping").  "snap" is accepted for old files and
              behaves as "lanes" (its extra shadow log is not ported).
  0 / false / off
              The shipped cluster.py mapping (C0 = C1 = 0, C2 * 4), unchanged.

Why. While engaged the cluster draws openpilot's 0x239 lane path but stock
Mobileye 0x309 objects. The shipped path put C0 = C1 = 0 and C2 = 4 * model path
C2 (Tinkla IC_LANE_SCALE = 0.5 -> C_n * 2^n). On 0.9.7 AP1 rlogs (engaged, stock
0x309 LEAD-mux objects 3..100 m) 19.5 % of ego-lane objects fell outside the sent
lane, vs 6.0 % against stock 0x239. The lane-line fit below gives 3.0 %. The
cluster reads C0..C3 in plain meters, so no 2^n scale.

Mapping (DAS frame: x forward m, y + RIGHT m, same as DAS Dy and modelV2 y):
  - Lane center = (laneLines[1] + laneLines[2]) / 2, cubic least squares over
    0..60 m. C0..C3 unscaled, clipped to the DBC ranges. Width, usage and forks
    stay stock.
  - Fallback 1 (lane lines missing / short): model path through the origin,
    C2 unscaled, C0 = C1 = 0.
  - Fallback 2: actuator curvature, C2 = curvature / 2, unscaled, 50 m.

No CAN id, rate, counter, checksum, panda or safety change: 0x239 is already in
the AP1 TX allowlist and the substitution list, and its encoding is untouched.

Not a product, no warranty, driver remains responsible.
"""

from pathlib import Path

import numpy as np

from opendbc.car.tesla_ap1.cluster import (
  C0_RANGE, C1_RANGE, C2_RANGE, C3_RANGE, LANE_VIEW_RANGE_M, MODEL_C2_FIT_M, MODEL_FIT_MAX_M, MODEL_PATH_MIN_M,
  ModelPath, clamp_view_range_m,
)

ICLANES_PATH = Path("/data/params_bogpilot/ICLanes")
# Tests override this module attribute.
_iclanes_path = ICLANES_PATH

MODE_OFF = "off"
MODE_LANES = "lanes"
_OFF_WORDS = ("0", "false", "off")

LANE_FIT_MAX_M = 60.0
LANE_PROB_MIN = 0.0
LEFT_NEAR, RIGHT_NEAR = 1, 2
TOGGLE_POLL_FRAMES = 100  # 1 Hz at the 100 Hz control rate

SRC_LANES = "lanes"
SRC_PATH = "path"
SRC_CURV = "curvature"


def ic_lanes_mode(fingerprint, stored=None) -> str:
  """AP1 Model S only. lanes unless the file (or `stored`) says 0/false/off."""
  from opendbc.car.tesla_ap1.values import CAR
  if fingerprint != CAR.TESLA_AP1_MODELS:
    return MODE_OFF
  if stored is None:
    try:
      stored = _iclanes_path.read_text(encoding="utf-8", errors="replace") if _iclanes_path.is_file() else ""
    except OSError:
      stored = ""
  if isinstance(stored, bytes):
    stored = stored.decode(errors="replace")
  return MODE_OFF if stored.strip().lower() in _OFF_WORDS else MODE_LANES


def _clip(v, lo_hi):
  return float(min(max(float(v), lo_hi[0]), lo_hi[1]))


def _view_range(model_v2):
  try:
    xs = np.asarray(model_v2.position.x, dtype=float)
  except Exception:
    return None
  xs = xs[np.isfinite(xs) & (xs > 0.5)]
  if xs.size < 4:
    return None
  v = min(float(xs[-1]), MODEL_FIT_MAX_M)
  return v if v >= MODEL_PATH_MIN_M else None


def lane_poly_from_model_v2(model_v2):
  """Lane-center cubic from the two near lane lines, DAS units, unscaled."""
  try:
    lines = model_v2.laneLines
    probs = list(model_v2.laneLineProbs)
    if len(lines) <= RIGHT_NEAR or len(probs) <= RIGHT_NEAR:
      return None
    if probs[LEFT_NEAR] < LANE_PROB_MIN or probs[RIGHT_NEAR] < LANE_PROB_MIN:
      return None
    x = np.asarray(lines[LEFT_NEAR].x, dtype=float)
    yl = np.asarray(lines[LEFT_NEAR].y, dtype=float)
    yr = np.asarray(lines[RIGHT_NEAR].y, dtype=float)
  except Exception:
    return None
  if not (x.size == yl.size == yr.size) or x.size < 6:
    return None
  y = (yl + yr) / 2.0
  m = np.isfinite(x) & np.isfinite(y) & (x >= 0.0) & (x <= LANE_FIT_MAX_M)
  if int(m.sum()) < 6:
    return None
  c = np.polyfit(x[m], y[m], 3)[::-1]
  if not np.all(np.isfinite(c)):
    return None
  view = _view_range(model_v2)
  if view is None:
    view = float(LANE_VIEW_RANGE_M)
  return ModelPath(c0=_clip(c[0], C0_RANGE), c1=_clip(c[1], C1_RANGE), c2=_clip(c[2], C2_RANGE),
                   c3=_clip(c[3], C3_RANGE), view_range_m=float(clamp_view_range_m(view)))


def path_poly_unscaled(model_v2):
  """Shipped through-origin path C2 fit, without the 2^n scale."""
  try:
    xs = np.asarray(model_v2.position.x, dtype=float)
    ys = np.asarray(model_v2.position.y, dtype=float)
  except Exception:
    return None
  if xs.size < 4 or xs.size != ys.size:
    return None
  view = _view_range(model_v2)
  if view is None:
    return None
  n = np.isfinite(xs) & np.isfinite(ys) & (xs > 0.5) & (xs <= MODEL_C2_FIT_M)
  if int(n.sum()) < 4:
    return None
  den = float(np.sum(xs[n] ** 4))
  if den <= 0.0:
    return None
  c2 = float(np.sum(xs[n] ** 2 * ys[n]) / den)
  if not np.isfinite(c2):
    return None
  return ModelPath(0.0, 0.0, _clip(c2, C2_RANGE), 0.0, float(clamp_view_range_m(view)))


def corrected_lane_poly(model_v2, curvature: float):
  """(ModelPath, source). Lane lines, else path, else actuator curvature."""
  if model_v2 is not None:
    p = lane_poly_from_model_v2(model_v2)
    if p is not None:
      return p, SRC_LANES
    p = path_poly_unscaled(model_v2)
    if p is not None:
      return p, SRC_PATH
  return ModelPath(0.0, 0.0, _clip(float(curvature) / 2.0, C2_RANGE), 0.0, float(LANE_VIEW_RANGE_M)), SRC_CURV


class IcLanes:
  """Toggle state (re-read at 1 Hz) and the corrected lane polynomial."""

  def __init__(self, fingerprint):
    self.fingerprint = fingerprint
    self.mode = MODE_OFF
    self.frame = 0

  def poll(self) -> str:
    if self.frame % TOGGLE_POLL_FRAMES == 0:
      self.mode = ic_lanes_mode(self.fingerprint)
    self.frame += 1
    return self.mode

  @property
  def on(self) -> bool:
    return self.mode != MODE_OFF

  def poly(self, model_v2, curvature):
    return corrected_lane_poly(model_v2, curvature)
