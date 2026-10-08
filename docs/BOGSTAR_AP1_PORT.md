# BogStar: BogPilot Tesla AP1 port notes

Source: BogPilot `bogpilot-tesla` at fe06ec7a (milestones 3 and 4). BogStar base: StarPilot 2a12dbd0a
(no newer StarPilot release on `StarPilot` / `main` as of 2026-10-07).

## Where the BogPilot pieces live here

| BogPilot (FrogPilot) | BogStar (StarPilot) |
| --- | --- |
| `selfdrive/car/tesla/long_smooth.py` | `opendbc_repo/opendbc/car/tesla/ap1_long_smooth.py` |
| `selfdrive/car/tesla/throttle_gate.py` | `opendbc_repo/opendbc/car/tesla/ap1_throttle_gate.py` |
| `selfdrive/car/tesla/steer_counter.py` | `opendbc_repo/opendbc/car/tesla/ap1_steer_counter.py` |
| `selfdrive/car/tesla/stalk_fwd_hold.py` | `opendbc_repo/opendbc/car/tesla/ap1_stalk_fwd_hold.py` |
| `selfdrive/car/tesla/slc_raise.py` | `opendbc_repo/opendbc/car/tesla/ap1_slc_raise.py` |
| `selfdrive/car/tesla/regen_brake.py` | `opendbc_repo/opendbc/car/tesla/ap1_regen_brake.py` |
| carcontroller / carstate / teslacan AP1 parts | `ap1_carcontroller.py`, `ap1_carstate.py`, `ap1_teslacan.py`, `ap1_actuator_plan.py`, `ap1_cluster.py` |
| `frogpilot_vcruise.py` AP1 block | `starpilot/controls/lib/starpilot_vcruise.py` `_ap1_set_speed` |
| `frogpilot_card.py` stalk levels / FWD hold | `selfdrive/car/tesla_ap1_card.py` (`TeslaAp1CardHooks`) |
| controlsd cluster set lift | `selfdrive/car/card.py` (`cluster_set_kph`) |
| `long_mpc.py` comfort brake | same file, `comfort_brake` kwarg on `LongitudinalMpc.update` |
| `longitudinal_planner.py` throttle cap | same file, AP1 branch replaces StarPilot's confirmed 0/1 gate |
| panda `safety_tesla.h` angle resync | `opendbc_repo/opendbc/safety/modes/tesla_ap1.h` (rebuilt firmware in `panda/board/obj`) |

## Differences from BogPilot

- StarPilot's Speed Limit Controller keeps a persistent set-speed override. AP1 turns it off
  (`SpeedLimitController.set_speed_override_enabled = False`), because the AP1 layer owns the set and the
  override would stop a pull from going back to SLC+offset. The gas override is kept.
- StarPilot's gas override follows vEgo while the pedal is pressed. With `SLCOverride` = set speed, BogPilot
  holds the set speed instead. This only matters while the driver is on the accelerator.
- The SLC offset bands now compare rounded display units (25 mph uses Offset2). This applies to every car.
- StarPilot's throttle gate (hysteresis plus 0.25 s confirm) is replaced on AP1 by `Ap1ThrottleCap`, fed the
  raw model flag, same as BogPilot. Other cars keep StarPilot's gate.
- `starpilotCarState` gains `resumePressed` (@31) and `spdCtrlLvr` (@32).
- Not ported: the BogPilot device clock restore (not AP1 code) and the blind-spot prototype
  (`bogpilot-tesla-ap1-bsm`, still on its own branch).

## Offline checks (route 0000002a, 2e, 32)

- Set speed: BogStar `StarPilotVCruise.update` vs BogPilot `FrogPilotVCruise.update`, same logged inputs:
  identical on 2a and 2e. On 32, one 1.1 s gas-pressed stretch differs (StarPilot gas override follows vEgo).
- Longitudinal: the full BogStar AP1 CarInterface (parser, carstate, carcontroller, packer) vs BogPilot's smoother,
  open loop: identical accel on all three routes. Every DAS_control frame was accepted by `tesla_ap1.h`.

Not road-tested on BogStar.
