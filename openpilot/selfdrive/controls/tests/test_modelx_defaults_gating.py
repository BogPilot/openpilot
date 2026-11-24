"""AP1 Model X defaults (next build): which S features the X now gets, only while X openpilot long is on, with which values.

The Model S rows in every test prove the S is unchanged.
"""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from opendbc.car.tesla_ap1 import regen_aware as ra
from openpilot.selfdrive.controls.lib import csc_platform as P
from openpilot.selfdrive.controls.lib.curve_speed_planner import TESLA_CSC_MAX_LAT_ACCEL, curve_speed_planner_for
from openpilot.selfdrive.controls.lib.ap1_planning import Ap1Planning
from openpilot.selfdrive.controls.lib.comfort_regen import comfort_regen_enabled, comfort_regen_platform

S, X, PREAP = "TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"


def cp(fp, long):
  return NS(carFingerprint=fp, openpilotLongitudinalControl=long, pcmCruise=not long)


@pytest.fixture
def files_default(monkeypatch):
  import opendbc.car.tesla_ap1.regen_brake as rb
  monkeypatch.setattr(rb, "_read_regen_comfort_file", lambda: "")      # fresh install: no saved value
  return rb


# ---- Earlier, Gentler Regen Stops (comfort regen v2) -------------------------------------------------------------------

def test_comfort_regen_x_only_with_op_long(files_default):
  assert comfort_regen_platform(cp(X, True)) and comfort_regen_enabled(cp(X, True))
  assert not comfort_regen_platform(cp(X, False)) and not comfort_regen_enabled(cp(X, False))
  assert comfort_regen_enabled(cp(S, True)) and not comfort_regen_enabled(cp(S, False))           # S unchanged
  assert comfort_regen_enabled(cp(PREAP, True))
  assert not comfort_regen_enabled(cp("TESLA_MODEL_3", True))


def test_comfort_regen_x_saved_off_is_kept(monkeypatch):
  import opendbc.car.tesla_ap1.regen_brake as rb
  monkeypatch.setattr(rb, "_read_regen_comfort_file", lambda: "0")
  assert not comfort_regen_enabled(cp(X, True)) and not comfort_regen_enabled(cp(S, True))


# ---- Curve Speed Control, Smooth Curve Braking, Map Curve Speed ---------------------------------------------------------

def test_csc_x_only_with_op_long_and_s_cap_kept():
  assert P.csc_supported(cp(X, True)) and P.csc_row_visible(cp(X, True))
  assert not P.csc_supported(cp(X, False)) and curve_speed_planner_for(cp(X, False)) is None
  assert curve_speed_planner_for(cp(X, True)) is not None
  assert P.csc_supported(cp(S, True)) and not P.csc_supported(cp(S, False))                      # S unchanged
  # the X uses the S cornering cap: 2.0 m/s^2 (4.5 mph/s). X drive: engaged max 1.45 m/s^2, the driver's own sustained
  # curves up to about 2.2 m/s^2, so nothing in the X data asks for a lower cap.
  assert TESLA_CSC_MAX_LAT_ACCEL == 2.0


# ---- Regen-aware stop shaper and the set-speed shaping -----------------------------------------------------------------

def test_planner_regen_shaper_x_with_x_physics_only_with_op_long(monkeypatch):
  monkeypatch.setattr("openpilot.selfdrive.controls.lib.ap1_planning.regen_aware_enabled", lambda fp: fp in (S, X))
  x = Ap1Planning(cp(X, True), 0.05)
  # trim profiles: the X car is MODEL_X with the profile's mass and the measured rpm per m/s (Auto: the base 2400 kg)
  assert x.regen_enabled and x.power.car is x.stop.car and x.power.car.mass_kg == ra.MODEL_X.mass_kg == 2400.0
  assert x.power.car.p_nominal_kw == ra.MODEL_X.p_nominal_kw == 51.1 and x.power.p_kw == 51.1
  assert x.power.car.fade_bp == ra.MODEL_X.fade_bp and x.power.car.a_cap_max == ra.MODEL_X.a_cap_max
  assert not x.active                       # set-speed reaction shaping stays Model S only (needs an X long log first)
  assert not x.stalk_follow_active          # stalk follow distance stays S / Pre-AP only
  assert not Ap1Planning(cp(X, False), 0.05).regen_enabled
  s = Ap1Planning(cp(S, True), 0.05)        # S unchanged
  assert s.regen_enabled and s.active and s.power.car is ra.MODEL_S and s.stop.car is ra.MODEL_S and s.power.p_kw == 30.0
  assert not Ap1Planning(cp(S, False), 0.05).regen_enabled
  assert not Ap1Planning(cp(PREAP, True), 0.05).regen_enabled


def test_planner_regen_shaper_x_saved_off_is_kept(monkeypatch):
  import opendbc.car.tesla_ap1.regen_aware as ram
  monkeypatch.setattr(ram, "_TOGGLE_PATH", NS(is_file=lambda: True, read_text=lambda: "0"))
  assert not Ap1Planning(cp(X, True), 0.05).regen_enabled
  assert not Ap1Planning(cp(S, True), 0.05).regen_enabled


def test_x_shape_stop_runs_with_x_inputs():
  p = Ap1Planning(cp(X, True), 0.05)
  p.regen_enabled = True
  carstate = NS(vEgo=10.0, gasPressed=False, brakePressed=False, canValid=True,
                bogpilot=NS(ap1MotorTorqueNm=-40.0, ap1MotorRpm=10.0 * 249.9, ap1AmbientTempC=27.0))
  sm = {"carState": carstate, "radarState": NS(leadOne=NS(present=True, dRel=35.0, vLead=0.0)),
        "selfdriveState": NS(experimentalMode=False), "modelV2": NS(position=NS(x=[]), velocity=NS(x=[]))}
  outs = [p.shape_stop(sm, -0.1, True) for _ in range(60)]
  assert all(o <= -0.1 + 1e-9 for o in outs) and min(outs) < -0.1     # add-only, and it does add braking for the stop
