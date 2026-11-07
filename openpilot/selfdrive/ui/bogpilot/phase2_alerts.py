"""Active-only historical Alerts audit; no Params writes or safety/DM changes.
No optional alert has an executable current consumer. Omit the submenu.
"""
HISTORICAL_REVISION = "04d560f3ece97797b8f1ee2f714e682e6d0ef40e"
AUDITED_BASE = "c6582fc3efc1038b4e0e6bca8a6841b657e8ccf6"
OMITTED_ALERT_ROWS = (
  ("GoatScream", "Goat Scream", "No current steering-limit alert consumer."),
  ("GreenLightAlert", "Green Light Alert", "No current model-prediction trigger or event consumer."),
  ("LeadDepartingAlert", "Lead Departing Alert", "No current trigger; schema enum alone is not behavior."),
  ("LoudBlindspotAlert", 'Loud "Car Detected in Blindspot" Alert', "No current optional loud-blindspot consumer."),
  ("SpeedLimitChangedAlert", "Speed Limit Changed Alert", "No current speed-limit-change event consumer."),
)
# Only rows with a traced runtime consumer may be added here.
ACTIVE_ALERT_ROWS = ()
ACTIVE_ALERT_KEYS = tuple(row[0] for row in ACTIVE_ALERT_ROWS)


def has_active_alerts() -> bool:
  """Integration should omit Alerts when false; do not render inactive switches."""
  return bool(ACTIVE_ALERT_ROWS)
