# Phase 3 lane 2: driving-model runtime (install / select / activate / rollback)

Base c6582fc3 (c3x-rc-w4-candidate committed HEAD), isolated branch local/phase3-model-runtime-lane2.
New files only; no pinned modeld file, model payload, stock manifest, Params key, default or navigation edit.

## What it does
- `openpilot/common/phase3_model_runtime.py` (stdlib): immutable bundle store under /data/bogpilot/model_runtime
  (never /data/media, recordings or accounts); atomic fsync+rename state under flock; offroad-only select/delete with
  revision recheck and post-write onroad-race undo; stock is never copied/deleted and is the rollback target.
- Compatibility = static ABI read with a restricted unpickler (every global stubbed, nothing imported or executed),
  required EXACTLY equal to the ABI read the same way from the verified stock driving_tinygrad.pkl: input_specs,
  output_specs, metadata shapes, output_slices, referenced classes, run type. No shape is hardcoded.
- Runtime provenance gate: alternates are only selectable/loadable while lane1 `verify_runtime()` passes; missing
  lane1 module fails closed. Stock is never gated.
- `phase3_modeld_launcher.py`: wraps unmodified modeld.main(); resolves model once per modeld start (only_onroad, so a
  running modeld never switches); alternate load failure -> stock in-process + recorded rollback; run exception or
  non-finite alternate output -> rollback recorded, modeld crashes like stock and restarts on stock; at most 2
  unconfirmed starts then automatic stock rollback; ack.json written only after the first real (non-warmup) inference.
  Chestnut big model and its small fallback always run stock.
- `phase3_model_backend.py`: lane3 (da755c9) ModelBackend adapter. Advertises only select/delete when a real
  compatible alternate is installed; active_id only from runtime ack; download/automatic/randomizer/blacklist/ratings
  not advertised (no compatible source / consumer).

## Integration (primary only)
1. Cherry-pick this commit (and lane1 151e1f25, lane3 da755c9).
2. Apply PROPOSED process_config patch: modeld -> openpilot.common.phase3_modeld_launcher (process title becomes
   the launcher module name).
3. Wire lane3 widget with RuntimeModelBackend(Runtime()). Hook lane1 download_bundle output into Runtime.install()
   once a real compatible catalog entry exists.

## Blockers / limits
- No authentic 0.11.2-QCOM alternate with identical ABI exists; 0.9.7 thneed and split vision/policy pkls are rejected
  by the real-artifact harness. The selector is stock-only and truthful; NOT a functional alternate selector.
- Lane1 gate currently fails on c6582fc3: pyproject.toml + uv.lock differ from the f7db927 pin (telemetry removal +
  uv lock regeneration). Not weakened here; see lane2 lock evidence.
- Not validated: real modeld import/inference with the launcher (no built cereal/msgq/tinygrad env without a full build),
  device GPU load, AGNOS filesystem durability, bench/road.
