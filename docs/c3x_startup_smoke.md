# C3X startup lifecycle and sandbox smoke

Local startup integration; **not device/boot/road validation**. No native outputs
changed. CSC implementation and public replay evidence are unchanged.

## Lifecycle order

`manager_init` keeps existing bootlog / metadata / Params construction / all
transient clears (including release-only flags) first, then:

1. `bogpilot_startup.before_defaults(params)` snapshots originals through optional
   w5 adapter and calls w6 `reset_requested(params, file_root, backup=closure)`.
2. Existing RecordFrontLock handling and registered default initialization.
3. `after_defaults(params, startup=before_result)` runs w8's optional
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
BOGPILOT_BACKUP_DIR or /cache/bogpilot/settings. Injected `backup()` must return
only a durable success receipt or false/raise. Never pass a failed truthy wrapper.

**w5 contract not available during implementation.** Proposed default optional
adapter is `openpilot.system.bogpilot.settings_backup.backup_settings(params,
file_root, backup_root, reason="boot"|"pre-reset")`, returning an object whose
`success is True` only after durable originals. Absent adapter is nonfatal and
reported; requested resets stay blocked. Parent must confirm/adapt this small
adapter to w5's actual API before combined validation. No backup logic is copied.
The boot snapshot is never automatically restored. Reset takes a fresh pre-reset
snapshot; w5 owns retention/idempotence.

w6 exact contract reviewed at 7841fafe456c88e440f3985d1bbbc96f289d80a5:
`openpilot.system.bogpilot.toggle_reset.reset_requested(params, file_root,
backup=closure)` returns status not_requested/completed/failed and safe stage error.
Only typed DoToggleResetStock is supported; no invented DoToggleReset behavior.
No peer history was merged here.

Before a successful pre-reset receipt is handed to w6, startup atomically writes
and fsyncs file-only `AP1StockReset1` intent. This happens **after originals are
backed up, before reset can mutate or clear its request**; a marker failure blocks
reset. The marker suppresses AP1 profile replay across manager restarts, including
power loss between successful reset and the next hook. Keep this marker in backup
coverage. No typed Params operation uses it. A reset failure after receipt may leave
the marker; this intentionally preserves the owner's explicit stock-selection intent.
No marker is written on absent/failed backup. Pending or failed reset suppresses
AP1 for the current initialization even if the optional module is missing.

w8 helper is optional until assembled; missing helper emits dependency-missing.
Migration leaves timer settings and later opt-in alone. There is no C3X screensaver
renderer. w7 optional test path: panda/tests/test_build_identity.py.

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
31 pass / 2 skipped on the isolated base: w6 runtime and w8 migration skips are
explicit missing-peer validations. w7 suite absent. Contract fixture backup/reset
tests prove orchestration only, NOT durability or peer transaction correctness.

After assembly, use the matching AGNOS 19.9 build VM and acquire its existing
serialized build lock; never run native checks on the Mac or a device:

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
manifest or substitute for real compilation/link tests. w7 source identity suite
runs if present. Native firmware outputs must be rebuilt by the assembly owner;
this Python-only branch changes no prebuilt output. Real native/combined tests
remain pending; no VM lock was acquired by this worker.

Unchanged native Params regression could not collect on this host (missing zmq);
unchanged CSC unit suite could not collect (missing setproctitle). Neither was
modified or counted as passing; baseline public replay was not rerun.
