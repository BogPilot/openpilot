from openpilot.selfdrive.car.tesla.platform import EarlyPlatformFixture, classify_tesla_platform, long_control_allowed
from openpilot.selfdrive.car.tesla.values import CAR, TeslaPlatform


def test_ap1_model_s_maps_to_ap1_s_and_long_stays_off():
  platform = classify_tesla_platform(CAR.TESLA_AP1_MODELS)
  assert platform == TeslaPlatform.ap1_s
  assert long_control_allowed(platform) is False
  assert long_control_allowed(None) is False


def test_ap1_name_is_the_same_identity():
  assert classify_tesla_platform("TESLA_AP1_MODELS") == TeslaPlatform.ap1_s
  assert classify_tesla_platform([CAR.TESLA_AP1_MODELS, "TESLA_AP1_MODELS"]) == TeslaPlatform.ap1_s


def test_empty_and_garbage_are_unmatched():
  for fingerprint in (None, "", [], set(), {}, {0: {0x2bf: 8}}, b"\x00", 0, "not-a-tesla", "HONDA_CIVIC"):
    assert classify_tesla_platform(fingerprint) is None
    assert long_control_allowed(classify_tesla_platform(fingerprint)) is False


def test_ambiguous_ap1_and_ap2_is_refused():
  both = [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP2_MODELS]
  assert classify_tesla_platform(both) is None
  assert classify_tesla_platform(set(both)) is None
  assert long_control_allowed(None) is False


def test_raven_is_not_ap2():
  assert classify_tesla_platform(CAR.TESLA_MODELS_RAVEN) is None
  assert classify_tesla_platform(CAR.TESLA_MODELS_RAVEN) != TeslaPlatform.ap2
  assert classify_tesla_platform([CAR.TESLA_MODELS_RAVEN, CAR.TESLA_AP2_MODELS]) == TeslaPlatform.ap2
  assert classify_tesla_platform([CAR.TESLA_MODELS_RAVEN, CAR.TESLA_AP1_MODELS]) == TeslaPlatform.ap1_s


def test_ap2_alone_maps_to_ap2_without_long():
  platform = classify_tesla_platform(CAR.TESLA_AP2_MODELS)
  assert platform == TeslaPlatform.ap2
  assert platform != TeslaPlatform.ap1_s
  assert long_control_allowed(platform) is False


def test_ap1_model_s_does_not_select_preap_or_ap1_x():
  platform = classify_tesla_platform(CAR.TESLA_AP1_MODELS)
  assert platform != TeslaPlatform.preap
  assert platform != TeslaPlatform.ap1_x
  for candidate in (None, "", CAR.TESLA_AP2_MODELS, CAR.TESLA_MODELS_RAVEN, "TESLA_AP1_MODELS"):
    assert classify_tesla_platform(candidate) not in (TeslaPlatform.preap, TeslaPlatform.ap1_x)


def test_preap_and_ap1_x_only_from_explicit_fixture():
  assert classify_tesla_platform(EarlyPlatformFixture(TeslaPlatform.preap)) == TeslaPlatform.preap
  assert classify_tesla_platform(EarlyPlatformFixture(TeslaPlatform.ap1_x)) == TeslaPlatform.ap1_x
  assert long_control_allowed(TeslaPlatform.preap) is False
  assert long_control_allowed(TeslaPlatform.ap1_x) is False
  try:
    EarlyPlatformFixture(TeslaPlatform.ap1_s)
    raised = False
  except ValueError:
    raised = True
  assert raised


def test_long_refused_for_every_platform():
  for platform in TeslaPlatform:
    assert long_control_allowed(platform) is False
