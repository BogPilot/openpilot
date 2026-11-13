# Curve speed control: Pre-AP pedal (vision-only) — divergences

Credit: BogPilot 0.9.7 / na-preap 568fea947 (FrogPilot Curve Speed Controller lineage) for the behavior. NAP e99f4dc75
(opendbc cc39c7fa) and Tinkla 501c7de have no curve speed controller. The panda safety mode (`tesla_preap.h`) is unchanged.

## What 0.9.7 did
- CSC ran on any car with openpilot longitudinal and the toggle on, Pre-AP pedal cars included:
  `frogpilot/common/frogpilot_variables.py:851` (`openpilot_longitudinal and CurveSpeedController`), default ON at level 1
  (`:329`), and `frogpilot/controls/lib/frogpilot_vcruise.py:54-70` (control when `v_ego > CRUISING_SPEED`, enabled and a
  curve is detected; otherwise `log_data` training), merged as a `min()` with the cruise and SLC targets (`:106-112`).
- Road curvature was vision-only from modelV2: `frogpilot/common/frogpilot_utilities.py:104-115`
  `calculate_road_curvature` (orientationRate.z x velocity.x at the peak node), hooked at
  `frogpilot/controls/frogpilot_planner.py:106-108`. No map or 0x3C8 curvature.
- The Tesla look-ahead curve brake was built for every Tesla: `selfdrive/car/tesla/curve_speed.py:173-175`
  (`tesla_curve_brake_for`), with the 2.0 m/s^2 cornering cap at `:32`.
- Training ran while `longActive` was False (`frogpilot/controls/lib/curve_speed_controller.py:35-37`); weather could
  derate the learned limit (`:98-99`).

## This tree
- Platforms (`openpilot/selfdrive/controls/lib/csc_platform.py:35` `csc_supported`): AP1 with openpilot long (unchanged),
  or Pre-AP with openpilot long (`pcmCruise` False) and a stored, detected and calibrated Comma Pedal
  (`preap/calib.py` `pedal_long_allowed`). Never on a no-pedal Pre-AP car. Stricter than 0.9.7. The stored pedal state is
  read when the planner starts; a pedal calibrated later in the same drive enables CSC on the next start.
- Control gate (`csc_platform.py:71` `csc_gate`, used at `ap1_curve_speed.py:153` and `:186`): on Pre-AP, CSC is inactive
  unless the pedal is live on its latched bus (carState.bogpilot `preapPedalDetected`, `preapPedalCalibrated`, not
  `preapPedalUnavailable`, not `preapPedalNotResponding`), and it lowers vCruise or brakes only while the pull FSM is in
  FULL (`preapFsmMode` 4, `preap/engagement.py` Mode.FULL). Steering only (OFF, LOCKOUT, LAT_PENDING, LAT_ONLY) never
  caps and releases the curve brake. Missing fields fail closed. Stricter than 0.9.7, which followed `controlsState.enabled`.
- Everything else is the AP1 CSC unchanged: vision-only modelV2 path and its fail-closed checks, the 2.0 m/s^2 Tesla cap,
  the 2 s hold, never raising the driver's set speed, blinker suspension, CSC after SetSpeedLimit / SLC (`min()`), and the
  AP1 comfort arbitration (`longitudinal_planner.py:91`), which now also runs on Pre-AP pedal cars.
- Curve brake (`ap1_curve_brake.py:180` `ap1_curve_brake_for`): built on the same platforms. Its floor stays
  `A_MIN = -1.2` m/s^2 (`:41`), inside the Pre-AP regen range (`vdas_constants.REGEN_MAX` -1.5). Accel limits
  (`preap/accel_limits.py`) and the pedal command limit (`preap/pedal_can.py`, panda `tesla_preap.h` 2500) are unchanged;
  CSC can only lower demand.
- Toggle: the existing `CurveSpeedController` (default ON at level 1, `common/bogpilot_params.py:101`) and `ShowCSCStatus`
  (display only, `:344`). No new param.
- Settings row: `csc_row_visible` (`csc_platform.py:82`) is the visibility rule: AP1 with openpilot long, or Pre-AP with a
  stored calibrated pedal; hidden on a no-pedal Pre-AP car and without CarParams. No settings panel renders the
  `toggle_metadata.py` rows in this tree yet (the settings gate forbids importing it), so the rule is in place for when one does.

## Decisions
- Weather slowdown: Decision: the weather slowdown is left out of pre-AP CSC. BogPilot 0.9.7's weather derate
  (568fea947, `frogpilot/controls/lib/curve_speed_controller.py:98-99`) was internet-only (OpenWeatherMap at
  `frogpilot/controls/lib/weather_checker.py:12-14`, request at `:153`), off by default
  (`frogpilot/common/frogpilot_variables.py:619`, WeatherPresets default `"0"`), and stale when offline
  (a failed request still stamps `last_updated` at `:123` and keeps the previous `weather_id` at `:124-139`,
  with no expiry).

## Pending decisions (defaults in use)
- Learning in steering only: allowed (0.9.7 trained while `longActive` was False). CSC never caps in steering only.
  PENDING DECISION.
- Settings row before the pedal is calibrated: hidden until the stored pedal is detected and calibrated. PENDING DECISION.
- ShowCSCStatus on Pre-AP: same param, default ON at level 2, display only. PENDING DECISION.
- Map / 0x3C8 curvature: not ported (0.9.7 Pre-AP CSC was vision-only). PENDING DECISION.
- Default ON at level 1 (as 0.9.7) and the curve-brake floor -1.2 m/s^2 (not the full Pre-AP regen -1.5). PENDING DECISION.

## Tests
`openpilot/selfdrive/controls/tests/test_csc_platform_gate.py` (gate: no pedal, uncalibrated, steering only, FULL, AP1,
other cars, curve-brake factory, row visibility, toggle default), `test_preap_curve_speed.py` (Ap1CurveSpeed with synthetic
messages: FULL only, steering only never caps, fail closed, SetSpeedLimit then CSC, learning in steering only; needs the
native messaging and MPC libraries and skips without them), `test_ap1_curve_brake.py` (factory), and the AP1 tests
`test_ap1_curve_speed_planner.py`.
