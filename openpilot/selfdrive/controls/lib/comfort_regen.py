"""Comfort regen braking v2 for legacy Tesla (AP1 Model S and Pre-AP), setting RegenComfortBrake.

The stock 0.11.2 lead MPC, its desired gap and its constraints stay unmodified. This layer runs after the planner has picked
its acceleration and can only ask for more braking: final = min(stock, comfort).

It acts only for a radar-confirmed lead that is closing. It works out the constant decel that would settle the car at the
stock steady-state following gap (t_follow * v_lead + STOP_DISTANCE) using all of the remaining distance:

  a_req = v_close^2 / (2 * max(d_rel - d_desired, EPS))

with the lead speed filtered over about 1 s, so a short brake tap is not treated as a full stop (stock still owns real stops).
While a_req is gentle (at most A_GENTLE_ON, about 2 mph/s) the layer asks for -a_req. When more is needed it releases and
stock owns the stop, so the layer never adds a hard stop. Only the comfort request's onset and release are jerk-limited; a
stronger stock request always wins at once through the min(), so cut-ins and hard lead braking keep the stock response.
Inactive while not engaged, in gas override and at standstill. Set-speed changes, cancel and the accelerator are untouched.
"""
import math

STOP_DISTANCE = 6.0      # m, must equal long_mpc.STOP_DISTANCE (checked in tests)
A_GENTLE_ON = 0.9        # m/s^2: enter only when the settle decel is at most this (about 2.0 mph/s); also the request cap
A_GENTLE_OFF = 1.1       # m/s^2: once active, release when more than this is needed (hysteresis against chatter)
A_MIN_ACTIVE = 0.05      # m/s^2: ignore negligible requests
MARGIN = 1.05            # small margin on a_req, still capped at A_GENTLE_ON
CLOSING_MIN = 0.5        # m/s (about 1.1 mph): below this the lead is not closing
EPS = 1.0                # m: distance floor for a_req
LEAD_V_TAU = 1.0         # s: lead speed filter time constant
JERK_ON = 0.75           # m/s^3: comfort onset
JERK_OFF = 1.0           # m/s^3: comfort release


def settle_decel(v_ego, v_lead, d_rel, t_follow):
  """Constant decel (m/s^2, >= 0) that brings the closing speed to zero at the stock steady gap. inf when there is no room."""
  v_close = v_ego - v_lead
  if v_close <= 0.0:
    return 0.0
  space = d_rel - (t_follow * max(v_lead, 0.0) + STOP_DISTANCE)
  return v_close * v_close / (2.0 * max(space, EPS)) if space > 0.0 else math.inf


def comfort_regen_platform(CP):
  try:
    from opendbc.car.tesla_ap1.values import CAR
  except Exception:
    return False
  return str(CP.carFingerprint) in (str(CAR.TESLA_AP1_MODELS), str(CAR.TESLA_PREAP_MODELS)) and bool(CP.openpilotLongitudinalControl)


def comfort_regen_enabled(CP):
  if not comfort_regen_platform(CP):
    return False
  try:
    from opendbc.car.tesla_ap1.regen_brake import regen_comfort_brake_enabled
    return bool(regen_comfort_brake_enabled(str(CP.carFingerprint)))
  except Exception:
    return False


class ComfortRegen:
  def __init__(self, CP=None, dt=0.05, enabled=None):
    self.dt = dt
    self.enabled = comfort_regen_enabled(CP) if enabled is None else bool(enabled)
    self.reset()

  def reset(self):
    self.request = None       # current jerk-limited comfort accel (m/s^2), None when idle
    self.gentle = False       # hysteresis state of the gentle band
    self.v_lead_f = None
    self.track_id = None
    self.a_req = 0.0
    self.target = None

  def _lead_speed(self, lead):
    tid = int(getattr(lead, "radarTrackId", -1))
    if self.v_lead_f is None or tid != self.track_id:
      self.v_lead_f = float(lead.vLead)
      self.track_id = tid
    else:
      alpha = self.dt / (LEAD_V_TAU + self.dt)
      self.v_lead_f += alpha * (float(lead.vLead) - self.v_lead_f)
    return self.v_lead_f

  def _target(self, v_ego, lead, t_follow):
    """Comfort accel target (<= 0) or None when the layer wants nothing."""
    if lead is None or not bool(getattr(lead, "present", False)) or not bool(getattr(lead, "radar", False)):
      self.v_lead_f = None
      self.gentle = False
      return None
    v_lead = self._lead_speed(lead)
    a_req = settle_decel(v_ego, v_lead, float(lead.dRel), t_follow)
    self.a_req = a_req
    if v_ego - v_lead < CLOSING_MIN:
      self.gentle = False
      return None
    limit = A_GENTLE_OFF if self.gentle else A_GENTLE_ON
    self.gentle = A_MIN_ACTIVE <= a_req <= limit
    if not self.gentle:
      return None
    return -min(a_req * MARGIN, A_GENTLE_ON)

  def update(self, stock_accel, *, engaged, gas_pressed, standstill, v_ego, lead, t_follow):
    """Returns the final accel: stock_accel, or something lower. Never higher than stock_accel."""
    stock_accel = float(stock_accel)
    if not self.enabled:
      return stock_accel
    if not engaged or gas_pressed or standstill or not math.isfinite(t_follow):
      self.reset()
      return stock_accel
    target = self._target(float(v_ego), lead, float(t_follow))
    self.target = target
    if self.request is None:
      if target is None or target >= stock_accel:
        return stock_accel
      self.request = stock_accel       # start from where the car is, ramp down at JERK_ON
    goal = target if target is not None else math.inf
    if goal < self.request:
      self.request = max(goal, self.request - JERK_ON * self.dt)
    else:
      self.request = min(goal, self.request + JERK_OFF * self.dt)
    if self.request >= stock_accel and (target is None or target >= stock_accel):
      self.request = None              # released into stock: idle
      return stock_accel
    return min(stock_accel, self.request)
