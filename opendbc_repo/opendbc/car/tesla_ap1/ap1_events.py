"""AP1 car events, as event names (no cereal in opendbc).

0.9.7 added these in tesla/interface.py _update. In 0.11 car events are
built in openpilot selfdrive/car/car_events.py; for brand "tesla_ap1" it calls
Ap1Events.update and adds each returned name as log.OnroadEvent.EventName.

- Resume hold (bogpilot.ap1DriverYield): steerOverride, so the state stays
  overriding (grey border) until lateral resumes.
- Tinkla HSO: steerTempUnavailable becomes steerTempUnavailableSilent
  (steerUnavailable from EAC_FAULT is not rewritten).
- EPAS INHIBITED for ~1 s while lateral is wanted (and the driver is not
  steering): steerTempUnavailableSilent.
"""
from opendbc.car import DT_CTRL
from opendbc.car.tesla_ap1.hso import ap1_hso_event_names, ap1_steering_pressed

STEER_OVERRIDE = "steerOverride"
STEER_TEMP_SILENT = "steerTempUnavailableSilent"
INHIBIT_ALERT_FRAMES = int(1.0 / DT_CTRL)  # ~1 s at 100 Hz


class Ap1Events:
  def __init__(self):
    self.inhibit_alert_frames = 0

  def update(self, names, enabled: bool, lat_active: bool, bogpilot, steer_fault_permanent: bool = False) -> list[str]:
    """names: event names openpilot built so far. Returns the AP1 rewritten list."""
    yielding = bool(bogpilot.ap1DriverYield)
    out = list(names)
    if yielding:
      out.append(STEER_OVERRIDE)
    out = ap1_hso_event_names(out)

    # The hands pause sends NONE on purpose (EPAS goes INHIBITED at level 3);
    # that is the driver steering, not EPAS refusing control.
    want_lat = bool(enabled) and bool(lat_active)
    want_lat = want_lat and not ap1_steering_pressed(bogpilot.ap1HandsOnLevel) and not yielding
    if want_lat and bool(bogpilot.ap1EacInhibited) and not steer_fault_permanent:
      self.inhibit_alert_frames += 1
    else:
      self.inhibit_alert_frames = 0
    if self.inhibit_alert_frames >= INHIBIT_ALERT_FRAMES and STEER_TEMP_SILENT not in out:
      out.append(STEER_TEMP_SILENT)
    return out
