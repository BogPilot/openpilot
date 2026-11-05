"""Pre-AP settings menu copy (BogPilot wording). Pre-AP only — AP1 text unchanged.

Shown in the report for Bardo review. C++ vehicle_settings.cc mirrors these.
"""

# DisableOpenpilotLongitudinal — Pre-AP only (AP1 keeps stock FrogPilot text).
DISABLE_LONG_TITLE_PREAP = "Disable Pedal Longitudinal"
DISABLE_LONG_DESC_PREAP = (
  "<b>Comma Pedal longitudinal (Pre-AP).</b> Leave this off so BogPilot can drive "
  "gas through a detected, calibrated comma pedal. Turn it on to disable pedal "
  "longitudinal (steering only). Needs a comma pedal on the selected CAN bus."
)

# Pedal status line (read-only)
PEDAL_STATUS_TITLE = "Comma Pedal"
PEDAL_STATUS_DESC = (
  "<b>Comma Pedal status.</b> Not detected = no pedal reply on the selected CAN bus. "
  "Needs calibration = pedal seen; run Calibrate before longitudinal. "
  "Ready = detected and calibrated; longitudinal can use it."
)
PEDAL_STATUS_NOT_DETECTED = "Not detected"
PEDAL_STATUS_NEEDS_CALIBRATION = "Needs calibration"
PEDAL_STATUS_READY = "Ready"

# Calibrate action
PEDAL_CALIBRATE_TITLE = "Calibrate Pedal"
PEDAL_CALIBRATE_BUTTON = "CALIBRATE"
PEDAL_CALIBRATE_DESC = (
  "<b>Calibrate the comma pedal.</b> Park the car, foot off the pedal, then press "
  "Calibrate and follow the prompts: keep foot off for coast, then press the pedal "
  "fully once. Required before longitudinal."
)
PEDAL_CALIBRATE_CONFIRM = (
  "Park, foot off the pedal. OK arms calibration: keep foot off for a moment, "
  "then press the pedal fully. Cancel leaves calibration unchanged."
)

# Pedal CAN bus
PEDAL_CAN_BUS_TITLE = "Pedal CAN Bus"
PEDAL_CAN_BUS_DESC = (
  "<b>Which CAN bus the comma pedal is on.</b> Bus 2 is the usual install. Use bus 0 "
  "only if your pedal is wired there. Wrong bus shows Not detected."
)

# Bosch radar
RADAR_ENABLED_TITLE = "Bosch Radar"
RADAR_ENABLED_DESC = (
  "<b>Pre-AP Bosch radar.</b> Off by default. On lets BogPilot wake the radar and use "
  "its tracks. Needs a wired Bosch radar. Leave off if you have no radar."
)

RADAR_NOSECONE_TITLE = "Radar Behind Nosecone"
RADAR_NOSECONE_DESC = (
  "<b>Radar mounted behind the nosecone.</b> On if the Bosch unit sits behind the "
  "nosecone (common Pre-AP retrofit). Off if it is in the open bumper position."
)

RADAR_OFFSET_TITLE = "Radar Lateral Offset"
RADAR_OFFSET_DESC = (
  "<b>Sideways radar mount offset.</b> Positive = radar right of centerline, "
  "negative = left. Shown in inches; stored in meters. Use 0 in if the radar is centered."
)


RADAR_IGNORE_HW_FAIL_TITLE = "Ignore Radar Hardware Errors"
RADAR_IGNORE_HW_FAIL_DESC = (
  "<b>Ignore Bosch radar hardware-fail bit.</b> Off by default (same as NAP "
  "NAPRadarIgnoreHwFail). On lets BogPilot keep using radar tracks when RADC_HWFail "
  "is set — useful for a false hardware fail with live tracks. Pre-AP already "
  "ignores SGUFail (calibration / VIN / summary lamp) so engage is not blocked by "
  "that alone. Takes effect right away; no reboot."
)


RADAR_READ_VIN_TITLE = "Read Radar VIN"
RADAR_READ_VIN_DESC = (
  "<b>Read the Bosch radar donor VIN (F190).</b> Off by default. On lets BogPilot "
  "request the VIN from the radar over UDS while offroad / before engage, store it "
  "locally, and put it on the GTW VIN helper frames instead of the dummy. Never "
  "writes a VIN to the radar. Takes effect right away; no reboot."
)

RADAR_UPSIDE_DOWN_TITLE = "Radar Mounted Upside Down"
RADAR_UPSIDE_DOWN_DESC = (
  "<b>Radar mounted upside down.</b> Off by default. On inverts lateral distance "
  "and lateral velocity from the Bosch tracks so an inverted mount still tracks "
  "correctly. Pre-AP only. Takes effect right away; no reboot."
)

TESLA_PREAP_TOGGLES_TITLE = "Tesla Pre-AP Settings"
TESLA_PREAP_TOGGLES_DESC = (
  "<b>BogPilot features for Tesla Model S Pre-AP</b> (no Autopilot ECU): comma pedal "
  "longitudinal and optional Bosch radar."
)
