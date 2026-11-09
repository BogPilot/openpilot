# Phase 3 lane 1: model catalog / verified stock staging

## Result and hard blocker

Only **Stock openpilot 0.11.2 (QCOM)** is a verified compatible entry. This is not
an implemented multi-model selector; callers must display the unavailable reason
rather than list incompatible old models as functional options.

Authentic own BogPilot reference: `04d560f3` (0.9.7 bogpilot-tesla), specifically
`frogpilot/assets/model_manager.py`, `frogpilot/common/frogpilot_variables.py`, and
`frogpilot/ui/qt/offroad/model_settings.cc`. The old default is dark-souls/v9.
Old tinygrad files are separate driving_policy/vision plus metadata; older models
are thneed. No upstream legacy implementation was imported or copied.

Current source: `f7db927c728bab57bb1263e05465766a8f28fc9d` = openpilot v0.11.2;
lane base `c6582fc3efc1038b4e0e6bca8a6841b657e8ccf6`.
Current `modeld.py` loads one monolithic `driving_tinygrad.pkl`, including
`input_specs["new_img"]`, next-state pairs, new output metadata and captured JIT.
Current helpers use out-of-band tinygrad loading; AGNOS chooses QCOM. Matching
names or old version labels cannot demonstrate compatibility with this ABI.

Public audit on November 7, 2026 (America/New_York):

- https://raw.githubusercontent.com/FrogAi/FrogPilot-Resources/Versions/model_names_v17.json
  SHA256 `717bd23a3b74042b171c071d93605af583597ee63ab10474f1d19b8f689a78f8`;
  36 catalog models, generations v1-v9, no ABI or SHA256 bundle declarations.
- https://api.github.com/repos/FrogAi/FrogPilot-Resources/contents/compiled?ref=Models
  lists split policy/vision/metadata .pkl files, not 0.11.2 monolithic bundles.
- https://api.github.com/repos/FrogAi/FrogPilot-Resources/contents?ref=Models
  lists thneed, compiled, uncompiled and explicitly `openpilot-0_10_3`; the latter
  contains model .tar files plus models.json, not a verified 0.11.2 compilation.
- No alternate complete 0.11.2 QCOM bundle with pinned integrity and matching
  runtime/compiler provenance was found in these actual manifest/binary listings.
  This does not claim no such model could ever exist elsewhere.

## Inherited dependency-lock blocker (do not bypass)

The original immutable stock manifest still pins all 1662 compiler/runtime inputs.
At the lane base, `pyproject.toml` and `uv.lock` differ because telemetry dependencies
were removed. `verify_runtime()` therefore correctly rejects this source tree.
Lane 1 does **not** weaken/update the stock manifest or the six stock model pins.
Primary integration must deliberately revalidate dependency provenance (or obtain
an appropriate reviewed manifest) before allowing activation. UI may read catalog
metadata, but must not translate it into an unconditional activation success.

## Contract (no central wiring changes)

`openpilot.common.phase3_model_catalog` is stdlib-only. It matches the existing stock-gate
inventory without importing build tools on-device. It intentionally lives OUTSIDE
modeld, whose Python inventory is pinned by the original model gate.

- `load_catalog(root=None) -> Catalog(entries, blockers)`; metadata only, no I/O
  other than pinned local manifest. Entries are immutable dataclasses.
- `ModelEntry`: id, name, version, architecture, backend, format, stock_commit,
  assets; `ModelAsset`: name, sha256, size, url.
- `verify_runtime(root=None, architecture="comma_arm64", backend="QCOM")` checks
  exact input inventory/hashes and original model builder; no model execution.
- `verify_bundle(entry, directory, *, root=None)` validates trusted catalog entry,
  all six sizes, hashes and format. Never deserializes pickle code.
- `download_bundle(entry, cache_root, cancel_event=None, *, root=None,
  architecture="comma_arm64", backend="QCOM", timeout=180, progress=None) -> Path`
  verifies runtime, downloads only pinned public full-commit HTTPS stock URLs,
  enforces content size and integrity, fsyncs, then publishes a staged directory.
  Does NOT write Params, activate models, restart processes or touch source files.
  `progress(done_bytes,total_bytes)` is optional. Event exposes `is_set()`.
- Errors: `CatalogError`, `DownloadCancelled` (subclass). No retries. Per socket
  timeout <=3 seconds and deadline checks before/after single-read chunks. DNS and
  filesystem operations are subject to OS scheduling; no real-time guarantee.
- Cache must be private application storage, outside and non-overlapping with
  source checkout, with no symlink path components. Hash verification is repeated
  for cache reuse. Failure/cancel removes only that attempt's unpublished temp dir.
- Lane 2 owns offroad guards, restart, rollback and final verification immediately
  before activation. Lane 3 owns an honest disabled/unavailable selector state.

## Native evidence and limits

Tests ran on M4P48 macOS arm64, Python 3.12; no box builds/tests/rendering.
Full public download E2E: **91,403,700 bytes / all six exact SHA256 pins**, 8.142s.
E2E used a separate hardlink fixture of the original 1662 pinned inputs, restoring
only pyproject.toml/uv.lock original bytes inside that fixture, NOT in primary or
lane checkout. This demonstrates downloader behavior, NOT current candidate ABI
approval. Model binaries never executed, no vehicle/bench/road tests performed.

Evidence on M4P48:
`~/BogPilotTeam/work/research/phase3-model-catalog/native-public-download.json`
`~/BogPilotTeam/work/research/phase3-model-catalog/public-download-cache/`

No primary/bench edits, clone, push, telemetry or cloud-account access. The six
original stock asset files and original manifest remain untouched.

## Lane 3 adapter alignment (da755c9)

`inspect_entry(entry, directory=None, *, root=None, architecture="comma_arm64",
backend="QCOM") -> ModelInspection` supplies fresh, immutable catalog-side facts:
id, name, available, downloaded, compatible, reason, protected, revision.
The field names match Lane3 `Model`; `downloaded` requires all six actual hashes,
not file presence. `compatible=False` when ABI/architecture/dependency provenance
fails even if `downloaded=True`. The catalog revision changes with these facts.
Run hashing in a backend worker, never on the render loop. For an atomic adapter
snapshot, recheck files/state before accepting a mutation; inspection alone is not
an authorization lock and does not solve offroad/inference races.

Lane2 must combine this revision with runtime acknowledgement, queue, capabilities
and action state. NEVER derive `Snapshot.active_id` from entry.id or downloaded.
Absent actual inference acknowledgement, active_id stays None. Pending likewise
comes only from the runtime activation queue. No automatic/randomizer/blacklist/
ratings/delete capabilities are advertised by this catalog. Ratings and automatic
model discovery have no service/account implementation. The downloader only stages
known pinned stock; it does not justify a select capability for an alternate.

On the lane base, the truthful Model has downloaded=True, compatible=False,
protected=True, and reason naming the dependency-lock ABI drift. Existing stock
file verification is NOT running-inference acknowledgement or permission to select.

Package the pinned local manifest with this module if introducing it on-device;
missing manifest must remain a fail-closed error, not an empty or guessed catalog.

Final native focused run: 30 catalog tests + 13 original stock gate tests =
**43 passed**, pytest 0.76s. Public binary download evidence remains 8.142s.
