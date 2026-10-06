# Tesla safety and behavior divergences

Not a product. No warranty. Driver remains responsible. Comply with local law. Not safe to drive until a human validates on a bench and in a car. This tree has not been validated on a bus (no captured route). `dashcamOnly` remains true.

Recorded disagreements only where the cited files were read. No speculation.

## frog_ap1 vs BogPilot (safety gates)

`frog_ap1` (`73a16cdd50033cb9f57a03fd619e2129558eef43`, classified in `docs/tesla/BRIDGE_DIFF.md`) set `dashcamOnly` false, set Tesla panda safety flags to 0, forced `FINGERPRINT=TESLA_AP1_MODELS`, and sent longitudinal commands without a long-active gate.

BogPilot keeps the stricter path:

- `selfdrive/car/tesla/interface.py` still sets `ret.dashcamOnly = True`.
- The Tesla safety model and its flags remain; they are not zeroed.
- As of `f1bcae66833526e75df4d8c7898656bcc0ee4f42`, `DAS_control` is planned only when `openpilotLongitudinalControl` and `CC.enabled` and `CC.longActive` are all true. The gate is `longitudinal_command_allowed` in `selfdrive/car/tesla/actuator_plan.py`, called from `selfdrive/car/tesla/carcontroller.py`.

## Tinkla human-accel override (HAO) not ported

In earlytesla-openpilot `selfdrive/car/tesla/carstate.py`, when `self.enableHAO` is set, Tinkla zeros `ret.gas` and sets `ret.gasPressed = False` after reading `DI_pedalPos` (human-accel override so gas does not look pressed to the rest of the stack).

BogPilot does not port HAO. Current `selfdrive/car/tesla/carstate.py` keeps `ret.gasPressed = (ret.gas > 0)`. Panda Tesla RX sets `gas_pressed` from the gas pedal byte in `panda/board/safety/safety_tesla.h`. Generic safety then clears controls on a rising gas edge in `panda/board/safety.h` (`generic_rx_checks`: `if (gas_pressed && !gas_pressed_prev && !(alternative_experience & ALT_EXP_DISABLE_DISENGAGE_ON_GAS)) { controls_allowed = false; }`). That gas-pressed disengage path is stricter than Tinkla HAO hiding the press. HAO stays deferred.

## Instrument-cluster frames (AP1)

Branch `bogpilot-tesla-cluster`. Code: `selfdrive/car/tesla/cluster.py`, wired in `carstate.py` / `carcontroller.py`; panda `board/safety/safety_tesla.h`. Behavior reference: Tinkla earlytesla-openpilot `501c7de` `selfdrive/car/tesla/HUD_module.py` and `teslacan.py` (`create_das_status`, `create_das_status2`, `create_lane_message`), earlytesla-panda `f7751e4` (`TESLA_AP_FWD_MODDED`, `tesla_fwd_hook`). BogPilot's own code.

**How it differs from Tinkla's mechanism.** Tinkla's panda edits each stock bus-2 frame in the forward hook: it keeps the stock bits named by a mask and writes openpilot's bits over the rest. BogPilot's forward hook gets only `(bus, addr)` and cannot edit a frame. So openpilot rebuilds each new stock frame from its decoded DBC signals, writes the same openpilot fields, and sends it on bus 0 with stock counter + 1. The panda drops the stock copy only while openpilot sent that address within 1.5x its stock period (750 ms for 0x399 and 0x389, 150 ms for 0x239). Without `TESLA_FLAG_AP1`, or without a recent openpilot TX, stock frames pass as before. openpilot sends nothing for an address until it has a stock frame for it. Known edge: when substitution stops, one stock frame of that address is dropped (about 0.5 s for 0x399 / 0x389, 0.1 s for 0x239). Counters stay continuous.

**Frames.**

| id | this tree's DBC name | sent | openpilot fields (everything else is stock) |
| --- | --- | --- | --- |
| 0x399 | `AutopilotStatus` (Tinkla: `DAS_status`) | engaged, and 4 s after | engaged: `autopilotStatus` 5 (stock 3..5 left alone), `DAS_autopilotHandsOnState` 2 / 3 (quiet steer-required or hands on) / 5 (with chime), `DAS_autoLaneChangeState` 8 / 6 / 7 / 1 from the stock Mobileye lane bits, 9 / 10 during an openpilot lane change, FCW 1 and LDW 1 (left) / 2 (right) only when openpilot has one. After: `autopilotStatus` 1 becomes 2, nothing else |
| 0x389 | `DAS_status2` | engaged, and 4 s after | `DAS_activationFailureStatus` 0. Engaged also: `DAS_driverInteractionLevel` 0, CSA state 2 (bits 32-33), `DAS_longCollisionWarning` 1 only when openpilot has an FCW |
| 0x239 | `DAS_lanes` | engaged (toggle on) | C2 from a through-origin fit (y = c2·x²) of `modelV2.position` over 50 m (IC_LANE_SCALE 0.5) when engaged and toggle on; C0, C1, C3 0 (the model path starts at the car; Tinkla suppress_x_coord); view range = model path length capped at 100 m (Tinkla max_distance) and clamped to [0|160] m; fallback = actuator curvature + 50 m if model path missing/invalid. Stock Exists/LineUsage/forks/width preserved |

Checksum for 0x399 and 0x389 is `(addr & 0xFF) + (addr >> 8) + sum(bytes 0..6)` in byte 7, the same as Tinkla's `tesla_compute_checksum`; it matches every stock frame in the AP1 rlogs on the box. 0x239 has no checksum.

**Narrower than Tinkla on purpose.**

- openpilot warnings only add. Tinkla overwrote `DAS_forwardCollisionWarning`, `DAS_laneDepartureWarning`, and `DAS_longCollisionWarning` with openpilot's values (0x0F SNA when none), which could hide a stock Mobileye warning. Here a stock warning is always kept.
- Post-disengage: Tinkla forced `DAS_autopilotState` to 2 for 4 s regardless of the stock value. Here only stock 1 (UNAVAILABLE) becomes 2.
- Panda rejects a 0x399 with autopilot state 3, 4, or 5 unless `controls_allowed`. Tinkla had no such check.
- Tinkla's constant is `TIME_TO_HIDE_ERRORS = 4000000` us; its comment says 3 s. 4 s is used.
- `enableICIntegration` (Tinkla name) gates all AP1 cluster substitution. July prebuilt `params_pyx.so` has no Tesla* keys, so this is **file-backed** at `/data/params_bogpilot/EnableICIntegration` (not a Params key, not in `frogpilot_default_params`). AP1 fingerprint defaults **on** when the file is absent; non-AP1 is always off. Toggle off → openpilot sends no cluster frames → panda recent-TX drop does not arm → stock 0x399 / 0x389 / 0x239 forward. The July prebuilt vehicle Settings panel does not show this toggle (same as other Tesla Early metadata); change with `echo 0` / `echo 1` into that file and restart. Documented in `selfdrive/car/tesla/toggles.py` and `TESLA_EARLY_TOGGLES`.
- Engaged 0x239 curvature and view range come from `modelV2.position` (ego-frame through-origin fit y = c2·x² over 50 m, so C0 offset and C1 heading are always 0 and C3 is 0; sending a fitted heading and offset drew the path off to one side and diagonally across the car on the AP1 cluster, and Tinkla likewise forces C1 = 0 via `suppress_x_coord`; view range is the model path length capped at 100 m) when `enableICIntegration` is on; fallback is actuator curvature + 50 m. CarController lazily subscribes to `modelV2` only for that path (not for lead cars). `DAS_object` (0x309) and `DAS_telemetry` (0x3a9) are not in this DBC and are not invented. Stale/absent modelV2 never stops substitution by itself; toggle off stops it immediately. Lane presence / LineUsage stay stock (do not draw a fused line the stock frame did not report). Forks stay stock. 0x399 state 5, hands-on, lane-change, and FCW/LDW behavior are unchanged; stock warnings stay additive.

**DBC disagreement.** This tree's `tesla_can.dbc` and Tinkla's (`BogGyver/opendbc` `9c0b6fe`) disagree for 0x399 bits 27-36 and 0x389 bits 31-33. Only one openpilot field lands there: CSA state, which Tinkla's DBC puts at 0x389 32|2 (this tree calls bits 31-33 `DAS_lssState`). AP1 rlogs only ever set bits 32-33 of that region, which fits Tinkla's layout, so `cluster.py` writes CSA there as a raw 2-bit field with that citation. Every other field is written by this tree's DBC name. Over 10218 stock 0x399 / 0x389 / 0x239 frames in the rlogs, every set bit is inside a signal of this tree's DBC, so the rebuild is byte-exact.

**Deferred.**

- 0x3e9 `DAS_bodyControls`. It carries turn-signal, hazard, headlight, and wiper requests, not display. BogPilot has no ALCA or hazard feature to drive it, so replacing it could only suppress stock requests. Stock frames also set bits 22, 23, 26, 28 that no DBC signal covers, so a rebuilt frame would change them. Not in the panda TX list.
- `DAS_object` (0x309) and `DAS_telemetry` (0x3a9): not `BO_` lines in this tree's DBC. No invented signals.
- Warning matrices 0x329 / 0x369 (0x349 stays the all-zero Hold clear only), pre-AP 0x659.


## AP1 regen-sized comfort braking

File-backed toggle `/data/params_bogpilot/RegenComfortBrake` (July prebuilt cannot store new Params keys). AP1 fingerprint defaults **on** when the file is absent; non-AP1 is always off. When on, the lead MPC desired-distance cost uses a 1.2 m/s² comfort brake (regen-sized) via a runtime `x_obstacle` adjustment in `long_mpc.py`; the acados-generated solver still embeds stock `COMFORT_BRAKE=2.5` and is not regenerated. Hard accel limits stay at `ACCEL_MIN` (FCW/AEB/cut-in/danger keep full braking). `STOP_DISTANCE` and the panda braking floor are unchanged. Code: `selfdrive/car/tesla/regen_brake.py`, wired from `longitudinal_planner.py`.

## Planner FCW while longitudinal control is off

`selfdrive/controls/lib/fcw_gate.py` (used by `longitudinal_planner.py`): while `reset_state` is true (long control off / disengaged), `mpc.crash_cnt` is cleared and planner FCW is not set. FrogPilot publishes min/maxAcceleration = 0 while disengaged, which coasts the MPC into a closing lead and latches `crash_cnt`; without this clear, controlsd raises EventName.fcw ("BRAKE!" / "Risk of Collision") at the engage instant. Model FCW (`hardBrakePredicted`), stock AEB passthrough, and engaged planner FCW are unchanged.

## AP1 driver steering input (override border and hands pause)

- `carState.steeringPressed` on AP1 is any non-zero `EPAS_handsOnLevel` (`hso.ap1_driver_input`, `AP1_DRIVER_INPUT_LEVEL = 1`), the stock Tesla port and `frog_ap1` mapping. It raises `steerOverride`, controlsd enters `overriding`, and the prebuilt UI draws the grey border. `f8aadaa8` had raised it to >= 2 (TinklaHandsOnLevel); logged AP1 EPAS only reports levels 0, 1 and 3 (never 2), so the border only went grey on brief level 3 peaks.
- The Tinkla hands pause is unchanged at level >= 2 (`hso.ap1_steering_pressed`): CarController sends 0x488 type NONE at the measured angle and cruise stays up. controlsd no longer clears `latActive` from `steeringPressed` on AP1, so a level 1 override keeps openpilot steering (as in `frog_ap1`) with the border grey. `_ap1_epas_inhibit_alert` does not count EPAS INHIBITED during the hands pause (EPAS reports INHIBITED with code 3 while the driver is at level 3).
- Resume hold (`hso.AP1_RESUME_HOLD_S = 0.5`, `hso.Ap1DriverYield`, used by CarController). Once hands reach level >= 2 while engaged, 0x488 stays type NONE at the measured angle until `EPAS_handsOnLevel` has been 0 for 0.5 s in a row; any level >= 1 restarts the count. Lateral then resumes through the 300 ms measured-angle soft-start (`AP1_ENGAGE_SOFT_START_FRAMES`), the same one used at engage, so the first ANGLE frame is the wheel's own angle. Before this, lateral resumed as soon as the level fell to 1, which is still driver torque, so openpilot steered against the driver between level 3 peaks. During the hold the interface adds `steerOverride` so the border stays grey; `steeringPressed` itself is not extended. Not engaged clears the hold at once, so disengage, cancel, and re-engage are not delayed; longitudinal, FCW/AEB and driver monitoring are not touched. Tinkla's 50-frame numb period and 15 degree handoff are still not ported.
- Hold length: first shipped at 0.8 s from the log evidence below; after driving it the user chose 0.5 s, which matches Tinkla's 50-frame HSO period (Tinkla also extends it on the turn-signal stalk and a 15 degree angle difference, which are not ported). Evidence for the original 0.8 s: in three logged AP1 drives (about 70k EPAS samples) 9 of 14 level 3 overrides dropped to level 1 first and reached level 0 up to 2.9 s later. After reaching 0, the driver pressed again within 0.24 to 0.56 s in 9 of 10 re-presses (the other at 1.0 s, then nothing under 2 s). 0.8 s bridges every engaged gap between driver inputs up to 0.76 s. Replaying those drives through `Ap1DriverYield`, openpilot no longer takes the wheel back between two overrides (10 times in under 1 s before, 0 after). Level 1 input without a level 2+ peak still keeps openpilot steering with the border grey, as in `frog_ap1`.

## Angle steering and dashcamOnly

Angle steering does not blend with driver torque. `selfdrive/car/tesla/interface.py` documents that and keeps `ret.dashcamOnly = True` for that reason. This document does not propose turning `dashcamOnly` off.

## AP1 angle-rate table (Tinkla) vs shared Tesla table

Tinkla is the authority for AP1 angle rates. Source read: earlytesla-panda `board/safety/safety_tesla.h` (`TESLA_LOOKUP_ANGLE_RATE_UP`, `TESLA_LOOKUP_ANGLE_RATE_DOWN`, `TESLA_DEG_TO_CAN`). The shared `TESLA_STEERING_LIMITS` table is the Model 3/Y and non-AP1 limit. It is not an AP1 limit, and its numbers were not changed.

| | speeds (m/s) | rate up (deg/s) | rate down (deg/s) | deg to CAN |
| --- | --- | --- | --- | --- |
| `TESLA_STEERING_LIMITS` (shared, non-AP1) | 0, 5, 15 | 10, 1.6, 0.3 | 10, 7.0, 0.8 | 10 |
| `TESLA_AP1_STEERING_LIMITS` (Tinkla AP1) | 2, 7, 17 | 8, 4, 2.5 | 9, 5, 4.5 | 10 |

`TESLA_FLAG_AP1` is bit 3, value 8. It does not overlap `TESLA_FLAG_POWERTRAIN` (1), `TESLA_FLAG_LONGITUDINAL_CONTROL` (2), or `TESLA_FLAG_RAVEN` (4). `tesla_tx_hook` passes `TESLA_AP1_STEERING_LIMITS` to `steer_angle_cmd_checks` only when that flag is set, and `TESLA_STEERING_LIMITS` otherwise. The choice does not read `0x2bf`.

`flags_for_candidate` in `selfdrive/car/tesla/safety_flags.py` sets bit 8 (`Panda.FLAG_TESLA_AP1`, value 8) only when the candidate is `CAR.TESLA_AP1_MODELS`. Raven keeps `FLAG_TESLA_RAVEN` and does not get bit 8. AP2 gets neither. The `0x2bf` powertrain path still adds `FLAG_TESLA_LONG_CONTROL` and a second config with `FLAG_TESLA_POWERTRAIN`; those flags also include bit 8 only if the candidate is AP1. AP1 is not expected to have `0x2bf`. This does not set `openpilotLongitudinalControl` for AP1. `ret.dashcamOnly = True` is unchanged. The flag selects `TESLA_AP1_STEERING_LIMITS` in panda when that safety config is installed. It does not engage the car by itself.

## AP1 speed-limit raise (low-conflict, no stalk injection)

When FrogPilot **Speed Limit Controller** is on, a confirmed higher posted limit lifts openpilot's cruise target to limit+offset (e.g. 30 zone set 36 → 45 zone with +6 → 51) so longitudinal accelerates into the faster zone. Lift runs **after** the min() merge so a low DI_cruiseSet seed cannot undo the raise; CSC re-caps only when the curve controller is actively controlling. Uses existing SLC toggles: `SLCConfirmationHigher` must be off (or tip-up / accept) for unattended raises; override and denied limits are respected.

Cruise set source is `DI_cruiseSet` (Tinkla-aligned), not `DI_digitalSpeed`. `DAS_accSpeedLimit` on 0x389 stays stock (Tinkla-aligned): overlaying the OP raised set while DI set stayed low locked `DI_digitalSpeed` at 60 on the IC (route 21 @ bd26defe; dig==60 tracked 2× the raised 30). Comma/HUD set may still lift via `cluster_display_kph`; longitudinal follows `frogpilotPlan.vCruise`. No Ap1RaiseHoldoff / stalk-DECEL suppress — simple post-min raise only; all other stalk behaviors stay stock. Stock fused/vision speed-limit sign fields stay stock. **No** fake stalk on 0x45; panda CANCEL-only on 0x45 is unchanged. Code: `selfdrive/car/tesla/slc_raise.py`, `frogpilot/controls/lib/frogpilot_vcruise.py`, `cluster.py`, `controlsd.py` cluster display lift.

## Last-known wall clock (device-global)

comma devices lose RTC across power-off and boot into a fixed AGNOS/systemd epoch (~Nov 2023) until GPS or NTP sets the clock, so rlog wall-clock stamps and route directory names collide across boots. BogPilot writes the current UTC unix time to `/data/params_bogpilot/LastKnownTime` about every 5 minutes from `system.timed` once `system_time_valid()` is true (tiny file; same durable dir as other BogPilot file-backed prefs; not a Params key). At `manager_init`, before `save_bootlog` / loggerd, `maybe_restore_last_known_time` sets the clock from that file when the clock is still on the bogus epoch or far behind the saved stamp. GPS/NTP via `timed.set_time` still correct afterward (`set_time` uses `abs(diff)` so a restored-but-slightly-stale clock can be advanced). First boot after install stays wrong until one valid-time period saves a stamp. Code: `common/bogpilot_clock.py`. No panda change; not car-specific.

