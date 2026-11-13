"""AP1 cruiseState.speed under openpilot long (op_long_set_speed.py), through the real CarState and DBC-packed frames.

DI_cruiseState values from tesla_ap1_can.dbc VAL_ 872: 1 STANDBY, 2 ENABLED, 3 STANDSTILL, 4 OVERRIDE, 6 PRE_FAULT,
7 PRE_CANCEL. SpdCtrlLvr_Stat 4 = UP (accelCruise), 8 = DN (decelCruise) (values.py BUTTONS).
"""
import math
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1.ap1_events import Ap1Events, SPEED_LIMIT_UNKNOWN
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.op_long_set_speed import (TAP_FROM_ZERO_KPH, TAP_WINDOW_S, OpLongSetSpeed,
     format_tap_from_zero_display, parse_tap_from_zero_mph, tap_from_zero_kph_from_param)
from opendbc.car.tesla_ap1.slc_raise import Ap1RaiseHoldoff, ap1_cruise_ms
from opendbc.car.tesla_ap1.speed_limit import LIMIT_MAX_AGE_S, frame_fresh, ui_map_speed_limit_ms
from opendbc.car.tesla_ap1.values import CAR

STANDBY, ENABLED, STANDSTILL, OVERRIDE, PRE_FAULT, PRE_CANCEL = 1, 2, 3, 4, 6, 7
ENGAGED = [ENABLED, STANDSTILL, OVERRIDE, PRE_FAULT, PRE_CANCEL]
MPH = 0  # DI_speedUnits 0 (the MPH branch in carstate.py)
UP, DN, CANCEL, RWD = 4, 8, 1, 2
UP_1ST, DN_1ST = 16, 32
MAP_65 = 14  # UI_mapSpeedLimit enum 14 = 65 mph
V_CRUISE_UNSET = 255

PACKER = CANPacker("tesla_ap1_can")


def _carstate(fingerprint, op_long):
  cp = SimpleNamespace(carFingerprint=fingerprint, openpilotLongitudinalControl=op_long)
  return CarState(cp), CarState.get_can_parsers(cp)


class Car:
  def __init__(self, fingerprint=CAR.TESLA_AP1_MODELS, op_long=True, offset_ms=None):
    self.state, self.parsers = _carstate(fingerprint, op_long)
    if offset_ms is not None:
      self.state.op_long_offset = lambda limit_ms: offset_ms
    self.chassis = self.parsers[Bus.chassis]
    self.t = 0
    self.counter = 0

  def step(self, cruise_state, di_cruise_set_raw, v_kph, units=MPH, map_limit=0, lever=0, map_msg=True):
    """One DI_state + ESP_B (+ map limit, stalk) frame. di_cruise_set_raw is the raw 9-bit DI_cruiseSet (DBC factor 0.5)."""
    self.t += 10_000_000
    self.counter = (self.counter + 1) % 16
    msgs = []
    for name, values in (
      ("DI_state", {"DI_cruiseState": cruise_state, "DI_cruiseSet": di_cruise_set_raw * 0.5,
                    "DI_speedUnits": units, "DI_stateCounter": self.counter}),
      ("ESP_B", {"ESP_vehicleSpeed": v_kph}),
      ("UI_driverAssistMapData", {"UI_mapSpeedLimit": map_limit} if map_msg else None),
      # A map-limit latch also needs a fresh 0x2F8 units frame (unknown units => no limit-based engage set).
      ("UI_gpsVehicleSpeed", {"UI_mapSpeedLimitUnits": MPH} if map_msg else None),
      ("STW_ACTN_RQ", {"SpdCtrlLvr_Stat": lever}),
    ):
      if values is None:
        continue   # message not on the bus this frame (optional, freq 0)
      addr, dat, _bus = PACKER.make_can_msg(name, self.chassis.bus, values)
      msgs.append((addr, dat, self.chassis.bus))
    self.chassis.update([(self.t, msgs)])
    return self.state.update(self.parsers)


def _vcruise(rets):
  """openpilot VCruiseHelper (pcmCruise branch, as AP1 uses) over the CarState outputs."""
  cruise = pytest.importorskip("openpilot.selfdrive.car.cruise")
  helper = cruise.VCruiseHelper(SimpleNamespace(pcmCruise=True))
  out = []
  for ret in rets:
    helper.update_v_cruise(ret, True, False)
    out.append(helper.v_cruise_kph)
  return out


def _events(ret, enabled=False):
  return Ap1Events().update([], enabled, False, ret.bogpilot, False)


def test_dbc_cruise_state_names():
  """The engaged states this change keys on are 2/3/4/6/7 in the DBC (no invented values)."""
  state, _ = _carstate(CAR.TESLA_AP1_MODELS, True)
  dv = state.can_define.dv["DI_state"]["DI_cruiseState"]
  assert [dv[s] for s in [STANDBY] + ENGAGED] == ["STANDBY", "ENABLED", "STANDSTILL", "OVERRIDE", "PRE_FAULT", "PRE_CANCEL"]
  assert state.can_define.dv["DI_state"]["DI_speedUnits"][MPH] == "MPH"


def test_tap_from_zero_is_15_mph_exactly():
  assert TAP_FROM_ZERO_KPH == pytest.approx(24.14016, abs=1e-9)


@pytest.mark.parametrize("cruise_state", ENGAGED)
def test_op_long_never_zero_or_di_while_engaged(cruise_state):
  """Engaged at 64 kph, DI_cruiseSet (about half of ego) then raw 0 at the stop: never DI, never 0, vCruise never 255."""
  car = Car()
  rets = [car.step(cruise_state, 40, 64.0)] + [car.step(cruise_state, r, v) for r, v in ((30, 48.0), (10, 16.0), (0, 0.0))]
  rets += [car.step(cruise_state, 0, 0.0) for _ in range(3)]
  for ret, raw in zip(rets, [40, 30, 10] + [0] * 4, strict=True):
    assert ret.cruiseState.enabled
    assert ret.cruiseState.speed == pytest.approx(64.0 * CV.KPH_TO_MS, abs=1e-3)
    assert ret.cruiseState.speed != pytest.approx(raw * 0.5 * CV.MPH_TO_MS)
  assert all(v != V_CRUISE_UNSET for v in _vcruise(rets))


def test_op_long_not_engaged_publishes_no_di_seed():
  """Op long, cruise not engaged: 0 (unset), never DI_cruiseSet; the engage edge steps straight to the set."""
  car = Car()
  pre = [car.step(STANDBY, 24, 50.0) for _ in range(3)]
  assert all(r.cruiseState.speed == 0.0 for r in pre)
  edge = car.step(ENABLED, 24, 50.0)
  assert edge.cruiseState.speed == pytest.approx(50.0 * CV.KPH_TO_MS, abs=1e-3)
  v = _vcruise(pre + [edge])
  assert v[:3] == [V_CRUISE_UNSET] * 3 and v[3] == pytest.approx(50.0, abs=1e-3)


@pytest.mark.parametrize("cruise_state", [ENABLED, STANDSTILL])
def test_standstill_engage_with_limit_is_limit_plus_offset(cruise_state):
  offset = 5 * CV.MPH_TO_MS
  car = Car(offset_ms=offset)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65)
  ret = car.step(cruise_state, 0, 0.0, map_limit=MAP_65)
  limit = ui_map_speed_limit_ms(MAP_65, False)
  assert ret.bogpilot.dashboardSpeedLimit == pytest.approx(limit)
  assert ret.cruiseState.speed == pytest.approx(limit + offset, abs=1e-3)
  assert not ret.bogpilot.ap1SpeedLimitUnknown and SPEED_LIMIT_UNKNOWN not in _events(ret)


def test_moving_pull_engage_takes_limit_and_holds_through_stop():
  car = Car()
  limit = ui_map_speed_limit_ms(MAP_65, False)
  car.step(STANDBY, 20, 40.0, map_limit=MAP_65, lever=RWD)          # pull toward the driver engages SLC
  rets = [car.step(ENABLED, 20, 40.0, map_limit=MAP_65)]
  rets += [car.step(ENABLED, 0, 0.0, map_limit=0) for _ in range(3)]  # limit gone, stopped: latch holds
  assert all(r.cruiseState.speed == pytest.approx(limit, abs=1e-3) for r in rets)


@pytest.mark.parametrize("lever", [0, UP, DN, UP_1ST, DN_1ST])
def test_moving_tap_or_no_stalk_engage_latches_vego_and_holds_through_stop(lever):
  """A rolling tap, or an engage with no stalk seen, latches vEgo even with a known limit; held through a stop."""
  car = Car()
  if lever:
    car.step(STANDBY, 20, 40.0, map_limit=MAP_65, lever=lever)
  rets = [car.step(ENABLED, 20, 40.0, map_limit=MAP_65)]
  rets += [car.step(ENABLED, 0, 0.0, map_limit=0) for _ in range(3)]
  assert all(r.cruiseState.speed == pytest.approx(40.0 * CV.KPH_TO_MS, abs=1e-3) for r in rets)
  assert all(not r.bogpilot.ap1SpeedLimitUnknown for r in rets)


def test_standstill_no_limit_no_tap_raises_no_entry():
  """Standstill engage, no limit, no tap: the NO_ENTRY event; 0 (unset) while refused, no 8 kph placeholder."""
  car = Car()
  assert car.step(STANDBY, 0, 0.0).bogpilot.ap1SpeedLimitUnknown
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.enabled
  assert ret.bogpilot.ap1SpeedLimitUnknown
  assert SPEED_LIMIT_UNKNOWN in _events(ret)
  assert ret.cruiseState.speed == 0.0


def test_no_entry_alert_text():
  """Top line "BogPilot not Engaged", bottom "Speed Limit Unknown" (NoEntryAlert swaps on mici, events.py)."""
  try:
    from openpilot.selfdrive.selfdrived import events
    from openpilot.cereal import log
  except ImportError as e:  # needs the built msgq/cereal (VM); skipped on a bare checkout
    pytest.skip(f"openpilot runtime not built: {e}")
  alert = events.EVENTS[log.OnroadEvent.EventName.ap1SpeedLimitUnknown][events.ET.NO_ENTRY]
  top, bottom = alert.alert_text_1, alert.alert_text_2
  if events.HARDWARE.get_device_type() == 'mici':
    top, bottom = bottom, top
  assert (top, bottom) == ("BogPilot not Engaged", "Speed Limit Unknown")


@pytest.mark.parametrize("lever", [UP, DN])
def test_tap_from_zero_sets_24_14_kph_and_clears_no_entry(lever):
  car = Car()
  car.step(STANDBY, 0, 0.0)
  ret = car.step(STANDBY, 0, 0.0, lever=lever)       # tap before the engage
  assert not ret.bogpilot.ap1SpeedLimitUnknown
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)
  assert SPEED_LIMIT_UNKNOWN not in _events(ret)
  # Tap during a refused engage (DI on, NO_ENTRY): after the edge, so it latches.
  car = Car()
  assert car.step(STANDSTILL, 0, 0.0).bogpilot.ap1SpeedLimitUnknown
  ret = car.step(STANDSTILL, 0, 0.0, lever=lever)
  assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)
  # The tap is used once: a re-engage after the cancel needs a fresh tap (or a limit).
  car.step(STANDBY, 0, 0.0)
  ret = car.step(ENABLED, 0, 0.0)
  assert ret.cruiseState.speed == 0.0 and ret.bogpilot.ap1SpeedLimitUnknown
  ret = car.step(ENABLED, 0, 0.0, lever=lever)
  assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)
  assert not ret.bogpilot.ap1SpeedLimitUnknown


def _frames(seconds):
  return int(round(seconds / 0.01))


@pytest.mark.parametrize("lever", [UP, DN])
def test_stale_tap_at_red_light_does_not_latch_later_standstill_engage(lever):
  """Tap at a red light, engage at a later standstill: the old tap is dropped, NO_ENTRY, no 15 mph."""
  car = Car()
  car.step(STANDBY, 0, 0.0, lever=lever)
  rets = [car.step(STANDBY, 0, 0.0) for _ in range(_frames(TAP_WINDOW_S) + 5)]
  assert rets[-1].bogpilot.ap1SpeedLimitUnknown
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == 0.0
  assert ret.bogpilot.ap1SpeedLimitUnknown and SPEED_LIMIT_UNKNOWN in _events(ret)
  rets = [car.step(STANDSTILL, 0, 0.0) for _ in range(50)]   # held at the stop: never drives off on the old tap
  assert all(r.cruiseState.speed == 0.0 for r in rets)


@pytest.mark.parametrize("lever", [UP, DN])
def test_tap_inside_window_before_edge_counts(lever):
  """Tesla clears the stalk event 80-240 ms before the enable edge: a tap inside TAP_WINDOW_S still counts."""
  car = Car()
  car.step(STANDBY, 0, 0.0, lever=lever)
  for _ in range(_frames(TAP_WINDOW_S) - 2):
    car.step(STANDBY, 0, 0.0)
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)


def test_moving_no_limit_vego_latch_no_event():
  car = Car()
  ret = car.step(ENABLED, 6, 12.0)
  assert ret.cruiseState.speed == pytest.approx(12.0 * CV.KPH_TO_MS, abs=1e-3)
  assert SPEED_LIMIT_UNKNOWN not in _events(ret)
  assert car.step(ENABLED, 0, 3.0).cruiseState.speed == pytest.approx(12.0 * CV.KPH_TO_MS, abs=1e-3)
  slow = Car().step(ENABLED, 0, 3.0)  # creeping (not standstill), no limit: exact vEgo, no 8 kph clamp
  assert slow.cruiseState.speed == pytest.approx(3.0 * CV.KPH_TO_MS, abs=1e-3)


@pytest.mark.parametrize("stop_state", ENGAGED)
def test_mid_drive_latch_holds_through_later_stop(stop_state):
  car = Car()
  rets = [car.step(ENABLED, 20, 40.0), car.step(ENABLED, 4, 10.0), car.step(ENABLED, 0, 2.0)]
  rets += [car.step(stop_state, 0, 0.0) for _ in range(5)]
  for ret in rets:
    assert ret.cruiseState.speed == pytest.approx(40.0 * CV.KPH_TO_MS, abs=1e-3)
    assert not ret.bogpilot.ap1SpeedLimitUnknown
  assert all(v != V_CRUISE_UNSET for v in _vcruise(rets))


def test_set_clamped_to_170_kph():
  """Tinkla ACC_module.py:231-232 upper clip."""
  assert Car().step(ENABLED, 0, 200.0).cruiseState.speed == pytest.approx(170.0 * CV.KPH_TO_MS, abs=1e-3)


@pytest.mark.parametrize("cruise_state", [STANDBY] + ENGAGED)
def test_stock_ap_path_unchanged(cruise_state):
  """No openpilot long: cruiseState.speed is still DI_cruiseSet, including 0 (vCruise UNSET) at a stop; no event."""
  car = Car(op_long=False)
  assert car.state.op_long_set is None
  for raw, v in ((40, 64.0), (8, 16.0), (0, 0.0)):
    ret = car.step(cruise_state, raw, v)
    assert ret.cruiseState.speed == pytest.approx(raw * 0.5 * car.state.cruise_set_scale * CV.MPH_TO_MS)  # x2 (cruise_set.py)
    assert not ret.bogpilot.ap1SpeedLimitUnknown
  if cruise_state != STANDBY:
    assert _vcruise([ret])[-1] == V_CRUISE_UNSET


def test_model_x_op_long_off_unchanged():
  """AP1 Model X with openpilot long off (the interface.py default) stays on DI_cruiseSet."""
  car = Car(fingerprint=CAR.TESLA_AP1_MODELX, op_long=False)
  assert car.state.op_long_set is None
  assert car.step(ENABLED, 24, 50.0).cruiseState.speed == pytest.approx(12.0 * car.state.cruise_set_scale * CV.MPH_TO_MS)


def test_model_x_op_long_on_gets_same_behavior():
  """AP1 Model X with openpilot long on is in is_ap1_family (values.py:158-159): same latch and NO_ENTRY."""
  car = Car(fingerprint=CAR.TESLA_AP1_MODELX, op_long=True)
  rets = [car.step(ENABLED, 20, 50.0)] + [car.step(STANDSTILL, 0, 0.0) for _ in range(3)]
  assert all(r.cruiseState.speed == pytest.approx(50.0 * CV.KPH_TO_MS, abs=1e-3) for r in rets)
  assert Car(fingerprint=CAR.TESLA_AP1_MODELX).step(STANDSTILL, 0, 0.0).bogpilot.ap1SpeedLimitUnknown


def test_preap_carstate_untouched():
  """Pre-AP has its own CarState (preap/carstate.py) and never sets the AP1 flag."""
  from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
  state = PreApCarState(SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True))
  assert not hasattr(state, "op_long_set")


def _stale_limit_car(seconds):
  """65 mph map limit seen once, then the (optional) map frame stops for `seconds` at a standstill."""
  car = Car()
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65)
  for _ in range(int(round(seconds / 0.01))):
    ret = car.step(STANDBY, 0, 0.0, map_msg=False)
  return car, ret


def test_stale_limit_standstill_engage_is_no_entry():
  """The last map value persists in the parser; older than LIMIT_MAX_AGE_S it is unknown for the engage set."""
  car, ret = _stale_limit_car(LIMIT_MAX_AGE_S + 0.5)
  assert ret.bogpilot.dashboardSpeedLimit == pytest.approx(ui_map_speed_limit_ms(MAP_65, False))  # display unchanged
  ret = car.step(STANDSTILL, 0, 0.0, map_msg=False)
  assert ret.cruiseState.speed == 0.0
  assert ret.bogpilot.ap1SpeedLimitUnknown and SPEED_LIMIT_UNKNOWN in _events(ret)
  rets = [car.step(STANDSTILL, 0, 0.0, map_msg=False) for _ in range(50)]
  assert all(r.cruiseState.speed == 0.0 for r in rets)   # no drive-off on the stale limit


def test_stale_limit_moving_engage_falls_through_to_vego():
  car, _ = _stale_limit_car(LIMIT_MAX_AGE_S + 0.5)
  ret = car.step(ENABLED, 0, 40.0, map_msg=False)
  assert ret.cruiseState.speed == pytest.approx(40.0 * CV.KPH_TO_MS, abs=1e-3)
  assert not ret.bogpilot.ap1SpeedLimitUnknown


def test_limit_inside_age_gate_still_latches():
  car, _ = _stale_limit_car(LIMIT_MAX_AGE_S - 0.5)
  ret = car.step(STANDSTILL, 0, 0.0, map_msg=False)
  assert ret.cruiseState.speed == pytest.approx(ui_map_speed_limit_ms(MAP_65, False), abs=1e-3)


def _x_step(car, cruise_state, v_kph, fused=None, units=None):
  """Model X frame: chassis via Car.step (no map frame), plus optional cam AutopilotStatus and UI_gpsVehicleSpeed."""
  if units is not None:
    addr, dat, _ = PACKER.make_can_msg("UI_gpsVehicleSpeed", car.chassis.bus, {"UI_mapSpeedLimitUnits": units})
    car.chassis.update([(car.t + 10_000_000 - 1, [(addr, dat, car.chassis.bus)])])
  if fused is not None:
    cam = car.parsers[Bus.cam]
    addr, dat, _ = PACKER.make_can_msg("AutopilotStatus", cam.bus, {"DAS_fusedSpeedLimit": fused})
    cam.update([(car.t + 10_000_000, [(addr, dat, cam.bus)])])
  return car.step(cruise_state, 0, v_kph, map_msg=False)


@pytest.mark.parametrize("cruise_state", [STANDSTILL, ENABLED])
def test_model_x_units_unknown_does_not_latch_metric_like_limit(cruise_state):
  """Model X, no UI_gpsVehicleSpeed (units unknown), fused 100 (a kph sign): never latched as 100 mph."""
  car = Car(fingerprint=CAR.TESLA_AP1_MODELX)
  v = 0.0 if cruise_state == STANDSTILL else 40.0
  _x_step(car, STANDBY, v, fused=100)
  ret = _x_step(car, cruise_state, v, fused=100)
  assert ret.cruiseState.speed < 100 * CV.KPH_TO_MS
  if cruise_state == STANDSTILL:
    assert ret.cruiseState.speed == 0.0 and ret.bogpilot.ap1SpeedLimitUnknown
  else:
    assert ret.cruiseState.speed == pytest.approx(40.0 * CV.KPH_TO_MS, abs=1e-3)


def test_model_x_units_known_metric_latches_kph():
  car = Car(fingerprint=CAR.TESLA_AP1_MODELX)
  _x_step(car, STANDBY, 0.0, fused=100, units=1)
  ret = _x_step(car, STANDSTILL, 0.0, fused=100, units=1)
  assert ret.cruiseState.speed == pytest.approx(100 * CV.KPH_TO_MS, abs=1e-3)


@pytest.mark.parametrize("cruise_state", [ENABLED, STANDSTILL, OVERRIDE])
def test_op_long_engaged_at_standstill_guard(cruise_state):
  """Replaces test_op_long_engaged_at_standstill_waits_for_8_kph for the kept standstill drive-off (known limit / fresh tap).

  - No fresh limit or tap: NO_ENTRY on every tick, 0 published, so openpilot is never enabled with a 0/UNSET set.
  - A stale tap plus a stale limit: the same (no drive-off on either).
  - Once latched: never 0 and vCruise never UNSET through the stop.
  """
  car = Car()
  rets = [car.step(cruise_state, 0, 0.0, map_msg=False) for _ in range(5)]
  for ret in rets:
    assert ret.cruiseState.enabled and ret.cruiseState.speed == 0.0
    assert ret.bogpilot.ap1SpeedLimitUnknown and SPEED_LIMIT_UNKNOWN in _events(ret)

  car = Car()
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=UP)
  for _ in range(int(round((LIMIT_MAX_AGE_S + 0.5) / 0.01))):
    car.step(STANDBY, 0, 0.0, map_msg=False)
  rets = [car.step(cruise_state, 0, 0.0, map_msg=False) for _ in range(50)]
  for ret in rets:
    assert ret.cruiseState.speed == 0.0 and ret.bogpilot.ap1SpeedLimitUnknown

  car = Car()
  car.step(cruise_state, 0, 0.0, map_msg=False)
  rets = [car.step(cruise_state, 0, 0.0, map_msg=False, lever=UP)]
  rets += [car.step(cruise_state, 0, 0.0, map_msg=False) for _ in range(20)]
  rets += [car.step(cruise_state, 0, v, map_msg=False) for v in (3.0, 7.9, 30.0, 0.0)]
  for ret in rets:
    assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)
    assert not ret.bogpilot.ap1SpeedLimitUnknown
  assert all(v != V_CRUISE_UNSET for v in _vcruise(rets))


@pytest.mark.parametrize("cruise_state", [ENABLED, STANDSTILL, OVERRIDE])
def test_standstill_drive_off_only_from_fresh_limit_or_fresh_tap(cruise_state):
  """Kept standstill drive-off (AP1StandstillEngage is on by default on Model S): the target comes only from a fresh,
  age-gated limit (+ offset) or a fresh tap; it is held at the stop so the car can drive off to it."""
  offset = 5 * CV.MPH_TO_MS
  limit = ui_map_speed_limit_ms(MAP_65, False)
  car = Car(offset_ms=offset)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65)
  rets = [car.step(cruise_state, 0, 0.0, map_limit=MAP_65) for _ in range(50)]
  rets += [car.step(cruise_state, 0, 0.0, map_msg=False) for _ in range(int(round((LIMIT_MAX_AGE_S + 1.0) / 0.01)))]
  for ret in rets:   # fresh limit latched; it then going stale after the latch does not drop the set
    assert ret.cruiseState.speed == pytest.approx(limit + offset, abs=1e-3)
    assert not ret.bogpilot.ap1SpeedLimitUnknown
  assert all(v != V_CRUISE_UNSET for v in _vcruise(rets))

  # No fresh source at a standstill: stale limit, stale tap, both, or none -> NO_ENTRY, no target.
  for map_first, lever_first in ((MAP_65, 0), (0, UP), (MAP_65, DN), (0, 0)):
    car = Car(offset_ms=offset)
    car.step(STANDBY, 0, 0.0, map_limit=map_first, lever=lever_first)
    for _ in range(int(round((LIMIT_MAX_AGE_S + 0.5) / 0.01))):
      car.step(STANDBY, 0, 0.0, map_msg=False)
    rets = [car.step(cruise_state, 0, 0.0, map_msg=False) for _ in range(20)]
    assert all(r.cruiseState.speed == 0.0 and r.bogpilot.ap1SpeedLimitUnknown for r in rets)


@pytest.mark.parametrize("stop_state", [STANDBY, 0])
def test_disengage_then_reengage_resets_the_set(stop_state):
  """A disengage clears the latch and any used tap: each engage edge picks its own set from what is fresh then."""
  car = Car()
  assert car.step(ENABLED, 0, 40.0, map_msg=False).cruiseState.speed == pytest.approx(40.0 * CV.KPH_TO_MS, abs=1e-3)
  off = car.step(stop_state, 0, 40.0, map_msg=False)
  assert off.cruiseState.speed == 0.0 and car.state.op_long_set.set_kph == 0.0
  ret = car.step(ENABLED, 0, 60.0, map_msg=False)            # moving re-engage: new vEgo, not the old 40
  assert ret.cruiseState.speed == pytest.approx(60.0 * CV.KPH_TO_MS, abs=1e-3)
  car.step(stop_state, 0, 0.0, map_msg=False)
  ret = car.step(STANDSTILL, 0, 0.0, map_msg=False)           # standstill re-engage, nothing fresh: NO_ENTRY
  assert ret.cruiseState.speed == 0.0 and ret.bogpilot.ap1SpeedLimitUnknown
  ret = car.step(STANDSTILL, 0, 0.0, lever=UP, map_msg=False)  # fresh tap while engaged: 15 mph
  assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)
  car.step(stop_state, 0, 0.0, map_msg=False)
  ret = car.step(STANDSTILL, 0, 0.0, map_msg=False)           # the used tap is not reused
  assert ret.cruiseState.speed == 0.0 and ret.bogpilot.ap1SpeedLimitUnknown
  car.step(stop_state, 0, 0.0, map_limit=MAP_65)
  ret = car.step(STANDSTILL, 0, 0.0, map_limit=MAP_65)        # fresh limit: limit set
  assert ret.cruiseState.speed == pytest.approx(ui_map_speed_limit_ms(MAP_65, False), abs=1e-3)


@pytest.mark.parametrize("cruise_state", [STANDSTILL, ENABLED])
def test_model_s_units_unknown_or_stale_does_not_latch_metric_like_limit(cruise_state):
  """Model S, fused 100 (a kph sign) with units missing or stale: never latched as 100 mph."""
  v = 0.0 if cruise_state == STANDSTILL else 40.0
  # Missing 0x2F8 (units never seen).
  car = Car()
  _x_step(car, STANDBY, v, fused=100)
  ret = _x_step(car, cruise_state, v, fused=100)
  assert ret.cruiseState.speed < 100 * CV.KPH_TO_MS
  if cruise_state == STANDSTILL:
    assert ret.cruiseState.speed == 0.0 and ret.bogpilot.ap1SpeedLimitUnknown
  else:
    assert ret.cruiseState.speed == pytest.approx(40.0 * CV.KPH_TO_MS, abs=1e-3)
  # Stale 0x2F8: units were seen, then the gps frame stops while fused stays fresh.
  car = Car()
  _x_step(car, STANDBY, v, fused=100, units=1)
  for _ in range(_frames(LIMIT_MAX_AGE_S + 0.5)):
    _x_step(car, STANDBY, v, fused=100)
  ret = _x_step(car, cruise_state, v, fused=100)
  assert ret.cruiseState.speed < 100 * CV.KPH_TO_MS
  if cruise_state == STANDSTILL:
    assert ret.cruiseState.speed == 0.0 and ret.bogpilot.ap1SpeedLimitUnknown
  else:
    assert ret.cruiseState.speed == pytest.approx(40.0 * CV.KPH_TO_MS, abs=1e-3)


def test_model_s_units_known_metric_latches_kph():
  """Model S with a fresh 0x2F8 (KPH) still converts a fused limit in kph."""
  car = Car()
  _x_step(car, STANDBY, 0.0, fused=100, units=1)
  ret = _x_step(car, STANDSTILL, 0.0, fused=100, units=1)
  assert ret.cruiseState.speed == pytest.approx(100 * CV.KPH_TO_MS, abs=1e-3)


@pytest.mark.parametrize("lever", [UP, DN])
def test_tap_window_just_inside_and_just_outside(lever):
  """Exact TAP_WINDOW_S = 0.8 s boundary.

  Age starts at 0 on the tap frame and grows by DT_CTRL (0.01 s) on each later tick. The stale
  check (age > 0.8 + 1e-6) runs only while not engaged, so the last STANDBY tick decides it.
  80 STANDBY ticks after the tap leave age at 0.80 s (just inside). 81 ticks leave 0.81 s (just
  outside) and clear the tap before the engage edge.
  """
  car = Car()
  car.step(STANDBY, 0, 0.0, lever=lever)
  for _ in range(80):
    car.step(STANDBY, 0, 0.0)
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)
  car = Car()
  car.step(STANDBY, 0, 0.0, lever=lever)
  for _ in range(81):
    car.step(STANDBY, 0, 0.0)
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == 0.0
  assert ret.bogpilot.ap1SpeedLimitUnknown and SPEED_LIMIT_UNKNOWN in _events(ret)


@pytest.mark.parametrize("lever", [CANCEL, RWD])
def test_cancel_and_rwd_do_not_count_as_a_tap(lever):
  """SpdCtrlLvr_Stat 1 (cancel) and 2 (RWD / resumeCruise) must not arm the standstill 15 mph latch."""
  car = Car()
  car.step(STANDBY, 0, 0.0, lever=lever)
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == 0.0
  assert ret.bogpilot.ap1SpeedLimitUnknown and SPEED_LIMIT_UNKNOWN in _events(ret)
  ret = car.step(STANDSTILL, 0, 0.0, lever=lever)
  assert ret.cruiseState.speed == 0.0 and ret.bogpilot.ap1SpeedLimitUnknown


def test_frame_fresh_whole_bus_silence_is_stale():
  """Empty parser updates still advance _last_update_nanos, so a silent bus ages the last limit out."""
  car = Car()
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65)
  assert frame_fresh(car.chassis, "UI_driverAssistMapData")
  t = car.t
  for _ in range(_frames(LIMIT_MAX_AGE_S + 0.5)):
    t += 10_000_000
    car.chassis.update([(t, [])])
  assert not frame_fresh(car.chassis, "UI_driverAssistMapData")


def _roll(car, cruise_state, v_kph, lever=0):
  """Step until CarState.standstill is False. vEgo is KF-filtered, so 0.5-2 kph takes a few ticks."""
  ret = None
  for _ in range(20):
    ret = car.step(cruise_state, 0, v_kph, lever=lever)
    if not ret.standstill:
      return ret
  raise AssertionError("car stayed at standstill")


@pytest.mark.parametrize("v_kph", [0.5, 2.0, 7.9])
@pytest.mark.parametrize("lever", [0, UP])
def test_rolling_engage_no_limit_latches_exact_vego(v_kph, lever):
  """Rolling, no fresh limit: exact vEgo, including below 8 kph. A tap does not switch to the standstill 15 mph set."""
  # Reach a true rolling state before the engage edge (CarState.standstill uses filtered vEgo).
  car = Car()
  _roll(car, STANDBY, v_kph)
  ret = car.step(ENABLED, 0, v_kph, lever=lever)
  assert not ret.standstill
  assert ret.cruiseState.speed == pytest.approx(v_kph * CV.KPH_TO_MS, abs=1e-3)
  assert not ret.bogpilot.ap1SpeedLimitUnknown
  assert SPEED_LIMIT_UNKNOWN not in _events(ret)
  held = car.step(ENABLED, 0, v_kph)
  assert held.cruiseState.speed == pytest.approx(v_kph * CV.KPH_TO_MS, abs=1e-3)


def test_tap_from_zero_setting_default_edges_live_and_display():
  """AP1TapFromZeroMph: default 15, edges 5 and 30, invalid/missing/out-of-range -> 15, live change, metric text, 0x389."""
  from opendbc.car.tesla_ap1.slc_raise import cruise_set_mph
  assert parse_tap_from_zero_mph(None) == 15
  assert parse_tap_from_zero_mph("") == 15
  assert parse_tap_from_zero_mph("  ") == 15
  assert parse_tap_from_zero_mph("foo") == 15
  assert parse_tap_from_zero_mph("15.5") == 15
  assert parse_tap_from_zero_mph(15.5) == 15
  assert parse_tap_from_zero_mph("4") == 15
  assert parse_tap_from_zero_mph("31") == 15
  assert parse_tap_from_zero_mph(4) == 15
  assert parse_tap_from_zero_mph(31) == 15
  assert parse_tap_from_zero_mph("5") == 5
  assert parse_tap_from_zero_mph(30) == 30
  assert parse_tap_from_zero_mph("15") == 15
  assert tap_from_zero_kph_from_param(None) == pytest.approx(TAP_FROM_ZERO_KPH)
  assert format_tap_from_zero_display(15, False) == "15 mph"
  assert format_tap_from_zero_display(15, True) == "15 mph (24 km/h)"
  assert format_tap_from_zero_display(5, True) == "5 mph (8 km/h)"
  assert format_tap_from_zero_display(30, True) == "30 mph (48 km/h)"

  car = Car()
  car.step(STANDBY, 0, 0.0, lever=UP)
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == pytest.approx(15 * CV.MPH_TO_MS, abs=1e-6)

  for mph in (5, 30):
    car = Car()
    car.state.op_long_tap_from_zero = lambda m=mph: m * CV.MPH_TO_KPH
    car.step(STANDBY, 0, 0.0, lever=UP)
    ret = car.step(STANDSTILL, 0, 0.0)
    assert ret.cruiseState.speed == pytest.approx(mph * CV.MPH_TO_MS, abs=1e-6)

  # A live change takes effect on the next standstill tap (after disengage).
  box = {"mph": 20}
  car = Car()
  car.state.op_long_tap_from_zero = lambda: box["mph"] * CV.MPH_TO_KPH
  car.step(STANDBY, 0, 0.0, lever=UP)
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == pytest.approx(20 * CV.MPH_TO_MS, abs=1e-6)
  car.step(STANDBY, 0, 0.0)
  box["mph"] = 10
  car.step(STANDBY, 0, 0.0, lever=DN)
  ret = car.step(STANDSTILL, 0, 0.0)
  assert ret.cruiseState.speed == pytest.approx(10 * CV.MPH_TO_MS, abs=1e-6)

  # 0x389 overlay uses cruise_set_mph (DAS_accSpeedLimit, DBC factor 0.4).
  for mph in (5, 15, 20, 30):
    assert cruise_set_mph(mph * CV.MPH_TO_MS) == pytest.approx(float(mph), abs=1e-6)


# Rolling engage: tap latches the current speed, only a pull takes limit + offset.

def _rolling_engage(v_kph, lever, offset_ms=None, gap_frames=0, map_limit=MAP_65):
  car = Car(offset_ms=offset_ms)
  _roll(car, STANDBY, v_kph)
  car.step(STANDBY, 0, v_kph, map_limit=map_limit, lever=lever)
  for _ in range(gap_frames):
    car.step(STANDBY, 0, v_kph, map_limit=map_limit)
  return car, car.step(ENABLED, 0, v_kph, map_limit=map_limit)


@pytest.mark.parametrize("lever", [UP, DN, UP_1ST, DN_1ST])
def test_rolling_tap_engage_latches_vego_not_limit(lever):
  car, ret = _rolling_engage(72.0, lever, offset_ms=5 * CV.MPH_TO_MS)
  assert not ret.standstill
  assert ret.cruiseState.speed == pytest.approx(72.0 * CV.KPH_TO_MS, abs=1e-3)
  limit = ui_map_speed_limit_ms(MAP_65, False)
  assert abs(ret.cruiseState.speed - limit) > 1.0
  held = [car.step(ENABLED, 0, 90.0, map_limit=MAP_65) for _ in range(20)]   # speeding up later never moves it
  assert all(h.cruiseState.speed == pytest.approx(72.0 * CV.KPH_TO_MS, abs=1e-3) for h in held)


def test_rolling_pull_engage_latches_limit_plus_offset():
  offset = 5 * CV.MPH_TO_MS
  _car, ret = _rolling_engage(72.0, RWD, offset_ms=offset)
  limit = ui_map_speed_limit_ms(MAP_65, False)
  assert ret.cruiseState.speed == pytest.approx(limit + offset, abs=1e-3)


def test_rolling_pull_engage_without_a_limit_latches_vego():
  _car, ret = _rolling_engage(50.0, RWD, map_limit=0)
  assert ret.cruiseState.speed == pytest.approx(50.0 * CV.KPH_TO_MS, abs=1e-3)


@pytest.mark.parametrize("mph", [5.0, 7.5, 10.0])
@pytest.mark.parametrize("lever", [UP, DN])
def test_low_speed_tap_with_limit_latches_vego(mph, lever):
  v_kph = mph * CV.MPH_TO_KPH
  _car, ret = _rolling_engage(v_kph, lever, offset_ms=5 * CV.MPH_TO_MS)
  assert not ret.standstill
  assert ret.cruiseState.speed == pytest.approx(v_kph * CV.KPH_TO_MS, abs=1e-3)
  assert not ret.bogpilot.ap1SpeedLimitUnknown and SPEED_LIMIT_UNKNOWN not in _events(ret)


def test_stale_pull_before_rolling_engage_latches_vego():
  """A pull older than TAP_WINDOW_S before the engage edge does not count: vEgo, not the limit."""
  _car, ret = _rolling_engage(72.0, RWD, offset_ms=5 * CV.MPH_TO_MS, gap_frames=_frames(TAP_WINDOW_S) + 5)
  assert ret.cruiseState.speed == pytest.approx(72.0 * CV.KPH_TO_MS, abs=1e-3)


@pytest.mark.parametrize("first,last,want_limit", [(RWD, UP, False), (UP, RWD, True)])
def test_most_recent_stalk_action_decides_the_rolling_engage(first, last, want_limit):
  offset = 5 * CV.MPH_TO_MS
  car = Car(offset_ms=offset)
  _roll(car, STANDBY, 72.0)
  car.step(STANDBY, 0, 72.0, map_limit=MAP_65, lever=first)
  car.step(STANDBY, 0, 72.0, map_limit=MAP_65)
  car.step(STANDBY, 0, 72.0, map_limit=MAP_65, lever=last)
  ret = car.step(ENABLED, 0, 72.0, map_limit=MAP_65)
  limit = ui_map_speed_limit_ms(MAP_65, False)
  want = (limit + offset) if want_limit else 72.0 * CV.KPH_TO_MS
  assert ret.cruiseState.speed == pytest.approx(want, abs=1e-3)


@pytest.mark.parametrize("cruise_state", [ENABLED, STANDSTILL])
@pytest.mark.parametrize("lever", [UP, DN, UP_1ST, DN_1ST])
def test_standstill_tap_with_known_limit_latches_tap_from_stop_speed(lever, cruise_state):
  """From a full stop a tap never takes SLC: the tap-from-stop speed (15 mph default) even with a known limit."""
  offset = 5 * CV.MPH_TO_MS
  car = Car(offset_ms=offset)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=lever)
  rets = [car.step(cruise_state, 0, 0.0, map_limit=MAP_65) for _ in range(20)]
  for ret in rets:
    assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)
    assert not ret.bogpilot.ap1SpeedLimitUnknown and SPEED_LIMIT_UNKNOWN not in _events(ret)
  # Tap during an engage that is already on at the stop (nothing latched yet): the same.
  car = Car(offset_ms=offset)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65)
  ret = car.step(cruise_state, 0, 0.0, map_limit=MAP_65, lever=lever)
  assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)


def test_standstill_tap_uses_the_tap_from_stop_setting_with_known_limit():
  """The AP1TapFromZeroMph setting (here 20 mph), not limit + offset, for a standstill tap with a known limit."""
  car = Car(offset_ms=5 * CV.MPH_TO_MS)
  car.state.op_long_tap_from_zero = lambda: 20 * CV.MPH_TO_KPH
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=UP)
  ret = car.step(STANDSTILL, 0, 0.0, map_limit=MAP_65)
  assert ret.cruiseState.speed == pytest.approx(20 * CV.MPH_TO_MS, abs=1e-6)


@pytest.mark.parametrize("cruise_state", [ENABLED, STANDSTILL])
def test_standstill_pull_with_known_limit_uses_limit_plus_offset(cruise_state):
  """From a full stop only a pull engages SLC: limit + offset, as before."""
  offset = 5 * CV.MPH_TO_MS
  limit = ui_map_speed_limit_ms(MAP_65, False)
  car = Car(offset_ms=offset)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=RWD)
  ret = car.step(cruise_state, 0, 0.0, map_limit=MAP_65)
  assert ret.cruiseState.speed == pytest.approx(limit + offset, abs=1e-3)
  # Tap then pull inside the window: the most recent press (the pull) wins.
  car = Car(offset_ms=offset)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=UP)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=RWD)
  ret = car.step(cruise_state, 0, 0.0, map_limit=MAP_65)
  assert ret.cruiseState.speed == pytest.approx(limit + offset, abs=1e-3)
  # Pull then tap: the tap wins, tap-from-stop speed.
  car = Car(offset_ms=offset)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=RWD)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=DN)
  ret = car.step(cruise_state, 0, 0.0, map_limit=MAP_65)
  assert ret.cruiseState.speed == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)


def test_standstill_tap_with_known_limit_car_and_planner_agree_on_tap_from_stop_speed():
  """Car layer (cruiseState.speed) and planner (Ap1RaiseHoldoff + ap1_cruise_ms) both give 15 mph after a tap
  from a full stop with a 65 mph limit known, never limit + offset."""
  offset = 5 * CV.MPH_TO_MS
  limit = ui_map_speed_limit_ms(MAP_65, False)
  tap_ms = TAP_FROM_ZERO_KPH * CV.KPH_TO_MS
  car = Car(offset_ms=offset)
  car.step(STANDBY, 0, 0.0, map_limit=MAP_65, lever=UP)
  car_ms = car.step(STANDSTILL, 0, 0.0, map_limit=MAP_65).cruiseState.speed

  hold = Ap1RaiseHoldoff()
  hold.tap_from_zero_ms = tap_ms
  slc_ms = limit + offset
  hold.update(False, False, True, False, slc_ms, 0.0, cruise_on=False)                 # UP tap at the stop
  hold.update(False, False, False, False, slc_ms, 0.0, current_set_ms=car_ms, cruise_on=True)   # cruise edge
  allow, sticky = hold.update(True, False, False, False, slc_ms, 0.0, current_set_ms=car_ms, cruise_on=True)
  plan_ms = ap1_cruise_ms(car_ms, sticky, hold.tip_ms, allow, slc_ms, slc_ms, 0.0, False, 0.0,
                          sticky_zero_is_none=True)
  assert car_ms == pytest.approx(tap_ms, abs=1e-6)
  assert plan_ms == pytest.approx(tap_ms, abs=1e-6)
  assert not allow


@pytest.mark.parametrize("lever", [UP, DN, RWD])
def test_short_tap_between_planner_ticks_classified(lever):
  """A one-frame (10 ms) stalk press stays on the published level for 6 frames (> one 50 ms planner tick), so a
  20 Hz sample at any phase sees it. buttonEvents are not stretched."""
  car = Car()
  car.step(STANDBY, 0, 50.0)
  rets = [car.step(STANDBY, 0, 50.0, lever=lever)]
  rets += [car.step(STANDBY, 0, 50.0) for _ in range(12)]
  field = {UP: "accelPressed", DN: "decelPressed", RWD: "resumePressed"}[lever]
  levels = [bool(getattr(r.bogpilot, field)) for r in rets]
  assert all(levels[:6]) and not any(levels[6:]), levels
  for phase in range(5):   # samples every 5 frames starting at any phase: at least one sees the press
    assert any(levels[phase::5])
  assert len([be for r in rets for be in r.buttonEvents if be.pressed]) == 1


def test_cancel_drops_held_stalk_levels():
  car = Car()
  car.step(STANDBY, 0, 50.0, lever=UP)
  ret = car.step(STANDBY, 0, 50.0, lever=CANCEL)
  assert not ret.bogpilot.accelPressed and not ret.bogpilot.decelPressed and not ret.bogpilot.resumePressed


NONFINITE = [float("inf"), float("-inf"), float("nan")]
LIMIT_45_MS = 45 * CV.MPH_TO_MS
OFFSET_5_MS = 5 * CV.MPH_TO_MS


def _latch(v_ms, standstill, limit_ms, offset=OFFSET_5_MS, tap_zero=None, **press):
  """A press with cruise off, then the engage edge. -> (set m/s on the edge, the OpLongSetSpeed)."""
  ols = OpLongSetSpeed()
  offset_fn = (lambda _limit: offset) if offset is not None else None
  ols.update("STANDBY", v_ms, standstill, limit_ms=limit_ms, offset_fn=offset_fn, tap_from_zero_kph=tap_zero, **press)
  out = ols.update("ENABLED", v_ms, standstill, limit_ms=limit_ms, offset_fn=offset_fn, tap_from_zero_kph=tap_zero)
  return out, ols


@pytest.mark.parametrize("bad", NONFINITE)
def test_nonfinite_limit_is_an_unknown_limit(bad):
  # Rolling pull: no usable limit -> exact vEgo latch (as a pull with no known limit).
  out, ols = _latch(20.0, False, bad, pull=True)
  assert math.isfinite(out) and out == pytest.approx(20.0, abs=1e-6)
  assert not ols.speed_limit_unknown
  # Standstill, no tap: refused (NO_ENTRY ap1SpeedLimitUnknown), nothing latched.
  out, ols = _latch(0.0, True, bad, pull=True)
  assert out == 0.0 and ols.set_kph == 0.0 and ols.speed_limit_unknown
  # Standstill tap: the tap-from-stop speed.
  out, ols = _latch(0.0, True, bad, tap=True)
  assert out == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)


@pytest.mark.parametrize("bad", NONFINITE)
def test_nonfinite_offset_makes_the_limit_unknown(bad):
  out, ols = _latch(20.0, False, LIMIT_45_MS, offset=bad, pull=True)
  assert math.isfinite(out) and out == pytest.approx(20.0, abs=1e-6)
  out, ols = _latch(0.0, True, LIMIT_45_MS, offset=bad, pull=True)
  assert out == 0.0 and ols.set_kph == 0.0 and ols.speed_limit_unknown
  out, ols = _latch(0.0, True, LIMIT_45_MS, offset=bad)
  assert out == 0.0 and ols.speed_limit_unknown
  out, ols = _latch(0.0, True, LIMIT_45_MS, offset=bad, tap=True)
  assert out == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)


@pytest.mark.parametrize("bad", NONFINITE)
@pytest.mark.parametrize("press", [{"pull": True}, {"tap": True}, {}])
@pytest.mark.parametrize("standstill", [False, True])
def test_nonfinite_vego_never_latches_and_refuses(bad, press, standstill):
  out, ols = _latch(bad, standstill, LIMIT_45_MS, **press)
  assert out == 0.0 and ols.set_kph == 0.0
  assert ols.speed_limit_unknown   # refused like an unknown limit, never a 0 / placeholder set while enabled
  # The next frame with a finite speed latches as usual (rolling: vEgo; nothing held from the bad frame).
  nxt = ols.update("ENABLED", 20.0, False, limit_ms=LIMIT_45_MS, offset_fn=lambda _l: OFFSET_5_MS)
  assert math.isfinite(nxt) and nxt > 0.0 and not ols.speed_limit_unknown


@pytest.mark.parametrize("bad", NONFINITE)
def test_nonfinite_vego_after_the_latch_keeps_the_set(bad):
  out, ols = _latch(20.0, False, LIMIT_45_MS, pull=True)
  want = (45 + 5) * CV.MPH_TO_MS
  assert out == pytest.approx(want, abs=1e-3)
  held = ols.update("ENABLED", bad, False, limit_ms=bad, offset_fn=lambda _l: bad)
  assert held == pytest.approx(want, abs=1e-3) and not ols.speed_limit_unknown


@pytest.mark.parametrize("bad", NONFINITE)
def test_nonfinite_tap_from_stop_setting_uses_the_default(bad):
  out, _ols = _latch(0.0, True, 0.0, tap_zero=bad, tap=True)
  assert out == pytest.approx(TAP_FROM_ZERO_KPH * CV.KPH_TO_MS, abs=1e-6)


def _rolling_tap_then_stop(stop_frames, tap_mph=3.0, limit_ms=LIMIT_45_MS, engaged_state="ENABLED"):
  """A tap at tap_mph while rolling with a known limit, stop_frames at a full stop with cruise off, then the engage edge
  at the stop. -> (car-side sets over 20 engaged frames, the OpLongSetSpeed)."""
  ols = OpLongSetSpeed()
  offset_fn = lambda _limit: OFFSET_5_MS
  ols.update("STANDBY", tap_mph * CV.MPH_TO_MS, False, limit_ms=limit_ms, offset_fn=offset_fn, tap=True)
  for _ in range(stop_frames):
    ols.update("STANDBY", 0.0, True, limit_ms=limit_ms, offset_fn=offset_fn)
  sets = [ols.update(engaged_state, 0.0, True, limit_ms=limit_ms, offset_fn=offset_fn) for _ in range(20)]
  return sets, ols


@pytest.mark.parametrize("engaged_state", ["ENABLED", "STANDSTILL"])
@pytest.mark.parametrize("stop_frames", [1, 20, int(TAP_WINDOW_S / 0.01) - 2])
def test_rolling_tap_then_stop_within_window_keeps_tap_set(stop_frames, engaged_state):
  """A tap while rolling (3 mph, 45 mph limit known), then a stop inside the 0.8 s window, then the engage at the
  stop: the car-side set keeps the tap's vEgo latch, never limit + offset (50 mph)."""
  sets, ols = _rolling_tap_then_stop(stop_frames, engaged_state=engaged_state)
  for v in sets:
    assert v == pytest.approx(3.0 * CV.MPH_TO_MS, abs=1e-6)
    assert v < (45 + 5) * CV.MPH_TO_MS - 1.0
  assert not ols.speed_limit_unknown


def test_rolling_tap_then_stop_within_window_car_and_planner_agree():
  """The planner (Ap1RaiseHoldoff + ap1_cruise_ms) classifies the same engage as a tap and latches the vEgo at the
  tap; the car-side cruiseState.speed now gives the same set."""
  sets, _ols = _rolling_tap_then_stop(20)
  car_ms = sets[0]
  slc_ms = LIMIT_45_MS + OFFSET_5_MS
  hold = Ap1RaiseHoldoff()
  hold.tap_from_zero_ms = TAP_FROM_ZERO_KPH * CV.KPH_TO_MS
  hold.update(False, False, True, False, slc_ms, 3.0 * CV.MPH_TO_MS, cruise_on=False)   # UP tap while rolling
  for _ in range(4):   # 0.2 s at the stop (planner ticks)
    hold.update(False, False, False, False, slc_ms, 0.0, cruise_on=False)
  hold.update(False, False, False, False, slc_ms, 0.0, current_set_ms=car_ms, cruise_on=True)   # cruise edge
  allow, sticky = hold.update(True, False, False, False, slc_ms, 0.0, current_set_ms=car_ms, cruise_on=True)
  plan_ms = ap1_cruise_ms(car_ms, sticky, hold.tip_ms, allow, slc_ms, LIMIT_45_MS, 0.0, False, 0.0,
                          sticky_zero_is_none=True)
  assert car_ms == pytest.approx(3.0 * CV.MPH_TO_MS, abs=1e-6)
  assert plan_ms == pytest.approx(car_ms, abs=1e-6)


def test_rolling_tap_then_stop_after_window_is_unchanged():
  """Past the 0.8 s window the tap is stale: the standstill rule with a known limit and no stalk (limit + offset)."""
  sets, _ols = _rolling_tap_then_stop(int(TAP_WINDOW_S / 0.01) + 5)
  assert sets[0] == pytest.approx((45 + 5) * CV.MPH_TO_MS, abs=1e-3)


def test_rolling_tap_then_pull_at_the_stop_uses_limit_plus_offset():
  """The most recent press decides: a pull after the rolling tap still engages SLC at limit + offset."""
  ols = OpLongSetSpeed()
  offset_fn = lambda _limit: OFFSET_5_MS
  ols.update("STANDBY", 3.0 * CV.MPH_TO_MS, False, limit_ms=LIMIT_45_MS, offset_fn=offset_fn, tap=True)
  ols.update("STANDBY", 0.0, True, limit_ms=LIMIT_45_MS, offset_fn=offset_fn, pull=True)
  out = ols.update("ENABLED", 0.0, True, limit_ms=LIMIT_45_MS, offset_fn=offset_fn)
  assert out == pytest.approx((45 + 5) * CV.MPH_TO_MS, abs=1e-3)


@pytest.mark.parametrize("lever", [UP, DN, UP_1ST, DN_1ST])
def test_rolling_tap_then_stop_within_window_keeps_tap_set_on_can(lever):
  """The same through CarState: a tap at 10 kph with a 65 mph map limit, a stop, the engage at the stop."""
  car = Car(offset_ms=5 * CV.MPH_TO_MS)
  _roll(car, STANDBY, 10.0)
  car.step(STANDBY, 0, 10.0, map_limit=MAP_65, lever=lever)
  for _ in range(20):
    car.step(STANDBY, 0, 0.0, map_limit=MAP_65)
  rets = [car.step(STANDSTILL, 0, 0.0, map_limit=MAP_65) for _ in range(10)]
  for ret in rets:
    assert ret.cruiseState.speed == pytest.approx(10.0 * CV.KPH_TO_MS, abs=0.05)
    assert not ret.bogpilot.ap1SpeedLimitUnknown


def _held_levels(lever, press_frames, after_frames=12):
  """Published stalk levels for one press held press_frames 100 Hz frames, then released."""
  car = Car()
  car.step(STANDBY, 0, 50.0)
  rets = [car.step(STANDBY, 0, 50.0, lever=lever) for _ in range(press_frames)]
  rets += [car.step(STANDBY, 0, 50.0) for _ in range(after_frames)]
  field = {UP: "accelPressed", UP_1ST: "accelPressed", DN: "decelPressed", DN_1ST: "decelPressed",
           RWD: "resumePressed"}[lever]
  return [bool(getattr(r.bogpilot, field)) for r in rets]


@pytest.mark.parametrize("lever", [UP, DN, UP_1ST, DN_1ST, RWD])
@pytest.mark.parametrize("press_frames", [6, 10, 40, 45])
def test_held_stalk_level_ends_at_the_release_of_a_longer_press(lever, press_frames):
  """A press at least the minimum width (6 frames) is published exactly as long as it is held: no 50 ms tail."""
  levels = _held_levels(lever, press_frames)
  assert all(levels[:press_frames]) and not any(levels[press_frames:]), levels


@pytest.mark.parametrize("lever", [UP, DN, RWD])
@pytest.mark.parametrize("press_frames", [1, 2, 5])
def test_held_stalk_level_short_press_is_stretched_to_the_minimum_width(lever, press_frames):
  levels = _held_levels(lever, press_frames)
  assert all(levels[:6]) and not any(levels[6:]), levels


@pytest.mark.parametrize("phase", range(5))
@pytest.mark.parametrize("press_frames,want_mph", [(40, 51), (45, 55)])
def test_planner_hold_upgrade_follows_the_physical_hold(phase, press_frames, want_mph):
  """A shallow UP held 0.40 s stays a +1 tip; held 0.45 s (TIP_HOLD_S) it upgrades to next 5. The planner samples the
  published level at 20 Hz (every 5th frame, any phase)."""
  levels = _held_levels(UP_1ST, press_frames, after_frames=20)
  samples = ([False] * phase + levels)[::5]
  hold = Ap1RaiseHoldoff()
  base = 50 * CV.MPH_TO_MS
  for _ in range(3):
    hold.update(True, False, False, False, base, 20.0, current_set_ms=base, cruise_on=True)
  hold._clear_tip()
  for up in samples:
    hold.update(True, False, up, False, base, 20.0, current_set_ms=base, cruise_on=True)
  assert hold.tip_ms == pytest.approx(want_mph * CV.MPH_TO_MS, abs=1e-3)


def _rolling_tap_stop_then_engage(tap_mph, stop_s, press=None, tap_zero_mph=15):
  """Car side (OpLongSetSpeed at 100 Hz) and planner (Ap1RaiseHoldoff + ap1_cruise_ms at 20 Hz) over one sequence:
  an UP tap while rolling at tap_mph (45 mph limit known, offset 5 mph), a full stop for stop_s, then optionally a NEW
  press at that same stop ("tap" or "pull"), then the engage edge at the stop. -> (car-side set, planner set) in m/s."""
  tap_zero_kph = tap_zero_mph * CV.MPH_TO_KPH
  offset_fn = lambda _limit: OFFSET_5_MS
  slc_ms = LIMIT_45_MS + OFFSET_5_MS
  ols = OpLongSetSpeed()
  hold = Ap1RaiseHoldoff()
  hold.tap_from_zero_ms = tap_zero_mph * CV.MPH_TO_MS
  car_kw = dict(limit_ms=LIMIT_45_MS, offset_fn=offset_fn, tap_from_zero_kph=tap_zero_kph)

  ols.update("STANDBY", tap_mph * CV.MPH_TO_MS, False, tap=True, **car_kw)        # tap while rolling
  hold.update(False, False, True, False, slc_ms, tap_mph * CV.MPH_TO_MS, cruise_on=False)
  for _ in range(int(round(stop_s / 0.01))):                                        # full stop
    ols.update("STANDBY", 0.0, True, **car_kw)
  for _ in range(int(round(stop_s / 0.05))):
    hold.update(False, False, False, False, slc_ms, 0.0, cruise_on=False)
  if press is not None:                                                              # new press at the same stop
    ols.update("STANDBY", 0.0, True, tap=press == "tap", pull=press == "pull", **car_kw)
    hold.update(False, False, press == "tap", press == "pull", slc_ms, 0.0, cruise_on=False)
    ols.update("STANDBY", 0.0, True, **car_kw)
    hold.update(False, False, False, False, slc_ms, 0.0, cruise_on=False)
  car_ms = ols.update("STANDSTILL", 0.0, True, **car_kw)                             # engage edge at the stop
  assert all(ols.update("STANDSTILL", 0.0, True, **car_kw) == car_ms for _ in range(20))   # held
  hold.update(False, False, False, False, slc_ms, 0.0, current_set_ms=car_ms, cruise_on=True)   # cruise edge
  allow, sticky = hold.update(True, False, False, False, slc_ms, 0.0, current_set_ms=car_ms, cruise_on=True)  # long edge
  plan_ms = ap1_cruise_ms(car_ms, sticky, hold.tip_ms, allow, slc_ms, LIMIT_45_MS, 0.0, False, 0.0,
                          sticky_zero_is_none=True)
  return car_ms, plan_ms


@pytest.mark.parametrize("stop_s", [0.1, 0.3, 0.6])
@pytest.mark.parametrize("tap_zero_mph", [15, 17])
def test_rolling_tap_at_8_mph_then_stop_within_window_gives_8_mph_car_and_planner(stop_s, tap_zero_mph):
  """A tap while rolling at 8 mph sets the rolling speed: a stop and the engage inside 0.8 s keep 8 mph on the car side
  and in the planner, not the tap-from-stop speed and not limit + offset."""
  car_ms, plan_ms = _rolling_tap_stop_then_engage(8.0, stop_s, tap_zero_mph=tap_zero_mph)
  assert car_ms == pytest.approx(8.0 * CV.MPH_TO_MS, abs=1e-6)
  assert plan_ms == pytest.approx(8.0 * CV.MPH_TO_MS, abs=1e-6)


@pytest.mark.parametrize("stop_s", [0.3, 1.5])
@pytest.mark.parametrize("tap_zero_mph", [15, 17])
def test_rolling_tap_at_8_mph_stop_then_new_standstill_tap_gives_tap_from_stop_speed(stop_s, tap_zero_mph):
  """After the 8 mph rolling tap and the stop, a NEW tap at the stop sets AP1TapFromZeroMph (15 default, 17 on this
  car) on the car side and in the planner, whether or not the rolling tap is still inside the 0.8 s window."""
  car_ms, plan_ms = _rolling_tap_stop_then_engage(8.0, stop_s, press="tap", tap_zero_mph=tap_zero_mph)
  assert car_ms == pytest.approx(tap_zero_mph * CV.MPH_TO_MS, abs=1e-6)
  assert plan_ms == pytest.approx(tap_zero_mph * CV.MPH_TO_MS, abs=1e-6)


@pytest.mark.parametrize("stop_s", [0.3, 1.5])
@pytest.mark.parametrize("tap_zero_mph", [15, 17])
def test_rolling_tap_at_8_mph_stop_then_pull_gives_limit_plus_offset(stop_s, tap_zero_mph):
  """After the 8 mph rolling tap and the stop, a pull at the stop goes to SLC: limit + offset (45 + 5) on the car side
  and in the planner."""
  car_ms, plan_ms = _rolling_tap_stop_then_engage(8.0, stop_s, press="pull", tap_zero_mph=tap_zero_mph)
  assert car_ms == pytest.approx((45 + 5) * CV.MPH_TO_MS, abs=1e-3)
  assert plan_ms == pytest.approx((45 + 5) * CV.MPH_TO_MS, abs=1e-3)

