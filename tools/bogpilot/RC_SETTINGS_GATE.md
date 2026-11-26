# C3X release-candidate settings gate

`python3 tools/bogpilot/rc_settings_gate.py [--root REPO] [--json]` — static audit, exit 0 only if all checks PASS.
No openpilot imports, no native params library, no /data or /cache access. Missing inputs, unparsable
literals, unknown header types/flags all FAIL (never skip).

Checks (21 regression tests in `tools/bogpilot/tests/test_rc_settings_gate.py`, synthetic temp-copy mutations):
- header: known types/flags, generated `params_keys_bogpilot.h` == `BOGPILOT_PARAMS`, no duplicates with upstream `params_keys.h`
- defaults: AlwaysOnLateral 0, NudgelessLaneChange 0, AlertVolumeControl 0, every *Volume 101, TuningLevel 0 +
  TuningLevelConfirmed 0 (registry, header and shipping overlay agree); reset leaves tuning unset; AP1 profile never sets them
- file-only: RedesignUI/BSMFlameTracks/SwapSpeedGraph/DeveloperHUD/HideAccelGraph are file toggles and never typed Params;
  shipping file defaults match the file registry; AP1 file profile keys are not typed
- screensaver: OffroadScreensaver reserved file key default OFF, not typed, no C3X settings row
- UI: every stored `param`/`parent_param` in toggle_metadata.py is registered (MANAGE-labelled BUTTON grouping panels excepted);
  documented known gap `TeslaEarly` tolerated only while no module imports toggle_metadata
- CSC: CurveSpeedController/ShowCSCStatus/calibration/long-control keys registered; ShowCSCStatus child of CSC;
  CSC requires openpilot_longitudinal; no controls code reads ShowCSCStatus (display only)
- manager: default loop writes only when `params.get(k) is None` (user edits preserved)
