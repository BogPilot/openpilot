# AP1 and Pre-AP: far camera-only leads need a higher model confidence

AP1 Model S (`TESLA_AP1_MODELS`) and Pre-AP Model S (`TESLA_PREAP_MODELS`). Nothing changes on Model X, AP2 or any other platform.

## Reference behaviour
- Stock openpilot 0.11.2 `radard.get_lead` uses a camera lead (prob above the detection threshold) with no radar track
  matched as a camera-only lead at any distance. Tinkla, NAP and 0.9.7 do the same.
- This tree already lowers the threshold from 0.50 to 0.35 (`LeadDetectionThreshold`, default 35) for earlier lead pickup.

## Ours
- Threshold stays at 0.35.
- A camera-only lead (no radar track matched) strictly beyond 50 m (camera range minus the 1.52 m radar offset) needs
  prob of 0.6 or more (the lead-probability-filtered value), unless ego is closing on it at 5 m/s (11 mph) or more
  (`v_ego - lead.v >= 5`). Otherwise it is not used as a lead, and the low-speed override and radar-matched leads work as before.
- Applies to both lead slots. Radar-matched leads, leads within 50 m, the AP1 glitch filter and the Pre-AP radar point filters (stuck track, Bosch point gate) are unchanged. On Pre-AP the gate sees only what is left after those filters: a track the stuck filter withholds becomes a camera-only lead, and the gate then applies to it beyond 50 m.
- Constants: `VISION_ONLY_FAR_M`, `VISION_ONLY_FAR_PROB`, `VISION_ONLY_CLOSING_MS` in `selfdrive/controls/radard.py`.
  Wired as `RadarD(vision_only_gate=...)`, on when `vision_only_gate_platform(CP.carFingerprint)` is true (AP1 Model S and Pre-AP Model S). No toggle.
- Why: an AP1 drive showed phantom braking from weak camera-only leads (prob 0.35 to 0.6) far ahead with no radar
  confirmation, caused by the 0.35 threshold. Raising the threshold itself delays real leads; this rule does not.

## Data (replay, 715 segments of AP1 drives, radard logic as in this file, surrogate brake request, no MPC)
- Same-lane pickups (421): 0 later than stock 0.35, 0 never picked. Worst delay 0.
- Cut-ins (303): 0 not selected within 10 s, 0 later first brake request.
- Frames with TTC under 3 s (10,506): 0 where the lead is lost or delayed by more than 0.5 s.
- Regen start (260 events): 0 later by more than 0.25 s.
- Unconfirmed camera-lead time: down 25 % off-highway and 34 % on highway.
- Braking frames of one phantom-brake drive with a false lead present: 74 -> 57.
- Without the closing-speed exemption the replay missed 1 of 303 cut-ins. That event was a camera-only stopped
  object approached at 6 to 7 m/s, which the exemption keeps.
- Not covered: the real MPC response, road behaviour, or any platform other than AP1 Model S.

## Pre-AP data (proxy; there are no Pre-AP drive logs in the archive)
- No Pre-AP rlogs exist on the team Macs or the 14 TB archive (all logged drives fingerprint as AP1 Model S). So the Pre-AP numbers below are a PROXY: the same 715 AP1 segments (same Bosch radar and camera model) replayed through the Pre-AP radard path: the branch's real `get_lead`, `Track`, `KalmanParams` and `vision_only_lead_blocked`, plus the real `StuckTrackFilter`, no AP1 glitch filter, and no radar-only low-speed lead. Nothing was measured on a Pre-AP car.
- Gate on vs gate off, surrogate brake request, no MPC (`work/scratch/preap_vo60_proxy_20261121`):
  - Same-lane pickups (429 events, 25 to 50 mph): 0 later than 0.25 s, 0 never picked, worst delay 0.
  - Cut-ins (418): 0 not selected within 10 s, 0 later first brake request.
  - Regen start (169 events): 0 later by more than 0.25 s.
  - Lead frames removed: 9,432 of 796,656 (1.2 %). Every one is a camera-only lead (radar flag off) at 164 ft or farther; of the engaged ones (6,628), none has a closing TTC under 8 s, and 333 close at 6.7 mph or more (max 14.6 mph) but all are 8 s or more away.
  - TTC under 3 s (2,450 lead frames): 0 lost.
  - Of the removed engaged frames, 6,196 had no radar track near the lead (false-lead candidates) and 432 had a radar track near it that the model lead did not match (205 of them in path and closing 2.2 mph or more, all with TTC of 8 s or more).
- Bound that holds without data: a lead is blocked only when it is beyond 164 ft and ego closes on it slower than 11 mph, so the time to reach it is at least about 10 s at the moment of blocking. A lead that is stopped or slowing hard is exempt by the closing-speed rule as soon as ego is at 11 mph or more.
- Not covered: any Pre-AP drive, the radar-behind-nosecone degradations and radar dropouts a Pre-AP car may see more often than AP1, the real MPC response. First Pre-AP drive with a log should be replayed with the same scripts.

## Safety-relevant
Yes (lead selection). It can only remove a camera-only lead that is far away and low confidence and that ego is not closing on quickly.

## Tests
`openpilot/selfdrive/controls/tests/test_ap1_vision_only_lead_gate.py` (AP1 and Pre-AP cases, platform selection).
