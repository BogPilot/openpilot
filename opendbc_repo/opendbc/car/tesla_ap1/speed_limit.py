"""AP1 posted speed limit for BogPilot dashboardSpeedLimit.

Mobileye DAS_fusedSpeedLimit (stock AutopilotStatus on autopilot_chassis /
bus 2) first, then GTW UI_mapSpeedLimit / UI_mppSpeedLimit. Output is m/s for
bogpilotCarState.dashboardSpeedLimit (same as Toyota/Ford/Hyundai).

Stock 0x399 only: CarState reads AutopilotStatus from cp_cam
(CANBUS.autopilot_chassis). Cluster TX is on chassis bus 0 and never reaches
that parser. SNA / UNKNOWN / UNLIMITED / missing → 0.

UI_mapSpeedLimit is a DBC enum (VAL_ 568 / BO_ 968), not a scaled mph field.
UI_mppSpeedLimit and DAS_fusedSpeedLimit use factor 5 (opendbc returns the
physical mph or kph). Units come from UI_mapSpeedLimitUnits (0 MPH, 1 KPH).

No new Params keys. AP1-only callers. Not a product, no warranty.
"""

import math

from opendbc.car.common.conversions import Conversions as CV

# VAL_ UI_mapSpeedLimit on UI_driverAssistMapData. Codes not listed → no limit.
_UI_MAP_LIMIT = {
  1: 5, 2: 7, 3: 10, 4: 15, 5: 20, 6: 25, 7: 30, 8: 35, 9: 40, 10: 45,
  11: 50, 12: 55, 13: 60, 14: 65, 15: 70, 16: 75, 17: 80, 18: 85, 19: 90,
  20: 95, 21: 100, 22: 105, 23: 110, 24: 115, 25: 120, 26: 130, 27: 140,
  28: 150, 29: 160,
}
_UI_MAP_UNKNOWN = 0
_UI_MAP_UNLIMITED = 30
_UI_MAP_SNA = 31

# DAS_fusedSpeedLimit physical (after DBC factor 5). NONE is 31*5=155.
_FUSED_NONE_MIN = 150.0

# UI_mppSpeedLimit physical after the same factor of 5. tesla_ap1_can.dbc has no VAL_ for this
# signal (the sibling UI_mapSpeedLimit enumerates 31 as "SNA"; DAS_fusedSpeedLimit enumerates 31
# as "NONE"). Tinkla 501c7de carstate.py:355 uses the physical value with no SNA check. 155 cannot
# be a real posted limit, so treat it as none (fail closed).
_MPP_SNA_PHYS = 31 * 5  # 155


def _uom_to_ms(value: float, metric: bool) -> float:
  return float(value) * (CV.KPH_TO_MS if metric else CV.MPH_TO_MS)


# Engage-set input only: a limit frame older than this counts as unknown. The UI map / mpp messages and
# AutopilotStatus are frequency 0 (optional), so the parser keeps their last value forever. No age gate in
# the refs (Tinkla 501c7de, BogPilot 0.9.7 and NAP parse them with no check), so this is our choice:
# 3x the slowest period measured in captures (UI_gpsVehicleSpeed 1 s; UI_driverAssistMapData and
# AutopilotStatus 0.5 s; worst gap seen 1.01 s).
LIMIT_MAX_AGE_S = 3.0


def frame_fresh(parser, msg_name: str, max_age_s: float = LIMIT_MAX_AGE_S) -> bool:
  """True if msg_name was received within max_age_s of the parser's last update.

  Uses CANParser._last_update_nanos (set on every update(), including empty
  ones) so a silent bus does not keep a stale limit looking fresh against
  last_nonempty_nanos. Falls back to last_nonempty_nanos if needed.
  """
  ts = getattr(parser, "ts_nanos", {}).get(msg_name)
  last = max(ts.values()) if ts else 0
  now = getattr(parser, "_last_update_nanos", 0) or getattr(parser, "last_nonempty_nanos", 0)
  return last > 0 and (now - last) <= max_age_s * 1e9


def fused_speed_limit_ms(fused_phys, metric: bool) -> float:
  """DAS_fusedSpeedLimit physical value → m/s, or 0 if SNA/NONE/missing."""
  if fused_phys is None:
    return 0.0
  try:
    v = float(fused_phys)
  except (TypeError, ValueError):
    return 0.0
  if v <= 0.0 or v >= _FUSED_NONE_MIN:
    return 0.0
  return _uom_to_ms(v, metric)


def ui_map_speed_limit_ms(ui_map_code, metric: bool) -> float:
  """UI_mapSpeedLimit enum code → m/s, or 0 if unknown/SNA/unlimited."""
  if ui_map_code is None:
    return 0.0
  try:
    code = int(ui_map_code)
  except (TypeError, ValueError):
    return 0.0
  if code in (_UI_MAP_UNKNOWN, _UI_MAP_UNLIMITED, _UI_MAP_SNA):
    return 0.0
  limit = _UI_MAP_LIMIT.get(code)
  if limit is None:
    return 0.0
  return _uom_to_ms(limit, metric)


def mpp_speed_limit_ms(mpp_phys, metric: bool) -> float:
  """UI_mppSpeedLimit physical value → m/s, or 0 if missing/zero/non-finite/raw 31 (155)."""
  if mpp_phys is None:
    return 0.0
  try:
    v = float(mpp_phys)
  except (TypeError, ValueError):
    return 0.0
  if v <= 0.0 or v >= _MPP_SNA_PHYS or not math.isfinite(v):
    return 0.0
  return _uom_to_ms(v, metric)


def units_are_metric(ui_map_speed_limit_units) -> bool:
  """UI_mapSpeedLimitUnits: 0 MPH, 1 KPH. Missing → MPH (AP1 US default)."""
  try:
    return int(ui_map_speed_limit_units) == 1
  except (TypeError, ValueError):
    return False


# Mobileye misread guard (drive 35 seg 11: camera read 80 for 9.6 s while the car's map said 35).
# When the camera limit is more than this far ABOVE a valid map limit, the map limit is used instead.
# Real sign changes seen in drives 2a-35 lead the map by at most 20 mph for about 1 s, so they are untouched.
IMPLAUSIBLE_RISE_MPH = 20.0
IMPLAUSIBLE_RISE_KPH = 30.0
MIN_MAP_CHECK_MPH = 15.0      # map limits below this (e.g. a stray 5) are not trusted for the check
MIN_MAP_CHECK_KPH = 25.0


# Base-map guard. UI_baseMapSpeedLimitMPS (UI_driverAssistRoadSign 0x238, mux UI_roadSign 3) is the GTW's own
# map limit for the road; 0 means the map does not know it. DAS_visionOnlySpeedLimit (AutopilotStatus 0x399, next
# to DAS_fusedSpeedLimit) is the limit the camera alone has read. Both are in tesla_ap1_can.dbc; no reference reads
# them (BogPilot 0.9.7, Tinkla and NAP use fused then map with no such check), so this guard is ours.
# A captured drive had the fused and GTW map/mpp limits rise 25 -> 55 while the base map read 0 and the camera
# still read 25; SLC then targeted 55 + offset. With the base map 0, stale or missing, a candidate more than this far
# above the camera limit is replaced by the camera limit.
VISION_RISE_TOL_MPH = 10.0
VISION_RISE_TOL_KPH = 15.0
_UNSET = object()   # "argument not passed": the caller predates the guard, keep the old result


def _dashboard_candidate(fused_phys, ui_map_code, mpp_phys, ui_map_speed_limit_units):
  metric = units_are_metric(ui_map_speed_limit_units)
  fused = fused_speed_limit_ms(fused_phys, metric)
  map_limit = ui_map_speed_limit_ms(ui_map_code, metric) or mpp_speed_limit_ms(mpp_phys, metric)
  if fused > 0.0 and map_limit > 0.0:
    rise = IMPLAUSIBLE_RISE_KPH if metric else IMPLAUSIBLE_RISE_MPH
    floor = MIN_MAP_CHECK_KPH if metric else MIN_MAP_CHECK_MPH
    if map_limit >= _uom_to_ms(floor, metric) - 1e-3 and fused - map_limit > _uom_to_ms(rise, metric) + 1e-3:
      return map_limit, False
  if fused > 0.0:
    return fused, False
  for value in (
    ui_map_speed_limit_ms(ui_map_code, metric),
    mpp_speed_limit_ms(mpp_phys, metric),
  ):
    if value > 0.0:
      return value, True
  return 0.0, False


def base_map_unknown(base_map_ms) -> bool:
  """UI_baseMapSpeedLimitMPS: None (stale / missing), non-finite or <= 0 -> the map does not know the limit."""
  if base_map_ms is None:
    return True
  try:
    v = float(base_map_ms)
  except (TypeError, ValueError):
    return True
  return not math.isfinite(v) or v <= 0.0


def dashboard_speed_limit_ms(fused_phys, ui_map_code, mpp_phys, ui_map_speed_limit_units,
                             vision_phys=None, base_map_ms=_UNSET, hold_ms=0.0) -> float:
  """Mobileye fused first, then UI map enum, then UI mpp. m/s or 0.

  Exception: a fused (camera) limit far above a plausible map limit is treated as a misread
  and the map limit is returned. Lower camera limits always win (construction / school zones).

  Optional base-map guard (only when base_map_ms is passed; callers without it get the result above):
  - base_map_ms: UI_baseMapSpeedLimitMPS in m/s, or None when stale or missing. 0 or None = map limit unknown.
  - vision_phys: DAS_visionOnlySpeedLimit physical value (same units and NONE / SNA codes as fused), None if stale.
  - hold_ms: the limit this function last returned for the car (m/s), held when map-only values are ignored.
  With the map limit unknown:
  - a candidate more than VISION_RISE_TOL above a valid camera limit returns the camera limit. The camera limit
    is used rather than 0: 0 hands the choice to the planner's SLC fallback setting, and a fallback other than
    the previous limit goes back to the set speed or Experimental Mode, which can be higher. The camera limit is
    the lower, car-confirmed value whatever that setting is.
  - with no camera limit, a value that comes only from the GTW map / mpp is ignored: hold_ms is kept, except
    that a map value below hold_ms is returned (a lower limit always wins).
  A candidate at or below the camera limit, or within the tolerance, is returned unchanged.
  """
  candidate, map_only = _dashboard_candidate(fused_phys, ui_map_code, mpp_phys, ui_map_speed_limit_units)
  if base_map_ms is _UNSET or candidate <= 0.0 or not base_map_unknown(base_map_ms):
    return candidate
  metric = units_are_metric(ui_map_speed_limit_units)
  vision = fused_speed_limit_ms(vision_phys, metric)
  if vision > 0.0:
    tol = _uom_to_ms(VISION_RISE_TOL_KPH if metric else VISION_RISE_TOL_MPH, metric)
    return vision if candidate - vision > tol + 1e-3 else candidate
  if map_only:
    try:
      hold = float(hold_ms)
    except (TypeError, ValueError):
      hold = 0.0
    if not math.isfinite(hold) or hold <= 0.0:
      return 0.0
    return candidate if candidate < hold - 1e-3 else hold
  return candidate
