# Explicit candidate-local precompiled stock QCOM models
Opt in ONLY with `python3 -m SCons --verified-stock-models -j4` on comma_arm64.
This is our disclosed local build-system option, NOT an upstream recipe/cache.
Default flag=false leaves the original builder byte-identical outside marked guard.
All other default SCons targets remain registered and must actually build.
Verifier pins all1662 compiler/runtime/transform/ONNX/lock inputs and six model
payloads to public stock f7db927c728bab57bb1263e05465766a8f28fc9d Git blob/SHA256.
Manifest SHA256 is hardcoded in the candidate verifier; no arbitrary replacement
manifest, cache metadata, timestamps or prebuilt sentinel. Original default-builder
body is SHA256 checked. Models must contain QCOM backend opcodes (static inspection,
never unpickled/executed). Missing/drift/extra compiler inputs, wrong assets/backend,
wrong architecture or dirty/missing candidate .panda-source identity fail closed.
Model origin is PRECOMPILED-STOCK, NOT newly generated. No GPU/inference/boot claim.
Clean nonmodel outputs with `python3 -m SCons --verified-stock-models -c`, then full
normal default build with same flag. Verify all six hashes before and after build.
Source freeze/firmware export/real native gates/artifact inventory/privacy/package
are still mandatory; no installation/road validation asserted by this option.
