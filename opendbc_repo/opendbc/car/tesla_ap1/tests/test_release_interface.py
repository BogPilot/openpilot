"""Release-base registration, fail-closed selection and parser smoke tests."""
import os
import pytest
from opendbc.car import Bus, gen_empty_fingerprint, structs
from opendbc.car.car_helpers import interfaces
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.values import CAR, AP1_CHASSIS_SIGNATURE


def fingerprint():
  fp = gen_empty_fingerprint()
  fp[0] = dict(AP1_CHASSIS_SIGNATURE)
  fp[2] = {0x399: 8, 0x2B9: 8, 0x488: 4}
  return fp


def params(fp=None):
  return CarInterface.get_params(CAR.TESLA_AP1_MODELS, fingerprint() if fp is None else fp, [], False, False, False)


def test_ap1_registered_separately_from_stock_tesla():
  assert interfaces[CAR.TESLA_AP1_MODELS] is CarInterface
  from opendbc.car.tesla.values import CAR as TESLA
  for model in TESLA:
    assert interfaces[model].__module__ == "opendbc.car.tesla.interface"


def test_no_preap_actuation_from_chassis_or_fixed_name_alone():
  for fp in (gen_empty_fingerprint(), {0:dict(AP1_CHASSIS_SIGNATURE)}):
    cp = params(fp)
    assert cp.dashcamOnly and not cp.openpilotLongitudinalControl
    assert str(cp.safetyConfigs[0].safetyModel) == "noOutput"


def test_ap1_uses_stream2_safety_contract_and_stock_pcm_stalk():
  cp = params()
  assert cp.brand == "tesla_ap1" and not cp.dashcamOnly
  assert cp.openpilotLongitudinalControl and cp.pcmCruise
  assert str(cp.safetyConfigs[0].safetyModel) == "tesla"
  assert cp.safetyConfigs[0].safetyParam == 25
  assert cp.wheelbase == pytest.approx(2.959)
  assert cp.steerRatio == pytest.approx(15.0)


def test_ap1_parsers_initialize_without_data():
  ci = CarInterface(params())
  assert ci.CS is not None and ci.CC is not None


def test_carstate_roundtrip_requires_stream6_schema():
  if "bogpilot" not in structs.CarState.schema.fields:
    if os.environ.get("BOGPILOT_REQUIRE_SCHEMA"):
      pytest.fail("stream 6: CarState.bogpilot/BogPilotCarState is missing")
    pytest.skip("integration dependency: stream 6 CarState.bogpilot/BogPilotCarState")
  ci = CarInterface(params())
  cs = ci.update([])
  assert not cs.canValid
  with structs.CarState.from_bytes(cs.to_bytes()) as restored:
    assert restored.bogpilot.ap1StalkFollowS == cs.bogpilot.ap1StalkFollowS


def _select(monkeypatch, candidate, fp):
  import inspect
  from opendbc.car import car_helpers
  from opendbc.car.vin import VIN_UNKNOWN
  monkeypatch.setattr(car_helpers, "fingerprint", lambda *args: (
    candidate, fp, VIN_UNKNOWN, [], structs.CarParams.FingerprintSource.can, True))
  kwargs = {"cached_params": None}
  if "num_pandas" in inspect.signature(car_helpers.get_car).parameters:
    kwargs["num_pandas"] = 1
  return car_helpers.get_car(lambda *args: [], lambda *args: None, lambda *args: None, False, False, **kwargs)


def test_fallback_selects_ap1_only_after_upstream_failed(monkeypatch):
  ci = _select(monkeypatch, None, fingerprint())
  assert ci.CP.carFingerprint == CAR.TESLA_AP1_MODELS


def test_fallback_does_not_override_stock_model3(monkeypatch):
  from opendbc.car.tesla.values import CAR as TESLA
  ci = _select(monkeypatch, TESLA.TESLA_MODEL_3, fingerprint())
  assert ci.CP.brand == "tesla" and ci.CP.carFingerprint == TESLA.TESLA_MODEL_3


def test_preap_chassis_falls_back_to_mock_not_ap1(monkeypatch):
  ci = _select(monkeypatch, None, {0:dict(AP1_CHASSIS_SIGNATURE)})
  assert ci.CP.brand == "mock"


def test_selfdrived_owns_gas_disengagement_and_brake_is_never_suppressed():
  # Evaluate the actual target's pedal-event predicate without launching a
  # driving process or substituting the entire old controlsd implementation.
  import ast
  from pathlib import Path
  from types import SimpleNamespace as NS
  import openpilot.selfdrive
  source = Path(openpilot.selfdrive.__file__).parent / "selfdrived/selfdrived.py"
  tree = ast.parse(source.read_text())
  predicate = next(node.test for node in ast.walk(tree) if isinstance(node, ast.If) and
                   any(isinstance(child, ast.Attribute) and child.attr == "pedalPressed"
                       for statement in node.body if isinstance(statement, ast.Expr) for child in ast.walk(statement)))
  expression = compile(ast.Expression(predicate), str(source), "eval")
  previous = NS(gasPressed=False, brakePressed=False, regenBraking=False)
  cs = NS(gasPressed=True, brakePressed=False, regenBraking=False, standstill=False)
  owner = NS(CS_prev=previous, disengage_on_accelerator=True)
  assert eval(expression, {}, {"self":owner, "CS":cs})
  owner.disengage_on_accelerator = False
  assert not eval(expression, {}, {"self":owner, "CS":cs})
  cs.brakePressed = True
  assert eval(expression, {}, {"self":owner, "CS":cs})


def test_crc_matches_standard_check_vector():
  from opendbc.can import CANPacker
  from opendbc.car.tesla_ap1.teslacan import TeslaCAN
  can = TeslaCAN(CANPacker("tesla_ap1_can"), CANPacker("tesla_powertrain"))
  assert can.crc(b"123456789") == 0x4B


def test_disabling_longitudinal_keeps_ap1_safety_in_stock_mode(monkeypatch):
  import opendbc.car.tesla_ap1.interface as interface
  monkeypatch.setattr(interface, "disable_openpilot_long", lambda: True)
  cp = params()
  assert not cp.openpilotLongitudinalControl
  assert cp.safetyConfigs[0].safetyParam == 9  # AP1 chassis neutral messages, no standstill experiment


def test_bosch_radar_roundtrip_uses_target_radarpoint_schema():
  from opendbc.can import CANPacker
  from opendbc.car.tesla_ap1.radar_interface import RadarInterface
  from opendbc.car.tesla_ap1.values import DBC
  radar = RadarInterface(params())
  packer = CANPacker(DBC[CAR.TESLA_AP1_MODELS][Bus.radar])
  frames = [packer.make_can_msg("TeslaRadarSguInfo", 1, {}),
            packer.make_can_msg("RadarPoint0_A", 1, {"Tracked": 1, "Meas": 1, "Index": 1,
                                                      "LongDist": 40.0, "LatDist": 1.0, "LongSpeed": -2.0}),
            packer.make_can_msg("RadarPoint0_B", 1, {"Index2": 1}),
            packer.make_can_msg("RadarPoint31_B", 1, {})]
  output = radar.update([(1_000_000_000, frames)])
  assert output is not None and len(output.points) == 1
  assert output.points[0].dRel == pytest.approx(40.0)
  assert output.points[0].yRel == pytest.approx(1.0)
  assert output.points[0].vRel == pytest.approx(-2.0)
