"""Dashboard limit base-map guard (speed_limit.py dashboard_speed_limit_ms, carstate.py base_map_guard_args).

The car reported fused and GTW map / mpp limits of 55 while its own base map limit (UI_baseMapSpeedLimitMPS) read 0
and the camera-only limit (DAS_visionOnlySpeedLimit) still read 25. The guard returns the camera limit there.
"""
import itertools
import math
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1 import speed_limit as sl
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.speed_limit import LIMIT_MAX_AGE_S, dashboard_speed_limit_ms
from opendbc.car.tesla_ap1.values import CAR

MPH = CV.MPH_TO_MS
KPH = CV.KPH_TO_MS
UI_55 = 12   # UI_mapSpeedLimit enum: 12 = 55
UI_25 = 6
UI_65 = 14
BASE_25_MS = 24.6 * MPH
PACKER = CANPacker("tesla_ap1_can")


def mph(ms):
  return ms / MPH


# ---- the function ----

def test_fused_55_vision_25_base_map_0_gives_25_never_55():
  for base in (0.0, None):
    out = dashboard_speed_limit_ms(55, UI_55, 55, 0, vision_phys=25, base_map_ms=base, hold_ms=25 * MPH)
    assert mph(out) == pytest.approx(25.0, abs=1e-3), base


def test_real_rise_with_the_base_map_known_is_accepted():
  out = dashboard_speed_limit_ms(55, UI_55, 55, 0, vision_phys=25, base_map_ms=BASE_25_MS * 55 / 24.6, hold_ms=25 * MPH)
  assert mph(out) == pytest.approx(55.0, abs=1e-3)
  # The base map knows the road (any value > 0): the camera limit is not consulted.
  out = dashboard_speed_limit_ms(55, UI_55, 55, 0, vision_phys=25, base_map_ms=BASE_25_MS)
  assert mph(out) == pytest.approx(55.0, abs=1e-3)


def test_camera_agrees_or_is_within_the_tolerance():
  assert mph(dashboard_speed_limit_ms(55, UI_55, 55, 0, vision_phys=55, base_map_ms=0.0)) == pytest.approx(55.0, abs=1e-3)
  assert mph(dashboard_speed_limit_ms(35, UI_25, 25, 0, vision_phys=25, base_map_ms=0.0)) == pytest.approx(35.0, abs=1e-3)
  assert mph(dashboard_speed_limit_ms(40, UI_25, 25, 0, vision_phys=25, base_map_ms=0.0)) == pytest.approx(25.0, abs=1e-3)


@pytest.mark.parametrize("base", [0.0, None, BASE_25_MS])
def test_lower_limits_always_win(base):
  # A lower fused / map limit than the camera limit is never raised to the camera limit.
  assert mph(dashboard_speed_limit_ms(25, UI_55, 55, 0, vision_phys=55, base_map_ms=base)) == pytest.approx(25.0, abs=1e-3)
  assert mph(dashboard_speed_limit_ms(None, UI_25, 25, 0, vision_phys=55, base_map_ms=base)) == pytest.approx(25.0, abs=1e-3)
  # Map-only with no camera limit: a value below the held limit is taken at once.
  assert mph(dashboard_speed_limit_ms(None, UI_25, 25, 0, vision_phys=None, base_map_ms=base, hold_ms=45 * MPH)) == \
    pytest.approx(25.0, abs=1e-3)


def test_base_map_unknown_and_no_camera_limit_ignores_map_only_values():
  for vision in (None, 0, 155):   # stale, UNKNOWN_SNA, NONE
    out = dashboard_speed_limit_ms(None, UI_55, 55, 0, vision_phys=vision, base_map_ms=0.0, hold_ms=25 * MPH)
    assert mph(out) == pytest.approx(25.0, abs=1e-3), vision
    # nothing held yet: the map value, as the previous rule, never 0 (0 would hand over to the SLC fallback)
    out = dashboard_speed_limit_ms(None, UI_55, 55, 0, vision_phys=vision, base_map_ms=None, hold_ms=0.0)
    assert mph(out) == pytest.approx(55.0, abs=1e-3), vision
  # The base map known: map-only values are used as before.
  out = dashboard_speed_limit_ms(None, UI_55, 55, 0, vision_phys=None, base_map_ms=BASE_25_MS, hold_ms=25 * MPH)
  assert mph(out) == pytest.approx(55.0, abs=1e-3)
  # A fused limit with no camera limit is not map-only: unchanged.
  out = dashboard_speed_limit_ms(55, UI_55, 55, 0, vision_phys=None, base_map_ms=0.0, hold_ms=25 * MPH)
  assert mph(out) == pytest.approx(55.0, abs=1e-3)


def test_metric_tolerance_is_15_kph():
  out = dashboard_speed_limit_ms(80, None, None, 1, vision_phys=60, base_map_ms=0.0)
  assert out == pytest.approx(60 * KPH, abs=1e-3)
  out = dashboard_speed_limit_ms(75, None, None, 1, vision_phys=60, base_map_ms=0.0)
  assert out == pytest.approx(75 * KPH, abs=1e-3)


def test_bad_hold_values_are_no_hold():
  for hold in (None, float("nan"), float("inf"), -5.0, "x"):
    out = dashboard_speed_limit_ms(None, UI_55, 55, 0, base_map_ms=0.0, hold_ms=hold)
    assert mph(out) == pytest.approx(55.0, abs=1e-3), hold


@pytest.mark.parametrize("hold", [0.0, -1.0, None, float("nan")])
def test_nothing_held_returns_the_map_limit_not_zero(hold):
  # no camera limit, base map unknown (0) or stale (None), map / mpp-only value, nothing held
  for base, vision, (ui, mpp, want) in itertools.product((0.0, None), (None, 0, 155),
                                                       ((UI_25, 25, 25.0), (None, 25, 25.0), (UI_55, None, 55.0))):
    out = dashboard_speed_limit_ms(None, ui, mpp, 0, vision_phys=vision, base_map_ms=base, hold_ms=hold)
    assert out > 0.0 and out == pytest.approx(_legacy(None, ui, mpp, 0)), (base, vision, ui, mpp, hold)
    assert mph(out) == pytest.approx(want, abs=1e-3)


def test_the_25_to_55_rise_with_25_held_is_still_caught():
  for base, vision in itertools.product((0.0, None), (None, 0, 155)):
    out = dashboard_speed_limit_ms(None, UI_55, 55, 0, vision_phys=vision, base_map_ms=base, hold_ms=25 * MPH)
    assert mph(out) == pytest.approx(25.0, abs=1e-3), (base, vision)
  out = dashboard_speed_limit_ms(55, UI_55, 55, 0, vision_phys=25, base_map_ms=0.0, hold_ms=0.0)   # camera says 25
  assert mph(out) == pytest.approx(25.0, abs=1e-3)


def _legacy(fused_phys, ui_map_code, mpp_phys, units):
  """dashboard_speed_limit_ms as it was before the guard (copied)."""
  metric = sl.units_are_metric(units)
  fused = sl.fused_speed_limit_ms(fused_phys, metric)
  map_limit = sl.ui_map_speed_limit_ms(ui_map_code, metric) or sl.mpp_speed_limit_ms(mpp_phys, metric)
  if fused > 0.0 and map_limit > 0.0:
    rise = sl.IMPLAUSIBLE_RISE_KPH if metric else sl.IMPLAUSIBLE_RISE_MPH
    floor = sl.MIN_MAP_CHECK_KPH if metric else sl.MIN_MAP_CHECK_MPH
    if map_limit >= sl._uom_to_ms(floor, metric) - 1e-3 and fused - map_limit > sl._uom_to_ms(rise, metric) + 1e-3:
      return map_limit
  for value in (fused, sl.ui_map_speed_limit_ms(ui_map_code, metric), sl.mpp_speed_limit_ms(mpp_phys, metric)):
    if value > 0.0:
      return value
  return 0.0


FUSED = [None, 0, 5, 15, 25, 55, 80, 150, 155, "x"]
UIMAP = [None, 0, 1, 6, 12, 14, 30, 31, 40]
MPP = [None, 0, 25, 55, 155, float("nan")]
UNITS = [None, 0, 1]


def test_legacy_callers_unchanged():
  """Four-argument callers (Pre-AP carstate, older tests) and callers without base_map_ms get the old result."""
  for f, u, m, un in itertools.product(FUSED, UIMAP, MPP, UNITS):
    want = _legacy(f, u, m, un)
    assert dashboard_speed_limit_ms(f, u, m, un) == want, (f, u, m, un)
    assert dashboard_speed_limit_ms(f, u, m, un, vision_phys=25, hold_ms=10.0) == want, (f, u, m, un)


def test_guard_never_raises_the_old_result():
  for f, u, m, un in itertools.product(FUSED, UIMAP, MPP, UNITS):
    want = _legacy(f, u, m, un)
    for vision, base, hold in itertools.product([None, 0, 25, 55, 155], [None, 0.0, BASE_25_MS], [0.0, 25 * MPH, 70 * MPH]):
      out = dashboard_speed_limit_ms(f, u, m, un, vision_phys=vision, base_map_ms=base, hold_ms=hold)
      assert math.isfinite(out) and out >= 0.0
      # The guard only returns the old value or a camera / held value below it; never 0 where the old rule has a limit.
      assert out <= want + 1e-6 or out == pytest.approx(hold), (f, u, m, un, vision, base, hold)
      assert not (want > 0.0 and out == 0.0), (f, u, m, un, vision, base, hold)
      if base is not None and base > 0.0:
        assert out == want


# ---- CarState (real CANParser and DBC frames) ----

class Car:
  def __init__(self, fingerprint=CAR.TESLA_AP1_MODELS):
    cp = SimpleNamespace(carFingerprint=fingerprint, openpilotLongitudinalControl=True)
    self.state, self.parsers = CarState(cp), CarState.get_can_parsers(cp)
    self.chassis, self.cam = self.parsers[Bus.chassis], self.parsers[Bus.cam]
    self.t = 0
    self.sign_counter = 0

  def step(self, fused=None, vision=None, ui_map=None, mpp=None, base_mph=None, mux=3):
    """One 10 ms step. base_mph=None: no 0x238 frame this step. mux: UI_roadSign of that frame."""
    self.t += 10_000_000
    chassis, cam = [], []
    if ui_map is not None:
      chassis.append(PACKER.make_can_msg("UI_driverAssistMapData", self.chassis.bus, {"UI_mapSpeedLimit": ui_map}))
    if mpp is not None:
      chassis.append(PACKER.make_can_msg("UI_gpsVehicleSpeed", self.chassis.bus, {"UI_mppSpeedLimit": mpp, "UI_mapSpeedLimitUnits": 0}))
    if base_mph is not None:
      self.sign_counter = (self.sign_counter + 1) % 16
      vals = {"UI_roadSign": mux, "UI_roadSignCounter": self.sign_counter}
      vals["UI_baseMapSpeedLimitMPS" if mux == 3 else "UI_meanFleetSplineSpeedMPS"] = base_mph * MPH
      chassis.append(PACKER.make_can_msg("UI_driverAssistRoadSign", self.chassis.bus, vals))
    if fused is not None:
      cam.append(PACKER.make_can_msg("AutopilotStatus", self.cam.bus, {"DAS_fusedSpeedLimit": fused, "DAS_visionOnlySpeedLimit": vision or 0}))
    self.chassis.update([(self.t, [(a, d, b) for a, d, b in chassis])])
    self.cam.update([(self.t, [(a, d, b) for a, d, b in cam])])
    return mph(self.state.update(self.parsers).bogpilot.dashboardSpeedLimit)


def _the_drive(car, base_after_mph=0.0, n_before=300, n_after=300):
  """25 zone with the base map known, then the base map 0 / GTW map 55, then fused 55 with the camera still 25."""
  out = []
  for i in range(n_before):
    out.append(car.step(fused=25, vision=25, ui_map=UI_25, mpp=25, base_mph=24.6 if i % 40 == 0 else None))
  for i in range(n_after):
    out.append(car.step(fused=25, vision=25, ui_map=UI_55, mpp=55, base_mph=base_after_mph if i % 40 == 0 else None))
  for i in range(n_after):
    out.append(car.step(fused=55, vision=25, ui_map=UI_55, mpp=55, base_mph=base_after_mph if i % 40 == 0 else None))
  return out


@pytest.mark.parametrize("fingerprint", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_carstate_bug_scenario_stays_25(fingerprint):
  out = _the_drive(Car(fingerprint))
  assert max(out) == pytest.approx(25.0, abs=1e-3)
  assert out[-1] == pytest.approx(25.0, abs=1e-3)


def test_carstate_real_rise_with_base_map_known_is_accepted():
  out = _the_drive(Car(), base_after_mph=55.0)
  assert out[-1] == pytest.approx(55.0, abs=1e-3)


def test_carstate_base_map_never_sent_keeps_the_old_result():
  car = Car()
  out = [car.step(fused=25, vision=25, ui_map=UI_25, mpp=25) for _ in range(100)]
  out += [car.step(fused=55, vision=25, ui_map=UI_55, mpp=55) for _ in range(100)]
  assert out[-1] == pytest.approx(55.0, abs=1e-3)
  assert car.state.base_map_guard_args(car.chassis, car.cam) == {}


def test_carstate_stale_base_map_counts_as_unknown():
  car = Car()
  for i in range(300):
    car.step(fused=25, vision=25, ui_map=UI_25, mpp=25, base_mph=24.6 if i % 40 == 0 else None)
  # The base map keeps saying 25 once, then the frame stops for longer than LIMIT_MAX_AGE_S.
  out = [car.step(fused=25, vision=25, ui_map=UI_55, mpp=55) for _ in range(int((LIMIT_MAX_AGE_S + 0.5) / 0.01))]
  out += [car.step(fused=55, vision=25, ui_map=UI_55, mpp=55) for _ in range(100)]
  assert max(out) == pytest.approx(25.0, abs=1e-3)


def test_carstate_fresh_base_map_inside_the_window_still_counts():
  car = Car()
  for i in range(300):
    car.step(fused=25, vision=25, ui_map=UI_25, mpp=25, base_mph=24.6 if i % 40 == 0 else None)
  out = [car.step(fused=55, vision=25, ui_map=UI_55, mpp=55) for _ in range(int((LIMIT_MAX_AGE_S - 0.5) / 0.01))]
  assert out[-1] == pytest.approx(55.0, abs=1e-3)   # map known 25 a moment ago: a real rise, accepted


def test_carstate_other_mux_frames_do_not_set_the_base_map():
  car = Car()
  car.step(fused=25, vision=25, ui_map=UI_25, mpp=25, base_mph=24.6)
  assert mph(car.state.base_map_ms) == pytest.approx(24.5, abs=0.2)
  for mux in (0, 4, 5):
    car.step(fused=25, vision=25, ui_map=UI_25, mpp=25, base_mph=0.0, mux=mux)
    assert mph(car.state.base_map_ms) == pytest.approx(24.5, abs=0.2), mux


def test_carstate_lower_limit_wins_with_base_map_unknown():
  car = Car()
  _the_drive(car)
  out = [car.step(fused=15, vision=25, ui_map=UI_55, mpp=55, base_mph=0.0 if i % 40 == 0 else None) for i in range(50)]
  assert out[-1] == pytest.approx(15.0, abs=1e-3)
