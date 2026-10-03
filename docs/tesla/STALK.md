# AP1 stalk follow distance

BogPilot is not a product. No warranty. The driver remains responsible. Comply with local law. This commit does not command the car and is not a driving validation.

## Scale

`DTR_Dist_Rq` on `STW_ACTN_RQ` is the traffic-aware cruise stalk distance request. `opendbc/tesla_can.dbc`, `opendbc/tesla_powertrain.dbc`, and Tinkla `selfdrive/car/tesla/carstate.py` (the `cruise_distance` comment: pos1=0 through pos7=200, SNA=255) all use the same seven values. No third scale. Nothing was added to `docs/tesla/DIVERGENCES.md`.

| Raw | Detent | Profile | Follow seconds |
| --- | --- | --- | --- |
| 0 | ACC_DIST_1 | traffic | 1.00 |
| 33 | ACC_DIST_2 | closer_than_aggressive | 1.125 |
| 66 | ACC_DIST_3 | aggressive | 1.25 |
| 100 | ACC_DIST_4 | between_aggressive_and_standard | 1.35 |
| 133 | ACC_DIST_5 | standard | 1.45 |
| 166 | ACC_DIST_6 | between_standard_and_relaxed | 1.60 |
| 200 | ACC_DIST_7 | relaxed | 1.75 |

ACC_DIST_1 is the closest gap. ACC_DIST_7 is the farthest. 255 is SNA and is not a detent.

Named follow times are stock FrogPilot defaults, not live params and not a new param:

- Traffic uses `TRAFFIC_FOLLOW` at `v_ego >= CRUISING_SPEED` (5 m/s), which is 1.00 seconds. The same curve is 0.50 seconds at 0 m/s. This module does not see speed, so it does not apply that interpolation.
- Aggressive, standard, and relaxed are `get_T_FOLLOW` with `custom_personalities` false: 1.25, 1.45, and 1.75 seconds. Those match the `AggressiveFollow`, `StandardFollow`, and `RelaxedFollow` defaults.

The three intermediate rows are the midpoint of the neighboring named times. Each midpoint is equidistant from those neighbors, so picking the nearest cereal personality would be an arbitrary collapse. `long_mpc` and `frogpilot_following` are not modified.

## Hysteresis

Implemented in `selfdrive/car/tesla/stalk_follow.py` (`map_stalk_follow`). Exact raw values in the table commit that row.

SNA (255) and `None` hold the previous decision, including its validity. The first sample, with no ready history, is not ready and is not a guessed profile.

A non-exact value moves at most one detent. It has to fall strictly inside the previous detent's neighbor span (between the adjacent table raws, excluding those endpoints), and it has to be at least halfway to that neighbor. The halfway point belongs to the farther detent: `raw >= midpoint` steps away from ACC_DIST_1, and `raw < midpoint` steps toward it. Repeating the same raw does not step again.

Halfway points: 16.5, 49.5, 83, 116.5, 149.5, 183. On an upward integer sweep the steps are 17, 50, 83, 117, 150, 183. On a downward sweep they are 182, 149, 116, 82, 49, 16.

Any other raw holds the last profile and is invalid. That includes 1 (inside the closest span but not halfway, and outside every farther detent's neighbor span) and 999 (outside 0..200). The first unknown sample is not ready.

## Not wired

This commit does not call the mapper from `controlsd`, `carcontroller.py`, or `interface.py`. It does not actuate. A later carstate parser can pass `DTR_Dist_Rq` into `map_stalk_follow` and then pass `follow_s` through the `t_follow` argument `FrogPilotFollowing` and `desired_follow_distance` already accept. Detent 1 is traffic mode, not `LongitudinalPersonality`. Detents 3, 5, and 7 are `aggressive`, `standard`, and `relaxed`. Detents 2, 4, and 6 are follow times only.
