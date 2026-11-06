# C3X/C4 raylib cluster layout + hide-accel (stream 8)

Base: release-tizi `f7db927c7` (0.11.2 / AGNOS 19.9), on top of stream 4
(`ec9b1aeb8`) and stream 5 (`6d6ca84f0`) cherry-picks.
Source-only; no pyray render, device install or drive test.

## Layout contract

`onroad/bogpilot/cluster_layout.py` (pure Python) mirrors the C3 Qt
`bogpilot_cluster.h`. `bogpilot_hud.draw_cluster` composes the speed capsule
and the 10 s accel graph (`accel_graph.py`, ported from 23f47f903) in the
2160x1080 design space on both C3X and C4 paths.

| Toggle (file-backed) | Default | Effect |
|---|---|---|
| `SwapSpeedGraph` | ON | graph on top, capsule below |
| `HideAccelGraph` | OFF | graph skipped; capsule kept in the LOWER slot (`SpeedRowInputs.swap=True`) |

Graph samples carControl.actuators.accel vs carState.aEgo at 20 Hz regardless
of frame rate; cleared on drive start or stale carState. Settings row:
`toggle_metadata.py` HideAccelGraph, tuning_level 0, parent CustomUI.

## CSC in the MAX slot

`read_csc_status` takes only a fresh (<= 0.5 s), valid, current-drive
`frogpilotPlan` from an optional SubMaster created only when the service is in
SERVICE_LIST. Stock release-tizi never shows CSC. No planner or csc-straight
import. Dormant until a real `frogpilotPlan` publisher exists.

## Cherry-pick note

Stream 5's `onroad/bogpilot/file_toggles.py` and `__init__.py` conflicted with
stream 4. Stream 4's versions are kept (plus HideAccelGraph): the stream-5
variant imports a missing `bp_params` and lists the excluded ShowUploadRate.

## Validation (M4P48)

```sh
python3 -m unittest discover -s openpilot/selfdrive/ui/onroad/bogpilot/tests   # 46 pass (Python 3.9)
python3 -m compileall -q openpilot/selfdrive/ui/onroad/bogpilot
```

With Python 3.12 the 17 stream-8 tests pass; stream 4's adapter tests need numpy.
Rendering is tested with stand-ins, not pyray.
Full redesign parity beyond the speed capsule and graph (lead lock-on,
relocated DM, etc.) is still incomplete.
