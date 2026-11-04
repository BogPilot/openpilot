# BogPilot Pre-AP port — NotAutopilot source (`bogpilot-na-preap`)

User-facing name: **BogPilot**. Code/param keys remain FrogPilot-shaped where they already exist.

## Credit and license

- Primary source: **NotAutopilot** (`nap-release` + `opendbc` `tesla/preap` + `safety/modes/tesla_preap.h`).
- Spiritual predecessor also credited in safety comments: **Tinkla** (BogGyver) Pre-AP.
- License: MIT (Comma.ai / openpilot lineage). Keep LICENSE and these credit notices.

## Gate (AP1 unchanged)

- Production fingerprint: `CAR.TESLA_PREAP_MODELS` only (opt-in). AP1 chassis addrs (`0x45`/`0x2b9`/`0x488`) still classify as `ap1_s` only.
- Panda: `SAFETY_TESLA_PREAP` (32) / `SafetyModel.teslaPreap` — **not** `SAFETY_TESLA` (10).
- `panda/board/safety/safety_tesla.h` is not modified on this branch; AP1 TX/hooks unchanged.

## Ported in this cut

- Standalone Pre-AP panda safety (TX whitelist, pedal ENABLE rules, stalk engage/cancel with echo filter, gear/door disengage, AP1-matching steer rate limits).
- Interface wiring: `teslaPreap` safety config + pedal-gated `openpilotLongitudinalControl`.
- `PreApCarController`: angle steer via existing `TeslaCAN`, pedal `0x551` packing from NotAutopilot.
- Platform: `long_control_allowed(preap) == True`; AP1 still False at this layer.

## Left out (documented)

- Radar GTW emulation (`rx_all` / VIN fake) — BogPilot 0.9.7 `safety_hooks` has no `rx_all`.
- Full VirtualDAS, zero-torque learning, engage-grace pedal ramps, stock-CC spoofer.
- Buddy IC / DAS HUD TX.
- iBooster (NotAutopilot has no working path).
- In-UI EPAS flash procedure.
- Full NAP settings panel (use FrogPilot/BogPilot toggles; `disable_openpilot_long` gates pedal).

## Hardware expectation

- Pre-AP Model S + comma 3/3X/4-class + **Comma Pedal** for longitudinal.
- Without pedal: safety mode still loads but OP long stays off (`pcmCruise` true).
