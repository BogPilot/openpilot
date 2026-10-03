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
