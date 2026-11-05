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

- Full VirtualDAS / buddy IC still out (radar GTW `rx_all` is now ported — see Bosch radar).
- Full VirtualDAS, zero-torque learning, engage-grace pedal ramps, stock-CC spoofer.
- Buddy IC / DAS HUD TX.
- iBooster (NotAutopilot has no working path).
- In-UI EPAS flash procedure.
- Full NAP settings panel (use FrogPilot/BogPilot toggles; `disable_openpilot_long` gates pedal).

## Hardware expectation

- Pre-AP Model S + comma 3/3X/4-class + **Comma Pedal** for longitudinal.
- Without pedal: safety mode still loads but OP long stays off (`pcmCruise` true).


## Pedal calibration + Bosch radar (this cut)

### Pedal (Comma Pedal)
- **Sole long switch:** `DisableOpenpilotLongitudinal` (Pre-AP menu copy explains comma pedal on/off).
- **No separate Pedal Enabled.** Long ENABLE only when user wants long **and** pedal detected **and** calibrated.
- File-backed keys under `/data/params_bogpilot/`: `PedalCalibDone`, `PedalCalibMin/Max/Factor/Zero`, `PedalCanBus` (default **2**), `PedalCalibArmed`, `PedalDetected`.
- Status line: Not detected / Needs calibration / Ready.
- Calibrate: park, foot off, arm from menu, then full press (runtime samples).

### Bosch radar
- File-backed: `TeslaRadarEnabled` (**default off**), `TeslaRadarBehindNosecone`, `TeslaRadarOffset` (meters internal; UI inches).
- Safety: `PREAP_FLAG_RADAR_EMULATION` (bit 1) + optional `PREAP_FLAG_RADAR_BEHIND_NOSECONE` (bit 4). **Default off.**
- **Panda GTW (NAP port):** `safety_hooks.rx_all` → `tesla_preap_gtw_emulation` readdrs chassis bus0→radar bus1 (0x45→0x219, 0x108→0x109, 0x145→0x149, 0x20A→0x159, 0x308→0x209, 0x30A→0x2D9, 0x405→0x2B9; patched 0x398→0x2A9; SNA/CRC 0x0E→0x199; synth 0x115→0x129+0x1A9, 0x118→0x119+0x169). Firmware `can_send(..., skip_tx_hook=true)`.
- **Requires panda firmware rebuild** with `SAFETY_TESLA_PREAP` (32) + this source. Integrator builds once on `bogpilot-na-preap-combined` — this branch commits **source only**, no `panda/board/obj` binaries.
- Python `preap/radar_tx.py`: dummy VIN `TESTDUMMYVIN00000` (never a real VIN) + NAP-matching `GTW_carConfig` keepalive (Bosch fwd radar / autopilot bits / nosecone). Radar off → sends nothing.
- Live symptom without GTW fw: `radarState` invalid, `RadarPoint*` 0x322/0x323 timeouts, `radarFault`; missing mode 32 → panda `noOutput`.
- AP1 `safety_tesla.h` remains untouched.

### Menu copy
- Pre-AP-only strings live in `selfdrive/car/tesla/preap/menu_copy.py` and are mirrored in `vehicle_settings.cc`.
- AP1 Tesla panel text is unchanged.
