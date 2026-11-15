# Divergence: NoLogging stops all on-device recording

Entry in the `docs/tesla/DIVERGENCES.md` style, kept in its own file so it can be folded into `DIVERGENCES.md`.

### NoLogging ON: no rlog/qlog, no camera encodes, no bootlog
- Platforms: every car (manager process gate; no car, panda, DBC or CAN change).
- Reference behavior: BogPilot 0.9.7 (`568fea947`) `system/manager/process_config.py:50-51` `allow_logging` =
  `not frogpilot_toggles.no_logging and logging(...)`, used by `loggerd` and `encoderd` (`:80-82`) and by `logcatd`,
  `proclogd`, `logmessaged` (`:73-75`) and `statsd`. `toggle.no_logging` (`frogpilot_variables.py:931`) is
  `DeviceManagement` and `NoLogging`, each honoured at its tuning level, except on the vetting branch or with
  `force_onroad`. 0.9.7 still wrote a bootlog at every manager start (`manager.py:44`).
- Before this change: `NoLogging` (BogPilot param, default `"0"`) was registered but had no runtime reader and no
  settings row: `loggerd` ran on `logging` (only `DisableLogging` on a notCar), `encoderd`, `proclogd` and
  `journald` ran onroad, `logmessaged` always, and `save_bootlog()` ran at every manager start.
- Our behavior: `system/manager/nologging.no_logging(params)` = `DeviceManagement` and `NoLogging` (tuning levels and
  unset defaults read exactly as `bogpilot_settings.get_bool`, but straight from params; the manager does not import
  `bogpilot_settings`).
  When true, `process_config` does not start `loggerd` (rlog/qlog), `encoderd` (fcamera/ecamera/dcamera/qcamera),
  `proclogd`, `journald` (0.11's `logcatd`) or `logmessaged` (swaglog files), and `helpers.save_bootlog()` writes no
  bootlog. A change while onroad stops them on the next manager cycle. With `NoLogging` off (the default) every
  predicate is the same as before. There is no stream encoder, uploader, athena or statsd in this tree.
- Settings: the "Disable Logging" row is in its 0.9.7 spot (Device Settings, after the shutdown
  timer), tuning level 2 ("Advanced"), shown only while its parent `DeviceManagement` is on. 0.9.7's confirmation
  dialog on enabling it (`device_settings.cc:168`, `setConfirmation(true, false)`) is ported: turning it ON shows the
  row title and its 0.9.7 warning text with Enable / Cancel every time; Cancel leaves it OFF; turning it OFF saves
  at once with no dialog.
- Differences from 0.9.7: the bootlog is also skipped (ON means nothing is recorded); the vetting-branch and
  `force_onroad` exceptions are not ported (ON always means no recording); `encoderd` keeps its onroad predicate
  plus the gate (0.9.7 also tied it to `DisableLogging` on a notCar).
- Unchanged: `deleter` (local cleanup of older drive data only, no upload), `tombstoned` (local crash files, as 0.9.7),
  driving processes. `tools/bogpilot/manager_smoke.py` and the install verifier expect `logmessaged`, so run them
  with NoLogging off.
- Tests: `openpilot/system/manager/test/test_nologging_gate.py` (both states onroad and offroad, default OFF equal to
  the previous predicates across car/notCar and `DisableLogging`, parent and tuning-level gating, bootlog).
- Credits: BogPilot 0.9.7 (`allow_logging`, `no_logging`), FrogPilot (NoLogging toggle), comma.ai openpilot (`logging`).

## Known latent bug (not fixed here)

- `openpilot/common/bogpilot_settings.py` imports `BOGPILOT_BRANCHES` from `openpilot.common.version`, which this tree
  does not define, so importing `bogpilot_settings` raises ImportError. Nothing imported it at runtime before NoLogging;
  a first NoLogging version that imported it from `process_config` crashed the manager import in the gate build.
- This change leaves that import untouched (base file unchanged) and keeps `bogpilot_settings` out of the manager:
  `process_config.py` and `helpers.py` use `system/manager/nologging.py`, which imports only `bogpilot_params`.
  `test_nologging_gate.py::test_manager_imports_and_starts_without_bogpilot_settings` makes `bogpilot_settings`
  unimportable and checks the manager imports and builds its launch set with NoLogging OFF and ON.
- Any future runtime importer of `bogpilot_settings` must fix or guard that import first.
