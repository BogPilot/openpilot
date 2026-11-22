"""mapd v2 glue: engine switch, mapd settings, and the validated mapdOut reader shared by the planner consumers.

Engine: param MapdV2 (BOOL, default "0"). Off = mapd v1.12.0 exactly as before (memory params, mapd downloads). On =
mapd v2.4.0 (pinned in mapd_v2_manifest.json, installed next to v1 as osm/mapd_v2): msgq interface (mapdOut / mapdIn /
mapdExtendedOut), downloads by cell_fetch.py in a separate low-priority process so speed limits stay live.

BogPilot only READS mapd v2. mapd's own speed limit, map curve and vision curve controls stay OFF in the settings we
write (they are off in mapd's defaults too); the Speed Limit Controller and Curve Speed Control decide. The map curve
lateral acceleration mapd uses for mapCurveSpeed is pinned to MAP_CURVE_LAT_A for every personality, so the planner can
rescale mapCurveSpeed to its own learned cornering limit (CSCMapCurvature).

Reader safety (anything else reads as "no data"): the message must be fresh (<= FRESH_S), valid, from a loaded tile,
with a finite speed limit inside MIN/MAX_LIMIT_MS; mapCurveSpeed must be finite and inside MIN/MAX_CURVE_MS.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ENGINE_PARAM = "MapdV2"
CURVE_PARAM = "CSCMapCurvature"
SETTINGS_PARAM = "MapdSettings"                 # mapd v2 reads/writes /data/params/d/MapdSettings itself
PARAMS_DIR = Path("/data/params/d")
MAP_CURVE_LAT_A = 2.0                           # m/s^2, written to every personality (mapd default 1.9 / 2.2 / 2.4)
FRESH_S = 0.5                                   # mapdOut is published at 20 Hz
MIN_LIMIT_MS, MAX_LIMIT_MS = 1.0, 45.0          # same bounds as the v1 reader (map_data.py)
MIN_CURVE_MS, MAX_CURVE_MS = 4.0, 45.0          # mapd reports 0 for "no curve ahead"; below 4 m/s is not a road curve speed


def engine_v2(store=None) -> bool:
  """MapdV2 toggle; any read problem -> False (v1, the existing behaviour)."""
  try:
    if store is None:
      from openpilot.common.bogpilot_store import ParamStore
      store = ParamStore()
    return bool(store.get_bool(ENGINE_PARAM))
  except Exception:
    return False


def settings_json() -> str:
  """mapd v2 settings (schema 2): every mapd control off, BogPilot decides; quiet logging; fixed map-curve lat accel."""
  personality = {"target_speed_jerk": 0.6, "target_speed_accel": 1.2, "curve_target_speed_time_offset": 1.5,
                 "speed_limit_increase_target_speed_time_offset": 1.5, "speed_limit_decrease_target_speed_time_offset": 0.75,
                 "map_curve_target_lat_a": MAP_CURVE_LAT_A, "vision_curve_target_lat_a": 2.1,
                 "vision_curve_min_target_v": 4.4702725, "slow_down_for_next_speed_limit": True,
                 "speed_up_for_next_speed_limit": False}
  s = {
    "settings_version": 2, "msgq_queue_size": 0,
    "vision_curve_speed_control_enabled": False, "map_curve_speed_control_enabled": False,
    "speed_limit_control_enabled": False, "external_speed_limit_control_enabled": False,
    "conditional_speed_limit_control_enabled": False, "vision_curve_use_enable_speed": False,
    "speed_limit_use_enable_speed": False, "map_curve_use_enable_speed": False, "enable_speed": 0,
    "default_lane_width": 3.7,
    "subscriber": {"shadow_car_state": True, "shadow_model_v2": False, "shadow_gps_location": False,
                   "shadow_gps_location_external": False, "shadow_selfdrive_state": False},
    "speed_limit": {"press_gas_to_accept_speed_limit": False, "press_gas_to_override_speed_limit": False,
                    "adjust_set_speed_to_accept_speed_limit": False, "accept_speed_limit_timeout": 0,
                    "speed_limit_priority": "map", "speed_limit_change_requires_accept": False,
                    "hold_last_seen_speed_limit": False, "hold_speed_limit_while_changing_set_speed": True,
                    "speed_limit_offset": 0},
    "logger": {"log_level": "error", "log_json": True, "log_source": False},
    "personalities": {k: dict(personality) for k in ("relaxed", "standard", "aggressive")},
  }
  return json.dumps(s, sort_keys=True)


def launch_env(base=None) -> dict:
  """Environment for mapd_v2. gomsgq (v0.1.12) only uses openpilot's /dev/shm/msgq_<name> paths when it sees
  /dev/shm/msgq_logMessage at start (or USE_MSGQ_PREFIX=true); without it mapd would publish to /dev/shm/mapdOut, which
  no openpilot process reads, whenever it starts before logmessaged. Force the openpilot layout."""
  env = dict(os.environ if base is None else base)
  env["USE_MSGQ_PREFIX"] = "true"
  return env


def write_settings(params_dir: Path = PARAMS_DIR) -> bool:
  """Atomic write of MapdSettings before every mapd v2 start (so a setting changed in mapd's TUI never sticks)."""
  try:
    params_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_value_" + SETTINGS_PARAM, dir=params_dir)
    with os.fdopen(fd, "w") as f:
      f.write(settings_json())
      f.flush()
      os.fsync(f.fileno())
    os.replace(tmp, params_dir / SETTINGS_PARAM)
    return True
  except OSError:
    return False


def _finite_in(x, lo, hi) -> float:
  try:
    x = float(x)
  except (TypeError, ValueError):
    return 0.0
  return x if math.isfinite(x) and lo <= x <= hi else 0.0


@dataclass(frozen=True)
class MapdV2Data:
  fresh: bool = False
  speed_limit: float = 0.0        # m/s, 0 = none
  next_speed_limit: float = 0.0   # m/s, 0 = none
  next_distance: float = 0.0      # m
  curve_speed: float = 0.0        # m/s, mapd mapCurveSpeed at MAP_CURVE_LAT_A, 0 = no curve ahead
  road_name: str = ""


NO_V2 = MapdV2Data()


def parse(msg) -> MapdV2Data:
  """mapdOut -> MapdV2Data (pure; msg is a capnp MapdOut or a test double)."""
  try:
    if not bool(msg.tileLoaded):
      return MapdV2Data(fresh=True)
    sl = _finite_in(msg.speedLimit, MIN_LIMIT_MS, MAX_LIMIT_MS)
    nsl = _finite_in(msg.nextSpeedLimit, MIN_LIMIT_MS, MAX_LIMIT_MS)
    nd = _finite_in(msg.nextSpeedLimitDistance, 0.0, 1.0e5) if nsl else 0.0
    cv = _finite_in(msg.mapCurveSpeed, MIN_CURVE_MS, MAX_CURVE_MS)
    return MapdV2Data(True, sl, nsl, nd, cv, str(msg.roadName or "")[:64])
  except Exception:
    return NO_V2


class MapdOutReader:
  """Private, non-polling SubMaster on mapdOut, created on first use. update() once per planner tick."""

  def __init__(self, sm_factory=None, mono=time.monotonic):
    self._factory = sm_factory
    self._sm = None
    self._failed = False
    self._mono = mono
    self._last_t = None
    self._last = NO_V2
    self.data = NO_V2

  def _make(self):
    if self._sm is None and not self._failed:
      try:
        if self._factory is not None:
          self._sm = self._factory()
        else:
          from openpilot.cereal import messaging
          self._sm = messaging.SubMaster(["mapdOut"])
      except Exception:
        self._failed = True
    return self._sm

  def update(self) -> MapdV2Data:
    sm = self._make()
    now = self._mono()
    if sm is None:
      self.data = NO_V2
      return self.data
    try:
      sm.update(0)
      if sm.updated["mapdOut"]:
        if sm.valid["mapdOut"]:
          self._last, self._last_t = parse(sm["mapdOut"]), now
        else:
          self._last, self._last_t = NO_V2, None
    except Exception:
      self._last, self._last_t = NO_V2, None
    self.data = self._last if (self._last_t is not None and 0.0 <= now - self._last_t <= FRESH_S) else NO_V2
    return self.data


_SHARED: dict = {}


def shared_reader() -> MapdOutReader:
  """One reader per process (plannerd: the Speed Limit Controller and Curve Speed Control share it)."""
  r = _SHARED.get(os.getpid())
  if r is None:
    r = _SHARED[os.getpid()] = MapdOutReader()
  return r


class SharedTick:
  """Calls reader.update() at most once per `period` so two consumers in one planner tick read the same sample."""

  def __init__(self, reader: MapdOutReader | None = None, mono=time.monotonic, period: float = 0.02):
    self.reader = reader
    self._mono, self._period, self._t = mono, period, None

  def get(self) -> MapdV2Data:
    r = self.reader or shared_reader()
    now = self._mono()
    if self._t is None or now - self._t >= self._period:
      self._t = now
      return r.update()
    return r.data


def map_curve_cap(curve_speed: float, lat_accel_limit: float) -> float:
  """mapCurveSpeed was computed at MAP_CURVE_LAT_A (v = sqrt(a / k)); rescale to the planner's cornering limit, never up:
  v_cap = v_map * sqrt(min(a_limit, MAP_CURVE_LAT_A) / MAP_CURVE_LAT_A). 0 = no cap."""
  v = _finite_in(curve_speed, MIN_CURVE_MS, MAX_CURVE_MS)
  try:
    a = float(lat_accel_limit)
  except (TypeError, ValueError):
    return 0.0
  if v == 0.0 or not math.isfinite(a) or a <= 0.0:
    return 0.0
  return v * math.sqrt(min(a, MAP_CURVE_LAT_A) / MAP_CURVE_LAT_A)
