# C3X full-tree candidate packaging (offline only)

`rc_package.py` has **no installation, flash, upload or network action**. Its
`verify` command is the dry-run preinstall inventory check. `bundle` repeats that
verification before making an uncompressed local tar. Missing evidence is BLOCKED,
not skipped/pass. All output paths must be outside the source tree and outside
/data and /cache. Existing output files are never overwritten.

## Verified commands and test scope

From this checkout, tested on Mac Python 3.12 (synthetic sandbox git trees and
ELF headers, not native binaries):

```
python3.12 -m unittest discover -s tools/bogpilot/tests -p test_rc_package.py -v
python3.12 tools/bogpilot/rc_package.py --help
```

CLI argument shape (replace placeholders; not a claim that a final candidate
exists or has passed):

```
python3 tools/bogpilot/rc_package.py verify --root FINAL_TREE --candidate FULL_SHA --artifact-manifest ARTIFACTS_JSON --report OUTSIDE_TREE_REPORT
```

The same arguments with `bundle` and `--output OUTSIDE_TREE_TAR` generate a local
archive **only after all static checks pass**. Do not run against the current
unfinished assembly just to produce a large archive. There is no overlay mode:
metadata says full-tree-test-build, installable=false, road_validated=false,
hardware_validated=false, native_imports_executed=false and
 dynamic_linkage_validated=false. A partial overlay or source archive is never
called installable, even if its base revision is named.

## Artifact input contract

JSON: schema=1, candidate_sha=full lowercase 40hex, agnos_version="19.9",
architecture="aarch64", artifacts=list of objects with path, sha256, size, mode,
format. Paths are normalized relative POSIX paths; sha256 is lowercase 64hex;
size is a positive integer; mode is "0644" or "0755". format is "elf-aarch64",
"elf-arm" (Cortex-M firmware ELF only) or "data" (signed firmware/raw data).
AArch64 ELF class/endianness/machine183 and ARM class/endianness/machine40 are
checked without executing them. Every shipped ELF/shared library/firmware output
requires coverage. Runtime ELF must be AArch64; NativeProcess executables need
0755. Manifest coverage is not proof of compilation, signing or repeated builds:
the separate firmware and native acceptance gates remain mandatory.

## Full-source/runtime prerequisites

Exact checkout HEAD must match the candidate; source changes fail, including a
source modification disguised as a data artifact. Only declared native output
paths may differ. Gitlinks are recursively expanded only from initialized exact
clean checkouts. This repository currently vendors dependencies as tracked trees,
not independent submodules; no pretend dependency HEADs are fabricated. Required
vendor import packages, launcher/manager/model/UI sources, six complete model
assets, PythonProcess/DaemonProcess modules and NativeProcess executables are
checked. LFS pointers, missing/truncated models, unsafe modes, external/absolute
or dangling symlinks fail. Internal relative symlinks retain their targets.

A clean matching `.panda-source.json` with full source inventory is mandatory;
its hash is captured. Generate it using the existing reviewed panda identity
workflow only after the final clean source exists. Signing/DEBUG policy remains
unchanged. Native compilation/imports, dynamic dependencies and hardware boot
are not exercised by this tool. AGNOS19.9/comma3X prerequisites must be established
by the assembled build gate, not inferred from a static report.

## Privacy, integrity and rollback

Only committed source and explicitly manifested artifacts plus panda provenance
enter the archive; untracked files/private configs/rlogs are never swept in.
Suspicious shipping paths fail closed. The known tracked public eSIM CA bundle is
allowed only as a certificate, never a private key; schema source rlog.capnp and
qlog_size.py are not mistaken for recorded logs. This bounded path guard is not a
full secret-content audit: use the separate provenance/privacy gate before
shipping. Reports contain paths/checksums, never file contents or host identities.

Entries and checksum inventory are deterministic. Tar ordering, uid/gid, names,
mtime and modes are normalized. Files are rehashed before/after archive reading;
source writers must remain quiescent. Final tar SHA is returned in the external
report. Reports/archives are exclusive local files, no automatic pruning.

Rollback is a prerequisite, not an implemented operation: preserve a known-good
complete source+matching artifact inventory separately and verify it using this
same offline tool. Preserve private settings through the reviewed backup lifecycle,
not by adding /data to this bundle. No device rollback/install commands are
provided because none were executed/validated here. Launchers can mutate device
state and invoke AGNOS updating: **never execute them as a packaging check**.
Separate user approval and an audited deployment procedure are required later.

## Mandatory privacy evidence before bundling

`verify` alone is a static package check, not privacy clearance. `bundle` also
requires `--provenance-report PASSING_TRACK9_JSON --shipping-manifest EXACT_JSON`.
`bind_provenance` checks final candidate SHA/clean state, no findings, complete
scanned-file counts and exact byte-for-byte shipping hash inventory. It records
both evidence hashes. A worker exploratory audit or source-only report cannot
clear the package. Evidence inputs are unsigned local assertions, not signatures.

Track9 exact review API is now supported: only source-catalogue-bound, individually
reviewed internal links with matching payload/blob/target/representation attestations
may ship as symlinks. No blanket link waiver or private credential waiver exists.
Explicit exclusions change scope; never label excluded-source or a runtime overlay
as complete buildable source.
The generated RC_PACKAGE.json records the accepted inventory/evidence hashes; it
is reserved tool-generated metadata, not an extra unaudited source payload.

## Exact reviewed-link/excluded-source adapter (track9 142b2451)

API `verify(root, candidate, artifact_manifest, shipping_manifest=None)` reads
explicit source_exclusions from the shipping manifest. Each exclusion must match
the original source catalogue mode/blob and reason=private_or_build_host_only;
required runtime/source paths and every tracked notice basename are protected.
Only a passing track9 report can authorize exclusion policy (private/build-host
names or its exact known nonshipping fixture blob). Static verify alone cannot
approve that policy. Excluded source contents are not opened for packaging or
rehashing; native/firmware gates remain responsible for their source manifest.
The original Git catalogue, hash and exclusions remain in RC_PACKAGE.json.
With exclusions, kind=cataloged-excluded-source-test-build and
source_scope=cataloged_source_with_explicit_exclusions; this is NOT full source,
NOT an installable overlay, and does not contain build signing material.

`bind_provenance(report, gate_report, shipping_manifest, review_record=None)`
checks the exact final source SHA, canonical inventory/review/catalogue hashes,
source scope, every exclusion attestation and original source mode/blob.
For each symlink it additionally matches record kind=internal_link, original
link-payload hash, canonical tracked shipped regular target/hash, representation
and the corresponding hashed-path gate attestation. Missing, duplicate, extra,
changed or stale link attestations fail. This adapter supports only the gate's
`representation=symlink`: it preserves the original symlink bytes/mode and target
files, rather than modifying source or inventing regular materialization. Gate
records prove every committed intermediate link/target is shipped and nonprivate;
static verify independently rejects escaping/private/unshipped live targets.
Public-reference/name records are bound unchanged to the passing exact gate
review; no path-wide or credential-content override is added here.

### Integrator recipe (offline, final inputs required)

1. Freeze the final clean source SHA and complete matching native/artifact manifest.
   Generate exact original catalogue and shipping manifest with approved explicit
   exclusions; do not reuse the worker proof for final SHA.
2. Static inventory dry run may use `verify --shipping-manifest SHIPPING.json`
   without gate inputs; it reports provenance_gate_pass=false. API verify likewise
   produces deterministic shipping entries for the inventory-generation workflow.
3. Run the assembled track9 gate on the frozen source/stage with that exact manifest
   and exact review record; retain all notices (the reviewed worker had nine).
4. Final static verification with privacy binding:

```
python3 tools/bogpilot/rc_package.py verify --root FINAL_TREE --candidate FULL_SHA \
  --artifact-manifest ARTIFACTS.json --shipping-manifest SHIPPING.json \
  --provenance-report PASSING_GATE.json --review-record REVIEW.json \
  --report NEW_EXTERNAL_REPORT.json
```

5. Only after the integrator's native/build gates pass, use `bundle` with the same
   arguments and a NEW external tar path. This tool does not acquire VM locks,
   build native artifacts, install, or certify hardware behavior.

Adapter validation includes actual recorded worker consumable-schema binding
(6 links, 3 exclusions, 9 notices) and an independent tiny SYNTHETIC git tree passed
through the actual track9 audit, adapter and tar round-trip. Neither constitutes
final candidate attestation or a real native build. Final SHA/inventory/native run
remain exclusively the integrator's responsibility.
