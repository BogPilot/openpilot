# Stream 5 coordination (shipping defaults + visibility)

## Owned surfaces
- `bogpilot_shipping_defaults.py` — locked value/level policy
- defaults tables (`frogpilot_defaults.py` / `frogpilot_default_params_table.py`)
- `toggle_metadata.py` visibility (Minimal reparent of Border/Sidebar metrics + SwapSpeedGraph under CustomUI)
- file-toggle defaults (`DeveloperHUD` off, `SwapSpeedGraph` on)
- AP1 profile deltas (no TuningLevel lock; DeveloperHUD off)

## Peer contracts
- **Stream 3 (Qt) / Stream 4 (raylib):** honor `REPARENT_TO_CUSTOM_UI` and Minimal levels when wiring panels. Do not hide Border/Sidebar metrics behind DeveloperUI.
- **Stream 6 (params/cereal):** register keys used here; do not change shipping values without stream 5. Unknown-key-safe migration must keep `/data/params_bogpilot` file toggles.
- **Stream 8 (cluster/hide-accel):** implement HideAccel with `tuning_level=0`, `parent_param=CustomUI`, default per stream-8 plan; must leave lower speed capsule visible. SwapSpeedGraph default ON is set here.

## Non-goals
- Fresh-install Tuning Level remains unset (popup still offered).
- Model UI widths stay Advanced.
- No push; author BogPilot <bogpilot@users.noreply.github.com>.
