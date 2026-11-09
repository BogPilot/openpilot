# Lane 3 — Driving Models UI / explicit adapter contract

## Scope and evidence
Machine-specific native exception: repository/build dependencies live on M4P48. Used existing repository worktree only, no clone, fetch, push, bench access, shared-navigation edit, defaults edit or modeld edit.
Base: c6582fc3efc1038b4e0e6bca8a6841b657e8ccf6 committed HEAD of c3x-rc-w4-candidate. Isolated branch/worktree `phase3-model-ui-lane3`.
Approved historical reference only: `04d560f3:frogpilot/ui/qt/offroad/model_settings.cc`. No prohibited legacy reference read.

## Files and integration (primary e7d8fe75 only)
- `openpilot/selfdrive/ui/bogpilot/phase3_model_selector.py`: actual raylib factory, data protocol, guarded controller.
- `openpilot/selfdrive/ui/tests/test_phase3_model_selector.py`: synthetic-contract fixtures, not real models or hashes.
- Build a Lane1/Lane2 adapter implementing ModelBackend; inject it into ModelSelector(adapter, live_offroad_predicate), then create_model_selector_layout(controller).
- Add the resulting widget under BogPilot > Driving Controls > Driving Models, or parent-owned navigation matching verified old parent hierarchy. This lane verifies the old Driving Models contents, not the parent navigation inventory. NO shared navigation touched.
- Wiring deliberately not applied: require an actual adapter rather than a stock-only default or dummy Params implementation. Parent should implement adapter in a separate unique module and wire only after backend/inference validation.

## Snapshot contract
Dataclasses are immutable. All fields are required except explicitly defaulted ones. No catalog IDs, hashes or files are guessed here.
`snapshot()` is cached/nonblocking, yielding Snapshot(revision, models, capabilities, active_id, pending_id, automatic, randomizer, busy, progress, error, limitation).
Every Model includes stable opaque backend ID, display name, currently available, fully verified downloaded, tri-state compatibility (None unknown), reason, protected, blacklisted, rating summary.
`active_id` MUST come from running inference acknowledgement, never requested Params, file presence or UI acceptance. Leave None if unknown. `pending_id` is queued activation only. Both IDs must exist in snapshot catalog. Revision must change for compatibility/catalog/runtime/action changes. Unknown or duplicate identities fail closed.
`limitation` must state when only stock is supported; adapter MUST NOT advertise alternate capability or accept select for a model that runtime cannot load. A current catalog with only stock is truthful but does NOT fulfill the requested functional alternate selector.
`request(action, model_id_or_None, expected_revision) -> Result(accepted, message)` is nonblocking. Backend atomically rechecks revision, actual offroad state, supported operation, complete artifacts, compatibility and identities. Offroad UI checks are defense-in-depth, not backend authorization. Acceptance is never activation. Report download/inference errors in snapshot.error and progress in snapshot.progress.
UI always refreshes before action/confirmation dispatch and refuses stale revisions. UI does not write any legacy Model* params.

## Exact old submenu inventory and action contract
All seven old rows are retained in old order. Unsupported rows explain that no setting is written; operations stay disabled when capability absent.
1. Automatically Download New Models: automatic_on / automatic_off (no target). Actual background downloader required before advertising.
2. Delete Driving Models: delete(model ID), delete_all(None). Backend must preserve stock/protected, active, pending artifacts; UI protects individual targets. Confirmation required.
3. Download Driving Models: download(model ID), download_all(None), cancel(None). Backend bulk operation must use only available compatible models and preserve verification/cancel semantics. No implicit incompatible fallback. UI blocks unknown/incompatible single downloads.
4. Model Randomizer: randomizer_on / randomizer_off. Backend must implement real per-drive selection; UI additionally requires two verified compatible nonblacklisted models to enable.
5. Manage Model Blacklist: blacklist_add(ID), blacklist_remove(ID), blacklist_clear(None). Backend must preserve a usable candidate; ADD/REMOVE/REMOVE ALL equivalents.
6. Manage Model Ratings: read-only model rating summaries plus ratings_reset(None). Old VIEW is the ratings page; RESET is confirmed. No ratings fabricated if backend lacks them.
7. Select Driving Model: select(ID). Only verified compatible downloaded models selectable. Active/pending targets disabled. Runtime acknowledgement required before active label changes.
All mutation operations, including cancellation, are offroad-only. Detail screens include availability, verified download state, compatibility/reason, active and pending labels. Unknown compatibility is NOT treated as compatible.

## Validation and remaining gates
Focused tests on M4P48 native Python 3.12, lane-local `.lane3-venv`, installed comma-deps-raylib and dependencies. Existing candidate opendbc_repo/msgq_repo used read-only on PYTHONPATH. No parallel full build. Native widget construction tested with font/measurement stubs (no display/window). No native visual render, inference, real catalog download, actual activation or bench validation claimed.
Test command:
PYTHONPATH="$PWD:$HOME/BogPilotTeam/work/wt/c3x-rc-w4-candidate/opendbc_repo:$HOME/BogPilotTeam/work/wt/c3x-rc-w4-candidate/msgq_repo" .lane3-venv/bin/python -m pytest -q openpilot/selfdrive/ui/tests/test_phase3_model_selector.py

Parent gates: adapt actual Lane1 catalog + Lane2 runtime; test stock and at least one real supported alternate end-to-end; test offroad-to-onroad race inside backend, interrupted downloads, incompatible artifacts, pending-to-active acknowledgement and rollback/error; native render and touch navigation verification. Until then this is UI/contract delivery, NOT a completed functional model port or deployed feature.
