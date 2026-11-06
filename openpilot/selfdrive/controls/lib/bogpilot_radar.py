"""BogPilot radard publisher: frogpilotRadarState (adjacent leads) for stream-4 BSM flames / adjacent UI.

Stock release-tizi keeps liveTracksDEPRECATED @16; this module does not reclaim that ordinal.

Kept out of radard.py so the stock lead logic (and the AP1 lead filter wired by feat199) stays untouched:
radard calls `update(RD, sm)` after its own update and `publish(pm, valid)` after radarState.

  * frogpilotRadarState.leadLeft/leadRight: the closest radar track between the far and near lane lines
    on that side, inside the model's path length, moving (vLeadK >= 1) and not the in-path lead track
    (367e1fe Track.potential_adjacent_lead / get_adjacent_lead). Only computed when AdjacentLeadsUI
    (adjacent_lead_tracking) or HumanLaneChanges is on, as in 367e1fe; otherwise status is false.
  * liveTracks: every radar track, sorted by id (trackId, dRel, yRel, vRel), valid = radarState.valid.

Toggles are re-read from the shared store every TOGGLE_REFRESH_S (367e1fe re-read them on
frogpilotPlan.togglesUpdated; radard here does not subscribe to frogpilotPlan).
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from openpilot.cereal import custom

TOGGLE_REFRESH_S = 2.0
SERVICES = ["frogpilotRadarState"]


def _interp(x: float, xp, fp) -> float:
  if len(xp) == 0:
    return 0.0
  return float(np.interp(x, xp, fp))


def adjacent_side(track, model, exclude_ids) -> tuple[bool, bool]:
  """(left, right) for one track (367e1fe Track.potential_adjacent_lead)."""
  if getattr(track, "vLeadK", 0.0) < 1 or track.identifier in exclude_ids:
    return False, False
  lines = model.laneLines
  if len(lines) < 4 or len(model.position.x) == 0:
    return False, False
  d = track.dRel
  far_left = _interp(d, lines[0].x, lines[0].y)
  left = _interp(d, lines[1].x, lines[1].y)
  right = _interp(d, lines[2].x, lines[2].y)
  far_right = _interp(d, lines[3].x, lines[3].y)
  in_range = d < model.position.x[-1]
  y = -track.yRel
  return (far_left < y < left and in_range), (right < y < far_right and in_range)


def get_adjacent_lead(tracks: dict, model, left: bool, exclude_ids=()) -> dict[str, Any]:
  side = 0 if left else 1
  candidates = [t for t in tracks.values() if adjacent_side(t, model, exclude_ids)[side]]
  if not candidates:
    return {"status": False}
  closest = min(candidates, key=lambda t: t.dRel)
  lead = dict(closest.get_RadarState())
  lead.pop("present", None)
  lead["status"] = True
  return lead


def live_tracks(tracks: dict) -> list[dict[str, Any]]:
  return [{"trackId": int(tid), "dRel": float(tracks[tid].dRel), "yRel": float(tracks[tid].yRel), "vRel": float(tracks[tid].vRel)}
          for tid in sorted(tracks.keys())]


class BogPilotRadar:
  def __init__(self, CP=None, store=None):
    self.CP = CP
    self.store = store
    self.toggles = None
    self.last_refresh = -1e9
    self.lead_left: dict[str, Any] = {"status": False}
    self.lead_right: dict[str, Any] = {"status": False}
    self.tracks: list[dict[str, Any]] = []

  def refresh_toggles(self, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if self.toggles is not None and now - self.last_refresh < TOGGLE_REFRESH_S:
      return
    self.last_refresh = now
    try:
      if self.store is None:
        from openpilot.common.bogpilot_store import ParamStore
        self.store = ParamStore()
      from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
      self.store.invalidate()
      self.toggles = onroad_toggles(self.store, self.CP)
    except Exception:
      from openpilot.common.swaglog import cloudlog
      cloudlog.exception("bogpilot radar: toggles unreadable")

  @property
  def adjacent_enabled(self) -> bool:
    """Compute adjacent leads when FrogPilot gates say so, or when BSM flames need them.

    Stream 4 flames require leadLeft/leadRight.status + vLead; shipping defaults keep
    DeveloperWidgets off, so AdjacentLeadsUI alone would never arm. BSMFlameTracks
    (file-backed, default ON) therefore also enables adjacent tracking.
    """
    t = self.toggles
    if t is not None and (t.adjacent_lead_tracking or t.human_lane_changes):
      return True
    try:
      from openpilot.common.bogpilot_toggles import read_toggle
      return bool(read_toggle("BSMFlameTracks", True))
    except Exception:
      return True  # fail open on toggle read so flames can still see leads

  def update(self, RD, sm, now: float | None = None) -> None:
    self.refresh_toggles(now)
    self.tracks = live_tracks(RD.tracks)
    if self.adjacent_enabled and RD.ready and RD.radar_state is not None:
      rs = RD.radar_state
      exclude = {rs.leadOne.radarTrackId, rs.leadTwo.radarTrackId} - {-1}
      model = sm['modelV2']
      self.lead_left = get_adjacent_lead(RD.tracks, model, True, exclude)
      self.lead_right = get_adjacent_lead(RD.tracks, model, False, exclude)
    else:
      self.lead_left = {"status": False}
      self.lead_right = {"status": False}

  def frogpilot_radar_state(self):
    msg = custom.FrogPilotRadarState.new_message()
    msg.leadLeft = self.lead_left
    msg.leadRight = self.lead_right
    return msg

  def publish(self, pm, valid: bool) -> None:
    # messaging import deferred so Mac unit tests need not load AGNOS msgq
    from openpilot.cereal import messaging
    frs = messaging.new_message("frogpilotRadarState")
    frs.valid = valid
    frs.frogpilotRadarState = self.frogpilot_radar_state()
    pm.send("frogpilotRadarState", frs)
    # liveTracks stays DEPRECATED on stock release-tizi Event @16; flames use frogpilotRadarState only.
