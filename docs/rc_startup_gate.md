# C3X release-candidate startup acceptance gate

Scope: settings lifecycle, NOT full operating-system boot, device validation,
closed-loop actuation, firmware validation, or release promotion. No manager_init,
manager.main/thread, hardware processes, registration, network or live settings IO.
All values are labelled synthetic. Native API failures/missing libraries are FAIL,
not skip/pass. Gate reports no parameter/identity values or exception messages.

## Source and ownership

Base f5928f3b1, isolated port/c3x-rc-startup. Only this new tool, its tests and this
document are owned by track2. Production manager/reset/backup files unchanged.
Primary UI contract was read: port/c3x-w3-features at 86ff6d624 (WIP), not the final
candidate. Do not certify this base as the final build. Assemble this tooling onto
final primary candidate and pass its **full exact HEAD SHA** explicitly.

## Real-native pending invocation

The primary UI worker holds the VM lock for renders/tests. Do not compete. After
that owner releases the existing serialized VM lock, the integration operator must
acquire it using the existing protocol, sync final candidate + matching native
outputs to an isolated tree, and run inside AGNOS19.9 build environment:

```
PYTHONPATH=$PWD python openpilot/tools/bogpilot/rc_startup_gate.py \
  --sandbox-root /home/user/sandbox/c3x-startup-acceptance \
  --expected-commit "$(git rev-parse HEAD)"
```

For a git-free VM archive, first export scoped source identity on the clean final
source-host candidate (after committing this tool), then transfer it alongside the
matching archive and add --source-manifest /path/to/lifecycle-source.json above:

```
PYTHONPATH=$PWD python openpilot/tools/bogpilot/rc_startup_gate.py \
  --sandbox-root /dedicated/sandbox --expected-commit "$(git rev-parse HEAD)" \
  --write-source-manifest /outside/repo/lifecycle-source.json
```

Export mode is explicitly NOT acceptance. Verification requires all 13 fixed
lifecycle source paths and matching digests/commit; missing/mismatched identity
fails closed. The manifest is operator provenance, not an independent authenticity
proof. Git mode also rejects dirty lifecycle paths. Full build/source/native-output
manifest verification remains the packaging track's responsibility.
No outputs are rebuilt by this tool. Matching real libparams_c.so is mandatory;
Mac execution deliberately fails before importing it. Each run makes a new private
sandbox subtree (data are retained for audit); forbidden live/system roots and
source-tree sandbox paths are refused, including resolved symlink targets.
The native Params constructor always gets an explicit sandbox path; its resolved
storage path is checked. File and backup roots are passed explicitly and via
BOGPILOT_PARAMS_DIR / BOGPILOT_BACKUP_DIR; prior environment is restored.

## Eight required real-native cases

1. Ordinary AP1 boot, native default initializer and repeated reopen/boot preserve
   deliberate user edits, file-only upload choice, calibration, identity and
   synthetic non-key credential fixture; no reset intent invented.
2. Successful reset requires a real fsynced archive, preserves inactive fallback,
   identity/calibration/car selection; screensaver OFF; native settings defaults
   initialized; AP1StockReset1 survives a fresh-interpreter settings startup and prevents AP1 replay. Original
   content-addressed snapshots remain byte-identical across next boot.
3. Filesystem-unavailable backup fails closed, request and raw Params retained.
4. Corrupt same-content archive is rejected without overwriting it or resetting;
   request and originals retained.
5. Actual reset API with missing backup authority fails closed; actual missing
   snapshot reader rejects absent files.
6. One-shot native write fault delegates all other calls to real Params; actual
   reset rollback restores all seeded raw Params/files and retains request.
7. One-shot request-clear failure similarly rolls back and retains request.
8. Real backup/reset route all file-only keys to file storage; inactive typed-key
   fallback files are not erased. Tripwire proxy rejects file-only native calls.

FaultBoundary is explicitly a **fault injection proxy**, not storage simulation:
all successful calls reach actual libparams_c, production backup/reset/startup.
Default initialization reproduces the existing manager loop and transient clears;
it deliberately omits manager hardware/registration/metadata boot work. Native
module/class imports never have fake fallbacks. Scope compatibility is checked
against actual backup and reset exports. Gate exits nonzero unless all eight
cases pass; missing/failed cases never count as acceptance. No skip mode exists.

Host contract tests validate root safety, actual combined scope, actual archive
reader corruption handling, environment cleanup and stale-candidate refusal.
These are not counted as native acceptance evidence. Run:

```
PYTHONPATH=$PWD python -m pytest -q \
  openpilot/tools/bogpilot/tests/test_rc_startup_gate.py \
  openpilot/system/bogpilot/tests/test_settings_backup.py \
  openpilot/system/bogpilot/tests/test_toggle_reset.py
```

Limits: no real power cut/fsync failure certification, no private vehicle data,
no automatic recovery/restore, no data-retention policy change. Native VM run and
final candidate SHA acceptance are pending while primary owns the VM lock. No
production data mutation, product push, flash or binary commits.
