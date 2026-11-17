"""Stale thermal policy per car (bg_reads.stale_thermal_policy, called with hardwared's Params at start): "nap" is the default on
Pre-AP only; AP1, any other car and an unknown car get "strict"; an explicit STALE_THERMAL_POLICY wins for every car."""
import pathlib

import pytest

import openpilot.system.hardware.bg_reads as bg


class FakeParams:
  def __init__(self, **values):
    self.values = values

  def get(self, key, *a, **kw):
    return self.values.get(key)


class BrokenParams:
  def get(self, key, *a, **kw):
    raise OSError("params read failed")


def persistent(fingerprint: str) -> bytes:
  from opendbc.car.structs import car
  return car.CarParams.new_message(carFingerprint=fingerprint).to_bytes()


@pytest.mark.parametrize("params", [FakeParams(CarModel=b"TESLA_PREAP_MODELS"), FakeParams(CarModel="TESLA_PREAP_MODELS"),
                                    FakeParams(CarParamsPersistent=persistent("TESLA_PREAP_MODELS"))])
def test_preap_gets_nap(params):
  assert bg.STALE_THERMAL_POLICY is None
  assert bg.stale_thermal_policy(params) == "nap"


@pytest.mark.parametrize("params", [FakeParams(CarModel=b"TESLA_AP1_MODELS"), FakeParams(CarModel=b"TESLA_AP1_MODELX"),
                                    FakeParams(CarParamsPersistent=persistent("TESLA_AP1_MODELS")),
                                    FakeParams(CarParamsPersistent=persistent("TESLA_AP1_MODELX")),
                                    FakeParams(CarModel=b"TOYOTA_COROLLA_TSS2"),
                                    # CarModel says Pre-AP but the car last seen was an AP1 Model S: not Pre-AP, strict
                                    FakeParams(CarModel=b"TESLA_PREAP_MODELS", CarParamsPersistent=persistent("TESLA_AP1_MODELS"))])
def test_ap1_and_other_cars_get_strict(params):
  assert bg.stale_thermal_policy(params) == "strict"


@pytest.mark.parametrize("params", [None, FakeParams(), FakeParams(CarModel=b""), FakeParams(CarParamsPersistent=persistent("MOCK")),
                                    FakeParams(CarParamsPersistent=b"\x00garbage"), BrokenParams()])
def test_unknown_car_gets_strict(params):
  assert bg.stale_thermal_policy(params) == "strict"


@pytest.mark.parametrize("override", ["nap", "strict"])
@pytest.mark.parametrize("model", [b"TESLA_PREAP_MODELS", b"TESLA_AP1_MODELS", None])
def test_explicit_policy_wins_for_every_car(monkeypatch, override, model):
  monkeypatch.setattr(bg, "STALE_THERMAL_POLICY", override)
  assert bg.stale_thermal_policy(FakeParams(CarModel=model)) == override


def test_preap_fingerprint_alone_without_car_model_gets_nap():
  # an auto-fingerprinted Pre-AP car never sets CarModel; card's CarParamsPersistent alone must give nap
  assert bg.stale_thermal_policy(FakeParams(CarParamsPersistent=persistent("TESLA_PREAP_MODELS"))) == "nap"
  assert bg.stale_thermal_policy(FakeParams(CarModel=b"", CarParamsPersistent=persistent("TESLA_PREAP_MODELS"))) == "nap"


def test_hardwared_picks_the_policy_with_its_params():
  src = (pathlib.Path(__file__).resolve().parents[1] / "hardwared.py").read_text()
  assert src.count("stale_thermal_policy(params)") == 1 and "stale_thermal_policy()" not in src
