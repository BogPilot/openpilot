# Legacy Tesla (0.11.x): divergences from the reference forks

References: BogPilot 0.9.7 (`bogpilot-tesla`, `04d560f3e`), Tinkla / BogGyver openpilot (`501c7de91b59`) and
NotAutopilot (NAP, `e99f4dc75088`). Each entry records where this tree behaves differently from them and why.
Recorded disagreements only where the cited files were read. No speculation.

## Driver alerts: steerSaturated ("Turn Exceeds Steering Limit")
- Platforms: all (generic selfdrived).
- Reference behavior: BogPilot 0.9.7 `selfdrive/controls/controlsd.py` raises the alert when lateral control is active,
  there was no steering press in the last 2 s, the car is not a notCar, and the turn is undershooting while saturated.
  There is no openpilot-state gate. Tinkla `selfdrive/controls/controlsd.py` also has no override gate.
  NAP: no Python producer of this alert.
- Our behavior: the same gate as BogPilot 0.9.7 (`steer_saturated_alert_allowed` in
  `openpilot/selfdrive/selfdrived/selfdrived.py`). The alert still fires during an accelerator-only override.
- Why: not a divergence. Limit steer-saturated suppression to driver steering input, as 0.9.7 does.
- Safety-relevant: yes; matches the stricter reference posture.
- Tests: `openpilot/selfdrive/selfdrived/tests/test_steer_saturated_override.py`.
- Credits: BogPilot 0.9.7; Tinkla/BogGyver.

## Longitudinal: Experimental Mode with a known speed limit
- Platforms: all with openpilot longitudinal.
- Reference behavior: BogPilot 0.9.7 `selfdrive/controls/controlsd.py`: with CEM or the speed-limit fallback set to
  Experimental, the planner's flag replaces the driver's Experimental toggle.
- Our behavior: `EXPERIMENTAL_POLICY = "or"` (`openpilot/selfdrive/controls/lib/phase3_speed_control.py`): a known speed
  limit never turns off the driver's Experimental toggle. "replace" stays selectable.
- Why: keep the driver's explicit Experimental choice when a speed limit is known.
- Safety-relevant: low. No panda limit, gas/brake edge or controls_allowed change.
- Tests: `openpilot/selfdrive/controls/tests/test_phase3_speed_control.py`, `test_phase3_speed_control_wiring.py`.
- Credits: BogPilot 0.9.7.

## Curve speed control: hold the cap through the curve
- Platforms: AP1 (`openpilot/selfdrive/controls/lib/ap1_curve_speed.py`).
- Reference behavior: BogPilot 0.9.7 curve speed controller (FrogPilot lineage).
- Our behavior: the curve cap is held for `CSC_HOLD_S` after the curve is no longer detected, is not raised while
  already capping, and starts on a re-engage inside a curve. Output never exceeds the driver's set speed.
- Why: keep the curve cap until the curve ends instead of returning to the speed-limit target mid-curve.
- Safety-relevant: yes, more conservative (only lowers or holds speed longer). Blinker suspension unchanged.
- Tests: `openpilot/selfdrive/controls/tests/test_ap1_curve_speed_planner.py`.
- Credits: BogPilot 0.9.7.

## Onroad UI: stock lead chevron with RedesignUI
- Platforms: all (onroad UI only; not the Tesla instrument cluster).
- Reference behavior: BogPilot 0.9.7 draws the lead chevron unless the user turns on `HideLeadMarker`.
- Our behavior: with RedesignUI on, the stock chevron is not drawn; the lock-on box is the lead indicator
  (`openpilot/selfdrive/ui/onroad/bogpilot/hud_compose.py`).
- Why: avoid a duplicate or stale chevron under the lock-on box.
- Safety-relevant: minor. Not a warning; stock warnings are not hidden.
- Tests: `openpilot/selfdrive/ui/onroad/bogpilot/tests/test_hud_compose.py`.
- Credits: BogPilot 0.9.7.

## Panda safety (Pre-AP): stalk message 0x45 (STW_ACTN_RQ) is cancel-only on TX
- Platforms: Pre-AP Model S (`TESLA_FLAG_PREAP` on SAFETY_TESLA, `opendbc_repo/opendbc/safety/modes/tesla_preap.h`).
- Reference behavior: NAP (opendbc `cc39c7fa252e`) `opendbc/safety/modes/tesla_preap.h` whitelists 0x45 on bus 0
  (line 589) and `tesla_preap_tx_hook` (lines 458-550) has no 0x45 content check, so any lever value can be sent.
  BogPilot `bogpilot-na-preap` (`568fea947`) `panda/board/safety/safety_tesla_preap.h` is the same: whitelisted
  (line 80) with no 0x45 check in `tesla_preap_tx_hook` (lines 431-493). Tinkla / BogGyver (panda `f7751e4cf54d`)
  `board/safety/safety_tesla.h` whitelists 0x45 for Pre-AP (line 169); its cancel-only check (lines 1113-1121) is
  commented out and applied only with AP hardware.
- Our behavior: `tesla_preap_tx_hook` rejects any 0x45 frame whose lever field (`data[0] & 0x3F`) is not 1 (cancel)
  (lines 219-224), and 0x45 is whitelisted on bus 0 only (line 261). Engage stays a driver stalk pull read on RX.
- Why: openpilot never needs to send anything but cancel on the stalk message, so the panda blocks the rest.
- Safety-relevant: yes; stricter than all three references. Keep it.
- Tests: `opendbc_repo/opendbc/safety/tests/test_tesla_preap.py` (`test_stalk_is_cancel_only`).
- Credits: BogPilot `bogpilot-na-preap`; Tinkla/BogGyver; NAP.

## Onroad UI: confidence ball on the big (C3X) driving screen (D-CB1)
- Platforms: all (onroad UI only; not the Tesla instrument cluster).
- Reference behavior: stock 0.11.2 has the ball only on the comma four UI (`selfdrive/ui/mici/onroad/confidence_ball.py`);
  the big UI `selfdrive/ui/onroad/augmented_road_view.py` has none. BogPilot 0.9.7 adds it to the C3X Qt screen
  (`frogpilot/ui/qt/onroad/confidence_ball.h`, `selfdrive/ui/qt/onroad/onroad_home.cc`).
- Our behavior: the stock file `openpilot/selfdrive/ui/onroad/augmented_road_view.py` draws the ball after the status
  border, then the alert in a deferred tail (`HudComposer.begin_frame` / `render_tail` in
  `openpilot/selfdrive/ui/onroad/bogpilot/hud_compose.py`). Both scissor pairs and the blind-spot border pairs end in
  `finally`. A full-screen alert keeps the previous order and the ball is not drawn.
- Why: give the C3X the 0.9.7 confidence ball without changing what the alert covers.
- Safety-relevant: display only; the alert is still the last thing drawn and is drawn even when an earlier renderer raises.
- Tests: `openpilot/selfdrive/ui/onroad/bogpilot/tests/test_confidence_ball.py`.
- Credits: comma.ai openpilot (MIT) for the original ball; BogPilot 0.9.7 for the C3X port.

## Onroad UI: confidence ball drawn under alerts (D-CB2)
- Reference behavior: BogPilot 0.9.7 raises the ball widget above `OnroadAlerts` (`onroad_home.cc`, `confidence_ball.h`
  `raise()`), so it can cover the edge of a full-screen alert.
- Our behavior: every alert paints over the ball, and the ball is hidden while a full-screen alert is showing.
- Why: IC/onroad changes must never hide stock alerts. Stricter than the reference.
- Safety-relevant: yes; stricter.
- Tests: `test_confidence_ball.py` (view order, full-alert order).
- Credits: BogPilot 0.9.7.

## Settings: confidence ball rows (D-CB3)
- Reference behavior: BogPilot 0.9.7 has one Off / Left / Right control (`frogpilot/ui/qt/offroad/visual_settings.cc`).
- Our behavior: two rows at the top of Appearance, "Confidence Ball" (on/off, default on) and "Confidence Ball Side"
  (Left / Right, default Left), same files `/data/params_bogpilot/ConfidenceBall` and `ConfidenceBallSide`;
  reset returns the side to Left.
- Why: raylib list items have no three-way row.
- Safety-relevant: no.
- Tests: `test_confidence_ball.py`, `openpilot/selfdrive/ui/tests/test_bogpilot_nesting.py`.
- Credits: BogPilot 0.9.7.

## Onroad UI: confidence ball edge switch (D-CB4)
- Reference behavior: BogPilot 0.9.7 moves the ball to the other edge while the map panel covers its side.
- Our behavior: 0.11.2 has no map panel here; the ball moves to the other edge while a blind-spot flame track burns on
  its side, and hides if both sides burn.
- Why: never paint over a flame track.
- Safety-relevant: no.
- Tests: `test_confidence_ball.py`.
- Credits: BogPilot 0.9.7.

## Onroad UI: confidence ball always shown, engaged palette only while engaged (D-CB6)
- Reference behavior: stock (`mici/onroad/confidence_ball.py`) and BogPilot 0.9.7 (`confidence_ball.h`) drive the ball to
  -0.5 while disengaged, so it slides out below the screen; 0.9.7 keeps the widget visible but the ball is off screen.
  0.9.7 uses the engaged palette for every status except disengaged / override.
- Our behavior: shown in every state while the toggle is on; the height always follows the model. The engaged palette
  (green / orange / red) is used only while ENGAGED. OVERRIDE uses the stock white-to-grey ball and DISENGAGED the stock
  dark ball, so the colour never reads as openpilot active; engagement is shown by the border. Missing model data:
  bottom position, stock red only while engaged.
- Why: owner request (always visible), with the colour rule required by the safety review.
- Safety-relevant: display only; no control path reads it.
- Tests: `test_confidence_ball.py` (always shown, never engaged palette when not engaged).
- Credits: comma.ai openpilot (MIT); BogPilot 0.9.7.

## Settings: gated list_view actions (D2)
- Platforms: all (settings UI only).
- Reference behavior: stock v0.11.2 dual- and multiple-button list actions stay enabled and accept taps even when the row is locked.
- Our behavior: UI gated actions subclass the stock dual- and multiple-button actions. Stock `list_view.py` is unchanged. Locked rows are dimmed and ignore taps. The SLC and weather choice rows re-read the stored value. Unlocked rows behave as stock. Locked writes are still refused onroad by the existing editor checks.
- Why: locked BogPilot settings rows should look and act locked, without changing the stock list widget.
- Safety-relevant: no. UI only; no control or panda path.
- Tests: `openpilot/selfdrive/ui/tests/test_bogpilot_gated_actions.py`.
- Credits: stock v0.11.2; the rc7 locked-row audit. Full write-up: `docs/tesla/UI_GATED_ACTIONS.md`.
- Value rows (rc9): the shared value row adds a grey default hint, a changed-value highlight and one confirmed "Reset section to defaults" row per section, built on the same gated actions. Credits: BogPilot rc8 Alert Volume row and stock v0.11.2 `list_view.py` / `confirm_dialog.py`. See "Value rows" in `docs/tesla/UI_GATED_ACTIONS.md`.
- Steering Tuning (rc9): no per-row RESET. The Advanced and Quality of Life section Resets cover value rows only (numeric defaults from `numeric_rows`; `PauseLateralSpeed` default 0). Toggles stay out. Override Sensitivity is in neither section and has no reset. The unlabeled level-0 -/+ row for Pause Steering Below is hidden. Credits: BogPilot rc8 and stock v0.11.2. Details in `docs/tesla/UI_GATED_ACTIONS.md`.

## Cluster / DBC: AP1 AutopilotStatus (0x399) bits 27-36 follow BogPilot, not Tinkla
- Platforms: AP1 and pre-AP (legacy `tesla_ap1_can.dbc` `AutopilotStatus`, address 921 / 0x399, DLC 8).
- Reference behavior: BogPilot bogpilot-tesla `04d560f3` and na-preap `568fea947` `tesla_can.dbc:669` `AutopilotStatus` are byte-identical to this tree's `tesla_ap1_can.dbc:669` (every start|len@endian, sign, scale, and signal name; packing at `:670-695`). In bits 27-36 that layout is `DAS_summonFwdLeashReached` 28|1, `DAS_summonRvsLeashReached` 29|1, `DAS_sideCollisionAvoid` 30|2, `DAS_sideCollisionWarning` 32|2, `DAS_sideCollisionInhibit` 34|1, `DAS_csaState` 35|2 (all Intel `@1+`). Tinkla opendbc `9c0b6fe3` `tesla_can.dbc:649` uses the same address under the name `DAS_status`, but bits 27-36 differ (`DAS_lssState` 29|3, shifted side-collision, and no `DAS_csaState` at 35|2).
- Our behavior: the port follows the BogPilot / na-preap `AutopilotStatus` packing, not the Tinkla mid-frame packing, and not Model 3/Y `DAS_status` at 0x39b.
- Why: keep the legacy 0x399 cluster status layout that matches both BogPilot revisions.
- Safety-relevant: yes; cluster status, side-collision, and CSA bits.
- Tests: see `can_rc8_noxnor_names.md` (layout compared at the cited DBC lines).
- Credits: BogPilot bogpilot-tesla `04d560f3`; na-preap `568fea947`; Tinkla compared at opendbc `9c0b6fe3`.

## Gas press: level block, no panda edge drop
Panda safety does not end the session when the accelerator is pressed. While the pedal is pressed, longitudinal commands are blocked (longitudinal allowed = controls allowed and gas not pressed). Steering control continues, and controls come back without a new engage once the pedal is released. Ending the session on a gas press is a host-side option, the disengage-on-accelerator setting, which is off by default.
Pre-AP: the pedal-interceptor enable (0x551) is rejected while gas is pressed. AP1: accel requests (0x2b9) are blocked while gas is pressed.
Reference: matches NotAutopilot (NAP) and current upstream panda safety, where the gas-edge drop was removed (commaai/opendbc #2232). One legacy reference fork drops controls on a gas edge in its panda, but only when the disengage-on-accelerator setting is on, and its host also disengages in that case. Panda-side enforcement differs; the outcome the driver sees is the same. That fork is not used as the reference for this behavior, by project decision.
Tests: TX blocking while gas is pressed is covered for pre-AP and AP1. Asserting that controls stay allowed after a gas press is covered for pre-AP and AP1.

## Pre-AP stock cruise: host gas-pressed threshold
On pre-AP cars using stock cruise (no pedal interceptor), the host treats the accelerator as pressed only above 2% pedal position (DI_pedalPos raw > 5), so pedal-position noise doesn't cause sticky overrides. Reference: NotAutopilot (NAP) preap carstate, PEDAL_DI_PRESSED = 2. Panda safety is unchanged: any nonzero pedal reading still blocks longitudinal commands. AP1 and the pedal-interceptor path are unchanged.

## Removed: beta stalk bookmark (BETA-ONLY)
The beta-only "3 quick FWD stalk taps after disengaging -> userBookmark" detector (UI module `beta_stalk_bookmark`, file flag `/data/params_bogpilot/BetaStalkBookmark`, default off, AP1 Model S only) is removed. It had no parity source: BogPilot 0.9.7, Tinkla/BogGyver and NAP have no stalk bookmark, and FWD on 0x45 is cancel only in all three, which is again the only behavior here.
- Why: it was a beta-testing aid only; removed to keep the code simple. It also never ran on the device, because it checked carParams only on the first frame, before carParams arrives.
- Kept: the on-screen bookmark (`bookmarkButton` + `userBookmark`) and `carState.bogpilot.spdCtrlLvr` (used by phase3_speed_control) with its bus-0 isolation test.
- Safety-relevant: no; the module was UI-side and observe-only (no CAN TX, no panda, no car code).
- History: last present at 06f7f9135 (docs/tesla/DIVERGENCES_beta_stalk_bookmark.md and its tests).

## SLC section reset on AP1 Model S returns to the AP1 profile
- Platforms: AP1 Model S only (`CarModel` / `CarParamsPersistent` `TESLA_AP1_MODELS`, the AP1 profile's own `is_ap1()`). Pre-AP and AP1 Model X have their own entries below; other cars keep the general table.
- Reference behavior: BogPilot bogpilot-tesla `367e1fe` has no per-section reset. Its one-time AP1 Model S profile (`selfdrive/car/tesla/ap1_defaults.py`, ported here as `openpilot/common/bogpilot_ap1_profile.py`) runs again after "Reset toggles to default", so a full reset on that car lands on the profile values.
- Our behavior: the Speed Limit Controller section resets on AP1 Model S write the AP1 profile's values, read from the profile itself: Offset1-7 4/5/5/5/7/8/10 mph (converted and rounded to km/h on a metric device, 6/8/8/8/11/13/16), Override Max Set Speed (2), Priority 1 Dashboard, Priority 3 Navigation, Look-ahead 5 s, Show Speed Limit Offset off. Priority 2 is not in the profile and resets to its table default (Map Data). The row hints show the same values. The Visual Settings page gets a reset row on AP1 Model S for Show Speed Limit Offset.
- Structure: the panel picks a reset profile by car type (`SLC_RESET_PROFILES` in `phase3_speed_control_settings.py`); adding another car type is one entry.
- Unchanged: the AP1 profile, the general defaults table and its resets on other cars, and saved values (the profile still writes only once per device, and only keys at the table default).
- Why: a section reset matches what a full reset already gives on AP1 Model S.
- Safety-relevant: no; settings UI only. Car code and panda are unchanged.
- Tests: `openpilot/selfdrive/ui/tests/test_slc_ap1_section_reset.py`, `openpilot/selfdrive/controls/tests/test_slc_ap1_section_reset_panel.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (AP1 Model S profile values and the re-apply after reset).

## Pre-AP Model S SLC defaults use the AP1 speed settings
- Platforms: Pre-AP Model S only (`TESLA_PREAP_MODELS`, through the legacy SLC profile in `openpilot/common/bogpilot_ap1_profile.py`). `is_ap1()` is unchanged; AP1 Model S keeps its own profile.
- Reference behavior: BogPilot bogpilot-tesla `367e1fe` sets these speed settings only in its AP1 Model S profile (`selfdrive/car/tesla/ap1_defaults.py`); Pre-AP gets the general table there.
- Our behavior: the one-time legacy SLC profile on Pre-AP adds the AP1 profile's Offset1-7 (4/5/5/5/7/8/10 mph; 6/8/8/8/11/13/16 km/h on a metric device, same conversion and rounding) and Override Max Set Speed (2), read from the AP1 profile (nothing copied). Its priorities (Dashboard / Map Data / Navigation) and look-ahead are unchanged. Fallback is not written; its table default (Previous Limit) already matches AP1. No AP1-only display key (Show Speed Limit Offset) is added. The SLC section resets and row hints on Pre-AP return the same legacy profile values (a Pre-AP entry in `SLC_RESET_PROFILES`).
- Upgrades: the profile writes once per device (`LegacySlcDefaultsApplied` marker) and only keys still at the table default (or the settings UI's km/h conversion of it). A device that already has the marker keeps its current values; Reset BogPilot Settings clears the marker, so the next start applies the profile again.
- Why: the AP1 speed settings are known to work well and Pre-AP uses the same SLC.
- Safety-relevant: no; settings defaults only. Car code and panda are unchanged.
- Tests: `openpilot/selfdrive/ui/tests/test_slc_legacy_profile.py`, `openpilot/selfdrive/ui/tests/test_slc_ap1_section_reset.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (AP1 profile speed values).

## AP1 Model X SLC defaults match the AP1 Model S
- Platforms: AP1 Model X only (`TESLA_AP1_MODELX`, through the legacy SLC profile in `openpilot/common/bogpilot_ap1_profile.py`). `is_ap1()` is unchanged and stays Model S only.
- Reference behavior: BogPilot bogpilot-tesla `367e1fe` has no AP1 Model X platform; its SLC settings come from the AP1 Model S profile (`selfdrive/car/tesla/ap1_defaults.py`).
- Our behavior: the one-time legacy SLC profile on AP1 Model X adds the AP1 Model S profile's SLC settings and nothing else (`AP1_SLC_KEYS`, read from the profile, nothing copied): Offset1-7 4/5/5/5/7/8/10 mph (6/8/8/8/11/13/16 km/h on a metric device), Override Max Set Speed (2), priorities Dashboard / Map Data / Navigation, look-ahead 5 s lower / 0 higher, Show Speed Limit Offset off. No other AP1 profile key (themes, personalities, Conditional Experimental Mode and so on) is written on the X. The SLC section resets and row hints on the X return the same values (an AP1 Model X entry in `SLC_RESET_PROFILES`, with a Visual Settings reset row).
- Upgrades: same one-time path and `LegacySlcDefaultsApplied` marker as Pre-AP. An X that already has the marker keeps its current values; Reset BogPilot Settings clears the marker, so the next start applies the profile again.
- Why: the X uses the same SLC as the AP1 Model S, whose values are known to work well.
- Safety-relevant: no; settings defaults only. Car code and panda are unchanged.
- Tests: `openpilot/selfdrive/ui/tests/test_slc_legacy_profile.py`, `openpilot/selfdrive/ui/tests/test_slc_ap1_section_reset.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (AP1 Model S profile SLC values).

## "Offset Set Speed by:" row hidden on every car
- Platforms: all car types.
- Reference behavior: BogPilot bogpilot-tesla `367e1fe` lists the Set Speed offset (`SetSpeedOffset`) as a numeric row for cars without stock cruise control and with openpilot longitudinal.
- Our behavior: the row is never shown, on any car type. Nothing in this tree reads `SetSpeedOffset` while driving (controls, planner, car controller, longitudinal and speed limit code), so changing it did nothing; the speed limit offsets (Offset1-7) set the offset instead. The setting itself and its default (0) are kept, so saved values, backups and resets are unchanged and nothing is migrated.
- Why: a setting that does nothing should not be offered.
- Safety-relevant: no; settings UI only.
- Tests: `openpilot/selfdrive/ui/tests/test_set_speed_offset_hidden.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (the original row).

## "Reset section to defaults" resets the whole section, its switch included
- Platforms: all car types.
- Reference behavior: BogPilot section resets wrote only the section's number rows (and, on cars with an SLC reset profile, the toggle and choice rows that profile lists); the section's own on/off switch and its other toggle and choice rows kept their saved values.
- Our behavior: a section reset writes the shipped BogPilot defaults for the whole section, the same values "Reset BogPilot Settings to Defaults" writes: number rows, toggle and choice rows and the section's own switch, the switch last. On AP1 Model S, AP1 Model X and Pre-AP Model S the Speed Limit Controller reset then applies that car type's SLC values on top; other car types get the plain defaults. Sections with their own switch: Speed Limit Controller (on), Gas / Brake Quality of Life (on), Alert Volume Controller (off), Lane Changes (on), Automatic Lane Changes (off), Advanced Lateral Tuning (off), Steering Quality of Life (on), Advanced Longitudinal Tuning (off), Conditional Experimental Mode (on), and each Driving Personality profile (on). Lead Detection does not reset Longitudinal Tuning, whose switch is on another page. Only rows shown and editable at the time of the reset are written; hidden rows (for example "Offset Set Speed by:") and keys outside the section are never touched.
- Why: "defaults" should mean the whole section as shipped, not only its numbers.
- Safety-relevant: no; settings UI only. Every write goes through the same guarded path as the row's own control (offroad only, refused writes reported).
- Tests: `openpilot/selfdrive/ui/tests/test_section_reset_parent.py` and the panel section-reset tests (sounds, steering, lane changes, following, speed limit controller).
- Credits: BogPilot (the section reset rows).
