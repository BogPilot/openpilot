"""Model X AP1 marker detection. Data is Tinkla's capture; no AP2 platform exists."""
from opendbc.car.tesla_ap1.modelx_fingerprint import (
  ap1_sx_ambiguous,
  detect_ap1_candidate,
  match_ap1_modelx,
  s_contradicts_x,
  s_evidence,
  x_evidence,
)
from opendbc.car.tesla_ap1.modelx_fingerprint_data import TINKLA_AP1_MODELX as PROD_X
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import (
  TINKLA_AP1_MODELX,
  TINKLA_AP1_MODELS_VARIANTS,
  TINKLA_AP2_MODELX,
  TINKLA_AP2_MODELS,
  TINKLA_PREAP_MODELS,
)
from opendbc.car.tesla_ap1.values import AP1_CHASSIS_SIGNATURE, CAR, match_ap1_chassis

X = CAR.TESLA_AP1_MODELX
S = CAR.TESLA_AP1_MODELS
MOBILEYE = {0x399: 8, 0x2B9: 8, 0x488: 4}


def _fp(bus0, mobileye=True):
  fp = {0: dict(bus0)}
  if mobileye:
    fp[2] = dict(MOBILEYE)
  return fp


def test_production_dict_matches_tinkla_capture():
  assert PROD_X == TINKLA_AP1_MODELX
  assert len(PROD_X) == 252


def test_clean_model_x_detects_as_x():
  fp = _fp(TINKLA_AP1_MODELX)
  assert detect_ap1_candidate(fp) == X
  assert match_ap1_modelx(fp) is True
  assert x_evidence(fp)
  assert s_evidence(fp) == frozenset()
  assert s_contradicts_x(fp) is False


def test_tinkla_model_s_variants_stay_s():
  for variant in TINKLA_AP1_MODELS_VARIANTS:
    fp = _fp(variant)
    assert x_evidence(fp) == frozenset()
    assert match_ap1_modelx(fp) is False
    assert detect_ap1_candidate(fp) == S
    assert s_contradicts_x(fp) is True
    assert detect_ap1_candidate(fp) == (S if match_ap1_chassis(fp) else None)


def test_old_s_chassis_fixture_is_unchanged():
  fp = _fp(AP1_CHASSIS_SIGNATURE)
  assert x_evidence(fp) == frozenset()
  assert match_ap1_modelx(fp) is False
  assert detect_ap1_candidate(fp) == S
  assert detect_ap1_candidate(fp) == (S if match_ap1_chassis(fp) else None)
  # Empty X evidence keeps the previous chassis rule, including a miss.
  chassis_only = {0: dict(AP1_CHASSIS_SIGNATURE)}
  assert detect_ap1_candidate(chassis_only) is None
  assert match_ap1_chassis(chassis_only) is False


def test_conflicts_and_incomplete_x_are_not_detected():
  # S-only message on an otherwise clean X: ambiguous, not S and not X.
  mixed = _fp(TINKLA_AP1_MODELX)
  mixed[0][0x201] = 5
  assert x_evidence(mixed)
  assert s_evidence(mixed)
  assert match_ap1_modelx(mixed) is False
  assert ap1_sx_ambiguous(mixed) is True
  assert detect_ap1_candidate(mixed) is None

  # X markers without Mobileye bus 2.
  no_meye = _fp(TINKLA_AP1_MODELX, mobileye=False)
  assert ap1_sx_ambiguous(no_meye) is True
  assert detect_ap1_candidate(no_meye) is None

  # Address that is not in Tinkla's X dict.
  extra = _fp(TINKLA_AP1_MODELX)
  extra[0][0x123] = 8
  assert 0x123 not in TINKLA_AP1_MODELX
  assert detect_ap1_candidate(extra) is None
  assert ap1_sx_ambiguous(extra) is True

  # One X marker plus an S-only message is not a clean X.
  partial_conflict = _fp({0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8, 0x2F1: 8, 0x165: 8})
  assert detect_ap1_candidate(partial_conflict) is None

  # One X marker, chassis, Mobileye, and only addresses that are in the X dict is X.
  partial = _fp({0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8, 0x2F1: 8})
  assert detect_ap1_candidate(partial) == X

  # 0x303 length splits the two cars.
  assert 0x303 in x_evidence(_fp({0x303: 8, 0x2F1: 8}))
  assert 0x303 in s_evidence(_fp({0x303: 2}))

  # Addresses at or above 0x800 are ignored by the elimination rule.
  high = _fp(TINKLA_AP1_MODELX)
  high[0][0x800] = 3
  assert detect_ap1_candidate(high) == X


def test_ap2_and_preap_are_not_platforms():
  # Tinkla's AP2 Model X dict is an identical copy of the AP1 Model X dict.
  # There is no AP2 candidate. The same bytes detect as AP1 Model X.
  assert TINKLA_AP2_MODELX == TINKLA_AP1_MODELX
  assert not hasattr(CAR, "TESLA_AP2_MODELX")
  assert not hasattr(CAR, "TESLA_AP2_MODELS")
  assert detect_ap1_candidate(_fp(TINKLA_AP2_MODELX)) == X

  # AP2 Model S has no X marker. Empty X evidence keeps the old chassis rule,
  # so this capture is Model S AP1, not an AP2 platform.
  ap2_s = _fp(TINKLA_AP2_MODELS)
  assert x_evidence(ap2_s) == frozenset()
  assert detect_ap1_candidate(ap2_s) == S

  # PreAP as captured (bus 0 only, no Mobileye) is not AP1.
  preap = {0: dict(TINKLA_PREAP_MODELS)}
  assert x_evidence(preap) == frozenset()
  assert detect_ap1_candidate(preap) is None


def test_garbage_inputs():
  for bad in (None, [], "foo", 1, {0: "nope"}, {0: {True: 8}}, {"0": {0x2F1: 8}}):
    assert x_evidence(bad) == frozenset()
    assert s_evidence(bad) == frozenset()
    assert match_ap1_modelx(bad) is False
    assert ap1_sx_ambiguous(bad) is False
    assert detect_ap1_candidate(bad) is None
    assert s_contradicts_x(bad) is False


def test_no_s_x_cross_match():
  own = {
    X: (_fp(TINKLA_AP1_MODELX), _fp(TINKLA_AP2_MODELX)),
    S: tuple(_fp(v) for v in TINKLA_AP1_MODELS_VARIANTS) + (_fp(TINKLA_AP2_MODELS), _fp(AP1_CHASSIS_SIGNATURE)),
  }
  for expected, fps in own.items():
    other = S if expected == X else X
    for fp in fps:
      got = detect_ap1_candidate(fp)
      assert got == expected
      assert got != other
  assert detect_ap1_candidate({0: dict(TINKLA_PREAP_MODELS)}) not in (S, X)
