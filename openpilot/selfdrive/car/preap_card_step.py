"""Pre-AP-only 10 Hz OnroadDistanceButtonPressed snapshot and step-overrun timer.

07e8bd68f moved the button Params read to the 10 Hz params thread and added a
log-only step-overrun counter for every car. AP1 and unknown cars keep the
92aa9ee1f path: read the button every 100 Hz step, and do not run the timer.
"""


def use_10hz_distance_button(fingerprint) -> bool:
  return fingerprint == "TESLA_PREAP_MODELS"


def use_step_overrun_counter(fingerprint) -> bool:
  return fingerprint == "TESLA_PREAP_MODELS"
