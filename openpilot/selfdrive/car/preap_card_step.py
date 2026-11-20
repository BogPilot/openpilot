"""10 Hz OnroadDistanceButtonPressed snapshot (Pre-AP and AP1) and Pre-AP-only step-overrun timer.

07e8bd68f moved the button Params read to the 10 Hz params thread and added a
log-only step-overrun counter for every car. AP1 now reads the button on the same
10 Hz thread as Pre-AP, so card no longer does a Params file read every 100 Hz
step (up to 100 ms of extra button latency). Unknown cars keep the 92aa9ee1f path
(read every step). The step-overrun timer stays Pre-AP only.
"""


# How often card's 10 Hz params thread re-reads the Pre-AP engage-set toggles (PreapEngageSetLimit.refresh).
# Not in the 100 Hz step: that read is a few dozen params and used to land on the engage frame.
PREAP_ENGAGE_SET_REFRESH_S = 1.0


def use_10hz_distance_button(fingerprint) -> bool:
  return fingerprint in ("TESLA_PREAP_MODELS", "TESLA_AP1_MODELS")


def use_step_overrun_counter(fingerprint) -> bool:
  return fingerprint == "TESLA_PREAP_MODELS"
