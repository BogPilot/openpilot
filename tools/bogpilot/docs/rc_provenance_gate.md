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
No recursive account scan, no following symlinks, no reading git credentials/remotes.
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
block. VIN/route-shaped content blocks unless `reviewed_public_fixtures` maps the
exact path to its exact shipped digest after a human/source review establishes it
is a public synthetic/reference fixture. That review cannot waive keys/private paths.
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
