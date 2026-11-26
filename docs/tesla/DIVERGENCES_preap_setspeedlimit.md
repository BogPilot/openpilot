# Pre-AP SetSpeedLimit ("Match Speed Limit on Engage")

Credit: BogPilot 0.9.7 (568fea947) for the behavior; NAP (e99f4dc75, opendbc cc39c7fa) for the Pre-AP
engage cross-check. Signals as in Tinkla (501c7de), whose Pre-AP fingerprint carries 0x2F8 and 0x3C8.

## What 0.9.7 did
- `drive_helpers.py:146-158` `initialize_v_cruise`: returns early with `pcmCruise`; else accel/resume uses the
  last set speed; else, with `set_speed_limit` and a non-zero limit, the engage set is the limit; else the
  current speed clipped to the initial and max set speeds.
- `controlsd.py:667` passes `slcSpeedLimit + slcSpeedLimitOffset` (limit plus SLC offset).
- `frogpilot_variables.py:1143`: `set_speed_limit = speed_limit_controller and SetSpeedLimit`.
- The settings row was shown only with `!pcm_cruise`, i.e. Pre-AP with the pedal, never on AP1.

## What this tree does
- `cruise.py` `initialize_v_cruise(..., set_limit_kph=0.0)`: same order as 0.9.7; a positive value is the
  engage set, clipped to `V_CRUISE_MIN..V_CRUISE_MAX`. 0 (the default) is the stock behavior.
- `card.py`: only Pre-AP with `pcmCruise=False` builds `PreapEngageSetLimit`; on the enable edge it passes
  the fresh limit plus the SLC offset (`offset_for`, the same band rule as the SLC consumer).
- Limit source: `UI_gpsVehicleSpeed` (0x2F8: `UI_mppSpeedLimit`, `UI_mapSpeedLimitUnits`) and
  `UI_driverAssistMapData` (0x3C8: `UI_mapSpeedLimit`). No Mobileye fused limit on Pre-AP.
- Settings: the row sits in the SLC QOL sub-panel and is shown only on Pre-AP with the pedal.

## Divergences
1. Freshness (ours; no reference has it): the engage limit is used only if its frame arrived within
   `LIMIT_MAX_AGE_S` (3.0 s) of the parser's last update, empty updates included (`speed_limit.frame_fresh`,
   the same rule as AP1), so a silent bus does not keep an old limit fresh.
   The units frame (0x2F8) must be fresh too, so a limit in unknown units never sets the speed.
   Stale or unknown means the normal engage set. The display limit is unchanged.
2. Stricter posture (from NAP): NAP captures the current speed at engage (0 at a stop) and never sets a
   higher target. Here no limit is set when engaging at a standstill or with the gas pressed; the normal
   engage set applies. Standstill is `CS.vEgo < 0.1` m/s or `CS.standstill` (the stricter wins). Pre-AP
   with the pedal sets `CS.standstill` from the DI `STANDSTILL` cruise state (`preap/carstate.py`), which
   is false when DI cruise is not engaged, so the vEgo gate is what fires at a stop. Missing or non-finite
   vEgo fails closed. `CarState.standstill` itself is unchanged. Brake handling is unchanged (a brake
   press still drops long).
3. SLC must also be adopted (the existing SLC activation policy), and the toggle follows the SLC parent,
   as in 0.9.7.
4. AP1 keeps `pcmCruise=True`, so 0.9.7 never applied this there; the row stays hidden on AP1 and every
   other car, with the reason kept in `CAR_GATED`.
5. Units source: `UI_driverAssistMapData` (0x3C8) has its own units bit (`UI_mapSpeedUnits`,
   tesla_ap1_can.dbc, BO_ 968). The engage path (and the display path) use `UI_mapSpeedLimitUnits` from
   the fresh 0x2F8 frame (`UI_gpsVehicleSpeed`). That is fine while both frames are fresh together; a
   stale 0x2F8 already fails closed (divergence 1).
6. `UI_mppSpeedLimit` raw 31 (physical 155 after the DBC factor of 5) is treated as no limit.
   tesla_ap1_can.dbc has no VAL_ table for this signal (the sibling `UI_mapSpeedLimit` enumerates 31 as
   "SNA"; `DAS_fusedSpeedLimit` enumerates 31 as "NONE"). Tinkla 501c7de `carstate.py:355` applies the
   physical value with no SNA / 155 check. 155 cannot be a real posted limit, so this is a fail-closed
   divergence from Tinkla.
