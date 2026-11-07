# C3X full-system build/import acceptance

`python3 tools/bogpilot/rc_build_gate.py --source FINAL_GIT_CHECKOUT --candidate FULL40 --artifact-root STAGE --artifact-manifest artifacts.json --evidence-root EVIDENCE --evidence gates.json --output OUTSIDE_SOURCE/report.json`

Exit 0: all acceptance receipts and static checks passed. Exit 2: blocked, missing,
failed, stale, unrun or skipped evidence. This read-only tool does NOT acquire locks,
launch builds, import/start services, execute launchers, package files or install.
Even a passing result always says `installable=false`, `device_boot_validated=false`,
`road_validated=false`. Unsigned local evidence is not execution attestation.

## Inputs and responsibilities

Source is the clean Git source-of-truth checkout, full explicit candidate SHA,
descended from stock C3X release-tizi f7db927c728bab57bb1263e05465766a8f28fc9d.
Do not use `git_src_commit` as candidate identity: that is an upstream marker.
Only untracked `.panda-source.json` is allowed as generated metadata, and only with
matching source_commit and dirty=false; firmware gate additionally verifies its
content inventory. Do not build in/fill the frozen Git checkout with outputs.

Artifact manifest is EXACT packaging track's schema 1:

```json
{"schema":1,"candidate_sha":"FULL40","agnos_version":"19.9","architecture":"aarch64","artifacts":[{"path":"relative/path","sha256":"HEX64","size":123,"mode":"0755","format":"elf-aarch64"}]}
```

`data`/`0644` and package format `elf-arm` are also supported. ARM32 ELF32
machine40 is allowed ONLY for panda/board/obj/*.elf firmware; it cannot replace
a runtime service. ELF64 little-endian machine183 is checked without
execution. Every declared native service executable must be covered. Packaging
owns complete shipping native-extension/model/firmware coverage; its PASS receipt
is mandatory. Do not generate a second package or firmware artifact set here.
Artifact hashes/permissions/size, source identity, launcher syntax/mode, model
assets/LFS pointers, and tracked dependency pins are independently checked.
Dependencies vendored as tracked trees are reported as tree hashes, NOT invented
submodule commit IDs.

Evidence envelope schema 1:

```json
{"schema":1,"candidate_sha":"FULL40","primary_ui":{"status":"ready","candidate_sha":"FULL40","feature_tip":"FULL40"},"gates":{"startup":{"status":"pass","candidate_sha":"FULL40","logs":[{"path":"startup-result.json","sha256":"HEX64"}]}}}
```

Required receipts: startup, firmware, package, controls, settings, ui, recorder,
provenance, build, imports. No isolated-worker source SHA may stand in for final
assembled SHA. Primary feature tip must be an ancestor of the final source.
All log/report paths are relative to explicit evidence root, checksummed, and
source-bound: JSON reports identify candidate_sha/source_sha/source_commit, OR
plain logs begin `RC_SOURCE_SHA=FULL40`. A prefixed JSON report's own identity and
failure status are still checked. Old/failed JSON cannot be relabeled by a new
header. JSON PASS is case-insensitive; failed/skipped/pending/unrun/xfail counters
are not passing. For gate formats lacking identity, the coordinator must rerun on
final source with a source-prefixed log and truthful outcome; never relabel old
results. Static gate's ordinary output is not a native build/import proof.

Build receipt additionally requires `kind:"full_scons"`, `targets:[]`,
`exit_code:0`, `environment:"agnos:19.9-build/aarch64"`, and hashed log containing
`scons: done building targets.` at its end. Imports receipt requires
`modules:{EVERY_DECLARED_PYTHON_OR_DAEMON_MODULE:"pass"}`, `daemons_started:false`.
AST service inventory in the report enumerates exact required modules. Missing or
GPU/device-constrained imports stay BLOCKED, not skipped passes. Receipt counters
are deliberately not inferred from human prose. These receipts are unsigned.

## ONE final native session (coordinator recipe, NOT automatic execution)

1. Wait for explicit primary UI READY and native lock release. Assemble final UI,
   gates and any authorized confirmed controls correction outside product branch.
   Freeze exact full SHA; fast preflight first. Recorder fixes at feature477f08a9f
   supersede earlier86ff failures, but rerun on final source. Controls lane-change
   continuation gap is UNCONFIRMED until native gate runs. Package/provenance
   final exact inventory review must finish; no blanket privacy waivers.
2. Firmware owner's `RC_FIRMWARE_GATE.md` owns identity export, archive/reference,
   narrow clean-repeat firmware commands and snapshots. Use that exact recipe.
   Packaging owner supplies complete final artifact inventory. Do not duplicate
   implementations or merge peers automatically. Keep native outputs out of Git.
3. Claim native VM lock only after checking actual owner/liveness and final inputs.
   If occupied, stop/publish pending; never overwrite or steal. Keep the lock for
   the agreed session, release only if it still names your owner in an EXIT trap.
   This tool itself NEVER reads/writes global locks or changes VM state.
4. NEW isolated VM source tree from exact archive + generated firmware manifest;
   matching existing dependency environment. Inside `agnos:19.9-build`, use device
   build configuration (`/AGNOS` present); verify `/VERSION`=19.9 and uname=aarch64.
   Existing DEBUG/ALLOW_DEBUG/signing policy unchanged. Full system build ONCE:

```bash
set -euo pipefail
cd /data/openpilot
export PATH=/data/openpilot/.venv/bin:/usr/bin:/usr/local/venv/bin:/bin
export PYTHONPATH=/data/openpilot:/data/openpilot/opendbc_repo
{ printf 'RC_SOURCE_SHA=%s\n' "$FINAL"; scons -j4; } > /evidence/full-build.log 2>&1
```

   Record real exit status, exact image/compiler/environment and source archive
   hash. Full SCons direct invocation cannot be skipped by an old `prebuilt` marker.
   Preserve full output log. Firmware clean-repeat snapshots happen within this
   SAME session per owner3 recipe, not duplicate full-system builds.
5. Import probes/tests are NOT device boot. Use isolated container HOME,
   PARAMS_ROOT, BOGPILOT_PARAMS_DIR, LOG_ROOT, cache paths; never real /data or /cache
   settings. For host compatibility use a distinct PC-configured import scratch
   tree/container, not a rebuild that overwrites shipping device artifacts. Do
   not fabricate device tree/GPU data. Import exact modules from native_plan with
   bounded subprocess timeouts, no main/manager_init/prepare/start calls. GPU or
   device-only failures require explicit environment blockers; do not count them
   as success. Actual launch scripts contain updater/reboot/Params actions and
   must NEVER be run as a compatibility smoke test.
6. Run final assembled startup (real native Params, eight scenarios), controls
   (real planner imports/active cancellation/lane-change tests), UI composition,
   recorder real H264/ffprobe and fault gates, static settings, firmware repeat,
   provenance and package verify. Prefix logs with final SHA, keep exit/counts.
   Regressions with intentional skips can be separately reported, never used as
   missing mandatory gate acceptance. Render/real replay remain explicit evidence
   rather than simulated boot. No hardware daemons or device access.
7. Return artifacts and hashed evidence to packaging's existing private stage;
   run this read-only orchestrator against frozen Git source + stage + receipts.
   No all-green acceptance until every source-bound required gate passes.

## Tests

`python3 -m unittest discover -s tools/bogpilot/tests -p test_rc_build_gate.py -v`

Synthetic fixtures use deliberately fake ELF headers/model bytes and synthetic
receipts solely to exercise verifier rejection paths; they are NEVER runtime or
candidate artifacts. Unit-test PASS is not native acceptance. No devices, network,
imports of product services or source mutations are used by preflight.

## Exact default-C3X optional backend classification
The full declaration/source inventory still includes every module. Only the exact
stock `WEBCAM = os.getenv("USE_WEBCAM") is not None` single assignment plus
`PythonProcess("webcamerad", "openpilot.system.camerad.webcam.camerad", ...,
enabled=WEBCAM)` permits optional classification. Unknown/reassigned guards remain
required. An imports receipt must explicitly attest
`profile:{"target":"comma3x","use_webcam":false}` to apply this scope; otherwise
all declared modules are required as before. Missing required imports still block.
Report any attempted optional import failure separately, never as a required failure
or disguised skip. This does not waive GPU/model/native camerad requirements.
