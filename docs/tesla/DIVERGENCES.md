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

## Instrument-cluster frames deferred

In this tree's `opendbc/tesla_can.dbc`:

- `DAS_object` is absent.
- `DAS_telemetry` is absent.
- CAN id `0x399` (decimal 921) is `BO_ 921 AutopilotStatus`, not a `DAS_status` frame name at that id.

IC lead-car and telemetry frames that depended on those missing definitions are deferred. No invented signals.

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
