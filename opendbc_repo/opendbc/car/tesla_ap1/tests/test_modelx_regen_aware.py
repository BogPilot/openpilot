"""AP1 Model X: regen-aware stop shaper values, the X-only gates in opendbc, and proof the Model S is unchanged.

Every Model X number here comes from a real Model X drive or a public spec (see regen_aware.py's module doc).
"""
import math
from types import SimpleNamespace

import numpy as np
import pytest

from opendbc.car import Bus
from opendbc.car.tesla_ap1 import regen_aware as ra
from opendbc.car.tesla_ap1 import regen_brake, toggles
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.values import CAR

S, X, PREAP = CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX, CAR.TESLA_PREAP_MODELS
DT = 0.05


# ---- Model S: exactly as tuned before -------------------------------------------------------------------------------

def test_model_s_constants_unchanged():
  assert (ra.MASS_KG, ra.GEAR_RATIO, ra.WHEEL_RADIUS_M, ra.ETA) == (2100.0, 9.73, 0.35, 0.9)
  assert (ra.P_NOMINAL_KW, ra.P_COLD_KW, ra.P_MIN_KW, ra.COLD_AMBIENT_C) == (30.0, 18.0, 10.0, 5.0)
  assert (ra.FADE_BP, ra.FADE_V, ra.A_CAP_MAX, ra.LIMIT_MIN_SPEED) == ([0.9, 2.2, 4.7], [0.0, 0.38, 1.0], 1.6, 4.7)
  assert ra.MODEL_S == ra.RegenCar(2100.0, 9.73, 0.35, 30.0, 18.0, (0.9, 2.2, 4.7), (0.0, 0.38, 1.0), 1.6, 4.7)
  for fp in (S, "TESLA_AP1_MODELS", PREAP, "OTHER", None):
    assert ra.regen_car(fp) is ra.MODEL_S


def _s_reference_capacity(v, p_kw):
  # The pre-Model-X formula, written out with the S constants.
  power = p_kw * 1000.0 * 0.9 / (2100.0 * max(v, 0.5))
  return float(np.interp(v, [0.9, 2.2, 4.7], [0.0, 0.38, 1.0])) * min(1.6, power)


@pytest.mark.parametrize("v", [0.3, 1.0, 2.2, 3.0, 4.7, 6.0, 10.0, 15.0, 25.0, 35.0])
@pytest.mark.parametrize("p_kw", [10.0, 18.0, 30.0])
def test_model_s_default_path_is_identical_to_the_old_formula(v, p_kw):
  assert ra.regen_capacity(v, p_kw) == pytest.approx(_s_reference_capacity(v, p_kw), abs=1e-12)
  assert ra.regen_capacity(v, p_kw, ra.MODEL_S) == ra.regen_capacity(v, p_kw)
  assert ra.profile_decel(v, p_kw, ra.MODEL_S) == ra.profile_decel(v, p_kw)
  assert ra.profile_distance(v, p_kw, car=ra.MODEL_S) == ra.profile_distance(v, p_kw)
  assert ra.regen_decel_from_torque(-100.0) == pytest.approx(100.0 * 9.73 / 0.35 / 2100.0)


def test_model_s_estimator_and_shaper_defaults_unchanged():
  e = ra.RegenPowerEstimator()
  assert e.car is ra.MODEL_S and e.p_kw == 30.0 and e.ceiling(2.0) == 18.0 and e.ceiling(20.0) == 30.0
  assert ra.RegenPowerEstimator(25.0).p_kw == 25.0
  # the same S stop simulation with and without the explicit car argument gives the same trace
  a, b = ra.RegenStopShaper(), ra.RegenStopShaper(car=ra.MODEL_S)
  for i in range(200):
    v = 12.0 - 0.05 * i
    assert a.update(v, -0.1, 80.0 - 0.6 * i, 30.0, DT) == b.update(v, -0.1, 80.0 - 0.6 * i, 30.0, DT)


# ---- Model X values and their derivation -----------------------------------------------------------------------------

def test_model_x_values_are_derived_from_x_data_and_specs():
  x = ra.MODEL_X
  assert x.mass_kg == 2400.0                                          # Model X mass
  assert x.gear_ratio == 9.734                                        # X rear drive unit (0x108 is the rear motor)
  assert ra.MODELX_RPM_PER_MS == 249.9                                 # measured on the X drive
  assert x.wheel_radius_m == 0.372 and x.wheel_radius_m == pytest.approx(9.734 * 60 / (2 * math.pi * 249.9), abs=5e-4)
  # the X motor turns about 6 % slower per mph than the S constants predict
  s_rpm_per_ms = 9.73 * 60 / (2 * math.pi * 0.35)
  assert 1 - ra.MODELX_RPM_PER_MS / s_rpm_per_ms == pytest.approx(0.059, abs=0.005)
  assert ra.MODELX_REAR_REGEN_PEAK_KW == 49.0 and ra.MODELX_REGEN_PEAK_KW == 71.6   # rear 49 kW; front + rear (0x108 + 0x186) 71.6 kW
  assert x.p_nominal_kw == ra.MODELX_P_NOMINAL_KW == pytest.approx(71.6 * 30.0 / 42.0, abs=0.1)   # S: 30 of 42 kW -> same fraction
  assert x.p_cold_kw == ra.P_COLD_KW == 18.0                          # no X cold data: the S ceiling, below the X nominal
  assert ra.MODELX_REGEN_TORQUE_NM == 124.0
  assert x.a_cap_max == 1.35 and x.a_cap_max == pytest.approx(124.0 * 9.734 / 0.372 / 2400.0, abs=0.005)
  assert x.fade_bp == (0.6, 2.25, 4.5) and x.fade_v == (0.0, 0.43, 1.0) and x.limit_min_speed == 4.5
  assert ra.regen_car(X) is ra.MODEL_X and ra.regen_car("TESLA_AP1_MODELX") is ra.MODEL_X


# X pedal-off regen torque relative to its -124 Nm plateau on the X drive (p10 per 0.5 m/s bin); the fade table must not
# assume more regen than measured anywhere in the band.
X_FADE_MEASURED = {0.75: 0.07, 1.25: 0.23, 1.75: 0.23, 2.25: 0.43, 2.75: 0.62, 3.25: 0.79, 3.75: 0.90, 4.25: 0.96, 4.75: 1.0}


@pytest.mark.parametrize("v,measured", sorted(X_FADE_MEASURED.items()))
def test_model_x_fade_is_at_or_below_the_measured_regen(v, measured):
  assert ra.fade(v, ra.MODEL_X) <= measured + 0.08
  assert ra.fade(v, ra.MODEL_X) >= measured - 0.15


def test_model_x_capacity_and_decel_from_torque():
  x = ra.MODEL_X
  assert ra.regen_decel_from_torque(-124.0, x) == pytest.approx(124.0 * 9.734 / 0.372 / 2400.0)
  assert ra.regen_decel_from_torque(50.0, x) == 0.0
  assert ra.regen_capacity(10.0, 35.0, x) == pytest.approx(min(1.35, 35e3 * 0.9 / (2400 * 10.0)))
  assert ra.regen_capacity(5.0, 35.0, x) <= x.a_cap_max
  assert ra.regen_capacity(0.5, 35.0, x) == 0.0
  # power-limited at highway speed: the X and S gentle targets stay close (same comfort band, own physics)
  for v in (15.0, 20.0, 30.0):
    gx, gs = ra.gentle_target(v, 35.0, x), ra.gentle_target(v, 30.0)
    assert ra.A_GENTLE_FLOOR <= gx <= ra.A_GENTLE_MAX and abs(gx - gs) < 0.1


def test_model_x_estimator_uses_x_ceilings_and_x_limit_band():
  e = ra.RegenPowerEstimator(car=ra.MODEL_X)
  assert e.p_kw == 51.1 and e.ceiling(20.0) == 51.1 and e.ceiling(2.0) == 18.0
  e.update(10, 0.0, 0, 0, 2.0, DT)
  assert e.p_kw == 18.0
  for _ in range(int(80 / DT)):
    e.update(10, 0.0, 0, 0, 20.0, DT)
  assert e.p_kw == 51.1
  # limited: request 1.5 m/s^2 at 12 m/s while the torque gives about 0.55 m/s^2 (-50 Nm) for more than 0.5 s
  for _ in range(int(0.8 / DT)):
    e.update(12, -1.5, -50, 12 * 249.9, 20, DT)
  assert e.limited and e.p_kw < 51.1
  # no judgement inside the X fade band (4.5 m/s), even where the S band (4.7) would differ
  e2 = ra.RegenPowerEstimator(car=ra.MODEL_X)
  for _ in range(40):
    e2.update(4.4, -1.5, -10, 1100, 20, DT)
  assert e2.p_kw == 51.1 and not e2.limited
  e3 = ra.RegenPowerEstimator(car=ra.MODEL_X)
  for _ in range(40):
    e3.update(4.6, -1.5, -10, 1150, 20, DT)
  assert e3.limited


def test_model_x_shaper_is_add_only_and_lands_near_the_stop():
  s = ra.RegenStopShaper(car=ra.MODEL_X)
  rng = np.random.default_rng(1)
  for i in range(400):
    a_plan = float(rng.uniform(-3.5, 1.0))
    d = None if i % 7 == 0 else float(rng.uniform(5, 120))
    out, _ = s.update(12.0, a_plan, d, 35.0, DT)
    assert out <= a_plan + 1e-9
  assert ra.RegenStopShaper(car=ra.MODEL_X).update(15.0, -3.0, 200.0, 35.0, DT)[0] == -3.0
  s = ra.RegenStopShaper(car=ra.MODEL_X)
  v, x, stop, t, started, peak = 9.8, 0.0, 90.0, 0.0, None, 0.0
  while v > ra.MIN_SPEED and t < 60:
    a, early = s.update(v, -0.1, stop - x, 35.0, DT)
    if early < 0 and started is None:
      started = x
    peak = min(peak, a)
    v = max(0.0, v + a * DT)
    x += v * DT
    t += DT
  assert started is not None and started < 50
  assert abs(stop - x) < 8.0 and peak > -1.3          # gentle, regen-range stop that ends near the target


# ---- X-only gates in opendbc ------------------------------------------------------------------------------------------

def test_regen_aware_toggle_s_and_x_only():
  for fp in (S, X):
    assert ra.regen_aware_enabled(fp, stored="") and ra.regen_aware_enabled(fp, stored="1")
    assert not ra.regen_aware_enabled(fp, stored="0") and not ra.regen_aware_enabled(fp, stored="off")
  for fp in (PREAP, "TESLA_MODEL_3", "OTHER", None):
    assert not ra.regen_aware_enabled(fp, stored="1")


def test_comfort_regen_preference_default_on_for_x_saved_value_kept():
  for fp in (S, X, PREAP):
    assert regen_brake.regen_comfort_brake_enabled(fp, stored="") is True
    assert regen_brake.regen_comfort_brake_enabled(fp, stored="0") is False
  for fp in ("TESLA_MODEL_3", "OTHER", None):
    assert regen_brake.regen_comfort_brake_enabled(fp, stored="1") is False


def test_round_set_speed_tips_default_on_for_x_saved_value_kept():
  for fp in (S, X):
    assert toggles.ap1_tip_round_set(fp, stored="") is True
    assert toggles.ap1_tip_round_set(fp, stored="garbage") is True
    assert toggles.ap1_tip_round_set(fp, stored="0") is False
  for fp in (PREAP, "TESLA_MODEL_3", None):
    assert toggles.ap1_tip_round_set(fp, stored="1") is False


# ---- carstate: the X reads 0x208 ambient (a 4-byte frame on the X) ------------------------------------------------------

def _carstate(fingerprint):
  cp = SimpleNamespace(carFingerprint=fingerprint)
  return CarState(cp), CarState.get_can_parsers(cp)


@pytest.mark.parametrize("fp", [S, X])
def test_ambient_from_0x208_on_s_and_x_including_the_x_4_byte_frame(fp):
  state, parsers = _carstate(fp)
  chassis = parsers[Bus.chassis]
  assert 0x208 in chassis.message_states
  assert math.isnan(state.update(parsers).bogpilot.ap1AmbientTempC)      # not seen yet
  frame = bytes([0x00, 0x86, 0x00, 0x00]) if fp == X else bytes([0x00, 0x86, 0, 0, 0, 0, 0, 0])
  chassis.update([(10**9, [(0x208, frame, chassis.bus)])])
  assert state.update(parsers).bogpilot.ap1AmbientTempC == pytest.approx(0x86 * 0.5 - 40)   # 27.0 C


def test_ambient_never_on_preap():
  state, parsers = _carstate(PREAP)
  assert 0x208 not in parsers[Bus.chassis].message_states
