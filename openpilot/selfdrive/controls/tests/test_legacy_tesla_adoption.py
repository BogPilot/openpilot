"""rc5: Gas/Brake profiles are live by default on the legacy Tesla platforms (no UI re-select), safety floors kept, and the
AP1 cruise shape is justified against the 0.9.7 set-speed logs (fixtures/h1_097_setspeed.json)."""
import json
import os
import types
import numpy as np
import pytest
from opendbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.controls.lib import longitudinal_planner as lp
from openpilot.selfdrive.controls.lib import ap1_planning
from openpilot.selfdrive.controls.lib.phase3_long_accel import (
  Profiles, PROFILE_ACK, configure, profiles_default_on, profiles_adopted,
)

LEGACY = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS")
CP = types.SimpleNamespace(steerRatio=15.0, wheelbase=2.96)
class Store:
  """Same minimal store the phase3_long_accel tests use."""
  def __init__(self, **values):
    self.values = values
    self.hidden = set()
    self.writes = []
  def default(self, key):
    return BOGPILOT_PARAMS.get(key, (None, None, '0'))[2] or '0'
  def get(self, key, default=None):
    return self.values.get(key, self.default(key) if default is None else default)
  def get_bool(self, key, default=None):
    return str(self.get(key, default)).lower() in ('1', 'true')
  def get_float(self, key):
    return float(self.get(key))
  def get_int(self, key):
    return int(self.get_float(key))
  def tuning_level(self):
    return 3
  def honoured(self, key, level=None):
    return key not in self.hidden
  def toggle_bool(self, key, level=None):
    return self.get_bool(key) if self.honoured(key) else str(self.default(key)) == '1'
  def toggle_float(self, key, level=None):
    return self.get_float(key) if self.honoured(key) else float(self.default(key))
  def toggle_int(self, key, level=None):
    return int(self.toggle_float(key))
  def put(self, key, value, block=False):
    self.values[key] = value
    self.writes.append((key, value))
  def put_bool(self, key, value, block=False):
    self.put(key, value)
  def invalidate(self):
    pass


STORED_097 = dict(LongitudinalTune=1, AccelerationProfile=2, DecelerationProfile=2, HumanAcceleration=1)


@pytest.mark.parametrize("platform", LEGACY)
def test_legacy_tesla_platforms_adopt_without_an_ack(platform):
  s = Store(**STORED_097)
  assert profiles_default_on(platform) and profiles_adopted(s, platform)
  assert Profiles.read(s, platform) == Profiles(2, 2, True)
  assert s.writes == []                       # reading never writes


@pytest.mark.parametrize("platform", [None, "", "TESLA_AP2_MODELS", "TOYOTA_COROLLA_TSS2", "HYUNDAI_IONIQ_5"])
def test_every_other_car_keeps_the_explicit_ack_rule(platform):
  s = Store(**STORED_097)
  assert not profiles_default_on(platform)
  assert Profiles.read(s, platform) is None
  assert Profiles.read(s) is None
  configure(s, "AccelerationProfile", 2)     # the explicit UI action still adopts
  assert s.values[PROFILE_ACK] is True and Profiles.read(s, platform) == Profiles(2, 2, True)


def test_longitudinal_tune_off_is_respected_on_the_legacy_platforms():
  # LongitudinalTune=0 is the owner's off switch (and what "Reset to stock" stores): no profile, stock limits
  for platform in LEGACY:
    assert Profiles.read(Store(**{**STORED_097, "LongitudinalTune": 0}), platform) is None


def test_stored_custom_values_are_used_not_overwritten():
  s = Store(LongitudinalTune=1, AccelerationProfile=1, DecelerationProfile=1, HumanAcceleration=0)
  assert Profiles.read(s, "TESLA_PREAP_MODELS") == Profiles(1, 1, False)
  assert s.writes == []


def test_unwritten_keys_read_the_0_9_7_registry_defaults():
  # nothing stored: registry defaults are Sport / Eco / Human on (0.9.7 frogpilot_variables.py), tune on
  assert [BOGPILOT_PARAMS[k][2] for k in ("LongitudinalTune", "AccelerationProfile", "DecelerationProfile", "HumanAcceleration")] == ["1", "2", "1", "1"]
  assert Profiles.read(Store(), "TESLA_AP1_MODELS") == Profiles(2, 1, True)


def test_planner_passes_the_platform_to_the_profile_reader():
  import inspect
  from openpilot.selfdrive.controls.lib.phase3_long_accel import LongAccelPort
  assert 'Profiles.read(self.store, getattr(self.cp, "carFingerprint", None))' in inspect.getsource(LongAccelPort.update)


# ---- exact 0.9.7 limits and the safety floors that stay ---------------------------------------------------------
def test_sport_eco_plus_human_limits_match_the_0_9_7_source():
  p = Profiles(2, 2, True)
  # frogpilot_acceleration.py (026cfb31 == 04d560f3e): Sport table, Human low-speed + ramp-off, Eco+ = ACCEL_MIN / 4
  v_ego, v_cruise = 14.8 * 0.44704, 20.0 * 0.44704
  low, high = p.limits(v_ego, v_cruise, ACCEL_MIN)
  sport = np.interp(v_ego, [0, 5, 10, 15, 20, 25, 40], [3, 2.5, 2, 1.5, 1, .8, .6])
  human = min(np.interp(v_cruise, [0, 12.5, 25], [sport / 4, sport / 2, sport]), sport)
  human = min(np.interp(v_cruise - v_ego, [0, 1, 5], [0, .5, human]), human)
  assert high == pytest.approx(human) and high == pytest.approx(0.66, abs=0.02)   # logged fpMax 0.67
  assert low == pytest.approx(ACCEL_MIN / 4) and low == pytest.approx(-0.875)     # logged fpMin -0.88


def test_lead_braking_restores_the_full_floor_and_the_output_clip_stays():
  p = Profiles(2, 2, True)
  assert p.limits(10.0, 12.0, ACCEL_MIN, tracking_lead=True)[0] == ACCEL_MIN
  assert Profiles(2, 0, False).limits(10.0, 12.0, ACCEL_MIN)[0] == ACCEL_MIN
  # the planner still clips the final output to ACCEL_MIN/ACCEL_MAX and the cruise law keeps the lateral cap
  import inspect
  src = inspect.getsource(lp.LongitudinalPlanner.update)
  assert "np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)" in src
  assert "a_x_allowed" in inspect.getsource(lp.get_cruise_accel)


def run(v_set, v, prev=0.0, profile=None, steps=1, dt=0.05, shape=True):
  a = prev
  for _ in range(steps):
    a = lp.get_cruise_accel(False, v_set, v, a, 0.0, CP, dt, -0.3, True, profile, ap1_shape=shape)
  return a


def test_the_temporary_shape_floor_is_gone_and_eco_plus_owns_the_floor_once():
  assert not hasattr(ap1_planning, "AP1_CRUISE_A_MIN")
  eco_plus = Profiles(2, 2, True).limits(10.0, 5.0, ACCEL_MIN)
  assert run(5.0, 30.0, profile=eco_plus, steps=2000) == pytest.approx(-0.875)       # Eco+ floor, applied once
  eco = Profiles(2, 1, True).limits(10.0, 5.0, ACCEL_MIN)
  assert run(5.0, 30.0, profile=eco, steps=2000) == pytest.approx(-1.75)             # Eco keeps ITS floor (no hidden -0.875)
  assert run(5.0, 30.0, profile=None, steps=2000) == pytest.approx(lp.A_CRUISE_MIN)   # tune off: the stock -1.2, not -0.875


# ---- replay of the 0.9.7 set-speed logs: the gain/jerk shaping is still needed ----------------------------------
def _events():
  path = os.path.join(os.path.dirname(__file__), "fixtures", "h1_097_setspeed.json")
  with open(path) as f:
    return json.load(f)["events"]


def _replay(rows, gain, jerk, profile=True, dt=0.05):
  mph = 0.44704
  ts = np.array([r[0] for r in rows]); v = np.array([r[1] for r in rows]) * mph; cc = np.array([r[2] for r in rows])
  st = np.array([r[3] for r in rows]) * mph
  prof = Profiles(2, 2, True)
  saved = (lp.AP1_CRUISE_GAIN, lp.AP1_CRUISE_J_SCALE)
  lp.AP1_CRUISE_GAIN, lp.AP1_CRUISE_J_SCALE = gain, jerk
  try:
    a, out = cc[0], []
    for t in np.arange(ts[0], ts[-1] + 1e-9, dt):
      ve = float(np.interp(t, ts, v)); vc = float(st[np.searchsorted(ts, t, side="right") - 1]) if t >= ts[0] else st[0]
      pl = prof.limits(ve, vc, ACCEL_MIN) if profile else None
      a = lp.get_cruise_accel(False, vc, ve, a, 0.0, CP, dt, -0.3, True, pl, ap1_shape=(gain != 1.0 or jerk != 1.0))
      out.append((t, a))
  finally:
    lp.AP1_CRUISE_GAIN, lp.AP1_CRUISE_J_SCALE = saved
  out = np.array(out)
  rmse = float(np.sqrt(np.mean((out[:, 1] - np.interp(out[:, 0], ts, cc)) ** 2)))
  return rmse, float(out[:, 1].min()), float(out[:, 1].max()), float(np.max(np.abs(np.diff(out[:, 1]))) / dt)


def test_profiles_alone_are_not_enough_the_0_9_7_ramp_needs_the_shape():
  ev = _events()
  stock_profiles = [_replay(r, 1.0, 1.0) for r in ev.values()]     # B: Sport/Eco+/Human with the stock law
  shaped = [_replay(r, ap1_planning.AP1_CRUISE_GAIN, ap1_planning.AP1_CRUISE_J_SCALE) for r in ev.values()]
  for (rm_b, _, _, jerk_b), (rm_d, lo_d, hi_d, jerk_d) in zip(stock_profiles, shaped):
    assert jerk_b > 1.0                       # 0.9.7 logged a plan jerk of 0.49-1.06 (0.2 s window), stock law ramps at ~1.3
    assert jerk_d < 0.6                       # shaped: 0.45-0.53
    assert rm_d < rm_b / 1.5                  # closer to the logged 0.9.7 plan
    assert rm_d < 0.15
    assert -0.60 < lo_d and hi_d < 0.70       # 0.9.7 plateaus: +0.51 / -0.48


def test_shape_values_are_close_to_the_0_9_7_plan_and_far_from_the_stock_law():
  ev = list(_events().values())
  rms = lambda g, j: float(np.sqrt(np.mean([_replay(r, g, j)[0] ** 2 for r in ev])))
  here = rms(ap1_planning.AP1_CRUISE_GAIN, ap1_planning.AP1_CRUISE_J_SCALE)
  assert here < 0.12                       # m/s^2 rms against the logged 0.9.7 plan (profiles + stock law: 0.29, stock rc3: 0.60)
  assert here < rms(1.0, 1.0) / 2.5
  # the best fit in a wide grid (gain .42, jerk .25: rms 0.074) is closer to the log, but a 0.25 jerk scale also slows launches
  # from a stop and is two press events of evidence: kept at the rc4 values until a road check says otherwise
  best = min(rms(g, j) for g in (0.20, 0.30, 0.34, 0.42) for j in (0.25, 0.40, 0.60))
  assert here <= best * 1.45
