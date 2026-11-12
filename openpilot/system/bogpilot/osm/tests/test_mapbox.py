"""Mapbox filler (0.9.7 speed_limit_controller.py:89-208) offline: fake session/ping/executor, no network."""
import datetime
import json
from concurrent.futures import Future
from types import SimpleNamespace as NS

from openpilot.system.bogpilot.osm import mapbox as mb

NOW = datetime.datetime(2026, 11, 9, 12, 0, tzinfo=datetime.timezone.utc)
GPS = {"latitude": 0.5, "longitude": -0.5, "bearing": 90.0}


class SyncExecutor:
  def submit(self, fn):
    f = Future()
    try:
      f.set_result(fn())
    except Exception as e:  # pragma: no cover
      f.set_exception(e)
    return f


class Resp:
  def __init__(self, data, ok=True):
    self._d, self.ok = data, ok

  def raise_for_status(self):
    if not self.ok:
      raise RuntimeError("http")

  def json(self):
    return self._d


class Session:
  def __init__(self, data=None, exc=None, ok=True):
    self.data, self.exc, self.ok, self.calls = data, exc, ok, []

  def get(self, url, params=None, timeout=None):
    self.calls.append((url, params, timeout))
    if self.exc:
      raise self.exc
    return Resp(self.data, self.ok)


class Store:
  def __init__(self, v=None):
    self.d = {} if v is None else {"MapBoxRequests": v}

  def get(self, k, default=None):
    return self.d.get(k, default)

  def put(self, k, v):
    self.d[k] = v


def reply(kph=50, dist=120.0):
  return {"matchings": [{"legs": [{"annotation": {"distance": [dist], "maxspeed": [{"speed": kph, "unit": "km/h"}]}}]}]}


def filler(session=None, ping=True, store=None, token="pk.t"):
  f = mb.MapboxFiller(store=store or Store(), session=session or Session(reply()), ping=lambda u: ping, executor=SyncExecutor())
  f.set_token(token)
  return f


def tick(f, v=15.0, gps=GPS, steer=0.0, validated=True):
  f.update(gps, NOW, validated, v, steer)


def test_valid_response_sets_limit_and_segment_distance():
  f = filler()
  tick(f)
  assert abs(f.mapbox_limit - 50 / 3.6) < 1e-6
  assert f.segment_distance == 120.0
  assert f.mapbox_requests["total_requests"] == 1


def test_request_url_and_params_match_097():
  s = Session(reply())
  f = filler(s)
  tick(f)
  url, params, timeout = s.calls[0]
  assert url.startswith("https://api.mapbox.com/matching/v5/mapbox/driving/-0.5,0.5;")
  assert url.endswith(".json") and timeout == 10
  assert params == {"access_token": "pk.t", "annotations": "maxspeed,distance", "geometries": "polyline6", "overview": "full",
                    "steps": "false", "radiuses": "10;10", "tidy": "true"}


def test_no_key_is_a_noop_and_never_builds_a_session():
  f = mb.MapboxFiller(store=Store(), ping=lambda u: True, executor=SyncExecutor())
  for tok in (None, "", "  "):
    f.set_token(tok)
    tick(f)
    assert f.mapbox_limit == 0.0 and f.mapbox_requests["total_requests"] == 0
  assert f._session is None


def test_no_gps_or_hard_steering_or_standstill():
  s = Session(reply())
  f = filler(s)
  tick(f, gps=None)
  tick(f, steer=45.0)
  tick(f, v=0.5)
  assert s.calls == []
  f.mapbox_limit = 9.0
  tick(f, gps=None)
  assert f.mapbox_limit == 0.0


def test_segment_distance_throttles_requests():
  s = Session(reply(dist=100.0))
  f = filler(s)
  tick(f)
  for _ in range(20):
    tick(f, v=15.0)          # each tick consumes 15 m/s * 0.05 s of the 100 m segment
  assert len(s.calls) == 1
  for _ in range(200):
    tick(f, v=15.0)
  assert len(s.calls) >= 2


def test_none_speed_and_missing_data_are_no_limit():
  for data in ({"matchings": []}, {"matchings": [{"legs": []}]}, {}, reply(kph="none"),
               {"matchings": [{"legs": [{"annotation": {"maxspeed": []}}]}]}):
    f = filler(Session(data))
    tick(f)
    assert f.mapbox_limit == 0.0
    assert f.segment_distance == 15.0


def test_failures_are_swallowed():
  for s in (Session(exc=RuntimeError("net")), Session(reply(), ok=False)):
    f = filler(s)
    tick(f)
    assert f.mapbox_limit == 0.0 and not f.calling_mapbox


def test_unpingable_host_is_a_failure_not_a_request():
  s = Session(reply())
  f = filler(s, ping=False)
  tick(f)
  assert s.calls == [] and f.mapbox_limit == 0.0
  assert f.mapbox_requests["total_requests"] == 0


def test_limit_sanity_bounds():
  for kph in (3, 500, -20):
    f = filler(Session(reply(kph=kph)))
    tick(f)
    assert f.mapbox_limit == 0.0


def test_budget_and_month_rollover_persisted():
  st = Store(json.dumps({"total_requests": 99999, "max_requests": 97200, "month": 10}))
  f = filler(store=st)
  assert not f.budget_ok
  tick(f)           # a new month resets the counter before counting this request
  assert f.mapbox_requests["month"] == 11 and f.mapbox_requests["total_requests"] == 1
  assert f.mapbox_requests["max_requests"] == 100_000 - 30 * 100
  assert json.loads(st.d["MapBoxRequests"])["total_requests"] == 1
  assert f.budget_ok


def test_untrusted_clock_does_not_roll_the_month():
  st = Store(json.dumps({"total_requests": 5, "max_requests": 97200, "month": 10}))
  f = filler(store=st)
  tick(f, validated=False)
  assert f.mapbox_requests["month"] == 10 and f.mapbox_requests["total_requests"] == 6


def test_corrupt_saved_budget_resets_to_defaults():
  f = mb.MapboxFiller(store=Store("not json"), ping=lambda u: True)
  assert f.mapbox_requests == {"total_requests": 0, "max_requests": 100_000 - 2800}


def test_reset_clears_state():
  f = filler()
  tick(f)
  f.reset()
  assert f.mapbox_limit == 0.0 and f.segment_distance == 0.0


def test_bearing_offset_matches_097_formula():
  lat, lon = mb.calculate_bearing_offset(0.0, 0.0, 90.0, 6373000.0 * 0.001)
  assert abs(lat) < 1e-9 and abs(lon - 0.05729577951) < 1e-6


def test_ping_head_then_get_fallback():
  calls = []

  class R:
    def __init__(self, code, ok):
      self.status_code, self.ok = code, ok

    def close(self):
      pass

  class Req:
    def head(self, *a, **k):
      calls.append("head")
      return R(405, False)

    def get(self, *a, **k):
      calls.append("get")
      return R(200, True)

  assert mb.is_url_pingable("https://x", Req()) is True and calls == ["head", "get"]
  assert mb.is_url_pingable("", Req()) is False
