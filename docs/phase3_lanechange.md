# Phase 3 lane-change / adjacent-radar notes

The lane-change settings in this build, where each one came from in BogPilot 0.9.7, and how this build uses it. None of them changes CAN messages or panda safety.

## Settings and their BogPilot 0.9.7 origin

Reference: existing repository's own `04d560f3` (0.9.7 bogpilot-tesla), not an upstream/newer fork.

In the BogPilot 0.9.7 reference tree (`04d560f3`), `frogpilot/ui/qt/offroad/lateral_settings.cc` / `.h` define these rows, and `frogpilot/ui/qt/offroad/longitudinal_settings.cc` defines Human-Like Lane Changes:

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

Human-Like Lane Changes stays on the Gas / Brake > Longitudinal Tuning page, where 0.9.7 had it, not under Steering. When its gate passes (see `docs/bogpilot_c3x.md`), the row is a real setting: radard uses it to prefer the target-lane radar track for the lead during a lane change. On an AP1 Model S it is on by default, as in 0.9.7 (`human_lane_changes_default_on`); on any other car it stays off until the row is changed.

In the 0.9.7 reference tree, `selfdrive/controls/lib/desire_helper.py` handled the lane-change master switch, the automatic delay, the lane-width check and one change per signal; `frogpilot/common/frogpilot_utilities.py:86` `calculate_lane_width` used the median spacing to the adjacent lane line, with a road-edge veto; and `selfdrive/controls/radard.py` `match_vision_to_track` preferred the closest target-lane radar track during laneChangeStarting. HumanLaneChanges there was not a lane-clearance or blind-spot permission and did not start a lane change.

AOL/safety capability and controller tuning/NNFF/QoL belong to other modules. TurnDesires is implemented here with its exact historical LateralTune parent. No steering gain, actuator tuning, carcontroller, opendbc safety or panda file changes.

## Integration in this tree

- `desire_helper.py` and `radard.py` consume this module here: `desire_helper.py` imports the lane-change policy from `controls/lib/phase3_lanechange.py`, and `radard.py` calls `human_lane_change_track` (`radard.py:18`, `:261`).
- Lane Changes: `layouts/settings/bogpilot.py` builds `LaneChangeLayout(runtime_integrated=True, offroad=ui_state.is_offroad)`. With the default `runtime_integrated=False` the layout exposes no rows. Writes need the offroad predicate; without it the rows are read-only. No fake active controls are registered.
- Human-Like Lane Changes: `human_lane_change_item` is attached after Human-Like Following on the Gas/Brake Longitudinal Tuning page (`ui/bogpilot/phase3_following.py:389`). It returns no row unless `human_row_available` passes (radar available, openpilot longitudinal control on, LongitudinalTune on, and the tuning-level checks). No standalone Human switch is attached to any central menu.
- Turn Desires: the consumer is the below-lane-change-speed turnLeft/turnRight branch in `desire_helper.py`, separate from lane-change initiation; no new navigation or turn algorithm is added. `turn_desire_item` exists, but nothing in the settings mounts it, so this build has no Turn Desires row. `TurnDesires` is OFF by default and needs LateralTune ON.
- No AGNOS process/IPC replay or native UI acceptance is claimed. Do not call these features live-validated.

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

Tests in this tree:

- `openpilot/selfdrive/controls/tests/test_phase3_lanechange.py`: deterministic policy and consumer tests. They cover defaults and saved-preference preservation, units and the stock 20mph floor, bad or unreadable settings failing closed, blind-spot / opposing-intent / delay resets, held-signal and one-per-signal handling, lane width and road edges, model validity and timeout, stock manual-path parity, the TurnDesires consumer and its parent/default gates, the Human row gate, the adjacent-lead producer feeding `get_lead`, a `RadarD.update` replay with real capnp messages and the AP1 lead-filter order, AP1 blind-spot SNA/stale handling, and adoption (saved values stay dormant until `configure()`).
- `openpilot/selfdrive/ui/tests/test_lane_changes_page.py` and `openpilot/selfdrive/ui/tests/test_phase3_lanechange_section_reset.py`: the Lane Changes page and its section reset.
- `opendbc_repo/opendbc/car/tesla_ap1/tests/test_ap1_lead_filter.py`: AP1 lead-filter regression tests.

Limits:

- The radard replay extracts the RadarD functions and class bodies by AST so it can run without the AGNOS-only msgq/IPC binaries, and it uses fixed track/filter fixtures. It is not a full radard process, IPC, Kalman or model-inference replay.
- No onroad, AGNOS process/IPC or vehicle validation is claimed for this module.

## Adoption markers

Consumers stay stock-equivalent until the user changes a row in the matching panel (configure()).
Saved preferences (e.g. NudgelessLaneChange=1) never activate on first boot. Exception: Human-Like Lane Changes is on by default on the AP1 Model S (`human_lane_changes_default_on`).

| Marker | Clears on sysUtilities reset |
|---|---|
| Phase3LaneChangeEnabled | Lane Changes panel (nudgeless/delay/width/one-per-signal/master) |
| Phase3HumanLaneChangesEnabled | Human-Like Lane Changes (Gas/Brake); not needed on the AP1 Model S, where it is on by default |
| Phase3TurnDesiresEnabled | Turn Desires (Lateral Tuning) |

BSM: Ap1Blindspot treats SNA/stale/invalid as OCCUPIED (see `opendbc_repo/opendbc/car/tesla_ap1/blindspot.py`).
Human radard substitution: leadOne only, and only when valid and Human is on (marker adopted, or the AP1 Model S default).
