# Source/provenance/privacy release gate

Run on the clean **final assembled source commit**, not a worker base. No installation,
network, history rewriting, authorship editing, license editing or native builds occur.
This is separate from firmware signatures/repeatability and archive/runtime completeness.

```
python3 tools/bogpilot/rc_provenance_gate.py --repo FINAL_SOURCE \
  --shipping-root EXPLICIT_STAGE --manifest EXTERNAL_MANIFEST.json \
  --output NEW_EXTERNAL_REPORT.json
python3 -m unittest discover -s tools/bogpilot/tests -p test_rc_provenance_gate.py -v
```

Shipping root is optional (defaults to source). Only explicitly listed shipping files
are opened. Output must be a new file outside source AND staging; otherwise stdout.
No recursive account scan, no following unreviewed symlinks, no reading git credentials/remotes.
`git status` inventories only this checkout; it does not read ignored account files.
Do not put a manifest/report in source and accidentally make the candidate dirty.

## Manifest v1

```json
{
  "schema_version": 1,
  "source_commit": "FULL_FINAL_40_HEX_COMMIT",
  "submodules": {},
  "files": {"LICENSE": "SHA256_OF_SHIPPED_BYTES"},
  "required_build_assets": ["LICENSE"],
  "license_notices": ["LICENSE"],
  "reviewed_public_fixtures": {}
}
```

This abbreviated shape is **not** a passing full candidate inventory. `files` must
contain every shipping source/stage file; packaging owns verifying this equality
against the actual archive. The gate cannot detect files omitted from that inventory.
`required_build_assets` must additionally include candidate-specific build inputs.
The gate always requires root LICENSE, launch_chffrplus.sh, launch_openpilot.sh,
SConstruct, pyproject.toml, uv.lock and the six current model/warp pickle assets
under openpilot/selfdrive/modeld/models. Empty required assets and unresolved LFS
pointers fail. This does NOT verify pickle model identity, compiled ELF behavior,
firmware signing, archive extraction, hardware suitability or source origin legality.
Other tracks must supply those checks. Explicit hashes identify bytes, not their trust.

`submodules` is the exact gitlink-path -> commit map (empty for this vendored tree).
Each gitlink must be initialized, at its pinned commit, clean, and without nested
unaudited gitlinks. Nested gitlinks block pending a separate audit. Top-level
vendored *_repo and panda tree object IDs are reported as source provenance; they
are NOT invented upstream submodule commit IDs.

All tracked LICENSE*, NOTICE*, COPYING*, AUTHORS*, COPYRIGHT* basename files must
be declared in `license_notices` and shipped unchanged byte-for-byte from the pinned
source, including initialized submodule notices. This preserves required notices;
it is not a legal determination or proof that an earlier source commit preserved
every inline notice. Source/commit hashes identify the exact snapshot for review.
No authorship/history/license/notice rewrite is performed. Upstream legacy port is
reference naming only; this utility contains no legacy implementation code.

## Fail-closed checks and privacy

Exit 0 + `status: pass` means **only this scoped audit passed**. Exit 2 +
`status: blocked` includes missing manifests/inputs, dirty tracked/untracked source,
wrong commit/pins, stale source notices, wrong bytes, unreadable/nonregular files,
symlinks, path traversal, budget exceeded, prohibited names and content findings.
Source HEAD and status are checked again after scan. Serialize/freeze staging while
this gate and packaging run; this is not a filesystem transaction or race-proof
replacement for packaging's final byte inventory check.

Shipping credential/log/private-config names (including .ssh/.env/params/rlog/qlog,
private key extensions, config.json, compile_commands.json) are rejected **without
opening those files**. The other files receive streaming digest/content scans with
512 MiB/file and 4 GiB/run caps. Credential markers and token assignments always
block. VIN/route-shaped content blocks unless an explicit `--review-record` proves the whole file byte-identical to the
pinned public release source. Hash-only `reviewed_public_fixtures` is now rejected.
These are public references, not necessarily synthetic routes. No review waives private keys.
No automatic exception, rename, credential decoding or source deletion is performed.
Conservative public-key/test-fixture false positives require a separate packaging/
policy decision; do not silently bypass them for a candidate.

Content detection is heuristic, not a universal privacy guarantee. Compressed or
encoded content is not decompressed/decoded. Paths and identifiers may themselves
be private: diagnostics emit only generic codes and SHA256 path IDs, never raw
filenames, contents, token values, VINs/routes, absolute checkout paths or stderr.
Orchestrator can map path IDs privately using its input manifest, not public logs.
No candidate may be called road validated from this gate's result.

JSON reports schema_version, status, scope, checks, source commit/tree/clean,
submodule pins, vendored tree pins, notice blob hashes, shipping scan counts and
canonical manifest SHA256. No skipped prerequisite is represented as pass.

## Verification status

Unit tests use disposable small synthetic git repositories, fake assets/identifiers
and mocked scan budgets. They are not production/model/firmware/device tests.
Final candidate source/stage manifest must be generated after all source commits
and native artifacts are frozen, then this gate rerun. No final candidate attestation
is embedded in this utility's own source commit.

## Exact public-source/internal-link review record

`--review-record` consumes an explicit external JSON object; absent/invalid review
never defaults to acceptance. Binding fields:

- schema_version: 1
- source_commit: exact final HEAD
- manifest_sha256: SHA256 canonical shipping manifest
- source_catalog_sha256: SHA256 canonical `{path:{mode:gitmode,blob:gitblob}}`
  from exact source `git ls-tree -rz HEAD` (gitlinks retain their pinned commits)
- records: map relative path to proof record

Canonical means JSON sort_keys=True, separators=(",",":"). Each record contains
kind, source_mode, source_blob, shipping_sha256 matching source and inventory.
Public kind `public_reference` additionally requires public_commit equal to the
immutable public upstream release f7db927c728bab57bb1263e05465766a8f28fc9d,
identical tracked source mode/blob and byte digest. Public GitHub tree metadata was
used to confirm that release and subtree hashes, not labels/source comments alone.
`public_source_name` is limited to that release's rlog.capnp schema and GSMA CI
certificate bundle; certificate marker required, credential patterns still block.
No marker or key contents are exempted by being present in an upstream tree.

Link kind `internal_link` additionally contains link_sha256 (original git symlink
payload bytes), target (canonical final tracked regular-file path), target_sha256,
and representation (`symlink` or `regular`). Every committed intermediate link and
final target must remain internal/nonprivate and appear in the shipping inventory.
Original source payload/mode/blob and exact source target bytes are verified.
Symlink staging must preserve the exact payload; regular staging must materialize
exact target bytes. Neither choice rewrites source mode 120000 into 100644.
Cycle/absolute/escape/private/unshipped/changed targets and review/SHA tampering fail.

Output adds review sha256/source_catalog_sha256/record_count and
shipping.reviewed_links entries containing path_id, source_mode, source_blob,
link_sha256, target_path_id, target_sha256, representation. All paths remain hashed.
`scanned_files` includes audited symlink payloads AND separately scanned targets.
Packaging must match each attestation to its exact inventory, not lift link rejection
for a whole directory or trust an older candidate's report.

## Explicit nonshipping source catalogue entries

Every tracked source blob must appear in files or in source_exclusions. Exclusion
record `{source_mode,source_blob,reason:"private_or_build_host_only"}` must exactly
match the original catalogue. Only prohibited names or the exact known upstream
DEBUG private-key fixture blob can be excluded through this interface. Notices and
mandatory inputs can never be excluded. No key material is read to make exclusions.
This retains original git modes/blob identities without shipping private/build-host
material or scrubbing the source tree. Public-source debug signing fixture identity
was established by public tree/blob provenance and its SConscript debug-cert use,
not by reading key values; the gate still does NOT permit shipping that private key.

Output explicitly declares `source_scope: cataloged_source_with_explicit_exclusions`
and preserves each exclusion's path_id/mode/blob/reason. This is NOT a complete-source
archive or an overlay pretending to be full source. Packaging must retain catalogue
and exclusions in metadata and verify runtime completeness separately. Final source
commit/inventory freeze and rerun are mandatory; worker proof artifacts are not final
clearance. Existing DEBUG/signing policy and all license/author notices stay unchanged.
