# Phase 3 lane-change / adjacent-radar handoff

Primary e7d8fe75 is sole integration/deployment owner. This lane makes NO deployment, CAN, vehicle, road, or bench changes.

## Exact scope and historical inventory (read before implementation)

Reference: existing repository's own `04d560f3` (0.9.7 bogpilot-tesla), not an upstream/newer fork. Evidence exports accompany this note.

`frogpilot/ui/qt/offroad/lateral_settings.cc` / `.h` and the historical Python metadata establish:

| Historical path | Key | Exact label | Range / nesting |
|---|---|---|---|
| BogPilot / Driving Controls / Steering | LaneChanges | Lane Changes | Master + manage button |
| Steering / Lane Changes | NudgelessLaneChange | Automatic Lane Changes | Boolean |
| Steering / Lane Changes | LaneChangeTime | Lane Change Delay | 0–5 sec, 0.1 step; shown when automatic enabled |
| Steering / Lane Changes | MinimumLaneChangeSpeed | Minimum Lane Change Speed | 0–99 mph / 0–150 km/h, 1 step |
| Steering / Lane Changes | LaneDetectionWidth | Minimum Lane Width | 0–15 ft / 0–5 m, 0.1 step; shown when automatic enabled |
| Steering / Lane Changes | OneLaneChange | One Lane Change Per Signal | Boolean |
| Steering / Lateral Tuning | TurnDesires | Force Turn Desires Below Lane Change Speed | Boolean; LateralTune parent; OFF by default |
| Gas / Brake / Longitudinal Tuning | HumanLaneChanges | Human-Like Lane Changes | Boolean; radar + openpilot longitudinal + LongitudinalTune |

The Human row was NOT a Steering submenu in 0.9.7. Export `HUMAN_ROW`/`HUMAN_PATH` to the Gas/Brake integration lane rather than silently relocating it. Import `human_lane_change_item` to attach its actual native control to the existing Gas/Brake parent. This lane supplies that gated native item and its functional consumer, not merely a visibility flag.

Historical consumers: `selfdrive/controls/lib/desire_helper.py` handled lane master, automatic delay, lane-width eligibility and one-per-signal; `frogpilot/common/frogpilot_utilities.py:calculate_lane_width` used median adjacent-line spacing with a road-edge veto. `selfdrive/controls/radard.py:match_vision_to_track` preferred the closest target-lane radar track during laneChangeStarting. Historical HumanLaneChanges was NOT a lane-clearance/blindspot permission and did not initiate a lane change.

AOL/safety capability belongs to lane 8; controller tuning/NNFF and QoL belong to lane 10. Parent follow-up explicitly assigned TurnDesires to this lane, now implemented here with its exact historical LateralTune parent. No steering gain, actuator tuning, carcontroller, opendbc safety or panda file changes.

## Deliverables and integration order

Isolated lane worktree, branch `port/phase3-steering-lanechange`, based on committed candidate `c6582fc3efc1038b4e0e6bca8a6841b657e8ccf6`.

1. Cherry-pick the three local lane commits (see commits.txt). Only new uniquely named module/UI/tests/docs files are in them.
2. Review and apply **separate unapplied** `desire_helper.patch`, `modeld.patch`, `radard.patch` against your integration checkout. They change shared files deliberately excluded from this lane's commit. Reconcile with other control-lane patches before applying. `core-net.diff` combines these proposals.
3. Only then add Steering -> Lane Changes native navigation, instantiate `LaneChangeLayout(store, runtime_integrated=True, offroad=<real offroad predicate>)`. Default `runtime_integrated=False` exposes zero rows and refuses layout construction. No fake active controls are registered. Offroad predicate is mandatory for writes; absent predicate means read-only.
4. Gas/Brake owner should attach `human_lane_change_item(store, CP, runtime_integrated=True, offroad=<real predicate>)` at historical `LongitudinalTune` parent. The helper enforces radar/op-long/parent eligibility and allows a saved-OFF child to remain visible. It is functional only after radard.patch is installed. No standalone Human UI switch was attached to any central menu by this lane.
5. Lane 10 should import `turn_desire_item(store, runtime_integrated=True, offroad=<real predicate>)` into Steering / Lateral Tuning after desire_helper.patch + modeld.patch are integrated. This is the missing historical TurnDesires child, separate from lane-change initiation. It needs LateralTune ON, is OFF by default and preserves saved settings. Historical consumer was the final below-lane-change-speed turnLeft/turnRight branch in DesireHelper; no new navigation/turn algorithm is invented.
6. Re-run tests against the integrated root (`PHASE3_CORE_OVERLAY=$PWD`) and run AGNOS process/IPC replay and native UI acceptance before deployment. Do not call these features live-validated.

## Producer -> consumer trace

- SettingsReader reads existing ParamStore, preserving raw saved values and historical tuning-level eligibility; it never writes defaults or rewrites params. Refresh is <=2 sec. Read errors drop automatic/human permissions instead of keeping stale ON state.
- Modeld passes its current model output and actual publication validity plus carState/carControl input checks into DesireHelper. DesireHelper consumes the policy and stays the owner of stock state transitions, 0.5-sec start and 10-sec timeout.
- TurnDesires follows the authentic LateralTune -> use_turn_desires consumer: below minimum lane-change speed, single explicit signal and moving/not-standstill yields model turnLeft/turnRight. Additional safety gates require lateral_active, valid current model and finite probability/speed. It cannot engage steering or AOL.
- LaneChangePolicy adds automatic intent only for an explicit new single signal while lateral active, configured delay, correct minimum speed, no target-side blindspot, no opposing steering input, valid finite model probability, and sufficient lane width if configured. Opposing torque/blindspot/invalid input reset delay. Held signals across disengagement or direct left/right flips do not arm automatic moves. Manual stock sign-correct torque remains required when automatic is OFF.
- RadarD computes normal leads first, excludes those IDs, and calls `human_lane_change_track`. It calls the **existing real** `bogpilot_radar.get_adjacent_lead` producer, selecting nearest moving target-lane radar track from current model geometry. It validates finite/positive candidate data, current model/radar validity and all current RadarErrors fields (the schema is a struct, not a list).
- That actual Track enters real `get_lead` via optional preferred_track only while laneChangeStarting and valid raw vision lead probability >.5 (as well as the existing filtered vision gate). Missing/invalid data returns None, retaining normal matching; it does not synthesize a lead, accelerate, steer, or interpret absent radar as lane-clear.
- Existing low-speed closer-lead override runs AFTER target-track preference. Existing AP1 lead filters run AFTER get_lead. Stock radar publisher validity and the normal planner->MPC->carcontroller->panda paths remain unchanged.

## Deliberate safety-preserving differences

- Nudgeless default remains OFF; stored ON/OFF is preserved. No migration/seeding or bench parameter writes.
- Configurable minimum speed cannot lower the existing stock 20mph floor. A historical saved lower value is preserved on disk and displayed, but the runtime uses the 20mph floor. UI description discloses this. Other limits may be raised within historical ranges.
- Automatic intent is stricter than the old implementation on invalid models, opposing driver torque, a held signal across disengagement, and blindspot/delay resets. Invalid numerical preferences disable automatic instead of silently bypassing a configured width/delay guard.
- Model geometry is current-frame, not old per-track side flags. Human target tracking never grants lane-change permission. No AOL flags or alternativeExperience bits are invented or repurposed.

## Tests / limitations

`native-tests.txt`: 25 passing native Mac Python 3.12 deterministic tests; all three unapplied core patches also pass git apply --check against the isolated baseline. Policies, raw saved preference preservation, units, missing/corrupt config, BSM/driver-intent/standstill/min-speed/hazards, signal release, road edges, width geometry, current-model validity, timeout, stock manual state parity, exact TurnDesires consumer and parent/default/negative gating, actual adjacent producer->get_lead consumer, full RadarD.update source replay with real capnp messages, radar fault/invalid input fallback, raw/filtered lead-confidence guards, closer low-speed override and downstream AP1-filter ordering.

Consumer replay loads the actual proposed source; RadarD functions/class bodies are AST-extracted only to omit platform-specific imports, with deterministic track/filter fixtures. This is NOT a full radard process, IPC, Kalman or model inference replay. A direct full radard import is blocked on this Mac by the existing AGNOS ELF `msgq/ipc_pyx.so`, not native Mach-O. No box rendering or parallel full build attempted. Two small native test packages (setproctitle/zstandard) were installed into the lane-only evidence directory; shared venv was not modified.

`native-ap1-regression.txt`: 11 passing unchanged actual AP1 lead-filter pytest regression tests (not the spy), also run on Mac. `native-lint.txt`: scoped native ruff check. Final git diff/check and commits in commits.txt. No native UI rendering/interaction or AGNOS process acceptance claimed.

Only isolated lane source files were edited. Existing primary dependency checkout was read for schema/AP1 test imports; Python/pytest may create ordinary ignored caches there. No tracked shared-primary edits, parameters, pushes, bench or daily-driver access by this lane. Subsequent verification disables bytecode/cache writes.

## Adoption markers (t994 blocker fix)

Consumers stay stock-equivalent until the user changes a row in the matching panel (configure()).
Saved bench prefs (e.g. NudgelessLaneChange=1, HumanLaneChanges=1) never activate on first boot.

| Marker | Clears on sysUtilities reset |
|---|---|
| Phase3LaneChangeEnabled | Lane Changes panel (nudgeless/delay/width/one-per-signal/master) |
| Phase3HumanLaneChangesEnabled | Human-Like Lane Changes (Gas/Brake) |
| Phase3TurnDesiresEnabled | Turn Desires (Lateral Tuning) |

BSM: Ap1Blindspot treats SNA/stale/invalid as OCCUPIED (see PROPOSED_shared blindspot.py).
Human radard substitution: leadOne only, and only when Human marker adopted + valid.
