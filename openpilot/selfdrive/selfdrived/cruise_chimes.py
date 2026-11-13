"""Cruise engage and disengage chimes for tesla_ap1 (AP1 and Pre-AP).

0.9.7 (bogpilot-tesla 04d560f3) used the stock EngagementAlert sounds, not a
separate event or param:

  AudibleAlert.engage     -> engage.wav    on pcmEnable / buttonEnable
  AudibleAlert.disengage  -> disengage.wav on pcmDisable / buttonCancel /
                             parkBrake / pedalPressed / steerDisengage /
                             wrongCarMode / wrongCruiseMode

The AP1 profile muted EngageVolume and DisengageVolume to 0 because Tesla
firmware already chimes. There was no on/off key to reuse.

The 0.11.2 AP1 profile does not write those volume keys (see
_NEVER_PROFILE_VOLUME_KEYS). Fresh shipping defaults are AlertVolumeControl=0
and EngageVolume/DisengageVolume=101, so soundd uses ambient volume (MIN_VOLUME
0.1, not silence). A saved volume of 0, or a saved toggle OFF, is left alone.

This key (default on) lets tesla_ap1 drivers keep those stock chimes, or turn
them off when the car already sounds. Other brands are unchanged: their
EngagementAlert sounds always play.

Not copied: third-party pedal-cruise and Tesla-cruise engaged-style events.
Those play the same wav on edges that already raise pcmEnable or buttonEnable,
which would double the chime. Extra chimes are only for Pre-AP longitudinal
drop/return while openpilot stays engaged (preapLatOnly), which stock leaves
silent (gasPressedOverride has no sound).
"""
from __future__ import annotations

PARAM_KEY = "CruiseEngageDisengageChimes"
BRAND = "tesla_ap1"
DEFAULT_ON = True

_store = None


def _read_enabled() -> bool:
  global _store
  if _store is None:
    try:
      from openpilot.common.bogpilot_store import ParamStore
      _store = ParamStore(cache_ttl=1.)
    except Exception:
      return DEFAULT_ON
  try:
    return bool(_store.get_bool(PARAM_KEY, default=DEFAULT_ON))
  except Exception:
    return DEFAULT_ON


def chimes_allowed(brand: str | None, enabled: bool | None = None, reader=None) -> bool:
  """True when the engage/disengage chime should play.

  Non-tesla_ap1 brands always allow the stock sound. tesla_ap1 follows the
  saved toggle, default on.
  """
  if brand != BRAND:
    return True
  if enabled is not None:
    return bool(enabled)
  if reader is not None:
    return bool(reader())
  return _read_enabled()


# Q5 (PENDING DECISION): the Pre-AP speed on/off chimes (preapLatOnly edges: a brake or a re-pull in FULL, a second pull, no-pedal
# stock cruise drop / re-arm) follow the "Cruise engage/disengage chimes" toggle (True, plan default) or always sound (False).
PREAP_SPEED_CHIMES_FOLLOW_TOGGLE = True


def long_only_edge(prev_lat_only: bool, lat_only: bool, still_enabled: bool,
                   brand: str | None, *, enabled: bool | None = None, reader=None,
                   stock_chime: bool = False) -> str | None:
  """Return 'engage' or 'disengage' for a Pre-AP long-only edge stock does not sound.

  Rise of preapLatOnly (long drops, steering stays) -> disengage.
  Fall (long returns, still engaged) -> engage.
  Skip when openpilot is no longer engaged, when a stock enable/disable
  chime is already firing this frame, or when the toggle is off.
  """
  if brand != BRAND or stock_chime or not still_enabled:
    return None
  if PREAP_SPEED_CHIMES_FOLLOW_TOGGLE and not chimes_allowed(brand, enabled=enabled, reader=reader):
    return None
  if lat_only and not prev_lat_only:
    return "disengage"
  if prev_lat_only and not lat_only:
    return "engage"
  return None


def make_long_only_alert(kind: str, event_api=None):
  if event_api is None:
    from openpilot.selfdrive.selfdrived import events as event_api
  audible = event_api.AudibleAlert.engage if kind == "engage" else event_api.AudibleAlert.disengage
  alert = event_api.EngagementAlert(audible)
  alert.alert_type = f"bogpilotCruiseChime/{kind}"
  alert.event_type = event_api.ET.PERMANENT
  return alert


class CruiseChimeRuntime:
  """Tracks preapLatOnly edges. Call every selfdrived frame from update_alerts."""

  def __init__(self, reader=None):
    self.prev_lat_only = False
    self.reader = reader

  def reset(self):
    self.prev_lat_only = False

  def update(self, CP, CS, stock_chime: bool = False) -> str | None:
    bogpilot = getattr(CS, "bogpilot", None)
    lat_only = bool(getattr(bogpilot, "preapLatOnly", False))
    still_enabled = bool(getattr(getattr(CS, "cruiseState", None), "enabled", False))
    kind = long_only_edge(self.prev_lat_only, lat_only, still_enabled,
                          getattr(CP, "brand", None), reader=self.reader, stock_chime=stock_chime)
    self.prev_lat_only = lat_only
    return kind


def dispatch_long_only_chime(runtime, am, events, CP, CS, frame, event_api=None):
  """Add a one-shot chime when Pre-AP long drops or returns and stock is silent."""
  if runtime is None:
    return
  try:
    from openpilot.selfdrive.selfdrived.events import ET
    stock_chime = events.contains(ET.ENABLE) or events.contains(ET.USER_DISABLE)
    kind = runtime.update(CP, CS, stock_chime=stock_chime)
    if kind is None:
      return
    am.add_many(frame, [make_long_only_alert(kind, event_api=event_api)])
  except Exception:
    runtime.reset()


def tesla_ap1_visible(cp=None) -> bool:
  """Menu row: only tesla_ap1 (AP1 and Pre-AP). Hidden until a car is known."""
  if cp is None:
    try:
      from openpilot.selfdrive.ui.ui_state import ui_state
      cp = ui_state.CP
    except Exception:
      return False
  return cp is not None and getattr(cp, "brand", None) == BRAND
