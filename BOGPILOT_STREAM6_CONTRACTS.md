# Stream 6 contracts — Params / cereal (both tracks)

Owner: stream 6 (`port/c3-s6-params`, `port/c3x-s6-params`). Other streams must **not** rewrite `cereal/*.capnp`, `openpilot/cereal/*`, `params_keys*.h`, or `bogpilot_params.py` without coordinating here.

## Git roots
- Repo SoT: `~/BogPilotTeam/work/bogpilot` (BogPilot/openpilot)
- Track A worktree: `~/BogPilotTeam/work/wt/port-c3-s6-params` · branch `port/c3-s6-params` · base `release-tici` `551d08849` (0.10.0 / AGNOS 12.8 / Qt)
- Track B worktree: `~/BogPilotTeam/work/wt/port-c3x-s6-params` · branch `port/c3x-s6-params` · base `release-tizi` `f7db927c7` (0.11.2 / AGNOS 19.9 / raylib)

## Cereal / message compatibility

| Message | Event ordinal | Struct | Notes |
|---------|---------------|--------|-------|
| frogpilotCarControl | @107 | Custom.FrogPilotCarControl | IDs preserved from FrogPilot 0.9.7 / 367e1fe |
| frogpilotCarParams | @108 | Custom.FrogPilotCarParams | |
| frogpilotCarState | @109 | Custom.FrogPilotCarState | |
| frogpilotControlsState | @110 | Custom.FrogPilotControlsState | |
| frogpilotDeviceState | @111 | Custom.FrogPilotDeviceState | |
| frogpilotModelV2 | @112 | Custom.FrogPilotModelDataV2 | |
| frogpilotNavigation | @113 | Custom.FrogPilotNavigation | |
| frogpilotOnroadEvents | @114 | List(Custom.FrogPilotCarEvent) | |
| frogpilotPlan | @115 | Custom.FrogPilotPlan | |
| frogpilotRadarState | @116 | Custom.FrogPilotRadarState | Same capnp id as old CustomReserved10 |
| customReserved10–19 | @136–@145 | Custom.CustomReserved10–19 | Kept so Event has no holes before @146; CustomReserved10 has a **fresh** id (RadarState took the old one) |

- **C3 (0.10):** `cereal/custom.capnp` imports in-tree `car.capnp` (`using Car = import "car.capnp"`).
- **C3X (0.11):** `openpilot/cereal/custom.capnp` imports opendbc car (`using Car = import "/car.capnp"`); `cereal/__init__.py` already passes the opendbc import path.
- `services.py` registers the ten `frogpilot*` publishers on both tracks.
- Need a new custom field? Ask stream 6 for an ordinal/ID — do not occupy @107–@116 or change existing struct ids.

## Params / unknown-key-safe store

| Piece | C3 path | C3X path |
|-------|---------|----------|
| Registry SoT | `common/bogpilot_params.py` | `openpilot/common/bogpilot_params.py` |
| Generated keys header | `common/params_keys_bogpilot.h` | `openpilot/common/params_keys_bogpilot.h` |
| Included from | `common/params_keys.h` | `openpilot/common/params_keys.h` |
| File toggles registry | `common/bogpilot_toggles.py` | `openpilot/common/bogpilot_toggles.py` |
| Dual-read store | `common/bogpilot_store.py` (`ParamStore`) | `openpilot/common/bogpilot_store.py` |

**Rules for streams 1/3/4/5:**
1. Prefer `ParamStore` for every BogPilot/FrogPilot key. It uses real Params when `check_key` succeeds, else `/data/params_bogpilot/<Key>` files. Never call `Params.put` on a key that might be missing from the compiled table (boot `UnknownKeyName`).
2. One-shot migration markers (`AP1DefaultsApplied`, `PreApChimeOn1`, `AP1ThemeBogPilot2`, …) stay **files** under `/data/params_bogpilot/`.
3. Car-dependent file toggles (`EnableICIntegration`, `RegenComfortBrake`, `RegenAwareStop`, `AP1StandstillEngage`) default is decided by car/AP1 code; do not invent a Params default that forces them on for stock M3/Y.
4. Fresh-install **Tuning Level** stays intentionally unset by stream 6; stream 5 owns shipping defaults/visibility. Do not change `BOGPILOT_PARAMS` defaults without stream 5 + owner.
5. After editing `bogpilot_params.py`, regenerate the header:
   - C3X: `python3 -m openpilot.common.bogpilot_params --write-header`
   - C3: `python3 -m common.bogpilot_params --write-header`
   Then rebuild `libparams` / `params_pyx` on the matching AGNOS VM so the device table matches. Until that rebuild ships, `ParamStore` keeps file fallback.
6. UI file toggles (`RedesignUI`, `BSMFlameTracks`, `SwapSpeedGraph`, `DeveloperHUD`, `OffroadScreensaver`, …) remain readable as files for SSH `echo 0/1` ops even when also registered as Params.

## Out of scope for stream 6
- AP1 car/opendbc behavior (stream 1), panda/safety (stream 2), Qt/raylib painting (3/4), shipping default values / Tuning Level UX (5), alert volumes (7), cluster layout (8), AGNOS image builds (9/10).


## Stream 5 alignment (shipping defaults)

Registry defaults/levels follow `bogpilot_shipping_defaults.PARAM_OVERRIDES` (copied into this tree):
BorderMetrics/BlindSpotMetrics/SidebarMetrics/ShowCPU/ShowGPU/ShowMemoryUsage at **Minimal (0)** default ON;
DeveloperUI/Widgets/Sidebar default OFF under Developer (level 3); NudgelessLaneChange OFF; AlwaysOnLateral OFF;
TuningLevel=0 + TuningLevelConfirmed=0 (fresh-install unset); ModelUI path widths remain Advanced (level 2).
`DeveloperHUD` is **not** a Params key — file-only with RedesignUI/BSMFlameTracks/SwapSpeedGraph.
UI parenting of Minimal metrics under CustomUI is stream 5 `REPARENT_TO_CUSTOM_UI` / toggle_metadata; stream 6 only registers levels/values.
Do not change these shipping values without stream 5.


## Stream 7 alignment (alert volumes)

Typed Params registration for volume keys is in `bogpilot_params.py` / `params_keys_bogpilot.h`:
`AlertVolumeControl` default **0**, `EngageVolume`/`DisengageVolume`/`PromptVolume`/`PromptDistractedVolume`/`RefuseVolume`/`WarningSoftVolume`/`WarningImmediateVolume` default **101**.
`openpilot/common/bogpilot_alert_volumes.py` (from stream 7) defines `FROGPILOT_VOLUME_DEFAULTS` and `AP1_VOLUME_PROFILE` as the same non-mute profile.
Do **not** register or migrate an AP1 mute profile (`AlertVolumeControl=1` with engage/disengage 0).
File-backed overrides under `/data/params_bogpilot` remain valid via ParamStore when libparams lacks a key.
