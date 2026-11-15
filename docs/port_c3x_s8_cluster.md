# C3X/C4 raylib cluster layout + hide-accel

> Development note, kept for reference. It describes this piece of work at the time it was written, not the
> released build. For what the release does, see `README.md` and `docs/bogpilot_c3x.md`.

Base: release-tizi `f7db927c7` (0.11.2 / AGNOS 19.9), on top of the onroad
adapter (`ec9b1aeb8`) and shipping-defaults (`6d6ca84f0`) cherry-picks.
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
`bogpilotPlan` from an optional SubMaster created only when the service is in
SERVICE_LIST. Stock release-tizi never shows CSC. No planner or csc-straight
import. In the release, `plannerd` publishes `bogpilotPlan`.

## Cherry-pick note

The shipping-defaults `onroad/bogpilot/file_toggles.py` and `__init__.py` conflicted with
the onroad adapter. The adapter's versions are kept (plus HideAccelGraph): the shipping-defaults
variant imports a missing `bp_params` and lists the excluded ShowUploadRate.

## Validation

```sh
python3 -m unittest discover -s openpilot/selfdrive/ui/onroad/bogpilot/tests   # 46 pass (Python 3.9)
python3 -m compileall -q openpilot/selfdrive/ui/onroad/bogpilot
```

With Python 3.12 the 17 cluster tests pass; the adapter tests need numpy.
Rendering is tested with stand-ins, not pyray.
Full redesign parity beyond the speed capsule and graph (lead lock-on,
relocated DM, etc.) is still incomplete.
