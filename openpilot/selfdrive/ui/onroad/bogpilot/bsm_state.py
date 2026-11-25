"""BSM / adjacent-radar UI contract. Never substitute ego speed for lead speed; never invent detections.

Sources (C3X 0.11.2 schema):
  carState.leftBlindspot / rightBlindspot  car-frame sides (opendbc tesla_ap1 carstate, AP1 Model S and Model X: stock
                                           DAS_blindSpotRearLeft/Right, 0x399 bus 2, warning level 1/2, SNA, stale or
                                           bad checksum dropout read as occupied, 1 s hold)
  bogpilotRadarState.leadLeft / leadRight radard bogpilot_radar (closest moving track between that side's lane lines)
Freshness: valid, alive, current drive (recv_frame > started_frame) and recv_time no older than MAX_AGE_S.
RHD never swaps sides: both sources are car-frame left/right.
"""
import math
import time

MAX_AGE_S = 0.5


def _fresh(sm, name, started_frame, now, max_age=MAX_AGE_S):
  age = now - sm.recv_time[name]
  return bool(sm.valid[name] and sm.alive[name] and sm.recv_frame[name] > started_frame
              and math.isfinite(age) and age <= max_age)


def blindspots(sm, started_frame, now=None):
  """(left, right) from a fresh carState; (False, False) when missing/stale/invalid or while the source is not up yet
  (bsmWaiting)."""
  now = time.monotonic() if now is None else now
  try:
    if not _fresh(sm, "carState", started_frame, now):
      return False, False
    cs = sm["carState"]
    if bool(getattr(getattr(cs, "bogpilot", None), "bsmWaiting", False)):
      return False, False
    return bool(cs.leftBlindspot), bool(cs.rightBlindspot)
  except (KeyError, AttributeError, TypeError, ValueError):
    return False, False


def bsm_waiting(sm, started_frame, now=None):
  """True while a fresh carState says the blind spot source was not seen since start (bogpilot.bsmWaiting): the flags
  are False and mean unknown, so nothing is drawn as clear or occupied. False when carState is missing or stale."""
  now = time.monotonic() if now is None else now
  try:
    if not _fresh(sm, "carState", started_frame, now):
      return False
    return bool(sm["carState"].bogpilot.bsmWaiting)
  except (KeyError, AttributeError, TypeError, ValueError):
    return False


def adjacent_leads(sm, started_frame, now=None):
  empty = [(False, 0.0), (False, 0.0)]
  # Missing, invalid or stale data must fail closed, not produce fake flames.
  now = time.monotonic() if now is None else now
  try:
    if not (_fresh(sm, "bogpilotRadarState", started_frame, now) and _fresh(sm, "radarState", started_frame, now)):
      return empty
    radar = sm["bogpilotRadarState"]
    result = []
    for lead in (radar.leadLeft, radar.leadRight):
      speed = float(lead.vLead)
      result.append((bool(lead.status and math.isfinite(speed)), speed if math.isfinite(speed) else 0.0))
    return result
  except (KeyError, AttributeError, TypeError, ValueError):
    return empty


def has_bsm(cp) -> bool:
  """Car reports carState.left/rightBlindspot from a real source (opendbc tesla_ap1 values.bsm_wired: AP1 Model S and
  Model X from stock 0x399 bus 2, stock tesla brand from DAS_status). Pre-AP, other cars and no CarParams: False."""
  try:
    from opendbc.car.tesla_ap1.values import bsm_wired
    return bool(bsm_wired(cp))
  except Exception:
    return False


class BsmPolicy:
  """Daily toggle.blind_spot_path = has_bsm and ((CustomUI and BlindSpotPath) or DebugMode) (367e1fe :875).
  has_bsm: 0.11.2 moved CarParams.enableBsm into the `deprecated` group (opendbc car.capnp), so neither stock nor
  C3X can set it. The capability is the carstate condition that fills the flags (opendbc tesla_ap1 values.bsm_wired:
  the AP1 family in tesla_ap1 carstate, and the stock tesla brand). No CarParams -> hidden.
  BlindSpotPath keeps its typed/file reader (file_toggles).
  Cached 2 s; a store read failure keeps the previous typed/file BlindSpotPath behaviour."""

  def __init__(self, store=None, clock=time.monotonic, ttl=2.0):
    self._store, self.clock, self.ttl = store, clock, ttl
    self._next = -1.0
    self._custom, self._debug = True, False

  def enabled(self, blind_spot_path: bool, cp=None) -> bool:
    if not has_bsm(cp):
      return False
    now = self.clock()
    if now >= self._next:
      self._next = now + self.ttl
      try:
        if self._store is None:
          from openpilot.common.bogpilot_store import ParamStore
          self._store = ParamStore()
        level = self._store.tuning_level()
        self._custom = bool(self._store.toggle_bool("CustomUI", level))
        self._debug = bool(self._store.get_bool("DebugMode", False))
      except Exception:
        self._custom, self._debug = True, False
    return bool((self._custom and blind_spot_path) or self._debug)
