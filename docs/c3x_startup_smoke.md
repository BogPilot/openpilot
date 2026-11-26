# C3X startup lifecycle and sandbox smoke

> Development note, kept for reference. It describes this piece of work at the time it was written, not the
> released build. For what the release does, see `README.md` and `docs/bogpilot_c3x.md`.

Local startup integration; **not device/boot/road validation**. No native outputs
changed. CSC implementation and public replay evidence are unchanged.

## Lifecycle order

`manager_init` keeps existing bootlog / metadata / Params construction / all
transient clears (including release-only flags) first, then:

1. `bogpilot_startup.before_defaults(params)` snapshots originals through optional
   settings-backup adapter and calls the toggle reset's `reset_requested(params, file_root, backup=closure)`.
2. Existing RecordFrontLock handling and registered default initialization.
3. `after_defaults(params, startup=before_result)` runs the optional
   `migrate_screensaver_default_off(directory=...)`, then shared AP1 one-time
   defaults unless a stock reset is pending, failed, or previously backed up.
4. Existing msgq directory, version metadata, registration, logging. No process
   starts until the unchanged manager thread. Cleanup is unchanged.

AP1 was previously documented as boot-capable but the baseline manager contained
no call; this adds the call after registered defaults, using its existing markers
and shared typed/file-only store. Non-AP1 is untouched. Persistent values are not
restored from cache. Ordinary boot never invents a reset request. Native defaults
may recreate TuningLevel=0 / Confirmed=0; no selection is confirmed by startup.

## APIs and missing dependencies

`before_defaults(params, *, file_root=None, cache_root=None, backup=None,
reset=None) -> StartupResult(events, errors, profile_suppressed)`.
`after_defaults(params, *, file_root=None, startup=None) -> StartupResult`.
Default file root: BOGPILOT_PARAMS_DIR or /data/params_bogpilot. Backup root:
BOGPILOT_BACKUP_DIR or /cache/bogpilot/settings-backups. Injected `backup()` must return
only a durable success receipt or false/raise. Never pass a failed truthy wrapper.

Settings-backup contract. Default optional
adapter: `openpilot.system.bogpilot.settings_backup.backup_settings(params, *,
file_root, backup_root, reason="startup"|"before-reset")`, returning BackupResult
whose `success is True` only after durable originals. Absent adapter is nonfatal
and reported; requested resets stay blocked. No backup logic is copied.
Startup compares the toggle reset's reset_defaults keys with the backup's effective persistent SETTING_KEYS
plus FILE_KEYS; mismatched/private/unbacked scope blocks reset before invocation.
The toggle reset must use the corrected scope, not its original mismatched version.
The boot snapshot is never automatically restored. Reset takes a fresh pre-reset
snapshot; the settings backup owns retention/idempotence.

Toggle-reset contract:
`openpilot.system.bogpilot.toggle_reset.reset_requested(params, file_root,
backup=closure)` returns status not_requested/completed/failed and safe stage error.
Only typed DoToggleResetStock is supported; no invented DoToggleReset behavior.

Before a successful pre-reset receipt is handed to the toggle reset, startup atomically writes
and fsyncs file-only `AP1StockReset1` intent. This happens **after originals are
backed up, before reset can mutate or clear its request**; a marker failure blocks
reset. The marker suppresses AP1 profile replay across manager restarts, including
power loss between successful reset and the next hook. This lifecycle policy marker is deliberately outside the settings-backup snapshots;
it must persist in the live file store and is not restored from archives. No typed Params operation uses it. A reset failure after receipt may leave
the marker; this intentionally preserves the user's explicit stock-selection intent.
No marker is written on absent/failed backup. Pending or failed reset suppresses
AP1 for the current initialization even if the optional module is missing.

The screensaver migration helper is optional; a missing helper emits dependency-missing.
Migration leaves timer settings and later opt-in alone. There is no C3X screensaver
renderer. Optional panda source identity test: panda/tests/test_build_identity.py.

## Sandbox invocation (combined branch, matching runtime Python)

```
PYTHONPATH=$PWD python openpilot/tools/bogpilot/startup_smoke.py \
  --sandbox-root /path/to/dedicated/sandbox
```

Each run creates a new subdirectory with data/, cache/, pytest/ and report.json.
All BOGPILOT file/backup paths are sandboxed. The tests import **actual** Python
manager, process classes/config and hooks, but explicitly mock hardware, IPC,
registration, native Params, schemas and logging. Process.start and subprocess.Popen
raise if a daemon launch is attempted. No daemon/hardware/registration is started.
32 pass / 2 skipped on the isolated base: the runtime and migration skips are
explicit missing-module validations. Contract fixture backup/reset
tests prove orchestration only, NOT durability or cross-module transaction correctness.

After assembly, use the matching AGNOS 19.9 build VM and acquire its existing
serialized build lock; never run native checks on a desktop or a device:

```
PYTHONPATH=$PWD python openpilot/tools/bogpilot/startup_smoke.py \
  --sandbox-root /path/to/vm/sandbox --native-imports \
  --native-manifest /path/to/build-manifest.json
```

`--native-imports` requires Linux /VERSION=19.9, imports real Params/schema,
manager/process configs and calls settings lifecycle on sandbox Params. It does
NOT call manager_init/main/thread (bootlog and registration are not sandbox-safe).
Missing dependencies fail this stage, never count as a pass. Manifest JSON:
`{"agnos":"19.9","files":[{"path":"repo-relative","kind":"source|output",
"sha256":"..."}]}`; both source and output entries required. Hashes must be
recorded from actual matching build; this checker cannot prove an untrusted build
manifest or substitute for real compilation/link tests. The panda source identity
suite runs if present. Native firmware outputs must be rebuilt in the release build;
this Python-only branch changes no prebuilt output. Real native/combined tests
were not run for this note.

Unchanged native Params regression could not collect on this host (missing zmq);
unchanged CSC unit suite could not collect (missing setproctitle). Neither was
modified or counted as passing; baseline public replay was not rerun.
