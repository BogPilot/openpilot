"""Conservative 04d560f3 steering overrides for current controllers.

Read once at process start: edits are offroad-only and take effect next drive.
No selection of controllers, gain changes, default writes, or safety bypasses.
Missing/invalid values retain stock/live tuning, including existing saved values.

Consumers (0.11.2), per row:
  SteerDelay    -> lagd publishes it as lateralDelay (read by modeld, controlsd, torqued).
  SteerRatio    -> controlsd VehicleModel (angle, curvature and torque cars alike).
  SteerFriction / SteerLatAccel / ForceAutoTune(Off) -> LatControlTorque, torque cars only.
  Pause Steering Below / Turn Signal Only -> controlsd CC.latActive (suppress only).
Rows with no 0.11.2 consumer are omitted, not stubbed: SteerKP (no scalar Kp in the speed-scheduled
LatControlTorque PID), ForceTorqueController (no controller switching), NNFF / NNFFLite (no model).
"""
from dataclasses import dataclass
import math

# Exact current locationd/torqued.py ALLOWED_CARS, checked by native contract test.
# Runtime uses live.useParams, not this UI eligibility projection.
NATIVE_AUTO_TUNE_BRANDS = ("toyota", "hyundai", "rivian", "honda", "volkswagen")

# Mirror of locationd/lagd.py MIN_LAG / MAX_LAG and its `steerActuatorDelay + 0.2` initial lag,
# pinned to the real lagd constants by a native contract test. A user value can never leave lagd's own clamp.
LAG_MIN = 0.15
LAG_MAX = 0.65
LAG_INITIAL_OFFSET = 0.2


@dataclass(frozen=True)
class NumericRow:
  key: str
  title: str
  minimum: float
  maximum: float
  default: float
  # True when a saved value equal to the shown default still pins. The shown SteerDelay default is
  # only lagd's initial guess; the learned delay can differ, so pinning that value is a real choice.
  pin_default: bool = False


def numeric_rows(cp):
  rows = []
  # SteerDelay: legacy .01-1 s is narrowed to lagd's current .15-.65 s; the shown default is lagd's
  # initial lag (steerActuatorDelay + .2), and an unset value keeps lagd's learned delay untouched.
  delay = float(getattr(cp, "steerActuatorDelay", 0.) or 0.)
  if math.isfinite(delay) and delay >= 0:
    rows.append(NumericRow("SteerDelay", "Actuator Delay", LAG_MIN, LAG_MAX,
                           min(LAG_MAX, max(LAG_MIN, round(delay + LAG_INITIAL_OFFSET, 2))), pin_default=True))
  if math.isfinite(cp.steerRatio) and cp.steerRatio > 0:
    rows.append(NumericRow("SteerRatio", "Steer Ratio", cp.steerRatio * .5, cp.steerRatio * 1.5, cp.steerRatio))
  # A torque tuning union alone is not proof of a torque-controlled vehicle.
  if str(cp.steerControlType) == "torque" and cp.lateralTuning.which() == "torque":
    t = cp.lateralTuning.torque
    if math.isfinite(t.friction) and t.friction > 0:
      rows.append(NumericRow("SteerFriction", "Friction", 0., .5, t.friction))
    if math.isfinite(t.latAccelFactor) and t.latAccelFactor > 0:
      rows.append(NumericRow("SteerLatAccel", "Lateral Acceleration", t.latAccelFactor * .75, t.latAccelFactor * 1.25, t.latAccelFactor))
  return tuple(rows)


def valid_number(store, row):
  # No empty-param -> zero conversion; never rewrite/clamp a saved value.
  raw = store.raw(row.key)
  if raw in (None, "", b""):
    return None
  try:
    value = float(raw)
  except (TypeError, ValueError):
    return None
  return value if math.isfinite(value) and row.minimum <= value <= row.maximum else None


class _StockStore:
  """Everything off/unset: used only when the real store cannot be read, so steering stays stock."""
  def honoured(self, key):
    return False
  def raw(self, key):
    return None
  def toggle_bool(self, key):
    return False
  def toggle_float(self, key):
    return 0.
  def get_bool(self, key):
    return False


def load_steering_tuning(cp, store=None):
  """Process-start loader for controlsd/lagd. Never raises: any failure means stock steering."""
  try:
    if store is None:
      from openpilot.common.bogpilot_store import ParamStore
      store = ParamStore()
    return SteeringTuning(cp, store)
  except Exception:
    from openpilot.common.swaglog import cloudlog
    cloudlog.exception("steering tuning unavailable, using stock steering")
    return SteeringTuning(cp, _StockStore())


class SteeringTuning:
  def __init__(self, cp, store):
    self.cp = cp
    self.torque = str(cp.steerControlType) == "torque" and cp.lateralTuning.which() == "torque"
    self.values = {}
    if store.toggle_bool("AdvancedLateralTune"):
      for row in numeric_rows(cp):
        if store.honoured(row.key):
          value = valid_number(store, row)
          # Like the original, a saved stock value means keep learning.
          if value is not None and (row.pin_default or round(value, 2) != round(row.default, 2)):
            self.values[row.key] = value
    self.force_on = self.torque and store.toggle_bool("AdvancedLateralTune") and store.toggle_bool("ForceAutoTune")
    self.force_off = self.torque and store.toggle_bool("AdvancedLateralTune") and store.toggle_bool("ForceAutoTuneOff")
    if self.force_on:
      self.values.pop("SteerRatio", None)
    self.pause_speed = 0.
    self.signal_only = False
    if store.toggle_bool("QOLLateral"):
      speed = store.toggle_float("PauseLateralSpeed")
      metric = store.get_bool("IsMetric")
      if math.isfinite(speed) and 0 <= speed <= (150 if metric else 99):
        self.pause_speed = speed * (1 / 3.6 if metric else .44704)
        self.signal_only = self.pause_speed > 0 and store.toggle_bool("PauseLateralOnSignal")

  @property
  def delay_override(self):
    """Seconds to publish as lateralDelay, or None to keep lagd's own value."""
    return self.values.get("SteerDelay")

  def ratio(self, learned):
    return self.values.get("SteerRatio", learned)

  def lateral_allowed(self, cs):
    # 04d560f3 frogpilot_planner.py:97-98. Only suppress, never enable.
    return self.pause_speed <= 0 or cs.vEgo >= self.pause_speed or (self.signal_only and not (cs.leftBlinker or cs.rightBlinker))

  def update_torque(self, controller, live, valid):
    """Preserve current validity gate and stock update unless explicitly overridden."""
    if not self.torque:
      return
    native_auto = live.useParams
    forced_off = native_auto and self.force_off
    forced_on = not native_auto and self.force_on
    auto = (native_auto and not forced_off) or forced_on
    if valid and (native_auto or forced_on):
      factor, offset, friction = live.latAccelFactorFiltered, live.latAccelOffsetFiltered, live.frictionCoefficientFiltered
    else:
      factor, offset, friction = (controller.torque_params.latAccelFactor, controller.torque_params.latAccelOffset,
                                  controller.torque_params.friction)
    if forced_off:
      factor, friction = self.cp.lateralTuning.torque.latAccelFactor, self.cp.lateralTuning.torque.friction
    if not auto:
      factor = self.values.get("SteerLatAccel", factor)
      friction = self.values.get("SteerFriction", friction)
    changed = forced_off or (not auto and any(k in self.values for k in ("SteerLatAccel", "SteerFriction")))
    if (valid and (native_auto or forced_on)) or changed:
      # Guard malformed replay/estimator data without ever widening safety limits.
      if all(math.isfinite(v) for v in (factor, offset, friction)) and factor > 0 and friction >= 0:
        controller.update_torque_parameters(factor, offset, friction)
