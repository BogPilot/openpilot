"""AP1 Model S: FW autodetect and default longitudinal.

FW versions are from the user's AP1 rlogs (UDS F181 brake booster / radar, F188 EPAS).
AP2 / Raven versions are from BogPilot selfdrive/car/tesla/fingerprints.py; they share the AP1 brake
booster part (1037123-00-A) and must never match AP1.
"""
import re
from types import SimpleNamespace

from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.fw_versions import build_fw_dict, match_fw_to_car, match_fw_to_car_exact, match_fw_to_car_fuzzy
from opendbc.car.structs import CarParams
from opendbc.car.tesla.fingerprints import FW_VERSIONS
from opendbc.car.tesla.interface import CarInterface
from opendbc.car.tesla.values import CAR, FW_QUERY_CONFIG, TeslaAp1SafetyFlags, TeslaFlags, TeslaSafetyFlags

Ecu = CarParams.Ecu

AP1_EBB = b'1037123-00-A'
AP1_RADAR = b'\x01\x00W\x00\x00\x00\x07\x00\x00\x00\x00\x08\x00\x00\x00\x00\t\xff\xfe'
AP1_EPS = b'1016704-00-HAA' + b'\x00' * 10

AP2_RADAR = b'\x01\x00W\x00\x00\x00\x07\x00\x00\x00\x00\x08\x01\x00\x00\x00\x07\xff\xfe'
AP2_EPS = b'\x10#\x01'
RAVEN_RADAR = b'\x01\x00\x99\x02\x01\x00\x10\x00\x00AP8.3.03\x00\x10'
RAVEN_EPS = b'SX_0.0.0 (99),SR013.7'

M3Y_CARS = (CAR.TESLA_MODEL_3, CAR.TESLA_MODEL_Y, CAR.TESLA_MODEL_X)


def _fw(ecu, addr, version, rx_offset):
  return CarParams.CarFw(ecu=ecu, address=addr, subAddress=0, responseAddress=addr + rx_offset,
                         fwVersion=version, brand="tesla", bus=0)


def _ap1_fw(ebb=AP1_EBB, radar=AP1_RADAR, eps=AP1_EPS):
  fw = []
  if ebb is not None:
    fw.append(_fw(Ecu.electricBrakeBooster, 0x64d, ebb, 0x10))
  if radar is not None:
    fw.append(_fw(Ecu.fwdRadar, 0x671, radar, 0x10))
  if eps is not None:
    fw.append(_fw(Ecu.eps, 0x730, eps, 0x08))
  return fw


def _match(car_fw):
  return match_fw_to_car(car_fw, "", log=False)


class TestTeslaAp1Fingerprint:
  def test_ap1_fw_in_database(self):
    ecus = FW_VERSIONS[CAR.TESLA_MODEL_S_HW1]
    assert ecus[(Ecu.electricBrakeBooster, 0x64d, None)] == [AP1_EBB]
    assert ecus[(Ecu.fwdRadar, 0x671, None)] == [AP1_RADAR]
    # StarPilot's earlier HW1 EPS entry (b'\x10\x00A') is kept alongside the AP1 rlog version
    assert AP1_EPS in ecus[(Ecu.eps, 0x730, None)]

  def test_ap1_fw_format(self):
    # StarPilot's Tesla FW config has no fw_version_regex; check the AP1 rlog formats directly.
    ap1_re = br"\d{7}-\d{2}-[A-Z]{1,3}\x00*|\x01\x00W[\x00-\xff]{16}"
    for fw in (AP1_EBB, AP1_RADAR, AP1_EPS):
      assert re.fullmatch(ap1_re, fw) is not None, fw

  def test_user_fw_matches_ap1_exactly(self):
    exact, matches = _match(_ap1_fw())
    assert exact
    assert matches == {CAR.TESLA_MODEL_S_HW1}

  def test_ap1_without_eps_response_still_needs_eps(self):
    # EPS is an essential ECU: a missing F188 answer must not let AP1 match on radar + EBB alone
    assert _match(_ap1_fw(eps=None)) == (True, set())

  def test_unknown_radar_does_not_match(self):
    # Matching is exact. Another AP1 owner's radar version must be added to the database first.
    other_radar = AP1_RADAR[:-3] + b'\x0a\xff\xfe'
    assert _match(_ap1_fw(radar=other_radar)) == (True, set())

  def test_missing_radar_answer_still_matches_on_epas(self):
    # StarPilot's HW1 platform matched on the EPAS alone; the radar is non-essential for it so that stays true.
    assert _match(_ap1_fw(radar=None)) == (True, {CAR.TESLA_MODEL_S_HW1})

  def test_ap2_raven_never_match_ap1(self):
    # Same brake booster part as AP1, different radar/EPS
    for radar, eps in ((AP2_RADAR, AP2_EPS), (RAVEN_RADAR, RAVEN_EPS), (AP2_RADAR, AP1_EPS), (AP1_RADAR, AP2_EPS)):
      car_fw = _ap1_fw(radar=radar, eps=eps)
      assert CAR.TESLA_MODEL_S_HW1 not in _match(car_fw)[1]
      fw_dict = build_fw_dict(car_fw, filter_brand="tesla")
      assert CAR.TESLA_MODEL_S_HW1 not in match_fw_to_car_fuzzy(fw_dict, "tesla", log=False)

  def test_ap1_never_fuzzy_matches(self):
    # EPS and radar are excluded from fuzzy matching, so AP1 only has one fuzzy-eligible ECU (EBB)
    fw_dict = build_fw_dict(_ap1_fw(radar=AP2_RADAR, eps=b'1016704-00-XYZ' + b'\x00' * 10), filter_brand="tesla")
    assert match_fw_to_car_fuzzy(fw_dict, "tesla", log=False) == set()

  def test_model3y_fw_never_matches_ap1(self):
    for car_model in M3Y_CARS:
      for eps in FW_VERSIONS[car_model][(Ecu.eps, 0x730, None)]:
        car_fw = [_fw(Ecu.eps, 0x730, eps, 0x08)]
        exact, matches = _match(car_fw)
        assert CAR.TESLA_MODEL_S_HW1 not in matches, eps
        assert car_model in matches, eps
        # even with an AP1 EBB on the bus, no radar/EPS match means no AP1
        car_fw.append(_fw(Ecu.electricBrakeBooster, 0x64d, AP1_EBB, 0x10))
        assert CAR.TESLA_MODEL_S_HW1 not in match_fw_to_car_exact(build_fw_dict(car_fw, "tesla"), "tesla", log=False)

  def test_ap1_fw_never_matches_model3y(self):
    matches = match_fw_to_car_exact(build_fw_dict(_ap1_fw(), "tesla"), "tesla", log=False)
    assert not (matches & set(M3Y_CARS))

  def test_ap1_queries_are_separate(self):
    m3y, ap1_chassis, ap1_eps = FW_QUERY_CONFIG.requests
    # StarPilot's existing Model 3/Y query is unchanged (no whitelist)
    assert m3y.whitelist_ecus == []
    # AP1 brake booster 0x64d -> 0x65d, radar 0x671 -> 0x681
    assert ap1_chassis.whitelist_ecus == [Ecu.electricBrakeBooster, Ecu.fwdRadar]
    assert ap1_chassis.rx_offset == 0x10 and ap1_chassis.bus == 0
    assert ap1_chassis.request[-1] == b'\x22\xf1\x81'
    # AP1 EPAS 0x730 -> 0x738, F188
    assert ap1_eps.whitelist_ecus == [Ecu.eps]
    assert ap1_eps.rx_offset == 0x08 and ap1_eps.bus == 0
    assert ap1_eps.request[-1] == b'\x22\xf1\x88'
    for r in (ap1_chassis, ap1_eps):
      assert r.request[0] == b'\x3e\x00'
      assert not r.logging


class TestTeslaAp1Params:
  def _cp(self, alpha_long):
    return CarInterface.get_params(CAR.TESLA_MODEL_S_HW1, gen_empty_fingerprint(), _ap1_fw(), alpha_long, False, False,
                                   SimpleNamespace())

  def test_default_openpilot_long(self):
    for alpha_long in (False, True):
      CP = self._cp(alpha_long)
      assert CP.openpilotLongitudinalControl
      assert not CP.alphaLongitudinalAvailable
      assert CP.flags & TeslaFlags.AP1
      assert CP.safetyConfigs[0].safetyModel == structs.CarParams.SafetyModel.tesla
      assert CP.safetyConfigs[0].safetyParam == int(TeslaAp1SafetyFlags.HAS_AP | TeslaAp1SafetyFlags.LONG_CONTROL) == 18
      assert not CP.dashcamOnly
      assert not CP.steerAtStandstill

  def test_ap1_selector_clear_of_model3y_bits(self):
    # AP1 has its own param namespace (BogGyver/Tinkla numbering). Only the selector bit has to stay
    # clear of Model 3/Y/X bits so safety.h can never route a Model 3/Y param into tesla_ap1.h, and AP1 must
    # never carry FLAG_HW1 (8), which routes to tesla_legacy.h.
    assert not (int(TeslaAp1SafetyFlags.HAS_AP | TeslaAp1SafetyFlags.LONG_CONTROL) & int(TeslaSafetyFlags.FLAG_HW1))
    for flag in TeslaSafetyFlags:
      assert not (int(TeslaAp1SafetyFlags.HAS_AP) & int(flag)), flag

  def test_model3y_unchanged(self):
    for car_model in M3Y_CARS:
      CP = CarInterface.get_params(car_model, gen_empty_fingerprint(), [], False, False, False, SimpleNamespace())
      assert not CP.openpilotLongitudinalControl
      assert CP.safetyConfigs[0].safetyParam & int(TeslaAp1SafetyFlags.HAS_AP) == 0
      assert not (CP.flags & TeslaFlags.AP1)
