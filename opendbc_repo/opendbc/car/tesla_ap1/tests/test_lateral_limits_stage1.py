"""Stage 1 lateral limits, host side: lateral-accel bound, +-360 deg, Pre-AP +-20 deg clip, host rate tables trimmed under the panda.

The libsafety cross-checks compile the real panda safety code (needs cffi and a C compiler, like the panda tests) and skip otherwise.
"""
import math
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from opendbc.car import structs
from opendbc.car.lateral import MAX_LATERAL_ACCEL
from opendbc.car.tesla_ap1 import lateral_limits as LL
from opendbc.car.tesla_ap1.actuator_plan import apply_std_steer_angle_limits, build_actuator_plan
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401  (autouse: temp params dir, fake clock)
from opendbc.car.tesla_ap1.values import CarControllerParams

SAFETY = Path(__file__).resolve().parents[3] / "safety"
OLD = CarControllerParams  # the pre-stage-1 host tables (unchanged constants; the trim is applied inside the limiter)
SPEEDS = [0.5 * i for i in range(0, 91)]  # 0..45 m/s


def _c(x):
  return f"{x:g}" + ("." if float(x).is_integer() else "")


def _header(name):
  return (SAFETY / "modes" / name).read_text()


def test_constants_match_panda_headers():
  ap1 = _header("tesla_ap1.h")
  m = re.search(r"TESLA_LEGACY_LAT_ACCEL_PARAMS\s*=\s*\{(.*?)\}", ap1, re.S)
  vals = dict(re.findall(r"\.(\w+)\s*=\s*([-0-9.e]+)", m.group(1)))
  assert float(vals["slip_factor"]) == LL.LEGACY_S_SLIP_FACTOR
  assert float(vals["steer_ratio"]) == LL.LEGACY_S_STEER_RATIO
  assert float(vals["wheelbase"]) == LL.LEGACY_S_WHEELBASE
  for name in ("tesla_ap1.h", "tesla_preap.h"):
    txt = _header(name)
    bp = ", ".join(_c(x) for x in LL.PANDA_RATE_SPEED_BP)
    assert "{" + bp + "}" in txt, name
    assert "{" + ", ".join(_c(x) for x in LL.PANDA_RATE_UP) + "}" in txt, name
    assert "{" + ", ".join(_c(x) for x in LL.PANDA_RATE_DOWN) + "}" in txt, name
    assert ".max_angle = 3600" in txt, name


def test_bound_known_values_and_cap():
  # calc: 3.589 m/s^2 through the legacy Model S model
  for mph, expect in ((30, 55.9), (45, 27.7), (75, 13.3)):
    assert LL.max_lat_accel_angle_deg(mph * 0.44704) == pytest.approx(expect, abs=0.1)
  assert LL.max_lat_accel_angle_deg(0.0) == 360.0 and LL.max_lat_accel_angle_deg(2.0) == 360.0
  for v in SPEEDS:
    assert 0 < LL.max_lat_accel_angle_deg(v) <= 360.0
    assert abs(LL.limit_lat_accel_angle(1e4, v)) == LL.max_lat_accel_angle_deg(v) == abs(LL.limit_lat_accel_angle(-1e4, v))


def test_bound_agrees_with_the_stock_vehicle_model():
  # opendbc's own get_max_angle_vm with the stock tire-stiffness defaults; the model's slip factor does not depend on mass
  from opendbc.car import scale_tire_stiffness_per_mass
  from opendbc.car.lateral import AngleSteeringLimitsVM, get_max_angle_vm
  from opendbc.car.vehicle_model import VehicleModel, calc_slip_factor
  wb = LL.LEGACY_S_WHEELBASE
  tf, tr = scale_tire_stiffness_per_mass(wb, wb / 2, 1.0)
  CP = structs.CarParams.new_message(wheelbase=wb, centerToFront=wb / 2, steerRatio=LL.LEGACY_S_STEER_RATIO, tireStiffnessFrontPerMass=tf,
                                     tireStiffnessRearPerMass=tr, rotationalInertiaPerMass=1.0)
  VM = VehicleModel(CP)
  assert calc_slip_factor(VM) == pytest.approx(LL.LEGACY_S_SLIP_FACTOR, abs=1e-5)
  limits = SimpleNamespace(ANGLE_LIMITS=AngleSteeringLimitsVM(360))
  assert limits.ANGLE_LIMITS.MAX_LATERAL_ACCEL == MAX_LATERAL_ACCEL
  for v in SPEEDS[2:]:
    vm = get_max_angle_vm(v, VM, limits)
    host = LL.max_lat_accel_angle_deg(v)
    assert host == pytest.approx(min(vm, 360.0), abs=0.05 + 1e-3 * vm), v


def test_rate_trim_only_lowers_and_is_min_of_old_and_panda():
  for v in SPEEDS:
    for up, old in ((True, OLD.ANGLE_RATE_LIMIT_UP), (False, OLD.ANGLE_RATE_LIMIT_DOWN)):
      cur = float(np.interp(v, old.speed_bp, old.angle_v))
      ceil = LL.panda_rate_ceiling(v, up)
      start = 5.0  # away from the 0 corner
      out = apply_std_steer_angle_limits(start + 1e3 if up else start - 1e3, start, v, OLD)
      step = abs(out - start)
      assert step == pytest.approx(min(cur, ceil), abs=1e-6), (v, up)
      assert step <= cur + 1e-9


def test_old_windows_existed_and_new_ones_are_closed():
  # panda accepts a step of at most int(interp(v-1)*10 + 1) counts; host steps are rounded to 0.1 deg counts
  old_open, new_open = 0, 0
  for v in SPEEDS:
    for up, tbl in ((True, LL.PANDA_RATE_UP), (False, LL.PANDA_RATE_DOWN)):
      allowed = int(np.interp(v - 1.0, LL.PANDA_RATE_SPEED_BP, tbl) * 10 + 1.)
      lim = OLD.ANGLE_RATE_LIMIT_UP if up else OLD.ANGLE_RATE_LIMIT_DOWN
      old_counts = round(float(np.interp(v, lim.speed_bp, lim.angle_v)) * 10)
      new_counts = round(min(float(np.interp(v, lim.speed_bp, lim.angle_v)), LL.panda_rate_ceiling(v, up)) * 10)
      old_open += old_counts > allowed
      new_open += new_counts > allowed
      assert new_counts <= allowed - 1 or LL.panda_rate_ceiling(v, up) >= float(np.interp(v, lim.speed_bp, lim.angle_v)), (v, up)
  assert old_open > 0, "the old host tables must have had a window (otherwise this change is a no-op)"
  assert new_open == 0


def test_measured_wheel_clip_helper():
  assert LL.clip_to_measured_wheel(90.0, 3.0) == 23.0
  assert LL.clip_to_measured_wheel(-90.0, 3.0) == -17.0
  assert LL.clip_to_measured_wheel(10.0, 3.0) == 10.0


def _plan(req, meas, last, v, v_raw=None):
  return build_actuator_plan(0, True, False, True, True, False, meas, req, last, v, 0.0, 0, __import__("collections").deque(), False,
                             chassis_das_only=True, epas_error="EAC_ERROR_IDLE", eac_fault=False, hands_on_level=0,
                             eac_status="EAC_ACTIVE", v_ego_raw=v_raw)


def _plan_angle(*a, **k):
  return _plan(*a, **k).steer.angle_deg


def test_ap1_plan_keeps_its_20_deg_clip_and_adds_the_bound():
  # slow: bound is not binding, +-20 around the wheel still is
  assert _plan_angle(200.0, 0.0, 19.5, 5.0, 5.0) == pytest.approx(20.0, abs=1e-6)
  # 45 mph: bound 27.7 deg binds before the wheel clip allows 40 (wheel at 20, request 80, last just under the bound so the rate step is not the limit)
  v = 45 * 0.44704
  out = _plan_angle(80.0, 20.0, 27.7, v, v)
  assert out == pytest.approx(LL.max_lat_accel_angle_deg(v), abs=1e-6)
  # measured wheel outside the bound: the command is pulled back inside, never beyond the bound
  out = _plan_angle(80.0, 40.0, 40.0, v, v)
  assert abs(out) <= LL.max_lat_accel_angle_deg(v) + 1e-9
  assert _plan_angle(-80.0, -20.0, -27.7, v, v) == pytest.approx(-LL.max_lat_accel_angle_deg(v), abs=1e-6)


def test_ap1_plan_uses_the_trimmed_rate():
  for v in (3.0, 8.0, 15.0, 25.0):
    out = _plan_angle(1.0 + 100.0, 0.0, 1.0, v, v)
    assert abs(out - 1.0) <= LL.panda_rate_ceiling(v, True) + 1e-9, v


# ---------------- Pre-AP: +-20 deg clip against the measured wheel, end to end through the controller ----------------
def _decode_488(dat):
  return (((dat[0] & 0x7F) << 8 | dat[1]) - 16384) * 0.1


def test_preap_controller_clips_to_20_deg_of_the_wheel_and_to_the_bound():
  from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
  from opendbc.car.tesla_ap1.tests import test_preap_carstate_controller as T
  from opendbc.car.tesla_ap1.values import DBC, CAR
  for v_kph, target in ((50.0, 20.0), (130.0, None)):
    T.CLOCK[0] = 1000.0
    T.calib.apply_calibration_result(T.calib.compute_calibration(0.8, 107.0))
    T.params.set_bool(T.params.PreApParamKeys.DOUBLE_PULL, False)
    rig = T.Rig()
    ctl = PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP)
    angles, op_enabled = [], False
    for n in range(400):
      T._pedal_frame(rig, n)
      out = rig.frame(stalk=T.PULL if n == 20 else 0, op=op_enabled, v_kph=v_kph)
      rig.cs.out = out
      enable_req = rig.cs.update_button_enable(out.buttonEvents)
      op_enabled = bool(op_enabled and out.cruiseState.enabled) or bool(enable_req and out.cruiseState.available)
      act = structs.CarControl.Actuators.new_message(accel=0.0, steeringAngleDeg=150.0 if n >= 40 else 0.0)
      cc = structs.CarControl.new_message(enabled=op_enabled, latActive=op_enabled, longActive=False, actuators=act).as_reader()
      _, sends = ctl.update(cc, rig.cs, rig.nanos)
      for sd in sends:
        addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
        if addr == 0x488 and (dat[2] >> 6) == 1:
          angles.append(abs(_decode_488(dat)))
    assert angles, "never engaged"
    bound = LL.max_lat_accel_angle_deg(v_kph / 3.6)
    wheel = 0.0  # the rig's wheel stays at 0, so the clip is +-20 around it
    assert max(angles) <= min(20.0 + wheel, bound) + 0.11, (v_kph, max(angles))
    assert max(angles) >= min(20.0, bound) - 0.5, (v_kph, max(angles))


# ---------------- libsafety cross-checks: host never above the real panda, with margin ----------------
cffi = pytest.importorskip("cffi")
from opendbc.safety.tests import test_tesla_lateral_limits_stage1 as P  # noqa: E402

PLATFORMS = ((P.AP1, P.ap1_speed), (P.PREAP, P.preap_speed))


def _panda_accepts(cls, speed, wheel_counts, cmd_counts):
  cls.setup_car(speed, wheel_counts / 10.0)
  return cls.tx(cmd_counts)


def _panda_max_angle_counts(cls, speed):
  lo, hi = 0, 3600  # lo accepted (0 is always inside), hi bound of search
  if _panda_accepts(cls, speed, hi, hi):
    return hi
  while hi - lo > 1:
    mid = (lo + hi) // 2
    if _panda_accepts(cls, speed, mid, mid):
      lo = mid
    else:
      hi = mid
  return lo


@pytest.mark.parametrize("param,_enc", PLATFORMS)
def test_host_bound_is_below_the_panda_bound_everywhere(param, _enc):
  cls = P.Base()
  cls.PARAM = param
  worst = 1e9
  for v in SPEEDS:
    if v < 2.0:
      continue
    p = _panda_max_angle_counts(cls, v)
    host = LL.max_lat_accel_angle_deg(v)
    assert host * 10 <= p - 2 or (host == 360.0 and p == 3600), (param, v, host, p)
    # a command exactly on the host bound (rounded to 0.1 deg) is accepted
    assert _panda_accepts(cls, v, int(host * 10), int(host * 10)), (param, v)
    if host < 360.0:
      worst = min(worst, p / 10.0 - host)
  assert worst >= 0.2


@pytest.mark.parametrize("param,_enc", PLATFORMS)
def test_host_rate_steps_are_accepted_by_the_panda_and_old_windows_are_refused(param, _enc):
  cls = P.Base()
  cls.PARAM = param
  closed_windows = 0
  for v in (0.9, 1.0, 1.2, 1.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 15.0, 17.0, 18.0, 20.0, 25.0):
    bound_c = int(LL.max_lat_accel_angle_deg(v) * 10) - 15
    base = 50  # 5.0 deg: both signs of every window are away from the 0 corner
    if base + 120 > bound_c:
      continue
    for sign in (1, -1):
      for up in (True, False):
        # up = moving away from 0 on the current side
        tbl_new = LL.panda_rate_ceiling(v, up)
        lim = OLD.ANGLE_RATE_LIMIT_UP if up else OLD.ANGLE_RATE_LIMIT_DOWN
        old_step = float(np.interp(v, lim.speed_bp, lim.angle_v))
        for step, must_accept in ((min(tbl_new, old_step), True), (old_step, None)):
          counts = round(step * 10)
          target = sign * (base + counts if up else base - counts)
          ok = _panda_accepts(cls, v, sign * base, target)
          if must_accept:
            assert ok, (param, v, sign, up, step)
          elif not ok:
            closed_windows += 1
  # the old host tables only exceeded the panda allowance below ~1.7 m/s (calc); above that the trim just adds the CAN-step margin
  assert closed_windows > 0, "expected the panda to refuse the old host step somewhere (the window this change closes)"
