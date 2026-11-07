# C3X scoped settings backup

`openpilot.system.bogpilot.settings_backup.backup_settings(params, *, file_root,
backup_root=Path("/cache/bogpilot/settings-backups"), reason="startup")` returns
`BackupResult(success, path, error)`. Its boolean value is durable success, not
merely that a result object exists. Error is exception type only, never values.
`read_snapshot(path)` validates and returns a document, never restores settings.

Startup owner calls before reset, migrations and default initialization, while
writers/processes are quiescent. Reset owner receives a zero-argument closure:

```python
backup=lambda: backup_settings(params, file_root=data_root / "params_bogpilot",
                               backup_root=cache_root / "bogpilot/settings-backups",
                               reason="before-reset")
```

No reset may proceed on a false receipt. An ordinary startup backup failure must
not crash manager. This module has no manager hook, default initialization,
Params writes, migration, automatic restore, pruning or network behavior.

## Daily behavior verified, not transplanted blindly

The existing daily `frogpilot/common/frogpilot_functions.py:backup_toggles`
mirrors default-table values into `/data/params_backup` and `/cache/params`, then
creates dated archives under `/data/toggle_backups` (nominal five-backup cleanup).
Boot invokes it in a background thread after valid time; the process also calls
it periodically. Daily manager restores only missing live keys from its cache,
or chooses defaults during an explicit reset. It does not wholesale restore a
settings archive at boot. This port separates archival from those lifecycle
policies: it never imports old caches or resurrects settings after stock reset.
A future missing-key cache recovery feature needs a separate reviewed contract.

## Scope and format

`SETTING_KEYS` and `FILE_KEYS` are frozen reviewed ownership lists in the module;
registry additions are not automatically included. Only current exactly
PERSISTENT registered settings are eligible. Credentials, DONT_LOG keys,
VIN/dongle identity, accounts, route/navigation history, calibration blobs,
runtime/reset markers and ShowUploadRate are excluded. Freeform search/startup
text, private schedule, dynamic model lists and telemetry/history are excluded.
No registry defaults are synthesized. Empty or nonUTF8 stored bytes survive
base64 encoding. Known keys use checked raw Params paths, not lossy typed
get/string put conversion. Unknown compiled settings use injected file_root;
file-only UI keys never touch typed Params, even if the native table lists them.

V1 JSON holds entries `{key: {store: "params"|"file", value: base64}}` and a
SHA256 digest over canonical entries. Snapshot filename is its digest; latest.json
is a complete document, not a symlink. New versions and unknown keys fail closed.
Snapshots are immutable/reused by content, original revisions are never pruned.
Tempfiles have 0600 mode, backup root 0700; file and directory are fsynced before
success. Publishing is serialized with nonblocking flock. A failed latest commit
can leave an orphan durable snapshot but preserves the prior latest. /cache may
be evicted: this is local best-effort archival, not disaster recovery. No /data
fallback or external upload occurs. No multiple-key live transaction is claimed;
call while settings writers are quiescent.

## Validation

Pure-Python temporary-directory tests cover typed/raw/file-only handling,
nonUTF8/empty bytes, missing/corrupt/version-unknown data, future/transient/private
exclusions, duplicate revisions, pre-reset original retention, permissions,
locking, fsync and both snapshot/latest rename interruption. No real /data or
/cache is touched. Native AGNOS Params adapter and assembled manager/reset
lifecycle must still be validated on the serialized build VM. No native output
needs rebuilding for this Python-only component.
