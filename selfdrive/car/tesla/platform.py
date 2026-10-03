"""Map an already-resolved Tesla identity to TeslaPlatform. No actuation."""

from dataclasses import dataclass

from openpilot.selfdrive.car.tesla.values import CAR, TeslaPlatform

# Production identities that exist in this tree.
# CAR.TESLA_AP1_MODELS has no FW_VERSIONS row in fingerprints.py, so the
# platform enum member is the AP1 Model S identity. Do not match on shared
# CarSpecs or dbc_dict: AP1 and AP2 share those, and that would be ambiguous.
# CAR.TESLA_MODELS_RAVEN is intentionally absent. Raven is not ap2.
_PRODUCTION = {
  CAR.TESLA_AP1_MODELS: TeslaPlatform.ap1_s,
  CAR.TESLA_AP2_MODELS: TeslaPlatform.ap2,
}

_FIXTURE_ONLY = (TeslaPlatform.preap, TeslaPlatform.ap1_x)


@dataclass(frozen=True)
class EarlyPlatformFixture:
  """Test-built identity for preap and ap1_x.

  Not a CAN fingerprint and not an FW query result. Production recognition
  does not construct this. preap and ap1_x stay unmatched until a real
  fingerprint exists.
  """

  platform: TeslaPlatform

  def __post_init__(self) -> None:
    if self.platform not in _FIXTURE_ONLY:
      raise ValueError("EarlyPlatformFixture is only for preap and ap1_x")


def classify_tesla_platform(fingerprint) -> TeslaPlatform | None:
  """Return one TeslaPlatform, or None when the identity is empty or ambiguous.

  None means longitudinal is not allowed. A CAN message-count dict is not a
  fingerprint for this function and returns None. preap and ap1_x are returned
  only for an EarlyPlatformFixture.
  """
  if isinstance(fingerprint, EarlyPlatformFixture):
    return fingerprint.platform

  candidates = _candidates(fingerprint)
  if not candidates:
    return None

  matched: set[TeslaPlatform] = set()
  for token in candidates:
    if isinstance(token, EarlyPlatformFixture):
      matched.add(token.platform)
      continue
    try:
      resolved = _PRODUCTION.get(token)
    except TypeError:
      resolved = None
    if resolved is not None:
      matched.add(resolved)

  if len(matched) != 1:
    return None
  return next(iter(matched))


def long_control_allowed(platform: TeslaPlatform | None) -> bool:
  """Whether longitudinal commands are allowed.

  False for None. False for every TeslaPlatform, including ap1_s. This layer
  only recognizes. Longitudinal stays refused until a later layer adds a panda
  safety mode. Do not engage long from this helper.
  """
  if platform is None or isinstance(platform, TeslaPlatform):
    return False
  return False


def _candidates(fingerprint) -> list:
  if fingerprint is None:
    return []
  # CAR members and names are strings. Do not iterate them into characters.
  # A dict is an openpilot CAN fingerprint (bus -> addresses). Do not invent
  # a message-count match from it.
  if isinstance(fingerprint, (str, bytes)):
    return [fingerprint]
  if isinstance(fingerprint, dict):
    return []
  if isinstance(fingerprint, (list, tuple, set, frozenset)):
    return list(fingerprint)
  return [fingerprint]
