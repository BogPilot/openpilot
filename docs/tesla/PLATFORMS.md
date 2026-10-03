# Tesla early platforms

BogPilot is not a product. No warranty. The driver remains responsible. Comply with local law. This commit is not validated on a bench or in a car.

## This commit

Phase 3 layer 1, on the comma 3X / Tesla Model S AP1 target. Recognize a platform. Do not command lateral or longitudinal control.

`TeslaPlatform` in `selfdrive/car/tesla/values.py` has `preap`, `ap1_s`, `ap1_x`, and `ap2`. `classify_tesla_platform` in `selfdrive/car/tesla/platform.py` maps a resolved identity to one of those, or to `None`. `long_control_allowed` is false for `None` and for every platform, including `ap1_s`.

`None` means longitudinal is not allowed. Do not engage long. This commit does not change `controlsd`, panda safety, or `interface.py`. `dashcamOnly` stays as it was. Longitudinal stays refused until a later layer adds a panda safety mode for the platform.

## Control matrix

Nothing below is commanded by this commit.

| Platform | Production recognition | Lateral | Longitudinal |
| --- | --- | --- | --- |
| `preap` | unmatched (`None`) | not commanded | not allowed |
| `ap1_s` | `CAR.TESLA_AP1_MODELS` | not commanded | not allowed |
| `ap1_x` | unmatched (`None`) | not commanded | not allowed |
| `ap2` | `CAR.TESLA_AP2_MODELS`, or `None` if AP1 is also present | not commanded | not allowed; full control not enabled |
| Raven (`CAR.TESLA_MODELS_RAVEN`) | not an early platform | unchanged by this commit | unchanged by this commit |

## How `ap1_s` is recognized

`CAR.TESLA_AP1_MODELS` is the only AP1 Model S identity in this tree. `selfdrive/car/tesla/fingerprints.py` `FW_VERSIONS` lists `TESLA_AP2_MODELS` and `TESLA_MODELS_RAVEN` only. There is no AP1 Model S firmware row to prove, and this commit does not add CAN message-count fingerprints.

The classifier maps that existing platform member (and the same member's name, `TESLA_AP1_MODELS`) to `ap1_s`. It does not look at `CarSpecs` or `dbc_dict`. Those are shared with `TESLA_AP2_MODELS` in `values.py`, so matching them would also match AP2.

## `ap2` and Raven

`CAR.TESLA_AP2_MODELS` maps to `ap2` because it is a different platform member from `CAR.TESLA_AP1_MODELS`. Presented together, the two are ambiguous and the classifier returns `None`.

`CAR.TESLA_MODELS_RAVEN` does not map to `ap2`. Raven is not reclassified. It stays the existing platform and is not part of this early contract. A Raven identity next to a single AP1 or AP2 identity does not cast a second early vote.

Mapping `ap2` does not enable control.

## `preap` and `ap1_x`

Both members exist on the enum so the contract can name them. No production fingerprint, firmware entry, or CAN address set selects them. The classifier returns `None` for every production identity. It returns `preap` or `ap1_x` only when a test passes an `EarlyPlatformFixture` for that member. That fixture is not a bus fingerprint, and it cannot be built for `ap1_s` or `ap2`.

pre-AP and AP1 Model X are not enabled. AP2 full control is not enabled.

## Buses already named in this tree

These are the index comments already in `selfdrive/car/tesla/values.py` `CANBUS`. They are not install steps. This commit does not add an OBD-C, mirror-housing, or dual-harness procedure.

- Lateral harness: `chassis` 0, `radar` 1, `autopilot_chassis` 2
- Longitudinal harness: `powertrain` 4, `private` 5, `autopilot_powertrain` 6

Harness type for the car is not decided here.

## Engagement

Comma 3X. Tesla Model S AP1 (`ap1_s`). This commit does not enable lateral or longitudinal control. BogPilot is not a product. No warranty. The driver remains responsible. Comply with local law. Not validated on a bench or in a car.

`selfdrive/car/tesla/interface.py` still assigns dashcam mode before the safety config. That assignment was not changed:

```
ret.dashcamOnly = True
```

`frog_ap1` set this false. This tree does not.

The safety model is still `car.CarParams.SafetyModel.tesla`. The flag names in that file are unchanged:

- `Panda.FLAG_TESLA_RAVEN` is applied only when `candidate == CAR.TESLA_MODELS_RAVEN`. AP1 Model S does not take it.
- `Panda.FLAG_TESLA_LONG_CONTROL` is applied only when `0x2bf` is present on `CANBUS.autopilot_powertrain`.
- `Panda.FLAG_TESLA_POWERTRAIN` is applied only on the second panda config in that same branch.

The openpilot-long param in that branch is `not frogpilot_toggles.disable_openpilot_long`. The long flag above is set whenever `0x2bf` is present, even if that toggle disables the param.

AP1 Model S with no `0x2bf` on that bus gets one safety config and a flags value of `0`. That is not the bridge change that deleted the longitudinal gate. `panda/board/safety/safety_tesla.h` was not edited. `tesla_tx_hook` still refuses `DAS_control` when `TESLA_FLAG_LONGITUDINAL_CONTROL` is unset (`tesla_longitudinal` is false, and the else branch sets `violation`). Lateral TX still goes through `steer_angle_cmd_checks` and `TESLA_STEERING_LIMITS`. When the long flag is on, accel still goes through `longitudinal_accel_checks` and `TESLA_LONG_LIMITS`.

`CarController.update` was not executed in this environment. `opendbc/can/packer_pyx.so` is AArch64, and importing the controller also needs `parser_pyx` and `msgq`. The disengaged decision is `build_actuator_plan` in `selfdrive/car/tesla/actuator_plan.py`, which `update` calls, and `TeslaCAN.create_steering_control` packs it.

On an even frame with lateral inactive, the steering message is still `DAS_steeringControl` (`0x488` in `TESLA_TX_MSGS`) with `DAS_steeringControlType` 0. Type 0 is NONE. `tesla_tx_hook` does not treat 0 or 3 as steer control enabled. The angle field echoes the measured angle. It is not a request to move EPAS to the actuator angle. Odd frames send no steering message. No `DAS_control` is planned unless `CP.openpilotLongitudinalControl` is true.

Gap, not changed: `update` does not read `CC.enabled` or `CC.longActive`. If `openpilotLongitudinalControl` is true, a laterally inactive call still plans `DAS_control` (`0x2b9` on chassis, `0x2bf` on powertrain in `safety_tesla.h`) with `DAS_setSpeed`, `DAS_accelMin`, and `DAS_accelMax` taken from `actuators.accel`. There is no fixed set-speed of 145 or 0 in this controller. That frame is a longitudinal command, not a cancel. This commit does not turn the param on and does not add a command. Interface sets the param true only in the `0x2bf` branch above.

There is no pre-AP command builder. `long_control_allowed` is false for `preap`. The messages this controller can pack are `DAS_steeringControl`, `STW_ACTN_RQ`, and `DAS_control`. No iBooster apply and no friction-brake command. `BrakeMessage` (`0x20a` chassis, `0x1f8` powertrain) is an RX check in `safety_tesla.h`, not a TX message.

