# Divergence: AP1 cruise set speed under openpilot longitudinal

Entry in the `docs/tesla/DIVERGENCES.md` style, kept in its own file so it can be folded into `DIVERGENCES.md`.

### AP1: cruiseState.speed is openpilot's own set under openpilot long (Tinkla style)
- Platforms: every AP1 car with openpilot longitudinal on: Model S and Model X AP1 (`is_ap1_family`, `values.py:158-159`;
  Model X has openpilot long off by default in `interface.py`, and gets this latch when it is on). AP1 S and X with
  openpilot long off (stock AP), Pre-AP (own CarState) and the panda are unchanged.
- Reference behavior:
  - Tinkla/BogGyver `501c7de` (openpilot-long branch): `cruiseState.speed = acc_speed_kph`, openpilot's own set
    (`selfdrive/car/tesla/carstate.py:312-313`), taken from vEgoRaw when cruise engages (`ACC_module.py:154-158`) and
    clipped to 0-170 kph (`ACC_module.py:231-232`). Its stock-AP branch reads `DI_cruiseSet` (`carstate.py:302-305`).
  - BogPilot 0.9.7 (`568fea947`): `cruiseState.speed = DI_cruiseSet` in both modes (`carstate.py:213-219`).
  - NAP `e99f4dc75`: no AP1 set-speed path (Pre-AP only).
- Our behavior: with openpilot long, while `DI_cruiseState` is engaged (2 ENABLED, 3 STANDSTILL, 4 OVERRIDE, 6 PRE_FAULT,
  7 PRE_CANCEL; 6/7 included because they are in the same set that drives `cruiseState.enabled`), `cruiseState.speed` is
  openpilot's own set, latched on the engage edge (`opendbc/car/tesla_ap1/op_long_set_speed.py`), in this order:
  1. (rolling engage: only after a stalk pull, see "the stalk action that engages decides the set" below)
     a known `dashboardSpeedLimit` plus the speed-limit offset (`Offset1..7` toggles and bands, `offset_for` in
     `phase3_speed_control.py`, passed in by the card from params as `EngageLimitOffset`), as BogPilot 0.9.7 SLC
     (`speed_limit_controller.py`) sets the limit plus offset; at a standstill this applies after a fresh pull or
     with no stalk seen, never after a fresh tap (see 3);
  2. moving with no limit: vEgoRaw, floored at openpilot `V_CRUISE_MIN` (8 kph);
  3. standstill after a fresh stalk UP or DN tap (the most recent press), with or without a known limit: the
     AP1TapFromZeroMph setting (default 15 mph, whole mph
     5-30). The planner's tip path uses the same value (`slc_raise.Ap1RaiseHoldoff.tap_from_zero_ms`; a sticky 0
     counts as no sticky, AP1 openpilot long only);
  4. standstill, no limit, no tap: nothing is latched, `bogpilot.ap1SpeedLimitUnknown` is set and the new event
     `ap1SpeedLimitUnknown` (NO_ENTRY, "BogPilot not Engaged" / "Speed Limit Unknown", same form as
     `pedalNotResponding`) refuses the engage. 0 is published while refused; openpilot is not enabled.
  The set is clamped to 8-170 kph and held through later stops, including `DI_cruiseSet` 0, until cruise disengages,
  so the car resumes to the set after a lead pulls away. Not engaged under openpilot long: 0 (unset), never the raw
  `DI_cruiseSet` (about half of ego), so the engage edge steps straight to the set with no DI seed. Later limit changes
  stay in the planner SLC; later stalk tips stay in the planner tip path. Without openpilot long, `DI_cruiseSet` as before.
  On the mici layout `NoEntryAlert` swaps its two lines (`events.py`), so the top line there is "Speed Limit Unknown".
- Why: under openpilot long on AP1, `DI_cruiseSet` follows about half of ego speed and reads 0 at every stop.
  `VCruiseHelper` turns 0 into `V_CRUISE_UNSET`, the planner resets every cycle, `aTarget` stays below 0.1 and
  `shouldStop` stays latched after the lead pulls away, until the driver presses the gas.
- Inputs are CAN (`DI_cruiseState`, `ESP_vehicleSpeed`, the dashboard limit, stalk buttons) and the params offset; the set never reads `cruiseState.speed`, `carState.vCruise`,
  `bogpilotPlan` or `hudControl`, so there is no feedback loop.
- The car can speed back up to the engage speed after slowing when no sticky, tip or SLC set is active in the planner
  (as Tinkla's set does). Before this change that base followed `DI_cruiseSet`.
- Diverges from 0.9.7 (which reads `DI_cruiseSet`); matches Tinkla's openpilot-long latch. Differences from Tinkla:
  Tinkla latches vEgo and only engages above its minimum cruise speed; we prefer limit plus offset (0.9.7 SLC), allow a
  standstill engage with a limit or a 15 mph tap, and refuse it with NO_ENTRY otherwise. No stalk adjustment in CarState.
- Safety-relevant: longitudinal planning only. No panda, CAN TX, DBC or 0x45 change; engage and disengage still follow
  `DI_cruiseState`; `DAS_setSpeed` (`max(v + 3a, 0)`) is unchanged.
- Tests: `opendbc_repo/opendbc/car/tesla_ap1/tests/test_ap1_op_long_set_speed.py`, `test_ap1_tap_from_zero.py`.
- Credits: Tinkla/BogGyver (openpilot-long set speed); BogPilot 0.9.7 (SLC limit plus offset, stalk tips); comma.ai openpilot (`VCruiseHelper`, `V_CRUISE_MIN`).

### AP1: the 15 mph standstill tap must be fresh
- Our behavior: a stalk UP/DN tap (the `buttonEvents` pressed edge from `STW_ACTN_RQ`) counts for the 15 mph standstill
  set only if it is pressed while cruise is engaged with nothing latched, or at most `TAP_WINDOW_S` = 0.8 s before the
  engage edge. An older tap (for example at a red light before the engage) is dropped, and a tap is used once, so a
  disengage and re-engage at a standstill needs a fresh tap or a known limit (else NO_ENTRY).
- Window source: BogPilot 0.9.7 `slc_raise.py:183` `RECENT_S = 0.8` (`568fea947`), the same stalk-to-enable window its
  engage classifier uses ("Tesla clears buttonEvents 80-240 ms before enabled rises"). Tinkla has no standstill tap set.
- Why: a stale tap could latch 15 mph on a later standstill engage and drive off with no fresh driver request.
- Tests: `test_stale_tap_at_red_light_does_not_latch_later_standstill_engage`, `test_tap_inside_window_before_edge_counts`,
  `test_tap_from_zero_sets_24_14_kph_and_clears_no_entry` (`test_ap1_op_long_set_speed.py`).
- Credits: BogPilot 0.9.7 (stalk window).

### AP1: a stale speed limit is unknown for the engage set
- Our behavior: for the engage-set limit only, each limit source (`AutopilotStatus` fused, `UI_driverAssistMapData`,
  `UI_gpsVehicleSpeed` mpp and units) counts only if its frame arrived within `LIMIT_MAX_AGE_S` = 3.0 s
  (`speed_limit.frame_fresh`, parser `ts_nanos` against the parser's last update time, `_last_update_nanos`, so a
  silent bus does not keep a stale limit looking fresh). A stale limit is unknown: a
  standstill engage gets NO_ENTRY `ap1SpeedLimitUnknown` (unless a fresh tap), a moving engage takes the vEgo latch.
  `dashboardSpeedLimit` (display and planner SLC) is unchanged.
- Why: these messages are optional (frequency 0), so the parser keeps their last value forever and a limit from an
  earlier road could set the engage speed or drive off from a standstill.
- Threshold: no reference has one (Tinkla `501c7de` and BogPilot 0.9.7 `568fea947` parse these frames with no age check),
  so this is our choice: 3x the slowest measured period in AP1 captures (`UI_gpsVehicleSpeed` 1.0 s;
  `UI_driverAssistMapData`, `AutopilotStatus` 0.5 s; worst gap 1.01 s).
- Tests: `test_stale_limit_standstill_engage_is_no_entry`, `test_stale_limit_moving_engage_falls_through_to_vego`,
  `test_limit_inside_age_gate_still_latches` (`test_ap1_op_long_set_speed.py`).
- Credits: Tinkla/BogGyver and BogPilot 0.9.7 (limit sources).

### AP1: no limit-based engage set while the limit units are unknown
- Signal: `UI_mapSpeedLimitUnits` (`UI_gpsVehicleSpeed`, 0x2F8, bit 46, 0 MPH / 1 KPH). It is a real signal: 0x2F8
  (8 bytes) is in Tinkla's AP1 Model X fingerprint (`modelx_fingerprint_data.py`, Tinkla `values.py`), and Tinkla
  `501c7de` `carstate.py:319-320, 532` parses it for every model. Our Model S and Model X parsers already subscribe
  to it (optional). No new signal.
- Our behavior: on Model S and Model X, when that frame is missing or older than `LIMIT_MAX_AGE_S`, the engage set
  ignores every limit source (a fused 0x399 value could be a kph sign read as mph, because `units_are_metric` falls
  back to MPH) and falls through to the vEgo latch, a fresh tap, or NO_ENTRY. With a fresh units frame, the limit is
  converted with the reported units. `dashboardSpeedLimit` is unchanged.
- Tests: `test_model_x_units_unknown_does_not_latch_metric_like_limit`, `test_model_x_units_known_metric_latches_kph`,
  `test_model_s_units_unknown_or_stale_does_not_latch_metric_like_limit`, `test_model_s_units_known_metric_latches_kph`
  (`test_ap1_op_long_set_speed.py`).
- Credits: Tinkla/BogGyver (units signal and Model X fingerprint).

### AP1: the standstill tap-from-0 speed is a user setting
- Our behavior: `AP1TapFromZeroMph` is a BogPilot param (INT, default 15, whole mph 5-30). It is read live (1 s cache,
  same as the engage-limit offset) and used as the standstill tap-from-0 latch when there is no fresh speed limit.
  Missing, non-integer, or out-of-range values fall back to 15 (not clamped to 5 or 30). The Gas / Brake page shows
  the row ("Standstill Tap Speed") for AP1; when the UI is metric the value also shows the km/h equivalent. A rolling
  no-limit engage or tap still latches exact vEgo and does not use this setting.
- Why: 0.9.7 used a fixed 15 mph (and at a standstill its vEgo latch was 0). This 0.11 addition keeps that default
  and lets the driver pick 5-30 mph.
- Tests: `test_tap_from_zero_is_15_mph_exactly`, `test_tap_from_zero_setting_default_edges_live_and_display`
  (`test_ap1_op_long_set_speed.py`).
- Credits: BogPilot 0.9.7 (fixed 15 mph tap-from-0 starting point).

### AP1: a rolling engage with no fresh limit latches exact vEgo (including below 8 kph)
- Our behavior: with no fresh limit, a moving (not `standstill`) engage or tap latches the exact current vEgoRaw,
  including below 8 kph. There is no clamp-up to 8 kph and no 5 mph rounding. Only a tap from a true standstill
  uses the tap-from-0 speed (default 15 mph). True standstill is the existing CarState signal
  (`carstate.py`: `ret.standstill = (ret.vEgo < 0.1)` m/s). If the latched vEgo would round to 0 (0.1 kph or the
  0.4 mph 0x389 grid) or the car is at standstill, the standstill rules apply: fresh limit, fresh tap, or NO_ENTRY,
  so the set is never 0/UNSET while enabled. A rolling vEgo latch is only capped at 170 kph; limit and standstill-tap
  sets stay clamped to 8-170 kph. Engaging while rolling to a stop with no lead and no fresh limit also latches the
  exact vEgo (for example 1 kph), so the car keeps crawling at that set instead of stopping until the driver brakes
  or taps. That crawl is intended; there is no extra guard that forces a stop.
- Downstream (not changed here): AP1 uses `pcmCruise` (default True; `VCruiseHelper` copies `cruiseState.speed` and
  only turns a literal 0 into `V_CRUISE_UNSET`). `cluster.py:519-524` keeps the last nonzero IC set; `cruise_set_mph`
  only rejects non-positive / UNSET values. A 2 kph latch therefore publishes 2 kph on `cruiseState.speed` and
  `vCruise`. The IC 0x389 digit is that speed in mph on the 0.4 mph grid (about 1.2 mph). `card.py` cluster floor and
  `cluster_set_kph` do not clamp a small set back up to 8 kph. `cruise.py:111` `V_CRUISE_MIN` applies only on the
  non-pcmCruise button path, which AP1 openpilot long does not use.
- Why: product decision, restoring Tinkla's vEgo latch (`ACC_module.py:154-158` @501c7de) without the 8 kph openpilot
  floor on this rolling path. Replaces an earlier "clamp-up to 8 kph, kept" note.
- Tests: `test_moving_no_limit_vego_latch_no_event`, `test_rolling_engage_no_limit_latches_exact_vego` (0.5, 2, and
  7.9 kph) (`test_ap1_op_long_set_speed.py`).
- Credits: Tinkla/BogGyver (vEgo latch).

### AP1: stalk set-speed tips (deep 5 mph, shallow ±1, rolling exact vEgo)
- Our behavior, already in `slc_raise.Ap1RaiseHoldoff` (0.9.7 `bogpilot_vcruise` / `slc_raise`): while moving with an
  existing openpilot set, a deep tip (SpdCtrlLvr 4/8, or a 0.45 s hold) goes to the next or previous multiple of 5 mph
  (`next_5_ms` / `prev_5_ms`); a shallow tip (16/32) is ±1 mph (`step_1_ms`). A rolling tap or engage with no existing
  set latches exact vEgo (no 5 mph rounding). Only a true standstill tap uses the tap-from-0 setting. True standstill
  matches CarState (`vEgo < 0.1` m/s). A DN tip must never raise the set: decrease paths use
  `min(base, max(candidate, TIP_MIN_MS))` (`slc_raise.Ap1RaiseHoldoff._dn_set_ms`), so a crawl latch below the 1 mph
  floor (for example 0.5 kph) stays at that latch and stays above 0, rather than being lifted to 1 mph. A normal DN
  from 37 mph is still 35 (deep) or 36 (shallow).
- Tests: `test_ap1_stalk_set_rules.py` (including `test_dn_tip_from_crawl_latch_does_not_raise` and
  `test_normal_dn_from_37_goes_to_35_or_36`), `test_engaged_tips_plus_minus_one_and_next5` (`test_phase3_speed_control.py`).
- Credits: BogPilot 0.9.7 slc_raise / bogpilot_vcruise (deep vs shallow tips and the vEgo latch).

### AP1: two cruise ceilings (145 kph vs 170 kph)
- `OpLongSetSpeed` (the engage/latch published as `cruiseState.speed`, copied to `vCruise` on the `pcmCruise` path)
  caps a rolling vEgo latch at 170 kph and clamps a limit or standstill-tap set to 8-170 kph (`SET_MAX_KPH` in
  `op_long_set_speed.py`, Tinkla `ACC_module.py:231-232`).
- Stalk tip-up paths in `slc_raise.Ap1RaiseHoldoff` cap at `V_CRUISE_MAX_MS` (145 kph, openpilot `V_CRUISE_MAX`).
- The planner speed that longitudinal control follows (`Ap1SpeedControl.v_cruise_out` in `phase3_speed_control.py`)
  is always re-capped at 145 kph, so a 170 kph latch still commands at most 145 kph. That 145 kph planner cap is
  authoritative for the driven set and for tips.
- The IC 0x389 pack (`cruise_set_mph` in `slc_raise.py`) also rejects a value above about 145 kph
  (`V_CRUISE_MAX_MPH + 0.5`), so a latch above that does not update the digital set.
- No code change in this note; it records the existing behaviour.

### AP1: the stalk action that engages decides the set (tap latches the current speed, only a pull follows SLC)
- Platforms: AP1 Model S and Model X with openpilot longitudinal (car layer `op_long_set_speed.py`, planner
  `slc_raise.Ap1RaiseHoldoff` through `phase3_speed_control.Ap1SpeedControl`). Pre-AP keeps its own engagement
  (NAP-style double pull); a Pre-AP tap still neither engages nor adds speed control. No panda change.
- Reference behavior:
  - BogPilot 0.9.7 (`04d560f3e`): the planner classifies the engage on the `cruiseState.enabled` rising edge
    (`frogpilot_vcruise.py:119`) from the stalk level seen within 0.8 s (`slc_raise.py`, `RECENT_S`): UP/DN -> sticky
    vEgo, pull -> SLC limit plus offset. The car set is `DI_cruiseSet`; there is no limit-first car layer.
  - Tinkla/BogGyver `501c7de`: the openpilot-long set is vEgo when cruise engages (`ACC_module.py:154-158`).
- Our behavior:
  - Car layer: on a rolling engage edge the set is limit plus offset only after a fresh stalk pull (resumeCruise,
    `SpdCtrlLvr_Stat` 2); a fresh UP/DN tap, a pull with no known limit, or no stalk seen latches exact vEgoRaw.
    The most recent fresh press wins (same 0.8 s window). At a standstill a fresh tap gives the tap-from-stop speed
    (AP1TapFromZeroMph, default 15 mph) even with a known limit, matching the planner's tap from 0; a fresh pull (or
    no stalk seen) with a known limit gives limit plus offset as before. A pull after a tap with no limit still gives
    the tap-from-stop speed, and the NO_ENTRY `ap1SpeedLimitUnknown` refusal is unchanged.
  - Planner: the stalk action is classified on the cruise engage edge (`cruise_on` rising), remembered as
    `engage_kind` while cruise stays on, updated by newer presses (a lat-only second pull or tap), and applied when
    openpilot longitudinal becomes active. A tap latches vEgo as of the tap; an engage with no stalk seen latches vEgo
    as of the cruise edge; only a pull hands the set to SLC. There is no SLC fallback for an unclassified rolling engage.
    An unclassified engage at a standstill latches nothing (the car-layer standstill rule applies). It is cleared when
    cruise turns off (cancel, brake, any disengage) and when openpilot disengages.
  - Engaged in SLC tracking, an UP/DN tap leaves SLC and latches the tipped set (existing tip rule: shallow detent
    +/-1, deep detent next/previous 5, based on the current set). Later posted-limit changes in either direction do not
    move it (only Curve Speed Control may lower it temporarily); the next pull returns to SLC at limit plus offset.
    The IC set follows the plan set outside the engage floor (`cluster_set_kph`, `follow_plan`).
  - A longitudinal re-activation in the same cruise session (gas override longer than `LongEngageGate.DROP_S`)
    restores the driver's latched or tipped set instead of handing the set to SLC; after a pull it still follows SLC.
  - Published stalk levels (`bogpilot.accelPressed/decelPressed/resumePressed`) are at least 6 CAN frames (60 ms) wide
    from the press so the 20 Hz planner cannot miss a short press, and a longer press ends at its release (no tail);
    a cancel (FWD) clears them. `buttonEvents` are unchanged. See "stalk level minimum width" below.
- Why: classifying on the longitudinal edge let a tap made with the gas held fall outside the 0.8 s window once
  longActive rose on release, and the fallback chose SLC; the limit-first car set also gave limit plus offset for a
  rolling tap. Both made a tap follow SLC instead of latching the current speed.
- Diverges from 0.9.7 in three ways: a standstill tap with a known limit gives the tap-from-stop speed (0.9.7 had no
  standstill tap set and no car-layer set); an unclassified rolling engage latches vEgo (0.9.7 fell back to SLC), and a
  longitudinal re-activation in the same cruise session keeps the driver's set. Uses only existing signals
  (`SpdCtrlLvr_Stat` via `BUTTONS`, `cruiseState.enabled`, `carControl.longActive`, `selfdriveState.enabled`).
- Safety-relevant: set-speed choice only. No panda, CAN TX, DBC or cereal change; engage, disengage, NO_ENTRY and
  stale-tap rules are unchanged; the standstill set after a tap with a known limit drops from limit plus offset to the
  tap-from-stop speed.
- Tests: `test_ap1_op_long_set_speed.py`, `test_phase3_speed_control.py`, `test_phase3_speed_control_pull_modes.py`,
  `test_phase3_speed_control_lookahead.py`, `test_preap_set_speed_limit.py`, `test_preap_tap_never_slc.py`; standstill:
  `test_standstill_tap_with_known_limit_latches_tap_from_stop_speed`, `test_standstill_pull_with_known_limit_uses_limit_plus_offset`,
  `test_standstill_tap_with_known_limit_car_and_planner_agree_on_tap_from_stop_speed`.
- Credits: BogPilot 0.9.7 (cruise-edge classification, tap/pull policy); Tinkla/BogGyver (current-speed latch at engage);
  NAP (Pre-AP pull / double-pull engagement).

### AP1: Max Set Speed gas override returns to the driver's set, else the current limit plus offset
- Platforms: AP1 Model S and Model X with openpilot longitudinal (`Ap1SpeedControl._ap1_op_long`). Pre-AP keeps 0.9.7.
- Reference behavior: BogPilot 0.9.7 `frogpilot/controls/lib/speed_limit_controller.py:344-356` (`568fea947`): with
  SLCOverride 2 ("Max Set Speed") a gas press above limit plus offset sets `overridden_speed = v_cruise + v_cruise_diff`,
  and the override holds after the release while that value is above limit plus offset. In 0.9.7 `v_cruise` is the
  driver's cruise set.
- Our behavior: under AP1 openpilot long `v_cruise` is the car-layer engage latch (`op_long_set_speed.py`), which after a
  pull is the engage-time limit plus offset and is never refreshed on a limit change. So Max Set Speed uses the set the
  driver chose instead (`Ap1RaiseHoldoff.driver_set_ms`: the sticky tap / vEgo latch or an engaged tip, or the last one
  seen while longitudinal was ours); with none (pull engage, SLC tracking) it uses the current limit plus offset, so the
  override ends at the release. Example: pull at 45 + 5 (set 50), the limit drops to 35 (SLC 40), gas to 45, release:
  40, not 50. A tap latch or a tipped set is still restored after the gas.
- Gas override after longitudinal was ours: when the gas holds `carControl.longActive` False longer than
  `LongEngageGate.DROP_S` (1.0 s) while cruise and openpilot stay engaged, the planner is lateral only until
  longActive is seen again. That covers the gas hold, the release tick (gas already up, longActive still False from
  controlsd's previous step) and any further ticks longActive lags. On those ticks the planner used to publish
  `carState.vCruise`, that same engage latch, so plan, IC, HUD and the 0x389 set digit showed the earlier zone's limit
  plus offset. It now publishes the same set as above (`driver_set_ms`, else the current limit plus offset), with no
  vEgo floor. An openpilot disengage with cruise still on clears this state, so a re-engage is an engage again. A
  lateral-only state with no gas press since longActive was last seen (double-pull first pull, a re-pull demote) keeps
  the pass-through. The DROP_S timing, the gas-held engage before longitudinal is ours (pass-through floored at vEgo)
  and the double-pull first pull are unchanged. Example: pull at 35 + 5, tip down to 20, the limit drops to 25, gas
  held 2 s, longActive back 1 to 5 ticks after the release: 20 on every tick.
- Why: the old rule raised the set back to an earlier zone's limit plus offset with no driver set action.
- Safety-relevant: planner set speed only. Longitudinal is not commanding while the lateral-only path runs
  (longActive False). The plan computed on its last tick is what controlsd follows for up to one planner tick (~50 ms)
  after longActive returns; that is now the same set the planner holds after the release, not the engage latch. The
  0x389 set digit follows the published set by design. No panda, safety, DBC or cereal change.
- Tests: `TestMaxSetSpeedGasOverride`, `TestHeldGasPassThrough` and `test_override_manual_and_set_speed`
  (`test_phase3_speed_control.py`); `TestDoublePullMode` (`test_phase3_speed_control_pull_modes.py`).
- Credits: BogPilot 0.9.7 (SLC override rule).

### AP1: non-finite engage inputs never become a set
- Our behavior (`op_long_set_speed.py`): a non-finite (inf / NaN) dashboard limit, or a limit whose offset or limit plus
  offset is not finite, is an unknown limit (rolling pull: exact vEgo latch; standstill: a fresh tap's tap-from-stop
  speed or NO_ENTRY `ap1SpeedLimitUnknown`). A non-finite vEgoRaw latches nothing on that frame and the engage is refused
  through the same `ap1SpeedLimitUnknown` NO_ENTRY (no 0 or placeholder set while enabled); the next finite frame
  latches as usual, and a set already latched is held. A non-finite tap-from-stop setting is the 15 mph default, as
  `parse_tap_from_zero_mph` treats an invalid value. Before this, +inf gave a 170 kph set, a NaN offset gave a NaN set and
  a non-finite vEgoRaw raised.
- Reference behavior: Tinkla `ACC_module.py:231-232` (`501c7de`) clips the set; BogPilot 0.9.7 has no car-layer set.
  Neither checks finiteness; this is stricter.
- Safety-relevant: set-speed choice only; only removes sets that were not finite or came from a non-finite input.
- Tests: `test_nonfinite_*` (`test_ap1_op_long_set_speed.py`).

### AP1: a rolling tap followed by a stop inside the window keeps the tap's vEgo latch
- Our behavior (`op_long_set_speed.py`): a stalk UP/DN tap made while rolling, then a full stop and the engage edge
  within `TAP_WINDOW_S` (0.8 s) of the tap, latches the exact vEgoRaw at the tap (kept below 8 kph, capped at 170 kph),
  not limit plus offset. Before this the rolling tap cleared the standstill tap state, so the standstill engage fell to
  "known limit: limit plus offset" (a 3 mph tap with a 45 mph limit gave a 50 mph car-side set, shown on the cluster),
  while the planner classified the same engage as a tap and latched 3 mph. A later pull still wins (limit plus offset);
  past the window the tap is stale and the standstill rules are unchanged.
- Reference behavior: BogPilot 0.9.7 `slc_raise.py` (`04d560f3e`): a tap inside `RECENT_S` before the engage latches the
  vEgo at the tap (sticky); our planner keeps that (`Ap1RaiseHoldoff.engage_vego_ms`). Tinkla latches vEgo at the engage.
- Safety-relevant: set-speed choice only; the set is lower than or equal to the old one in the reported case.
- Tests: `test_rolling_tap_then_stop_within_window_keeps_tap_set`, `..._keeps_tap_set_on_can`,
  `test_rolling_tap_then_stop_within_window_car_and_planner_agree`, `test_rolling_tap_then_stop_after_window_is_unchanged`,
  `test_rolling_tap_then_pull_at_the_stop_uses_limit_plus_offset` (`test_ap1_op_long_set_speed.py`).

### AP1: stalk level minimum width counts from the press, not the release
- Our behavior (`carstate.py` `_held_stalk_levels`): a published stalk level is at least `STALK_LEVEL_HOLD_FRAMES` (6 x
  10 ms) wide from the press edge, so a one-frame press still spans a 50 ms planner tick, and a press longer than that is
  published exactly as long as it is held. Before this every press was extended 50 ms past its release, so the planner's
  measured hold was 50 ms longer than the driver's and the shown set (tip, hold upgrade) changed up to 50 ms late
  relative to the stalk. The planner's hold upgrade (`Ap1RaiseHoldoff.TIP_HOLD_S` 0.45 s, a ±1 tip becomes next/prev 5)
  now also counts nine 50 ms ticks as 0.45 s (float slack `TIP_HOLD_EPS_S`); before, nine ticks summed to just under
  0.45 s and the stretched level supplied the missing tick. Net: the upgrade follows a 0.45 s physical hold, a 0.40 s
  hold stays a ±1 tip.
- Reference behavior: BogPilot 0.9.7 `frogpilot/controls/frogpilot_card.py` `_apply_ap1_stalk_levels` (`04d560f3e`)
  publishes `button_states` as they are, with no stretch; the minimum width exists here so a one-frame press cannot fall
  between two 20 Hz planner samples.
- Safety-relevant: stalk-level timing only; cancel still clears every level at once; no panda, CAN TX, DBC or cereal change.
- Tests: `test_held_stalk_level_ends_at_the_release_of_a_longer_press`,
  `test_held_stalk_level_short_press_is_stretched_to_the_minimum_width`, `test_planner_hold_upgrade_follows_the_physical_hold`,
  `test_short_tap_between_planner_ticks_classified`, `test_cancel_drops_held_stalk_levels` (`test_ap1_op_long_set_speed.py`).


### AP1: a pull with SpeedLimitController off still engages at the dashboard limit (no offset)
- Our behavior (current, pinned by tests, not changed): the car-layer engage set (`op_long_set_speed.py`, rules 1 and 4)
  does not read the SpeedLimitController toggle. With SLC off, `EngageLimitOffset` gives offset 0 (`offset_for` is 0
  with SLC off), so a rolling pull with a fresh known limit, or a standstill pull / no-stalk engage with one, latches the
  bare dashboard limit; the planner is a pass-through with SLC off, so that limit stays the set for the engagement and no
  longer follows later limits. With no limit: rolling vEgo, standstill NO_ENTRY `ap1SpeedLimitUnknown`, as with SLC on.
- Reference behavior: BogPilot 0.9.7 sets the speed to the limit only through SLC: `toggle.set_speed_limit` requires
  `toggle.speed_limit_controller` (`frogpilot/common/frogpilot_variables.py:1143`, `568fea947`), and with SLC off the
  0.9.7 AP1 set is `DI_cruiseSet`. Tinkla/BogGyver (`501c7de`) latches vEgo at the engage (`ACC_module.py:154-158`) and
  has no standstill engage. NAP has no AP1 path.
- Why it is kept for now: the set is the posted limit with no offset, never above it, and is only taken on a driver
  pull. Gating it on the SLC toggle is not a contained change: at a standstill the limit rule is what lets a pull engage
  at all, so the gate would turn every standstill pull with SLC off and no tap into a NO_ENTRY `ap1SpeedLimitUnknown`
  refusal (an alert that names the limit while the limit feature is off), and the car layer would need the SLC toggle
  passed in from the card. That is a behavior change in its own right, not a clear bug fix.
- Possible gate (not implemented): with SLC off, a rolling pull latches exact vEgo (Tinkla); a standstill pull uses a
  fresh tap's tap-from-stop speed or is refused.
- Tests: `TestEngageSetWithSlcOff` (`test_phase3_speed_control.py`).
