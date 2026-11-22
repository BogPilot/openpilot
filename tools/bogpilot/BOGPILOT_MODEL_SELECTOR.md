# BogPilot Driving Model selector (0.11.2, clean-room)

Written from scratch for BogPilot. No third-party selector, catalog, loader or model code is used, copied or
paraphrased. The only inputs are this tree's own modeld.py contract and the shipped stock model files.

## What ships
- Exactly one driving model: the stock **Default (stock)** (`driving_tinygrad.pkl` + the two `driving_warp_*` programs).
  The six stock model hashes are pinned in `openpilot/common/bogpilot_models/stock.py` and tested against the real files
  and `tools/bogpilot/c3x_stock_models_f7db927.json`.
- Downloader (`openpilot/common/bogpilot_models/installer.py`): fetches a catalog item only while the car is off,
  only from our own GitHub releases (org BogPilot; redirects only to GitHub release-asset hosts,
  `source.py`), checks every file's pinned sha256 and size, stages it in a hidden directory, runs the full
  validation below, and only then renames it into `/data/bogpilot/models/<id>/`. A failed update keeps the old
  install. Installing never changes the choice. The shipped catalog (`source.CATALOG`) is empty: no model besides
  the stock one is both license-clear and 0.11.2-compatible today. `source.EXCLUDED` lists the reviewed ones and why.
  Sideloading a directory under `/data/bogpilot/models/` (override: `BOGPILOT_MODELS_DIR`) still works.

## Registry format
`/data/bogpilot/models/<id>/manifest.json` plus the files it lists (plain file names in the same directory, regular files only):
```json
{"schema": 1, "id": "my-model", "name": "My Model", "version": "1.0", "openpilot": "0.11.2",
 "license": {"name": "MIT"},
 "description": "optional",
 "abi_digest": "optional sha256 of the tensor interface (printed by the page / abi.digest)",
 "onnx_sha256": "required sha256 of the ONNX the driving program was compiled from",
 "files": [
  {"role": "driving_model",          "name": "driving_tinygrad.pkl",              "sha256": "...", "size": 70491206},
  {"role": "driving_warp_1344x760",  "name": "driving_warp_1344x760_tinygrad.pkl", "sha256": "...", "size": 844693},
  {"role": "driving_warp_1928x1208", "name": "driving_warp_1928x1208_tinygrad.pkl","sha256": "...", "size": 844502},
  {"role": "driving_onnx",           "name": "driving_supercombo.onnx",          "sha256": "...", "size": 123}]}
```
- `driving_model` is required; each warp is optional (a missing warp means the stock warp is used). `driving_onnx`
  is optional; when present its sha256 must equal `onnx_sha256`.
- 0.11.2 has ONE fused driving program (vision and policy are compiled together), so there is no separate vision/policy
  file. Manifests naming `vision` or `policy` roles are rejected with that explanation. The "pair" that is checked is
  driving program + the warp that produces its `new_img` input.
- `license` is required and shown on the page. Sideloaded models are the installer's responsibility. Models we host
  must have a clear redistributable license (MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, CC0-1.0, or
  MIT (openpilot)); unclear licenses are excluded and not fetched.
- The directory name must equal `id` (a readable token, not a hash folder). Ids are lowercase `[a-z0-9._-]`, and
  `default`/`stock`/`none`/`auto` are reserved. The page shows the manifest `name`.

## Validation (hash + compatibility), `bogpilot_models/registry.validate_entry`
1. manifest schema; `openpilot` equals 0.11.2; required `onnx_sha256`; sizes; every file is a regular file (no
   symlinks) matching its sha256; a listed `driving_onnx` file must match `onnx_sha256`;
2. static ABI read of the pickle WITHOUT importing tinygrad or running anything (every global becomes an inert stub);
3. the pickle may only reference classes the stock model references (allow-list from stock.py);
4. interface equals what modeld.ModelState consumes: `new_img/desire/traffic_convention/action_t` identical to stock,
   any extra state queue needs a matching `next_<name>` output, `outputs` identical, all `output_slices` names and
   lengths identical to stock, metadata shapes consistent with the tensor specs, warp input specs identical to stock.
Anything else is "Not usable: <reason>" on the page and can never be selected.

## Selection and loading
- Page row: an inline `[-] model [+]` row (Alert Volume style) steps through the usable models, Default first, and
  asks before saving. It is shown once a second model is installed. Hosted models not installed yet get a DOWNLOAD row.
- Page: Settings > BogPilot > Driving Controls > Driving Model. Default is always first. With only Default installed the
  page says so and shows nothing else (no buttons). Selection is refused unless the car is offroad (`ui_state.is_offroad`
  must be exactly True). The page and `selection.select` both block onroad param writes. The choice is stored (Params if
  the key is compiled, else the BogPilot file store) as `BogPilotDrivingModel` = JSON with the id and the sha256 of the
  manifest and the model, so later file swaps are caught. A switch applies at the next drive start, never mid-drive.
- modeld starts through `openpilot/common/bogpilot_models/launcher.py`. It resolves the choice ONCE per modeld start
  (modeld only runs onroad), so nothing can change mid-drive. Default selected, or any error inside the selector, means
  the untouched stock `modeld.main()` runs: no patching, no hashing, no writes.
- An alternate is used only if it validates again at start and the pins still match; then it loads and runs one zero-frame
  warm-up inference. Failure at validation, load, warm-up or first inference constructs the exact stock `ModelState`
  in the same process. Failure while driving (exception or non-finite output) records the fallback and lets modeld restart;
  the recorded fallback makes the next start stock. A failed model stays blocked until the user selects it again.
- One model per drive: the choice is saved with its time (`t`). The first modeld start of a drive latches it in
  `BogPilotDrivingModelState` (`latch`); the drive is the kernel boot id plus the time the manager wrote `IsOffroad`
  at the onroad transition. A modeld restart in the same drive reuses the latch, and a choice saved after the drive
  started waits for the next drive (stock meanwhile if nothing was latched, no alert). An unreadable latch means stock
  for that start. With nothing selected nothing is latched or written.
- Fallback state (`BogPilotDrivingModelState`) drives an **offroad alert** ("Driving model X was not used: <reason>. The Default
  (stock) model is driving instead...") on the home screen, shown until the user selects a model (or Default) again.
- Chestnut GPU setups always keep the stock models (alert says why); the DM model is never touched.

## Not covered / honest limits
- No alternate exists today that is compatible with this modeld; the machinery is proven with synthetic ABI-identical test
  models only. Real on-device inference of an alternate has never been run.
- Unpickling a model executes whatever tinygrad reconstruction that pickle encodes. The class allow-list and hash pins
  limit this, but installing a model is still a trust decision by the person who installs it.
- Mici (small screen) UI is not wired; the comma 3X uses the tici UI.

## Large-model hosts (ONNX id)
- `onnx_sha256` in a manifest is required for installed models and never read by modeld itself. The page shows its
  first 12 characters. A mismatch or a missing hash falls back to Default (stock).
- `bogpilot_models/big_model_param.py` turns the choice into `{"sha256": <onnx_sha256>, "displayName": <name>}`, or no
  value for Default, which is the shape a large-model host such as Jetlink (MIT) reads from the `JetlinkBigModel`
  param. It also maps a value written back (sha256, optional ref) to the one installed model with that ONNX hash. It
  is pure: it reads and writes no param and imports no host package. This branch does not write `JetlinkBigModel`
  yet; that hook is for the later merge with the Jetlink branch.
