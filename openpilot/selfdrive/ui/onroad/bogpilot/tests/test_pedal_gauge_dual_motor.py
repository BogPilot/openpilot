"""Pedal gauge on a dual-motor car: the 0x186 front motor's regen is summed into the regen bar against the dual-motor
peak; the live rpm per m/s replaces the fixed 9.73 / 0.35 m constants; single-motor cars are unchanged."""
import math
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED

S_FP, X_FP, P_FP = "TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"


def kw(tq, rpm):
  return -tq * rpm * 2 * math.pi / 60000


def test_peaks():
  assert G3.regen_peak_kw(S_FP) == 42.0 and G3.regen_peak_kw(P_FP) == 42.0      # single motor unchanged
  assert G3.regen_peak_kw(S_FP, dual=True) == 53.1
  assert G3.regen_peak_kw(X_FP) == G3.regen_peak_kw(X_FP, dual=True) == 71.6     # every X is dual


def test_front_regen_summed():
  rear_only = G3.regen_power_fill(-60.0, 5000.0, X_FP)
  both = G3.regen_power_fill(-60.0, 5000.0, X_FP, front_torque_nm=-50.0, front_rpm=4900.0)
  assert rear_only == pytest.approx(kw(-60, 5000) / 71.6)
  assert both == pytest.approx((kw(-60, 5000) + kw(-50, 4900)) / 71.6)
  s_single = G3.regen_power_fill(-60.0, 5000.0, S_FP)
  assert s_single == pytest.approx(kw(-60, 5000) / 42.0)                          # S without 0x186: as before
  s_dual = G3.regen_power_fill(-40.0, 5000.0, S_FP, front_torque_nm=-30.0, front_rpm=4900.0)
  assert s_dual == pytest.approx((kw(-40, 5000) + kw(-30, 4900)) / 53.1)


def test_measured_ratio_replaces_constants():
  old = G3.speed_from_rpm(5000.0, None)
  assert old == pytest.approx(5000.0 / (9.73 * 60 / (2 * math.pi * 0.35)))
  assert G3.speed_from_rpm(5000.0, 250.0) == pytest.approx(20.0)
  d = G3.regen_decel_from_torque(-100.0, 250.0, 2575.0, -50.0, 244.0)
  assert d == pytest.approx((100 * 250 + 50 * 244) * 2 * math.pi / 60 / 2575.0)


def test_drive_kwargs_only_use_front_on_detected_dual():
  bcs = SimpleNamespace(ap1DriveLayout=2, ap1FrontMotorTorqueNm=-40.0, ap1FrontMotorRpm=3000.0, ap1RearRpmPerMs=250.0,
                        ap1FrontRpmPerMs=244.0)
  out = PED.drive_kwargs(bcs, X_FP, now=0.0)
  assert out["front_torque_nm"] == -40.0 and out["front_rpm"] == 3000.0 and out["rpm_per_ms"] == 250.0
  assert out["front_rpm_per_ms"] == 244.0 and out["mass_kg"] == 2400.0     # Auto: the base X mass
  single = PED.drive_kwargs(SimpleNamespace(ap1DriveLayout=1, ap1FrontMotorTorqueNm=-40.0, ap1FrontMotorRpm=3000.0,
                                            ap1RearRpmPerMs=265.0, ap1FrontRpmPerMs=float("nan")), S_FP, now=0.0)
  assert "front_torque_nm" not in single and "front_rpm_per_ms" not in single
  stale = PED.drive_kwargs(SimpleNamespace(ap1DriveLayout=2, ap1FrontMotorTorqueNm=float("nan"), ap1FrontMotorRpm=float("nan"),
                                           ap1RearRpmPerMs=250.0, ap1FrontRpmPerMs=244.0), X_FP, now=0.0)
  assert "front_torque_nm" not in stale
  assert PED.drive_kwargs(SimpleNamespace(), "TOYOTA_RAV4", now=0.0) == {"mass_kg": None, "rpm_per_ms": None}


# ---------------------------------------------------------------- PedalGauge dual-motor mode (research section 4)
DT = 0.05
ON = PED.PedalPolicy(show=True)


class Rig:
  def __init__(self, fp=X_FP):
    self.g, self.t, self.fp = PED.PedalGauge(), 0.0, fp

  def step(self, rear, rpm, front=None, frpm=None, op=0.0, long=True, n=1):
    out = None
    for _ in range(n):
      self.t += DT
      out = self.g.update(ON, True, self.t, "ap1", brake_pressed=False, brake_level=0.0, pedal_pos=0.0, op_accel=op,
                          long_active=long, motor_torque_nm=rear, motor_rpm=rpm, fingerprint=self.fp,
                          front_torque_nm=front, front_rpm=frpm, rpm_per_ms=250.0, front_rpm_per_ms=244.0, mass_kg=2400.0)
    return out


def test_front_only_cruise_at_high_rpm_stays_live():
  # the X cruising on the front motor: rear flat zero at 7000 rpm, front carries the load; no fallback, no rpm cutoff
  r = Rig()
  out = r.step(0.0, 7000.0, front=40.0, frpm=6800.0, op=0.5, n=100)
  assert not r.g.dual_trust.dead and not r.g.trust.dead
  assert out.accel == pytest.approx(G3.accel_power_fill(None, None, 40.0, 6800.0), abs=1e-3) and out.accel > 0.0
  out = r.step(0.0, 7000.0, front=-60.0, frpm=6800.0, op=-1.0, n=100)
  assert out.regen == pytest.approx(kw(-60, 6800) / 71.6, abs=1e-3)


def test_accel_and_regen_sum_both_motors_power():
  r = Rig(S_FP)
  out = r.step(30.0, 5000.0, front=20.0, frpm=4900.0, op=0.5, n=40)
  assert out.accel == pytest.approx(G3.accel_power_fill(30.0, 5000.0, 20.0, 4900.0), abs=1e-3)
  assert G3.accel_power_fill(30.0, 5000.0, 20.0, 4900.0) > G3.accel_power_fill(30.0, 5000.0)
  out = r.step(-30.0, 5000.0, front=-20.0, frpm=4900.0, op=-1.0, n=40)
  assert out.regen == pytest.approx((kw(-30, 5000) + kw(-20, 4900)) / 53.1, abs=1e-3)


def test_fallback_only_when_both_zero_for_half_a_second_and_resume_on_either():
  r = Rig()
  r.step(0.0, 7000.0, front=0.0, frpm=6800.0, op=-1.0, n=int(PED.TORQUE_DEAD_HOLD_S / DT) - 2)
  assert not r.g.dual_trust.dead
  out = r.step(0.0, 7000.0, front=0.0, frpm=6800.0, op=-1.0, n=6)
  assert r.g.dual_trust.dead and out.regen > 0.0                     # openpilot's request drawn on the combined scale
  v = 7000.0 / 250.0
  assert out.regen == pytest.approx(min(1.0, 1.0 * 2400.0 * v / 1000.0 / 71.6), rel=0.05)
  r.step(0.0, 7000.0, front=8.0, frpm=6800.0, op=-1.0, n=2)            # a blip does not release
  assert r.g.dual_trust.dead
  r.step(0.0, 7000.0, front=8.0, frpm=6800.0, op=-1.0, n=int(PED.TORQUE_ALIVE_HOLD_S / DT) + 1)
  assert not r.g.dual_trust.dead


def test_no_fallback_for_a_real_coast_or_without_op_long_or_parked():
  coast = Rig()
  out = coast.step(0.0, 7000.0, front=0.0, frpm=6800.0, op=0.0, n=60)  # no request: a coast, empty is right
  assert not coast.g.dual_trust.dead and out.regen == 0.0 and out.accel == 0.0
  manual = Rig()
  manual.step(0.0, 7000.0, front=0.0, frpm=6800.0, op=-1.0, long=False, n=60)
  assert not manual.g.dual_trust.dead
  parked = Rig()
  parked.step(0.0, 0.0, front=0.0, frpm=0.0, op=-1.0, n=60)
  assert not parked.g.dual_trust.dead


def test_stale_front_drops_to_single_motor_mode():
  r = Rig()
  r.step(0.0, 7000.0, front=40.0, frpm=6800.0, op=0.5, n=10)
  out = r.step(0.0, 7000.0, front=float("nan"), frpm=float("nan"), op=0.5, n=20)   # 0x186 stale -> NaN
  assert r.g.trust.dead and r.g.trust.rpm_on == 5500.0                # rear-only + the X 5500 rpm gate
  assert out.accel == pytest.approx(min(1.0, 0.5 / PED.OP_ACCEL_FULL_SCALE), abs=1e-3)   # OP request fallback
  r2 = Rig()
  out = r2.step(-30.0, 5000.0, front=None, frpm=None, op=-1.0, n=20)
  assert out.regen == pytest.approx(kw(-30, 5000) / 71.6, abs=1e-3)   # rear only; never a stale front value


def test_single_motor_s_unchanged():
  r = Rig(S_FP)
  out = r.step(-30.0, 5000.0, op=-1.0, n=20)
  assert out.regen == pytest.approx(kw(-30, 5000) / 42.0, abs=1e-3)
  r.step(0.0, 6100.0, op=-1.0, n=20)
  assert r.g.trust.dead and r.g.trust.rpm_on == 6000.0


def test_request_regen_kw_is_m_a_v():
  assert PED.request_regen_kw(-1.0, 20.0, 2400.0) == pytest.approx(48.0)
  assert PED.request_regen_kw(0.5, 20.0, 2400.0) == 0.0 and PED.request_regen_kw(-1.0, None) is None
