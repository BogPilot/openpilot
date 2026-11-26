# BogPilot provenance and credits

BogPilot is forked from FrogPilot's work (FrogAi and contributors, MIT), which is itself a fork of openpilot (MIT, Comma.ai, Inc.),
and adds Tesla support. Thank you to the FrogPilot team for their brilliant work. The credit also stays in `README.md` and `LICENSE`.

## Where the code comes from
- Base: openpilot v0.11.2 (release-tizi). Every BogPilot commit on top is authored and committed as
  `BogPilot <bogpilot@users.noreply.github.com>`.
- Tinkla / BogGyver (Tesla AP1 port, MIT): mostly data (CAN definitions, fingerprints, rate tables) and a behavior reference. A
  small amount of Tinkla code is included in adapted form (CAN packer helpers in `car/tesla_ap1/teslacan.py` and a few signal
  reads in `car/tesla_ap1/carstate.py`).
- NotAutopilot (NAP, MIT, https://github.com/NotAutopilot/openpilot and https://github.com/NotAutopilot/opendbc): the Pre-AP pedal longitudinal stack is derived
  from NAP. `preap/virtual_das.py`, `preap/radar_donor_vin.py` and `preap/ff_table_default.py` are copied with small changes;
  `preap/pedal_feedback.py`, `preap/vdas_constants.py`, `preap/pedal_controller.py`, `preap/pedal_authority.py`,
  `preap/long_controller.py`, `preap/pedal_can.py`, `preap/stock_cc_spoofer.py` and the Pre-AP radar gateway
  (`safety/modes/tesla_preap_radar.h`) are adapted from NAP. The Pre-AP panda safety mode (`safety/modes/tesla_preap.h`) is
  written for BogPilot following NAP's structure. Pre-AP engagement, carstate and carcontroller are BogPilot code that uses NAP
  as a reference.
- Beta tester IRIT-able contributed Pre-AP fixes from their fork; see README Credits.
- Curve speed control (AP1 CSC, regular mode): the curve speed planner (`selfdrive/controls/lib/curve_speed_planner.py`) is
  BogPilot-authored. The learning/target logic and `calculate_road_curvature()` follow FrogPilot 0.9.7 code by FrogAi (the latter
  is credited upstream to Pfeiferj), so those modules name their origin in their docstrings (`bogpilot_csc.py`, `curve_speed_planner.py`). The map curve trigger distance follows mapd (MIT, pfeiferj).
  Not ported: the FrogPilot weather reduction (no weather source), and the Experimental / Conditional Experimental speed policy.
- The repository license is MIT (comma.ai LICENSE); see `LICENSE` for the FrogPilot and openpilot notices.

## Reserved key
- `OffroadScreensaver` is a reserved file-toggle key, default OFF. Nothing in this build reads it.
