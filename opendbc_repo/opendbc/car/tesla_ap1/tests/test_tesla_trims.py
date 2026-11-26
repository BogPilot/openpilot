"""Tesla trim profiles (trims.py): the sourced table, CAN detection, the picker list, the profile, the front-motor regen
sum and the measured rpm per m/s in the regen math, and the carstate wiring (0x186)."""
import math
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1 import regen_aware as ra
from opendbc.car.tesla_ap1 import trims as T
from opendbc.car.tesla_ap1.values import CAR

S_FP, X_FP, P_FP = "TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"
MPH = 0.44704


# ---------------------------------------------------------------- table
def test_table_values_are_the_tesla_manual_weights():
  expect = {  # key: (curb lb, curb kg) exactly as Tesla prints them
    "S60": (4407, 1999), "S60_2016": (4469, 2027), "S70": (4469, 2027), "S75": (4469, 2027), "S85": (4630, 2100),
    "SP85": (4630, 2100), "SP85PLUS": (4630, 2100), "S60D": (4647, 2108), "S70D": (4647, 2108), "S75D": (4647, 2108),
    "S85D": (4848, 2199), "S90D": (4736, 2148), "S100D": (4883, 2215), "SP85D": (4963, 2251), "SP85DL": (4963, 2251),
    "SP90D": (4841, 2196), "SP90DL": (4841, 2196), "SP100DL": (4941, 2241), "X60D": (5185, 2352), "X75D": (5185, 2352),
    "X90D": (5267, 2389), "X100D": (5421, 2459), "XP90D": (5377, 2439), "XP90DL": (5377, 2439), "XP100DL": (5483, 2487),
  }
  for key, (lb, kg) in expect.items():
    t = T.TRIM_BY_KEY[key]
    assert (t.curb_lb, t.curb_kg) == (lb, kg), key
    assert abs(lb * 0.45359237 - kg) < 1.0, key          # lb and kg agree
    assert t.mass_kg == kg + 136.0                        # mass = curb + 136 kg
  assert T.TRIM_BY_KEY["S40"].curb_kg is None and T.TRIM_BY_KEY["S40"].mass_kg is None   # Tesla published none
  assert set(expect) | {"S40"} == set(T.TRIM_BY_KEY)


def test_table_layout_flags():
  for t in T.TRIMS:
    if t.chassis == "X":
      assert t.dual                                       # every Model X is dual motor
    assert t.ludicrous == ("Ludicrous" in t.label)
    if t.ludicrous:
      assert t.dual and t.perf_rear                       # Ludicrous only on P dual cars
    assert t.source
  assert not any(t.key in ("SP70D", "SP75D") for t in T.TRIMS)   # never existed


def test_platform_lists():
  preap = [t.key for t in T.platform_trims(P_FP)]
  assert preap == ["S40", "S60", "S85", "SP85", "SP85PLUS"]
  assert all(not T.TRIM_BY_KEY[k].dual for k in preap)
  assert all(t.chassis == "X" for t in T.platform_trims(X_FP))
  assert all(t.chassis == "S" for t in T.platform_trims(S_FP)) and "S40" not in [t.key for t in T.platform_trims(S_FP)]
  assert T.platform_trims("TESLA_MODEL_3") == []


# ---------------------------------------------------------------- picker
def test_picker_filters_on_detection():
  x_p = T.picker_keys(X_FP, T.Detected("X", T.LAYOUT_DUAL, T.PERF_YES))
  assert x_p == ["Auto", "XP90D", "XP90DL", "XP100DL"]
  x_n = T.picker_keys(X_FP, T.Detected("X", T.LAYOUT_DUAL, T.PERF_NO))
  assert x_n == ["Auto", "X60D", "X75D", "X90D", "X100D"]
  s_n = T.picker_keys(S_FP, T.Detected("S", T.LAYOUT_DUAL, T.PERF_NO))
  assert s_n == ["Auto", "S60D", "S70D", "S75D", "S85D", "S90D", "S100D"]
  s_rwd = T.picker_keys(S_FP, T.Detected("S", T.LAYOUT_SINGLE))
  assert s_rwd == ["Auto", "S60", "S60_2016", "S70", "S75", "S85", "SP85", "SP85PLUS"]
  s_dual_unmeasured = T.picker_keys(S_FP, T.Detected("S", T.LAYOUT_DUAL))
  assert set(s_dual_unmeasured[1:]) == {t.key for t in T.TRIMS if t.chassis == "S" and t.dual}
  assert T.picker_keys(S_FP, T.Detected()) == ["Auto"] + [t.key for t in T.platform_trims(S_FP)]   # never driven: all


def test_saved_trim_that_contradicts_is_kept_and_listed():
  det = T.Detected("X", T.LAYOUT_DUAL, T.PERF_YES)
  keys = T.picker_keys(X_FP, det, saved="X90D")
  assert keys[:2] == ["Auto", "X90D"]
  p = T.profile_for(X_FP, "X90D", det)
  assert p.mismatch and not p.trim_used and p.mass_kg == T.BASE_MASS_KG[X_FP]   # CAN wins, base mass
  assert p.trim == "X90D"                                                     # never rewritten


def test_trim_file_roundtrip(tmp_path):
  path = tmp_path / "TeslaTrim"
  assert T.read_trim("") == "Auto" and T.read_trim(b" XP90DL\n") == "XP90DL"
  T.write_trim("SP90DL", path=path)
  assert path.read_text() == "SP90DL"
  with pytest.raises(KeyError):
    T.write_trim("P70D", path=path)
  assert T.read_trim("garbage") == "garbage"                  # kept as is; profile treats it as Auto
  assert T.profile_for(S_FP, "garbage", T.Detected("S", T.LAYOUT_DUAL, T.PERF_NO)).mass_kg == 2100.0


def test_detected_roundtrip(tmp_path):
  path = tmp_path / "TeslaTrimDetected"
  d = T.Detected("X", T.LAYOUT_DUAL, T.PERF_YES, 250.1, 244.0)
  assert T.write_detected(d, path) is True
  assert T.write_detected(d, path) is False                   # unchanged: no write
  assert T.read_detected(path=path) == d
  assert T.read_detected("{not json") == T.Detected()
  assert T.read_detected('{"chassis": "Y", "layout": 9}') == T.Detected()
  assert T.read_detected('{"chassis": "S", "layout": 1, "rear_rpm_per_ms": 9999}').rear_rpm_per_ms == T.RPM_PER_MS_MAX


def test_detected_text():
  assert T.detected_text(T.Detected("X", 2, 2), X_FP) == "Model X, dual motor, Performance rear (from CAN)"
  assert T.detected_text(T.Detected("S", 2, 1), S_FP) == "Model S, dual motor, standard rear (from CAN)"
  assert T.detected_text(T.Detected("S", 1, 0), P_FP) == "Model S, single motor (from CAN)"
  assert "drive the car once" in T.detected_text(T.Detected(), S_FP)
  assert T.detected_text(T.Detected(), "") == "Not detected yet"


# ---------------------------------------------------------------- profile
def test_auto_profile_keeps_base_tune():
  s = T.profile_for(S_FP, "Auto", T.Detected())
  assert s.mass_kg == 2100.0 and s.regen_peak_kw is None and s.layout == T.LAYOUT_UNKNOWN
  assert s.rear_rpm_per_ms == pytest.approx(9.73 * 60 / (2 * math.pi * 0.35))     # the old constants until detected
  x = T.profile_for(X_FP, "Auto", T.Detected())
  assert x.mass_kg == 2400.0 and x.layout == T.LAYOUT_DUAL and x.regen_peak_kw == 71.6 and x.rear_rpm_per_ms == 249.9
  p = T.profile_for(P_FP, "Auto", T.Detected())
  assert p.mass_kg == 2100.0 and p.layout == T.LAYOUT_SINGLE and p.front_rpm_per_ms is None and p.regen_peak_kw is None


def test_picked_trim_mass_and_seeds():
  p = T.profile_for(X_FP, "XP90DL", T.Detected("X", T.LAYOUT_DUAL, T.PERF_YES))
  assert p.trim_used and p.mass_kg == 2439 + 136 and p.perf == T.PERF_YES
  assert p.rear_rpm_per_ms * MPH == pytest.approx(111.8) and p.front_rpm_per_ms * MPH == pytest.approx(109.1)
  s = T.profile_for(S_FP, "S90D", T.Detected("S", T.LAYOUT_DUAL, T.PERF_NO))
  assert s.mass_kg == 2148 + 136 and s.regen_peak_kw == 53.1
  assert s.rear_rpm_per_ms * MPH == pytest.approx(115.1) and s.front_rpm_per_ms * MPH == pytest.approx(114.9)
  # a learned value from the last drive wins over the class seed (clamped)
  learned = T.profile_for(S_FP, "S90D", T.Detected("S", T.LAYOUT_DUAL, T.PERF_NO, 257.0, 256.0))
  assert learned.rear_rpm_per_ms == 257.0 and learned.front_rpm_per_ms == 256.0
  # S40: no published weight -> base mass, not a guess
  assert T.profile_for(P_FP, "S40", T.Detected("S", 1)).mass_kg == 2100.0
  # a trim fills in the Performance rear before CAN measured it
  assert T.profile_for(S_FP, "SP90DL", T.Detected("S", T.LAYOUT_DUAL)).perf == T.PERF_YES
  # a detection saved for the other chassis is ignored
  assert T.profile_for(S_FP, "Auto", T.Detected("X", 2, 2, 250.0, 244.0)).layout == T.LAYOUT_UNKNOWN


def test_derived_seeds_are_gear_ratio_scaled_measurements():
  assert T.DERIVED_RPM_PER_MPH[("S", 2, 2)][0] == pytest.approx(115.1 * 9.734 / 9.325, abs=0.05)
  assert T.DERIVED_RPM_PER_MPH[("X", 2, 1)][0] == pytest.approx(111.8 * 9.325 / 9.734, abs=0.05)
  for (rear, front) in list(T.MEASURED_RPM_PER_MPH.values()) + list(T.DERIVED_RPM_PER_MPH.values()):
    assert T.RPM_PER_MS_MIN <= rear / MPH <= T.RPM_PER_MS_MAX
    assert front is None or T.RPM_PER_MS_MIN <= front / MPH <= T.RPM_PER_MS_MAX


def test_clamps():
  assert T.clamp_rpm_per_ms(100) == T.RPM_PER_MS_MIN and T.clamp_rpm_per_ms(1e6) == T.RPM_PER_MS_MAX
  assert T.clamp_rpm_per_ms(float("nan")) is None and T.clamp_rpm_per_ms(-5) is None and T.clamp_rpm_per_ms("x") is None
  assert 227 < T.RPM_PER_MS_MIN < 229 and 271 < T.RPM_PER_MS_MAX < 273


# ---------------------------------------------------------------- detection
def _drive(det, seconds, v, rear_mph, front_mph=None, fwd=None, front=True):
  for _ in range(int(seconds / 0.01)):
    det.update(v, v / MPH * rear_mph, None if front_mph is None else v / MPH * front_mph,
               front and front_mph is not None, fwd)


def test_detects_x_performance_dual():
  d = T.DriveDetector(X_FP, 0.01)
  _drive(d, 5.0, 22.0, 111.8, 109.1, fwd=1)
  assert d.layout == T.LAYOUT_DUAL and d.perf == T.PERF_YES and d.measured
  assert d.rear_k * MPH == pytest.approx(111.8, rel=1e-3) and d.front_k * MPH == pytest.approx(109.1, rel=1e-3)


def test_detects_s_standard_dual():
  d = T.DriveDetector(S_FP, 0.01)
  _drive(d, 5.0, 22.0, 115.1, 114.9, fwd=1)
  assert d.layout == T.LAYOUT_DUAL and d.perf == T.PERF_NO


def test_detects_single_motor_after_moving_without_0x186():
  d = T.DriveDetector(S_FP, 0.01)
  _drive(d, 4.0, 10.0, 120.1)
  assert d.layout == T.LAYOUT_UNKNOWN                 # not yet: 4 s moving
  _drive(d, 1.5, 10.0, 120.1)
  assert d.layout == T.LAYOUT_SINGLE and d.perf == T.PERF_UNKNOWN and math.isnan(d.front_k)
  parked = T.DriveDetector(S_FP, 0.01)
  _drive(parked, 30.0, 0.0, 0.0)
  assert parked.layout == T.LAYOUT_UNKNOWN            # standing still never decides single


def test_four_wheel_drive_config_alone_marks_dual():
  d = T.DriveDetector(S_FP, 0.01)
  d.update(0.0, 0.0, None, False, 1)
  assert d.layout == T.LAYOUT_DUAL and d.perf == T.PERF_UNKNOWN


def test_preap_is_single_from_the_start():
  d = T.DriveDetector(P_FP, 0.01, front_possible=False)
  assert d.layout == T.LAYOUT_SINGLE
  _drive(d, 5.0, 20.0, 120.1)
  assert d.measured and d.rear_k * MPH == pytest.approx(120.1, rel=1e-3)


def test_learning_ignores_low_speed_sna_and_outliers():
  d = T.DriveDetector(S_FP, 0.01)
  seed = d.rear_k
  for _ in range(1000):
    d.update(5.0, 5.0 / MPH * 115.1, None, False, None)    # below K_MIN_SPEED
    d.update(20.0, -32768.0, None, False, None)            # SNA
  assert d.rear_k == seed and not d.measured
  _drive(d, 5.0, 20.0, 115.1, front=False)
  k = d.rear_k
  d.update(20.0, 20.0 / MPH * 115.1 * 1.3, None, False, None)   # 30 % off: slip / bad frame
  assert d.rear_k == k


# ---------------------------------------------------------------- regen math
def test_regen_sum_and_measured_ratio():
  car = ra.regen_car(X_FP, T.profile_for(X_FP, "XP90DL", T.Detected("X", 2, 2)))
  assert car.mass_kg == 2575.0 and car.p_nominal_kw == ra.MODELX_P_NOMINAL_KW == 51.1
  k_r, k_f = 250.0, 244.0
  rear_only = ra.regen_decel_from_torque(-100.0, car, rpm_per_ms=k_r)
  assert rear_only == pytest.approx(100.0 * k_r * 2 * math.pi / 60 / 2575.0)
  both = ra.regen_decel_from_torque(-100.0, car, front_torque_nm=-50.0, rpm_per_ms=k_r, front_rpm_per_ms=k_f)
  assert both == pytest.approx((100.0 * k_r + 50.0 * k_f) * 2 * math.pi / 60 / 2575.0)
  # front SNA / NaN / drive torque add nothing
  assert ra.regen_decel_from_torque(-100.0, car, front_torque_nm=-1024.0, rpm_per_ms=k_r) == rear_only
  assert ra.regen_decel_from_torque(-100.0, car, front_torque_nm=float("nan"), rpm_per_ms=k_r) == rear_only
  assert ra.regen_decel_from_torque(-100.0, car, front_torque_nm=30.0, rpm_per_ms=k_r) == rear_only
  # power: each motor's torque x its own rpm
  assert ra.regen_power_kw(-100.0, 5000.0, -60.0, 4900.0) == pytest.approx((100 * 5000 + 60 * 4900) * 2 * math.pi / 60000)
  assert ra.regen_power_kw(-100.0, 5000.0) == pytest.approx(100 * 5000 * 2 * math.pi / 60000)


def test_regen_car_without_profile_is_unchanged_for_the_s():
  assert ra.regen_car(S_FP) is ra.MODEL_S
  car = ra.MODEL_S
  assert ra.regen_decel_from_torque(-100.0, car) == pytest.approx(100.0 * 9.73 / 0.35 / 2100.0)   # old constants
  single = ra.regen_car(S_FP, T.profile_for(S_FP, "Auto", T.Detected("S", 1)))
  assert single.p_nominal_kw == 30.0 and single.mass_kg == 2100.0
  dual = ra.regen_car(S_FP, T.profile_for(S_FP, "S90D", T.Detected("S", 2, 1)))
  assert dual.p_nominal_kw == round(53.1 * 30 / 42, 1) == 37.9 and dual.mass_kg == 2284.0


def test_estimator_counts_front_regen_before_calling_it_limited():
  car = ra.regen_car(X_FP, T.profile_for(X_FP, "Auto", T.Detected("X", 2, 2)))
  rear_only = ra.RegenPowerEstimator(car=car)
  both = ra.RegenPowerEstimator(car=car)
  for _ in range(300):   # 3 s: request 1.2 m/s^2; rear 60 Nm alone is short of it, front + rear is not
    rear_only.update(15.0, -1.2, -60.0, 3750.0, 20.0, 0.01, rpm_per_ms=250.0)
    both.update(15.0, -1.2, -60.0, 3750.0, 20.0, 0.01, front_torque_nm=-110.0, front_rpm=3660.0, rpm_per_ms=250.0,
                front_rpm_per_ms=244.0)
  assert rear_only.limited and not both.limited


# ---------------------------------------------------------------- carstate wiring
def _cs(fp):
  from opendbc.car.tesla_ap1.carstate import CarState
  cp = SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=False)
  return CarState(cp), CarState.get_can_parsers(cp)


def test_carstate_subscribes_0x186_and_0x398_without_can_valid_effect():
  for fp in (CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX):
    _state, parsers = _cs(fp)
    chassis = parsers[Bus.chassis]
    assert 0x186 in chassis.message_states and 0x398 in chassis.message_states
    assert math.isnan(chassis.message_states[0x186].frequency) or chassis.message_states[0x186].frequency == 0


def test_dbc_front_frame_decodes_like_0x108():
  packer = CANPacker("tesla_ap1_can")
  addr, dat, _ = packer.make_can_msg("DI_torque1Front", 0, {"DI_torqueMotorFront": -55.25, "DI_motorRPMFront": 4321})
  assert addr == 0x186 and len(dat) == 7
  from opendbc.can import CANParser
  p = CANParser("tesla_ap1_can", [("DI_torque1Front", float("nan"))], 0)
  p.update([(int(1e9), [(addr, dat, 0)])])
  assert p.vl["DI_torque1Front"]["DI_torqueMotorFront"] == -55.25 and p.vl["DI_torque1Front"]["DI_motorRPMFront"] == 4321


def _send_at(parser, name, values, nanos):
  addr, dat, _ = CANPacker("tesla_ap1_can").make_can_msg(name, parser.bus, values)
  parser.update([(int(nanos), [(addr, dat, parser.bus)])])


def test_carstate_publishes_front_motor_and_layout():
  state, parsers = _cs(CAR.TESLA_AP1_MODELX)
  chassis = parsers[Bus.chassis]
  out = state.update(parsers).bogpilot
  assert math.isnan(out.ap1FrontMotorTorqueNm) and math.isnan(out.ap1FrontMotorRpm)
  assert out.ap1DriveLayout == T.LAYOUT_DUAL               # every X is dual before any frame
  _send_at(chassis, "DI_torque1Front", {"DI_torqueMotorFront": -40.0, "DI_motorRPMFront": 3000}, 1e9)
  out = state.update(parsers).bogpilot
  assert out.ap1FrontMotorTorqueNm == -40.0 and out.ap1FrontMotorRpm == 3000.0 and out.ap1DriveLayout == T.LAYOUT_DUAL
  _send_at(chassis, "GTW_carConfig", {}, 1.5e9)            # 0x186 now 0.5 s old: stale -> NaN
  out = state.update(parsers).bogpilot
  assert math.isnan(out.ap1FrontMotorTorqueNm)


def test_carstate_s_without_0x186_stays_unknown_while_parked():
  state, parsers = _cs(CAR.TESLA_AP1_MODELS)
  out = state.update(parsers).bogpilot
  assert out.ap1DriveLayout == T.LAYOUT_UNKNOWN and math.isnan(out.ap1FrontMotorTorqueNm)
  assert out.ap1RearRpmPerMs == pytest.approx(T.LEGACY_RPM_PER_MS["S"]) and not out.ap1RpmPerMsMeasured
