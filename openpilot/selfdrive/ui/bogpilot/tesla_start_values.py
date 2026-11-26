"""Tesla starting values quoted in the help text of EXISTING tuning rows (no new menu rows).

Each number is read from the constant the car or planner code uses (opendbc tesla_ap1 values / CarSpecs, the AP1 profile,
the parameter registry), so a help text cannot drift from the real value. `start_text(key, car)` is the sentence for one car
(shown under the row's own help through attach_help(extra=...)); `all_cars_text(key)` lists the three cars for the static
help entry. ASCII only, as the help font requires.
"""
from __future__ import annotations

from opendbc.car.tesla_ap1.values import (CAR, AP1_LONG_ACTUATOR_DELAY, PREAP_LONG_ACTUATOR_DELAY, AP1_S_STEER_ACTUATOR_DELAY,
                                          AP1_X_STEER_ACTUATOR_DELAY, PREAP_STEER_ACTUATOR_DELAY)

# lagd starts its estimate at steerActuatorDelay + 0.2 s (controls/lib/phase3_steering_tuning.py LAG_INITIAL_OFFSET).
LAG_INITIAL_OFFSET = 0.2
# CarParams stopAccel / the stopping rate every car gets from opendbc interfaces.py and phase3_long_stopping.py.
STOCK_STOP_ACCEL = -2.0
STOCK_STOPPING_RATE = 1.0

CARS = (("AP1 Model S", CAR.TESLA_AP1_MODELS), ("AP1 Model X", CAR.TESLA_AP1_MODELX), ("Pre-AP Model S", CAR.TESLA_PREAP_MODELS))
STEER_DELAY = {CAR.TESLA_AP1_MODELS: AP1_S_STEER_ACTUATOR_DELAY, CAR.TESLA_AP1_MODELX: AP1_X_STEER_ACTUATOR_DELAY,
               CAR.TESLA_PREAP_MODELS: PREAP_STEER_ACTUATOR_DELAY}
LONG_DELAY = {CAR.TESLA_AP1_MODELS: AP1_LONG_ACTUATOR_DELAY, CAR.TESLA_AP1_MODELX: AP1_LONG_ACTUATOR_DELAY,
              CAR.TESLA_PREAP_MODELS: PREAP_LONG_ACTUATOR_DELAY}
PROFILE_NAMES = {"AccelerationProfile": ("Standard", "Eco", "Sport", "Sport+"), "DecelerationProfile": ("Standard", "Eco", "Eco+")}


def _car(fingerprint):
  for _name, car in CARS:
    if str(fingerprint) == str(car):
      return car
  return None


def _registry_default(key):
  from openpilot.common.bogpilot_params import bogpilot_defaults
  return next(value for k, value, _level, _stock in bogpilot_defaults() if k == key)


def _profile_value(key, car):
  """What the car really starts on: the AP1 Model S profile value when it sets one, else the registry default."""
  if car == CAR.TESLA_AP1_MODELS:
    from openpilot.common.bogpilot_ap1_profile import AP1_PARAM_PROFILE
    if key in AP1_PARAM_PROFILE:
      return int(float(AP1_PARAM_PROFILE[key]))
  return int(float(_registry_default(key)))


def _value(key, car):
  """The starting value of `key` on `car` as text with its unit, or None when the key has no per-car starting value."""
  if key == "LongitudinalActuatorDelay":
    return f"{LONG_DELAY[car]:.2f} s"
  if key == "SteerDelay":
    return f"{round(STEER_DELAY[car] + LAG_INITIAL_OFFSET, 2):.2f} s"
  if key == "SteerRatio":
    return f"{car.config.specs.steerRatio:.1f}"
  if key == "StopAccel":
    return f"{STOCK_STOP_ACCEL:.1f} m/s^2"
  if key == "StoppingDecelRate":
    return f"{STOCK_STOPPING_RATE:.1f} m/s^3"
  if key == "MaxDesiredAcceleration":
    if car == CAR.TESLA_PREAP_MODELS:
      from opendbc.car.tesla_ap1.preap.vdas_constants import ACCEL_MAX
      return f"{float(_registry_default(key)):.1f} m/s^2 (the pedal path never asks for more than {ACCEL_MAX:.1f} m/s^2)"
    return f"{float(_registry_default(key)):.1f} m/s^2"
  if key in PROFILE_NAMES:
    return PROFILE_NAMES[key][_profile_value(key, car)]
  return None


def start_text(key, fingerprint=None):
  """Sentence for the car with this fingerprint, or the three-car list when the car is not known yet. '' for other keys."""
  car = _car(fingerprint)
  if car is None:
    return all_cars_text(key)
  v = _value(key, car)
  if v is None:
    return ""
  name = next(n for n, c in CARS if c == car)
  return f"Starting value on this car ({name}): {v}."


def all_cars_text(key):
  parts = []
  for name, car in CARS:
    v = _value(key, car)
    if v is None:
      return ""
    parts.append(f"{name} {v}")
  return "Starting values: " + "; ".join(parts) + "."


# ---- Tesla Tuning rows (Settings > Vehicle Settings > Tesla Tuning). The table lives with the consumers
# (opendbc tesla_ap1/tesla_tuning.py): the shipped value of each row is the constant the car code uses.
_CAR_TITLES = {"TESLA_AP1_MODELS": "AP1 Model S", "TESLA_AP1_MODELX": "AP1 Model X", "TESLA_PREAP_MODELS": "Pre-AP Model S"}
_TUNING_NOTES = {
  "AP1RiseJerk": "Model S and Model X (with openpilot longitudinal on). The panda does not limit jerk.",
  "AP1BrakeHardAccel": "Requests at or below this still pass through at once, so hard braking is never slowed. Closer to -2.0 is the shipped behavior.",
  "AP1BrakeOnsetJerk": "Braking above 8.0 m/s^3 is never held back: the jerk limit sent to the car is always 8.0 for deep braking.",
  "AP1StandbyAccelMin": "Model S only. The standby request must stay inside the panda window of -3.52 to 0.0 m/s^2; the top stays 0.0.",
  "ComfortRegenMaxDecel": "Needs Comfort Regen (Earlier, Gentler Regen Stops) on. The layer can only add braking, never remove it.",
  "StopShaperOnsetFrac": "Model S and Model X with openpilot longitudinal. The shaper can only add braking to the normal plan.",
  "CurveMaxDecel": "The curve slowdown can only add braking. Gentler than -1.2 m/s^2 only; it stays inside the AP1 regen range.",
  "PreApPedalAccelMax": "Pre-AP only. Cannot go below 1.1 m/s^2, the top of the Pre-AP accel profiles.",
  "PreApPedalRegenMax": "Pre-AP only. Cannot be weaker than -1.0 m/s^2, so the pedal always has real regen braking.",
}


def _tuning_row(key):
  from opendbc.car.tesla_ap1.tesla_tuning import BY_KEY
  return BY_KEY[key]


def _fmt(row, value):
  return f"{value:.{row.decimals}f}" + (f" {row.unit}" if row.unit else "")


def tuning_value_text(key, fingerprint):
  """The shipped value of a Tesla Tuning row on this car as text with its unit, or None when the row does not apply to it."""
  row = _tuning_row(key)
  return _fmt(row, row.shipped) if str(fingerprint) in row.cars else None


def tuning_start_text(key, fingerprint=None):
  """Sentence for the car with this fingerprint, or the three-car list when the car is not known yet."""
  row = _tuning_row(key)
  if _car(fingerprint) is not None:
    name = _CAR_TITLES[str(fingerprint)]
    v = tuning_value_text(key, fingerprint)
    return f"Starting value on this car ({name}): {v}." if v else f"Not used on this car ({name})."
  parts = [f"{name} {tuning_value_text(key, fp) or 'not used'}" for fp, name in _CAR_TITLES.items()]
  return "Starting values: " + "; ".join(parts) + "."


def tuning_help(key):
  """(title, what, when, note, default, range) strings for the help entry of a Tesla Tuning row. ASCII only."""
  row = _tuning_row(key)
  bounds = f"{_fmt(row, row.lo)} to {_fmt(row, row.hi)}"
  note = " ".join(part for part in (
    f"Kept between {bounds}, so it cannot reach the panda safety limits.", _TUNING_NOTES.get(key, ""),
    "Takes effect the next time the car starts. Used only while the Tuning Level is Advanced or higher.",
    "Reset to Tesla defaults puts every row in this section back.") if part)
  return (row.title, row.what + " Tesla starting values are listed under the row.", "Only if you know why the Tesla value does not suit your car.",
          note, _fmt(row, row.shipped), bounds)
