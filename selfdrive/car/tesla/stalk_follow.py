"""AP1 stalk distance scroll to FrogPilot follow profiles.

Pure mapping. No CAN, no params, no controlsd, no actuation.

DTR_Dist_Rq on STW_ACTN_RQ (opendbc tesla_can.dbc and tesla_powertrain.dbc,
and Tinkla carstate): 0, 33, 66, 100, 133, 166, 200 are ACC_DIST_1..7.
255 is SNA. Those two sources agree, so this module does not invent a third scale.

Follow seconds are the stock FrogPilot defaults, not live params:
  traffic cruising gap is TRAFFIC_FOLLOW at v_ego >= CRUISING_SPEED (5 m/s): 1.00s
    (the same curve is 0.50s at 0 m/s; this module has no v_ego and does not apply it)
  aggressive / standard / relaxed are get_T_FOLLOW with custom_personalities false:
    1.25 / 1.45 / 1.75
  which match AggressiveFollow, StandardFollow, and RelaxedFollow defaults.
Intermediate detents use the midpoint of the neighboring named times. Each midpoint
is equidistant from those neighbors, so collapsing onto a cereal personality would
be arbitrary. get_T_FOLLOW is not imported: that module pulls car interfaces and
setproctitle. Do not edit get_T_FOLLOW, long_mpc, or frogpilot_following to add a profile.

Later call site, not this commit: a carstate parser may pass DTR_Dist_Rq into
map_stalk_follow. Do not call it from controlsd yet. When wiring, pass
decision.follow_s through the t_follow argument FrogPilotFollowing and
desired_follow_distance already take. Detent 1 sets traffic mode
(frogpilotCarState.trafficModeEnabled), not LongitudinalPersonality.
Detents 3, 5, and 7 are LongitudinalPersonality aggressive, standard, and relaxed.
Detents 2, 4, and 6 are follow times only. No new persisted param.
"""

from dataclasses import dataclass

# ACC_DIST_1 is the closest gap. Order is closest to farthest.
_DETENT_RAW = (0, 33, 66, 100, 133, 166, 200)
SNA = 255

_TRAFFIC_S = 1.00
_AGGRESSIVE_S = 1.25
_STANDARD_S = 1.45
_RELAXED_S = 1.75

_PROFILES = (
  # detent, profile, traffic, follow_s
  (1, "traffic", True, _TRAFFIC_S),
  (2, "closer_than_aggressive", False, (_TRAFFIC_S + _AGGRESSIVE_S) / 2),
  (3, "aggressive", False, _AGGRESSIVE_S),
  (4, "between_aggressive_and_standard", False, (_AGGRESSIVE_S + _STANDARD_S) / 2),
  (5, "standard", False, _STANDARD_S),
  (6, "between_standard_and_relaxed", False, (_STANDARD_S + _RELAXED_S) / 2),
  (7, "relaxed", False, _RELAXED_S),
)

_BY_RAW = {raw: index for index, raw in enumerate(_DETENT_RAW)}


@dataclass(frozen=True)
class StalkFollowDecision:
  ready: bool
  valid: bool
  detent: int | None
  profile: str | None
  traffic: bool
  follow_s: float | None
  raw: int | None


def detent_edges() -> tuple[float, ...]:
  """Halfway raw values between adjacent detents. The higher detent owns the edge."""
  return tuple((_DETENT_RAW[i] + _DETENT_RAW[i + 1]) / 2 for i in range(len(_DETENT_RAW) - 1))


def map_stalk_follow(raw: int | None, previous: StalkFollowDecision | None = None) -> StalkFollowDecision:
  """Map one DTR_Dist_Rq sample.

  Exact detents commit that profile. SNA (255) and None hold the previous
  decision. The first such sample, with no ready history, is not ready.

  A non-exact raw moves at most one detent, and only when it is inside the
  previous detent's neighbor span and at least halfway to that neighbor.
  The halfway point belongs to the farther detent (raw >= midpoint moves away
  from ACC_DIST_1; raw < midpoint moves toward it). Repeating the same raw
  does not change the detent again.

  Any other raw holds the last decision and is invalid. With no ready history
  it is not ready and does not guess a profile.
  """
  if raw is None or raw == SNA:
    return _hold(previous, raw, keep_valid=True)

  if not isinstance(raw, int) or isinstance(raw, bool):
    return _hold(previous, None, keep_valid=False)

  exact = _BY_RAW.get(raw)
  if exact is not None:
    return _commit(exact, raw)

  if previous is None or not previous.ready or previous.detent is None:
    return _not_ready(raw)

  if raw < _DETENT_RAW[0] or raw > _DETENT_RAW[-1]:
    return _hold(previous, raw, keep_valid=False)

  stepped = _step(previous.detent - 1, raw)
  if stepped is None or stepped == previous.detent - 1:
    return _hold(previous, raw, keep_valid=False)
  return _commit(stepped, raw)


def _step(current: int, raw: int) -> int | None:
  """Neighbor step, or None when raw is outside this detent's span."""
  low = _DETENT_RAW[current - 1] if current > 0 else _DETENT_RAW[0]
  high = _DETENT_RAW[current + 1] if current < len(_DETENT_RAW) - 1 else _DETENT_RAW[-1]
  if raw <= low or raw >= high:
    return None
  if current < len(_DETENT_RAW) - 1:
    midpoint = (_DETENT_RAW[current] + _DETENT_RAW[current + 1]) / 2
    if raw >= midpoint:
      return current + 1
  if current > 0:
    midpoint = (_DETENT_RAW[current - 1] + _DETENT_RAW[current]) / 2
    if raw < midpoint:
      return current - 1
  return current


def _commit(index: int, raw: int) -> StalkFollowDecision:
  detent, profile, traffic, follow_s = _PROFILES[index]
  return StalkFollowDecision(True, True, detent, profile, traffic, follow_s, raw)


def _hold(previous: StalkFollowDecision | None, raw: int | None, keep_valid: bool) -> StalkFollowDecision:
  if previous is None or not previous.ready:
    return _not_ready(raw)
  return StalkFollowDecision(
    previous.ready,
    previous.valid if keep_valid else False,
    previous.detent,
    previous.profile,
    previous.traffic,
    previous.follow_s,
    raw,
  )


def _not_ready(raw: int | None) -> StalkFollowDecision:
  return StalkFollowDecision(False, False, None, None, False, None, raw)
