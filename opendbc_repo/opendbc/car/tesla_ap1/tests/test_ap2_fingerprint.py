"""AP2 Model S marker guard. Tinkla data only, no AP2 capture exists in our logs."""
from opendbc.car.tesla_ap1.ap2_fingerprint import AP2_S_MIN_MARKERS, AP2_S_ONLY, ap2_s_evidence, looks_like_ap2_s
from opendbc.car.tesla_ap1.modelx_fingerprint import detect_ap1_candidate
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import (
  TINKLA_AP1_MODELS_VARIANTS,
  TINKLA_AP1_MODELX,
  TINKLA_AP2_MODELS,
  TINKLA_PREAP_MODELS,
)
from opendbc.car.tesla_ap1.values import CAR

S = CAR.TESLA_AP1_MODELS
MOBILEYE = {0x399: 8, 0x2B9: 8, 0x488: 4}
CHASSIS = {0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8}


def _fp(bus0):
  return {0: dict(bus0), 2: dict(MOBILEYE)}


def test_markers_come_from_tinkla_ap2_s_and_nowhere_else():
  for addr, length in AP2_S_ONLY.items():
    assert TINKLA_AP2_MODELS[addr] == length
    assert addr not in TINKLA_AP1_MODELX
    assert addr not in TINKLA_PREAP_MODELS
    for variant in TINKLA_AP1_MODELS_VARIANTS:
      assert addr not in variant


def test_radar_bus_addresses_are_not_markers():
  # 0x32B and 0x350 are in Tinkla's AP2 S dict only but appear on the AP1 radar bus.
  assert 0x32B not in AP2_S_ONLY and 0x350 not in AP2_S_ONLY


def test_tinkla_ap2_s_capture_is_not_ap1_s():
  fp = _fp(TINKLA_AP2_MODELS)
  assert len(ap2_s_evidence(fp)) == len(AP2_S_ONLY)
  assert looks_like_ap2_s(fp)
  assert detect_ap1_candidate(fp) is None


def test_every_ap1_s_variant_still_detects_as_s():
  for variant in TINKLA_AP1_MODELS_VARIANTS:
    fp = _fp(variant)
    assert not looks_like_ap2_s(fp)
    assert detect_ap1_candidate(fp) == S


def test_marker_threshold():
  markers = list(AP2_S_ONLY.items())
  few = _fp({**CHASSIS, **dict(markers[:AP2_S_MIN_MARKERS - 1])})
  assert detect_ap1_candidate(few) == S
  enough = _fp({**CHASSIS, **dict(markers[:AP2_S_MIN_MARKERS])})
  assert detect_ap1_candidate(enough) is None


def test_marker_needs_matching_length_and_bus_zero():
  wrong_len = _fp({**CHASSIS, **{a: 3 for a in AP2_S_ONLY}})
  assert not looks_like_ap2_s(wrong_len)
  assert detect_ap1_candidate(wrong_len) == S
  other_bus = {0: dict(CHASSIS), 1: dict(AP2_S_ONLY), 2: dict(MOBILEYE)}
  assert not looks_like_ap2_s(other_bus)
  assert detect_ap1_candidate(other_bus) == S


def test_garbage_inputs():
  for bad in (None, [], "foo", 1, {0: "nope"}, {0: {True: 8}}, {"0": dict(AP2_S_ONLY)}):
    assert ap2_s_evidence(bad) == frozenset()
    assert looks_like_ap2_s(bad) is False
