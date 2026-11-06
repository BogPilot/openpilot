# Release-tizi raylib onroad adapter (stream 4)

Base: release-tizi/release-mici `f7db927c7` (0.11.2, AGNOS 19.9).
This is source-only work, not a prebuilt, device install or validated release.

## Included

- Reuses standalone `redesign.py`, `style.py`, `flame_tracks.py`, trigger logic
  and original trigger tests from the prior 19.9 integration `23f47f903`.
- Wires both actual entry paths: `onroad/augmented_road_view.py` for C3X and
  `mici/onroad/augmented_road_view.py` for C4. No Qt code/binaries.
- Narrow HUD subclasses replace speed/MAX with the BogPilot speed capsule.
  Stock speed state, experiment button, camera selection/calibration, road/path
  rendering, warnings, alerts, DM, bookmark and C4 torque indicator remain.
- C4 projection is rect-local; BSM/flame polygons add its origin once. C3X
  projection is already screen-space. Design scaling preserves outer matrices.
- Red BSM side paths use fresh car state and projected model lane boundaries.
  Invalid geometry and stale car/model/calibration data cannot draw the overlay.
- Redesign and flames default ON, with explicit user OFF respected. Swap defaults
  ON. No params migration, fresh-install tuning-level choice or car/safety edits.
- No upload-rate, HEVC, streaming or telemetry dependencies are included.

## Settings contract (streams 5/6)

`RedesignUI`, `BSMFlameTracks`, `SwapSpeedGraph` remain legacy file-backed booleans
under `/data/params_bogpilot`. Reads are throttled to once per two seconds.
`BlindSpotPath` uses its registered typed Params value if present, otherwise a
file fallback, otherwise ON. Unknown Params keys are never read or written.
No installer needs to create files merely to get the shipping defaults.

## Layout contract (stream 8)

`bogpilot_hud.draw_cluster(hud, rect, mici=False)` is the composition point.
It supplies a 2160x1080 design coordinate system fitted to each viewport. The
`speed_row_inputs` adapter handles C3X vs C4 set-speed unit differences.
`redesign.SpeedRowInputs`, `paint_speed_row`, `speed_row_geometry`,
`accel_graph_rect`, `max_slot_rect` and `style.py` are the existing 19.9 helpers.

Stream 8 owns adding the accel graph, hide-accel behavior while retaining the
lower capsule, and wiring validated CSC status into the existing MAX-slot
fields. Those are not falsely represented as complete in this patch. This
patch does not import a custom planner or invent CSC status from stock fields.
Lead lock-on, relocated DM, and other full daily-driver redesign details also
remain future parity work; this is the narrow speed-capsule/BSM adapter.

## Required adjacent-radar contract (stream 6 / integration blocker)

The flame burn retains the prior behavior: red BSM fill turning off, a fresh
adjacent lead faster than 88 mph during a 500ms grace window, then a 3s burn.
It never uses the comma's ego speed as a substitute for adjacent lead speed.

Stock release-tizi does not publish/subscribe `frogpilotRadarState`. Thus BSM
red paths work with stock data, but flames **cannot fire on stock messages**.
The optional consumer requires a subscribed, alive, valid, current-drive
`frogpilotRadarState` with `leadLeft`/`leadRight.status` and `vLead` in m/s, plus
fresh `radarState`. Missing/stale/invalid data fails closed. Streams responsible
for messages and radar must supply the real producer/subscription before
flames can be called integrated. No schema or producer is added by this stream.

## Validation

On M4P48:

```sh
python3 -m unittest discover -s openpilot/selfdrive/ui/onroad/bogpilot/tests -v
python3 -m compileall -q openpilot/selfdrive/ui/onroad/bogpilot \
  openpilot/selfdrive/ui/onroad/augmented_road_view.py \
  openpilot/selfdrive/ui/mici/onroad/augmented_road_view.py
git diff --check
```

29 tests pass (14 original flame tests, 15 adapter/contract tests). Adapter
render tests use dependency doubles, not a real graphics context. The available
Mac Python lacks pyray and ruff. Full module import in the matching AGNOS 19.9
build environment, rendered C3X/C4 layout validation, boot and device tests
remain outstanding. Existing source tests are not a claim of a full UI build.
