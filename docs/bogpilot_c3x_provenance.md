# BogPilot provenance and credits

BogPilot is forked from FrogPilot's work (FrogAi and contributors, MIT), which is itself a fork of openpilot (MIT, Comma.ai, Inc.),
and adds Tesla support. Thank you to the FrogPilot team for their brilliant work. The credit also stays in `README.md` and `LICENSE`.

## Where the code comes from
- Base: openpilot v0.11.2 (release-tizi). Every BogPilot commit on top is authored and committed as
  `BogPilot <bogpilot@users.noreply.github.com>`.
- Tinkla (Tesla AP1 research port): data values only (fingerprints, signal reference values); no Tinkla code is included.
- Curve speed control (AP1 CSC, regular mode): the curve speed planner (`selfdrive/controls/lib/curve_speed_planner.py`) is
  BogPilot-authored. The learning/target logic and `calculate_road_curvature()` follow FrogPilot 0.9.7 code by FrogAi (the latter
  is credited upstream to Pfeiferj), so those modules name their origin in their docstrings (`bogpilot_csc.py`, `curve_speed_planner.py`). The map curve trigger distance follows mapd (MIT, Jacob Pfeifer).
  Not ported: the FrogPilot weather reduction (no weather source), and the Experimental / Conditional Experimental speed policy.
- The repository license is MIT (comma.ai LICENSE); see `LICENSE` for the FrogPilot and openpilot notices.

## Reserved key
- `OffroadScreensaver` is a reserved file-toggle key, default OFF. Nothing in this build reads it.
