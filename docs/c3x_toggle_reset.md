# C3X explicit stock reset integration

`openpilot.system.bogpilot.toggle_reset.reset_requested(params, file_root, backup=closure)`
returns `ResetResult(status, error)`: `not_requested`, `completed`, or `failed`.
No native import, Params construction, default IO path, migrations, reboot, or UI mutation.

## Startup/backup contract

* Startup owner calls serially before registered defaults initialization and before daemons.
* Only typed `DoToggleResetStock=True` authorizes reset. Unknown/missing request is a no-op.
* Backup owner supplies a synchronous closure taking no arguments, returning a truthy
  receipt **only after durable preservation of the original typed Params and file store**.
  A missing closure, false result or exception fails before setting mutation. This branch
  does not implement or claim verification of the separate backup dependency.
* Do not pass an always-truthy result wrapper with a failed status. Adapt its success
  explicitly, e.g. return receipt if backup_result.success else None.
* Registered keys use typed `cpp2python` then blocking `put`; file-only keys never call
  Params, even if present in its compiled table. Uncompiled owned keys use the supplied
  file root. Stale fallback copies of typed owned keys are removed after backup.
* Failed reset retains its request, rolls back in-memory snapshots best-effort, and
  returns an error stage (not private values). An incomplete rollback requires restoring
  the durable backup. Do not clear the flag or call a legacy reset implementation on failure.
* Success clears the flag LAST. Prevent stale cache restoration or AP1 profile replay
  from undoing the stock selection. `TuningLevel` and `TuningLevelConfirmed` are removed;
  the default initializer must skip these if physical absence is required. Their compiled
  default of 0 is also unconfirmed, not a user-selected tuning level.

## Deliberate scope

Stock column comes from own daily 367e1fe registry, with approved C3X shipping
PARAM_OVERRIDES. The ownership snapshot is explicit: future/unknown registry keys
are not reset automatically. Audio stays audible (control=0, volumes=101), AOL and
nudgeless off, screensaver off. Targeted file UI toggles reset; upload-rate, AP1
car-dependent toggles, markers, vehicle identity, credentials, calibration/learned
values, runtime state, and other non-owned files remain untouched. Blank-default
vehicle tuning/auth/data fields are not erased. No generic factory reset or normal
DoToggleReset handler is added.

Tests: pure Python unittest with a strict typed Params fake and temporary directories;
not native Params/device/boot validation. Assembly must separately test w5 durable
backup plus w10 startup ordering/failure/cache behavior using sandbox roots.
