# FrogPilot -> BogPilot rename

BogPilot is forked from FrogPilot's work (FrogAi and contributors) and no longer tracks FrogPilot. Every FrogPilot name in
the code is now a BogPilot name. The credit to FrogPilot stays in `README.md`, `LICENSE` and
`docs/bogpilot_c3x_provenance.md`.

## What was renamed

| Before | After |
|---|---|
| `FrogPilot*` types in `custom.capnp` | `BogPilot*` (`FrogPilotCarState` is `BogPilotCarStateMsg`, see below) |
| `Event.frogpilot*` fields in `log.capnp` | `Event.bogpilot*` |
| services `frogpilotPlan`, `frogpilotCarState`, ... | `bogpilotPlan`, `bogpilotCarState`, ... |
| `FROGPILOT_*` constants, `frogpilot_*` modules, functions and variables | `BOGPILOT_*`, `bogpilot_*` |
| `FrogPilot*` Params keys | `BogPilot*` Params keys |
| `selfdrive/ui/bogpilot/frogpilot_defaults.py` | `selfdrive/ui/bogpilot/bogpilot_defaults.py` |

`custom.FrogPilotCarState` became `BogPilotCarStateMsg` because `car.capnp` already defines `BogPilotCarState`
(`CarState.bogpilot`) in the same C++ namespace. The struct id is unchanged.

## Wire compatibility (capnp)

Struct ids, field ordinals, union discriminants, offsets and sizes are unchanged. Only names changed. The Event union
members stay at ordinals @107..@116, and Cap'n Proto identifies them by ordinal, never by name, so a log recorded before
the rename decodes with the new schema.

`FrogPilotCarControl` had no explicit id (it was derived from its name), so it now carries the old derived id explicitly
(`@0x95bd710036ea524c`); renaming it does not change its id or the ids of its nested types.

Checked by compiling the old and new schemas and comparing all 350 schema nodes: same ids, same ordinals, same layout.

## Old service names (rlogs, tools, debug site)

A pre-rename rlog decodes with the new schema, but `msg.which()` reports the new name (`bogpilotPlan`, not `frogpilotPlan`).
For tools that still look events up by the old name:

* `cereal/services.py` has `LEGACY_SERVICE_ALIASES` (old name -> new name) and `canonical_service_name()`.
  The old names are not services: nothing is published or logged under them.
* `LogReader.filter()` accepts either name.
* A tool that compares `which()` strings itself should normalise with `canonical_service_name()`, or accept both names.

`openpilot/system/bogpilot/tests/test_legacy_names.py` decodes a small log recorded with the pre-rename schema
when that local fixture is present (it is not part of the public tree) and looks it up under both names.

## Saved settings and stats

Renamed Params keys that persist across boots:

`FrogPilotApiToken`, `FrogPilotCarParamsPersistent`, `FrogPilotDongleId`, `FrogPilotDrives`, `FrogPilotKilometers`,
`FrogPilotMinutes`, `FrogPilotStats`, `FrogPilotTelemetry` (each now `BogPilot...`). The other renamed keys are cleared on
every manager start, so there is nothing to carry over for them.

`openpilot/system/bogpilot/legacy_migration.py` copies the old values to the new keys once. `manager_init` runs it
through `bogpilot_startup.before_clear`, before its first `clear_all`: the old names are not registered keys any more, so
`clear_all` deletes their files from the Params directory as unknown names. That is also before registered defaults are
applied. `bogpilot_startup.before_defaults` runs it again after the clears (a no-op once the done marker exists), which
still finds values kept only under `/data/params_bogpilot`.

* Reads the old value from the real Params directory first, then from `/data/params_bogpilot/<OldKey>`.
* Writes the new key to real Params when the params library knows it, otherwise to `/data/params_bogpilot/<NewKey>`.
* Copy only: the migration never deletes or rewrites the old key. The old files in the Params directory are still
  removed by the manager's `clear_all` right after the copy, as for any unknown name; copies under
  `/data/params_bogpilot` stay.
* A new key that already holds a value is never overwritten. Running again changes nothing.
* The stats JSON also contained counters named `FrogPilotDrives`, `FrogPilotMeters` and `FrogPilotSeconds`; these are
  renamed inside the copy, every other counter is carried over untouched. `drive_tracking.load_stats` also accepts the
  old counter names.
* A failure on one key never stops the others and never raises into the manager. The done marker
  (`/data/params_bogpilot/BogPilotRenameMigrated1`) is written only when every key settled, so a partial run is retried
  on the next boot (by then only from `/data/params_bogpilot`), and once the marker exists the migration does not run
  again (a value the user cleared later is not brought back).

`/data/params_bogpilot` itself, and the other file-backed names under it, are unchanged.

Release channel names: `FrogPilot` and `FrogPilot-Vetting` stay in the accepted channel sets in `bogpilot_settings.py`, so a
device still tracking a branch with that name keeps its behaviour.

## Build outputs

The tracked C++ bindings in `openpilot/cereal/gen/cpp` and `openpilot/cereal/services.h` are regenerated from the current
schema. The compiled artifacts that are also tracked (`libparams_c.so`, `pandad`, `loggerd`, `camerad`, ...) are rebuilt
from the new names in this release, so the device's Params key table and the logged service names are the BogPilot ones.
