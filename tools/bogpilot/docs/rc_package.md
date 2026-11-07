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

Track9 currently refuses all symlinks, including legitimate internal source links.
Therefore this packager deliberately blocks bundling those until an explicitly
reviewed regular-file staging flow or audited gate adapter is provided. No blanket
symlink waiver is applied. Similarly, conservative identity/credential findings
remain blocking pending specific private review/exclusion; credentials cannot be
waived. Do not mislabel a runtime-only sanitized stage as full buildable source.
The generated RC_PACKAGE.json records the accepted inventory/evidence hashes; it
is reserved tool-generated metadata, not an extra unaudited source payload.
