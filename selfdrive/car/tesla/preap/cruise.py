"""Pre-AP cruiseState helpers for comma-pedal longitudinal.

NAP sets cruiseState.available=True always and engages on SpdCtrlLvr_Stat=2
(RWD / pull toward driver). With pcmCruise=False we cannot leave available
tied to DI_cruiseState STANDBY/ENABLED or the UI shows wrongCarMode
("Enable Adaptive Cruise to Engage"). Panda SAFETY_TESLA_PREAP already
arms controls_allowed on stalk lever==2 (not DI_cruiseState).
"""
from __future__ import annotations

# STW_ACTN_RQ.SpdCtrlLvr_Stat — same as NAP CruiseButtons / DBC
SPD_CTRL_CANCEL = 1  # FWD — push away
SPD_CTRL_MAIN = 2    # RWD — pull toward driver (engage)


def pedal_cruise_available(*, detected: bool, calibrated: bool, faulted: bool = False) -> bool:
  """True when pedal long may show cruise available (not stock DI-armed)."""
  return bool(detected and calibrated and not faulted)


def remap_preap_pedal_button_type(event_type):
  """Map stalk MAIN/RWD (resumeCruise in shared BUTTONS) to setCruise.

  Shared BUTTONS keep SpdCtrl=2 as resumeCruise for AP1 pcmCruise resume.
  Pre-AP pedal uses setCruise so buttonEnable initializes v_cruise from ego
  (resumeCruise alone would hit resumeBlocked: "Press Set to Engage").
  """
  from cereal import car
  ButtonType = car.CarState.ButtonEvent.Type
  if event_type == ButtonType.resumeCruise:
    return ButtonType.setCruise
  return event_type

# Echo windows (NAP engagement.py): suppress SpdCtrl CANCEL that is our own
# spoofed STW_ACTN_RQ so openpilot does not treat it as a driver FWD cancel.
CANCEL_ECHO_WINDOW_MS = 600
SPOOF_ECHO_WINDOW_MS = 300


def is_preap_cancel_echo(*, now_ms: int, last_stalk_non_cancel_ms: int,
                         last_cc_spoof_ms: int, cruise_enabled: bool = False) -> bool:
  """True when a SpdCtrl=CANCEL edge is likely our stalk spoof echo."""
  if cruise_enabled and last_stalk_non_cancel_ms and (
      now_ms - last_stalk_non_cancel_ms) < CANCEL_ECHO_WINDOW_MS:
    return True
  if last_cc_spoof_ms and (now_ms - last_cc_spoof_ms) < SPOOF_ECHO_WINDOW_MS:
    return True
  return False
