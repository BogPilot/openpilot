# Stream 1: AP1 vehicle/runtime integration

Local implementation only. **Not an integrated, boot-tested or road-tested product.**

## Branches and bases
- C3: `port/c3-s1-ap1`, worktree `work/wt/port-c3-s1-ap1`, release-tici `551d088497144425feb14299c6d725b63f1b942e` (0.10.0 / AGNOS 12.8).
- C3X/4: `port/c3x-s1-ap1`, worktree `work/wt/port-c3x-s1-ap1`, shared release-tizi/release-mici `f7db927c728bab57bb1263e05465766a8f28fc9d` (0.11.2 / AGNOS 19.9).
- Feature source: BogPilot `agnos199-integration @23f47f903`, selectively adapted rather than merging its old base. The earlier ap1_0112/int3 integration is not used as a replacement product base.
- Author/committer: BogPilot. No push, deployment, firmware build or device access.

## Scope implemented
- Separate `opendbc.car.tesla_ap1` brand; stock Tesla modules and `tesla_can.dbc` untouched. AP1 uses `tesla_ap1_can.dbc` (ambient-temperature signal and corrected cluster speed scale).
- AP1 fallback only after upstream fingerprinting fails. Chassis **and stock Mobileye bus-2 traffic** required; chassis-only Pre-AP stays unmatched. A forced AP1 name without that evidence is dashcam/noOutput. No Pre-AP actuation platform is registered; Ruling 6 remains pending.
- card: AP1 cluster model-provider hook, existing stalk long-hold ExperimentalMode pulses, custom-state mirror; retains each base's native radar topic and fingerprint API.
- selfdrived's native car-event adapter: AP1 driver-yield/HSO/inhibit rewrites; permanent faults stay disabling. No monolithic legacy controlsd replacement.
- controlsd: AP1-only opt-in AOL bridge. Default off; no invented safety bit. If the target safety implementation lacks `ALWAYS_ON_LATERAL`, the toggle cannot actuate AOL (fail closed). Safety work is needed to complete opt-in AOL.
- Planner: AP1 stalk follow time, default-on regen comfort cost/regen-aware early stopping; existing hard ACCEL_MIN/MAX retained. Generated acados model/OCP functions are unchanged. Model-only stop targets require experimental mode; driver override/inactive control resets early braking.
- radard: AP1-only lead glitch filter, adapts status/present field names without changing target wire schemas.
- IC transmit and AP1 standstill default on, preserving existing file overrides. No upload-rate/streaming/UI design work.
- AP1 volumes import stream 7 `common.bogpilot_alert_volumes.AP1_VOLUME_PROFILE`, through stream 6 `ParamStore`; missing values only. No legacy engage/disengage mute profile copied. Existing user choices are not overwritten.

## Cross-stream integration contracts / blockers
1. **Stream 2:** SafetyModel.tesla; LONG=1, AP1=8, STANDSTILL=16. Combined params 9 or 25 (never legacy 10/26). Matches `d4ed9844b` / `ba26a9a95`. New-base safety inhibits longitudinal on gas; unmodified selfdrived still owns the DisengageOnAccelerator option and brake disengagement. Tests evaluate each target's actual pedal-event predicate.
2. **Stream 6:** custom messages and services from `3e20ef151` / `b855d6207` are required. Those commits currently lack `CarState.bogpilot :BogPilotCarState`, required by vehicle state, events/planners and the UI mirror. Bring the existing 28-field contract from `23f47f903` into both A car schema copies and B opendbc car schema, checking target ordinal availability. Stream 1 deliberately made no schema/registry edits.
   - Existing source: `opendbc_repo/opendbc/car/car.capnp`, `BogPilotCarState` @0..27; `CarState.bogpilot` is @62 in that source.
   - Shared fields @0..20 mirror custom.FrogPilotCarState; AP1 extras: @21 ap1HandsOnLevel UInt8, @22 ap1EacInhibited Bool, @23 ap1DriverYield Bool, @24 ap1StalkPullToggle Bool, @25 ap1StalkFwdToggle Bool, @26 ap1StockApActive Bool, @27 ap1StalkFollowS Float32.
   - The real CarInterface, params and parsers initialize on both targets; `CarState.update` is blocked until that contract lands. An explicit integration test skips without it; set `BOGPILOT_REQUIRE_SCHEMA=1` to make this a hard failure on the integrated product.
3. **Streams 5/7:** do not let the older AP1 defaults profile reintroduce AlertVolumeControl=1 / EngageVolume=0 / DisengageVolume=0. Use stream 7's profile (controller=0, volumes=101). Stream 1 does not own or change stream 5's profile migration.
4. **Streams 9/10:** merge dependencies and run matching-AGNOS compile, generated bindings, safety/controller cross-tests and replay/device validation. Standalone stream branches are not install targets. No safety/actuation claim follows from the synthetic controller tests.

## Validation
On M4P48, from each worktree:

```sh
PYTHONPATH="$PWD:$PWD/opendbc_repo:$HOME/BogPilotTeam/work/venvs/port-s1-deps"   "$HOME/BogPilotTeam/work/venvs/bp-py312/bin/python" -m pytest -q -o addopts=''   --confcutdir=opendbc_repo/opendbc/car/tesla_ap1/tests   opendbc_repo/opendbc/car/tesla_ap1/tests
```

Synthetic tests cover real target CAN packing/CRC, slew and urgent braking, AP1 fallback/Pre-AP refusal, parser construction, stock Tesla registration, gas/brake event ownership, stalk/regen/lead filters and default-off AOL gating. They do not run an actual solver, panda firmware, driving process, boot or live vehicle.

Additional checks: modified/new Python syntax; `git diff --check`; byte-identical stock Tesla source/DBC; AST-identical generated MPC model/OCP; unchanged stock realtime affinity/priority call sites.

Final scoped regression result on M4P48 (2026-11-06 03:45 PM EST): **198 passed, 1 skipped per track**. The skip is the explicitly missing stream-6 car-state schema; all listed static checks passed.

Radar bridge note: C3 retains its legacy RadarPoint extra fields; C3X follows the target three-field RadarPoint and uses the existing in-memory Bosch DBC generator (no ignored generated DBC is shipped). A synthetic Bosch CAN-to-RadarData roundtrip covers this.

CSC/MAX: this stream does not publish frogpilotPlan or fabricate CSC state from stock fields; stream 8 correctly leaves the MAX CSC slot blank until a real valid publisher is integrated.
