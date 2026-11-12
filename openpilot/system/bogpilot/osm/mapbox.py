"""Mapbox speed-limit filler (0.9.7 bogpilot/controls/lib/speed_limit_controller.py:89-208, BogPilot, MIT).

Faithful port: a map-matching request for the segment ahead of the car, run on one worker thread, whose
`maxspeed` annotation becomes SpeedLimitController.mapbox_limit. It is used only as a *filler* (when no other source
has a limit, see SpeedLimitController.update_limits) and only works with a user-supplied key (MapboxSecretKey).
Without a key, without network, with a bad response or any error it does nothing: mapbox_limit stays 0 and every
failure is swallowed (the same as 0.9.7, which printed the error and set limit 0).

Differences from 0.9.7 (all are fail-closed hardening, none changes the order or the result for a valid response):
  * the limit is only accepted when finite and 1 <= v <= MAX_LIMIT_MS (the "no limit" value 0 otherwise);
  * request count is persisted through the BogPilot store (MapBoxRequests JSON, same key/shape as 0.9.7);
  * everything external (session, ping, executor, clock, store) is injectable so it is testable offline.
"""
from __future__ import annotations

import calendar
import json
import math
from concurrent.futures import ThreadPoolExecutor

KPH_TO_MS = 1 / 3.6
DT_MDL = 0.05
FREE_MAPBOX_REQUESTS = 100_000
MAPBOX_HOST = "https://api.mapbox.com"
MIN_LIMIT_MS = 1.0
MAX_LIMIT_MS = 45.0
EARTH_RADIUS = 6373000.0       # bogpilot_utilities.EARTH_RADIUS
USER_AGENT = "bogpilot-mapbox-speed-limit-retriever/1.0 (https://github.com/FrogAi/FrogPilot)"


def calculate_bearing_offset(latitude, longitude, current_bearing, distance):
  """bogpilot_utilities.calculate_bearing_offset (0.9.7 :60-69), unchanged."""
  bearing = math.radians(current_bearing)
  lat_rad = math.radians(latitude)
  lon_rad = math.radians(longitude)
  delta = distance / EARTH_RADIUS
  new_latitude = math.asin(math.sin(lat_rad) * math.cos(delta) + math.cos(lat_rad) * math.sin(delta) * math.cos(bearing))
  new_longitude = lon_rad + math.atan2(math.sin(bearing) * math.sin(delta) * math.cos(lat_rad),
                                       math.cos(delta) - math.sin(lat_rad) * math.sin(new_latitude))
  return math.degrees(new_latitude), ((math.degrees(new_longitude) + 540) % 360) - 180


def is_url_pingable(url, requests_module=None):
  """bogpilot_utilities.is_url_pingable (0.9.7 :203-220): HEAD, GET fallback on 405/501."""
  if not url:
    return False
  try:
    if requests_module is None:
      import requests as requests_module
    headers = {"User-Agent": "bogpilot-ping-test/1.0"}
    response = requests_module.head(url, headers=headers, timeout=10, allow_redirects=True)
    try:
      if response.status_code in (405, 501):
        response.close()
        response = requests_module.get(url, headers=headers, timeout=10, allow_redirects=True, stream=True)
      return bool(response.ok)
    finally:
      try:
        response.close()
      except Exception:
        pass
  except Exception:
    return False


class MapboxFiller:
  def __init__(self, store=None, session=None, ping=None, executor=None):
    self.store = store
    self.calling_mapbox = False
    self.mapbox_limit = 0.0
    self.segment_distance = 0.0
    self.mapbox_host = MAPBOX_HOST
    self.mapbox_token = None
    self._ping = ping or is_url_pingable
    self._session = session
    self._executor = executor
    self.mapbox_requests = {}
    try:
      self.mapbox_requests = json.loads((store.get("MapBoxRequests", "") if store is not None else "") or "{}")
      if not isinstance(self.mapbox_requests, dict):
        self.mapbox_requests = {}
    except Exception:
      self.mapbox_requests = {}
    self.mapbox_requests.setdefault("total_requests", 0)
    self.mapbox_requests.setdefault("max_requests", FREE_MAPBOX_REQUESTS - (28 * 100))

  # ---- lazily created network objects: nothing is built unless a request is really made ----
  @property
  def session(self):
    if self._session is None:
      import requests
      self._session = requests.Session()
      self._session.headers.update({"Accept-Language": "en"})
      self._session.headers.update({"User-Agent": USER_AGENT})
    return self._session

  @property
  def executor(self):
    if self._executor is None:
      self._executor = ThreadPoolExecutor(max_workers=1)
    return self._executor

  def set_token(self, token):
    """Key from MapboxSecretKey. Empty/None = no key (the filler is then a no-op)."""
    token = (token or "").strip() if isinstance(token, str) else None
    self.mapbox_token = token or None

  @property
  def budget_ok(self) -> bool:
    return self.mapbox_requests["total_requests"] < self.mapbox_requests["max_requests"]

  def reset(self):
    """update_limits' else branch (a source has a limit): `mapbox_limit = 0; segment_distance = 0`."""
    self.mapbox_limit = 0.0
    self.segment_distance = 0.0

  def _persist(self):
    if self.store is not None:
      try:
        self.store.put("MapBoxRequests", json.dumps(self.mapbox_requests))
      except Exception:
        pass

  @staticmethod
  def _valid_limit(v) -> float:
    try:
      v = float(v)
    except (TypeError, ValueError):
      return 0.0
    return v if math.isfinite(v) and MIN_LIMIT_MS <= v <= MAX_LIMIT_MS else 0.0

  def update(self, gps_position, now, time_validated, v_ego, steering_angle_deg):
    """get_mapbox_speed_limit. `now` = datetime (month rollover), steering_angle_deg = steeringAngleDeg - angleOffsetDeg."""
    if not gps_position or not self.mapbox_token or steering_angle_deg >= 45:
      self.mapbox_limit = 0.0
      self.segment_distance = 0.0
      return

    if v_ego < 1:
      return

    if self.segment_distance > 0:
      self.segment_distance -= v_ego * DT_MDL
      return

    if self.calling_mapbox:
      self.segment_distance = v_ego
      return

    token = self.mapbox_token

    def make_request():
      successful = False
      try:
        self.calling_mapbox = True

        if not self._ping(self.mapbox_host):
          self.segment_distance = 1000
          return None

        if time_validated:
          current_month = now.month
          if current_month != self.mapbox_requests.get("month"):
            self.mapbox_requests.update({
              "month": current_month,
              "total_requests": 0,
              "max_requests": FREE_MAPBOX_REQUESTS - calendar.monthrange(now.year, current_month)[1] * 100,
            })

        self.mapbox_requests["total_requests"] += 1
        self._persist()

        current_bearing = gps_position.get("bearing")
        current_latitude = gps_position.get("latitude")
        current_longitude = gps_position.get("longitude")
        future_latitude, future_longitude = calculate_bearing_offset(current_latitude, current_longitude, current_bearing, v_ego)

        url = (f"{self.mapbox_host}/matching/v5/mapbox/driving/"
               f"{current_longitude},{current_latitude};{future_longitude},{future_latitude}.json")
        mapbox_params = {
          "access_token": token,
          "annotations": "maxspeed,distance",
          "geometries": "polyline6",
          "overview": "full",
          "steps": "false",
          "radiuses": "10;10",
          "tidy": "true",
        }
        response = self.session.get(url, params=mapbox_params, timeout=10)
        response.raise_for_status()
        successful = True
        return response.json()
      except Exception:
        return None      # 0.9.7 printed the error here; the URL carries the key, so nothing is printed
      finally:
        self.calling_mapbox = False
        if not successful:
          self.mapbox_limit = 0.0
          self.segment_distance = v_ego

    def complete_request(future):
      try:
        data = future.result()
        if data:
          matchings = data.get("matchings") or []
          if not matchings:
            self.mapbox_limit = 0.0
            self.segment_distance = v_ego
            return

          legs = (matchings[0] or {}).get("legs") or []
          if not legs:
            self.mapbox_limit = 0.0
            self.segment_distance = v_ego
            return

          annotation = legs[0].get("annotation") or {}
          distances = annotation.get("distance") or [v_ego]
          segment_distance = distances[0]

          speed_data = annotation.get("maxspeed", [])
          speed_limit_kph = 0
          if speed_data:
            first_segment_speed = speed_data[0]
            speed_limit_kph = (first_segment_speed.get("speed") if first_segment_speed.get("speed") != "none" else 0) or 0

          limit = self._valid_limit(float(speed_limit_kph) * KPH_TO_MS)
          if limit > 0:
            self.mapbox_limit = limit
            self.segment_distance = segment_distance
            return

        self.mapbox_limit = 0.0
        self.segment_distance = v_ego
      except Exception:
        self.mapbox_limit = 0.0
        self.segment_distance = v_ego

    future = self.executor.submit(make_request)
    future.add_done_callback(complete_request)
