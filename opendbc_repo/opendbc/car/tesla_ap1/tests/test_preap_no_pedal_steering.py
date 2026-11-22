"""Pre-AP with no Comma Pedal at all: steering-only engage with a clear notice, never wrongCarMode blocking.

Pedal longitudinal (the Pre-AP default) runs the PREAP|PEDAL safety mode, whose RX checks require the GAS_SENSOR 0x552 stream, and
cruiseState.available needs the pedal heard: a car without a pedal could not engage at all. At car start, a real Pre-AP chassis
fingerprint without 0x552 now selects the existing no-pedal mode (PREAP safety param, pcmCruise, no openpilot long) and sets
CarParams.flags PREAP_NO_PEDAL so selfdrived can say why. The panda safety code and its limits are unchanged."""
import pytest

from opendbc.car import car_helpers, gen_empty_fingerprint, structs
from opendbc.car.tesla_ap1 import interface
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.safety_flags import flags_for_preap
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, Rig, _inv, _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.values import AP1_CHASSIS_SIGNATURE, CAR, TeslaAp1Flags

PREAP = CAR.TESLA_PREAP_MODELS


def _fp(pedal_bus=None):
  fp = gen_empty_fingerprint()
  fp[0].update(AP1_CHASSIS_SIGNATURE)
  fp[0].update({0x108: 8, 0x155: 8, 0x318: 8, 0x368: 8})
  if pedal_bus is not None:
    fp[pedal_bus][0x552] = 6
  return fp


@pytest.fixture(autouse=True)
def _long_wanted(monkeypatch):
  monkeypatch.setattr(interface, "disable_openpilot_long", lambda: False)   # the default: pedal long wanted


def _cp(fp, docs=False):
  return CarInterface.get_params(PREAP, fp, [], False, False, docs)


def test_no_pedal_on_the_bus_selects_the_no_pedal_mode():
  cp = _cp(_fp())
  assert cp.openpilotLongitudinalControl is False and cp.pcmCruise is True
  assert cp.safetyConfigs[0].safetyParam == flags_for_preap(pedal=False)
  assert cp.flags & TeslaAp1Flags.PREAP_NO_PEDAL
  assert not cp.dashcamOnly


@pytest.mark.parametrize("bus", [0, 2])
def test_pedal_on_either_bus_keeps_pedal_long(bus):
  cp = _cp(_fp(bus))
  assert cp.openpilotLongitudinalControl is True and cp.pcmCruise is False
  assert cp.safetyConfigs[0].safetyParam == flags_for_preap(pedal=True)
  assert not cp.flags & TeslaAp1Flags.PREAP_NO_PEDAL


def test_user_chose_no_pedal_mode_has_no_notice_flag(monkeypatch):
  monkeypatch.setattr(interface, "disable_openpilot_long", lambda: True)
  cp = _cp(_fp())
  assert cp.openpilotLongitudinalControl is False and not cp.flags & TeslaAp1Flags.PREAP_NO_PEDAL
  assert cp.safetyConfigs[0].safetyParam == flags_for_preap(pedal=False)


@pytest.mark.parametrize("docs", [False, True])
def test_empty_fingerprint_is_unchanged(docs):
  cp = _cp(gen_empty_fingerprint(), docs=docs)
  assert cp.openpilotLongitudinalControl is True and not cp.flags & TeslaAp1Flags.PREAP_NO_PEDAL


def test_selected_model_without_pedal_through_get_car(monkeypatch):
  fp = _fp()
  monkeypatch.setattr(car_helpers, "fingerprint", lambda *a, **k: (None, fp, "0" * 17, [], structs.CarParams.FingerprintSource.can, True))
  car = car_helpers.get_car(list, lambda msgs: None, lambda x: None, False, False,
                            fingerprint_override=lambda detected: (PREAP, True))   # CarModel + ForceFingerprint
  assert car.CP.carFingerprint == PREAP and car.CP.fingerprintSource == structs.CarParams.FingerprintSource.fixed
  assert car.CP.openpilotLongitudinalControl is False and car.CP.flags & TeslaAp1Flags.PREAP_NO_PEDAL
  assert car.CP.safetyConfigs[0].safetyParam == flags_for_preap(pedal=False)


def _di(r, state):
  r.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", state)


@pytest.mark.parametrize("state", ["OFF", "STANDBY", "ENABLED"])
def test_no_pedal_cruise_available_without_stock_cruise_standby(state):
  r = Rig(long=False)
  _di(r, state)
  out = r.frame()
  assert out.cruiseState.available is True                    # never wrongCarMode on a steering-only pull


def test_no_pedal_cruise_unavailable_only_on_di_fault():
  r = Rig(long=False)
  _di(r, "FAULT")
  assert r.frame().cruiseState.available is False


def test_pull_with_stock_cruise_off_engages_steering_only():
  r = Rig(long=False)
  _di(r, "OFF")
  r.frame()
  out = r.frame(stalk=PULL)
  assert out.cruiseState.available and out.cruiseState.enabled and out.bogpilot.preapLatOnly
