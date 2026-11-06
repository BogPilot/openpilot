"""Optional adjacent-radar contract. Never substitute ego speed for lead speed."""
import math


def adjacent_leads(sm, started_frame):
  empty = [(False, 0.0), (False, 0.0)]
  # Stock release-tizi has no adjacent-radar topic. Stream 6 may supply it;
  # missing, invalid or stale data must fail closed, not produce fake flames.
  try:
    name = "frogpilotRadarState"
    if (not sm.valid[name] or not sm.alive[name] or
        sm.recv_frame[name] <= started_frame or not sm.valid["radarState"] or
        not sm.alive["radarState"] or sm.recv_frame["radarState"] <= started_frame):
      return empty
    radar = sm[name]
    result = []
    for lead in (radar.leadLeft, radar.leadRight):
      speed = float(lead.vLead)
      result.append((bool(lead.status and math.isfinite(speed)), speed if math.isfinite(speed) else 0.0))
    return result
  except (KeyError, AttributeError, TypeError, ValueError):
    return empty
