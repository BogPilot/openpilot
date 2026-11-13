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
- Our behavior: the Speed Limit Controller section resets on AP1 Model S write the AP1 profile's values, read from the profile itself: Offset1-7 4/5/5/5/7/8/10 mph (converted and rounded to km/h on a metric device, 6/8/8/8/11/13/16), Override Max Set Speed (2), Priority 1 Dashboard, Priority 3 Navigation, Look-ahead 5 s, Show Speed Limit Offset off. Priority 2 is not in the profile and resets to its table default (Map Data). The row hints show the same values. The Visual Settings page gets a reset row on AP1 Model S for Show Speed Limit Offset. The same car-type table now supplies the whole AP1 profile (not only the SLC keys) so other section resets on this car also return to the profile; see the entry below.
- Structure: the panel picks a reset profile by car type (`SLC_RESET_PROFILES` in `phase3_speed_control_settings.py`); adding another car type is one entry.
- Unchanged: the AP1 profile, the general defaults table and its resets on other cars, and saved values (the profile still writes only once per device, and only keys at the table default). `is_ap1()` is unchanged.
- Why: a section reset matches what a full reset already gives on AP1 Model S.
- Safety-relevant: no; settings UI only. Car code and panda are unchanged.
- Tests: `openpilot/selfdrive/ui/tests/test_slc_ap1_section_reset.py`, `openpilot/selfdrive/controls/tests/test_slc_ap1_section_reset_panel.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (AP1 Model S profile values and the re-apply after reset).

## AP1 Model S section resets return to the AP1 profile
- Platforms: AP1 Model S only (the AP1 profile's own `is_ap1()`). AP1 Model X and Pre-AP keep the rows below (SLC values only).
- Reference behavior: BogPilot bogpilot-tesla `367e1fe` has no per-section reset. Its one-time AP1 Model S profile runs again after "Reset toggles to default", so a full reset on that car lands on the profile values.
- Our behavior: every section reset on AP1 Model S writes the AP1 profile's value for every key that both the reset writes and the profile sets, read from the profile itself (unit-aware where the profile is). The section defaults are built first, then the car-type overrides; the section's own switch takes the profile value when the profile sets one. So Conditional Experimental Mode resets to off (the profile's 0, not the shipped 1), Curve Detected Ahead to on, Longitudinal Tuning's deceleration profile to Eco+, and the Relaxed following distance to 2.0 s. Keys the profile does not list keep the shipped or catalog default. A Conditional Experimental Mode child that is hidden (navigation rows, until a navigation producer is connected) is left alone until it is shown.
- Precedence: this is a change from the earlier rule that a section's own switch always reset to the shipped default, with the car-type table applying only to SLC rows. The Pre-AP and AP1 Model X rows of the table are unchanged: they supply the legacy SLC profile and, from the entry "Conditional Experimental Mode off on every legacy Tesla" below, Conditional Experimental Mode off; no other AP1 profile key.
- Unchanged: `is_ap1()`, the AP1 profile itself, and section resets on every other car type.
- Why: a section reset matches what a full reset already gives on AP1 Model S.
- Safety-relevant: no; settings UI only. Car code and panda are unchanged.
- Tests: `openpilot/selfdrive/ui/tests/test_section_reset_parent.py`, `openpilot/selfdrive/ui/tests/test_slc_ap1_section_reset.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (AP1 Model S profile values and the re-apply after reset).

## Pre-AP Model S SLC defaults use the AP1 speed settings
- Platforms: Pre-AP Model S only (`TESLA_PREAP_MODELS`, through the legacy SLC profile in `openpilot/common/bogpilot_ap1_profile.py`). `is_ap1()` is unchanged; AP1 Model S keeps its own profile.
- Reference behavior: BogPilot bogpilot-tesla `367e1fe` sets these speed settings only in its AP1 Model S profile (`selfdrive/car/tesla/ap1_defaults.py`); Pre-AP gets the general table there.
- Our behavior: the one-time legacy SLC profile on Pre-AP adds the AP1 profile's Offset1-7 (4/5/5/5/7/8/10 mph; 6/8/8/8/11/13/16 km/h on a metric device, same conversion and rounding) and Override Max Set Speed (2), read from the AP1 profile (nothing copied). Its priorities (Dashboard / Map Data / Navigation) and look-ahead are unchanged. Fallback is not written; its table default (Previous Limit) already matches AP1. No AP1-only display key (Show Speed Limit Offset) is added. The SLC section resets and row hints on Pre-AP return the same legacy profile values (a Pre-AP entry in `SLC_RESET_PROFILES`).
- Upgrades: the profile writes once per device (`LegacySlcDefaultsApplied2` marker) and only keys still at the table default (or the settings UI's km/h conversion of it). A device from an earlier build has only the earlier `LegacySlcDefaultsApplied` marker (it was offered the priorities and look-ahead only): it is offered the keys added since (Offset1-7 and Override) once, with the same still-at-default rule, and its priorities and look-ahead are left as they are. A device with the new marker keeps its current values; Reset BogPilot Settings clears both markers, so the next start applies the whole profile again. Known limit: an owner who explicitly picked the table value of an added key (for example Override 1, gas latches) after the earlier build cannot be told apart from an untouched device and is moved to the profile value once.
- Why: the AP1 speed settings are known to work well and Pre-AP uses the same SLC.
- Safety-relevant: no; settings defaults only. Car code and panda are unchanged.
- Tests: `openpilot/selfdrive/ui/tests/test_slc_legacy_profile.py`, `openpilot/selfdrive/ui/tests/test_slc_ap1_section_reset.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (AP1 profile speed values).

## AP1 Model X SLC defaults match the AP1 Model S
- Platforms: AP1 Model X only (`TESLA_AP1_MODELX`, through the legacy SLC profile in `openpilot/common/bogpilot_ap1_profile.py`). `is_ap1()` is unchanged and stays Model S only.
- Reference behavior: BogPilot bogpilot-tesla `367e1fe` has no AP1 Model X platform; its SLC settings come from the AP1 Model S profile (`selfdrive/car/tesla/ap1_defaults.py`).
- Our behavior: the one-time legacy SLC profile on AP1 Model X adds the AP1 Model S profile's SLC settings and nothing else (`AP1_SLC_KEYS`, read from the profile, nothing copied): Offset1-7 4/5/5/5/7/8/10 mph (6/8/8/8/11/13/16 km/h on a metric device), Override Max Set Speed (2), priorities Dashboard / Map Data / Navigation, look-ahead 5 s lower / 0 higher, Show Speed Limit Offset off. No other AP1 profile key (themes, personalities, Conditional Experimental Mode and so on) is written on the X. The SLC section resets and row hints on the X return the same values (an AP1 Model X entry in `SLC_RESET_PROFILES`, with a Visual Settings reset row).
- Upgrades: same one-time path and markers as Pre-AP. An X from an earlier build (earlier marker only) is offered the keys added since (Offset1-7, Override, Show Speed Limit Offset) once, still-at-default only; an X with the new marker keeps its current values; Reset BogPilot Settings clears both markers, so the next start applies the whole profile again.
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
- Our behavior: a section reset writes the shipped BogPilot defaults for the whole section, the same values "Reset BogPilot Settings to Defaults" writes: number rows, toggle and choice rows and the section's own switch, the switch last. The car-type table is then applied on top, including the section switch when the profile sets one (a precedence change from the earlier rule that the switch always kept the shipped default). On AP1 Model S that table is the whole AP1 profile, so Conditional Experimental Mode resets to off; on AP1 Model X and Pre-AP Model S it is the SLC values plus Conditional Experimental Mode off, and other car types get the plain defaults. Sections with their own switch, at the shipped default unless a profile override applies: Speed Limit Controller (on), Gas / Brake Quality of Life (on), Alert Volume Controller (off), Lane Changes (on), Automatic Lane Changes (off), Advanced Lateral Tuning (off), Steering Quality of Life (on), Advanced Longitudinal Tuning (off), Conditional Experimental Mode (on, off on every legacy Tesla), and each Driving Personality profile (on). Lead Detection does not reset Longitudinal Tuning, whose switch is on another page. Only rows shown and editable at the time of the reset are written; hidden rows (for example "Offset Set Speed by:") and keys outside the section are never touched.
- Why: "defaults" should mean the whole section as shipped, not only its numbers.
- Safety-relevant: no; settings UI only. Every write goes through the same guarded path as the row's own control (offroad only, refused writes reported).
- Tests: `openpilot/selfdrive/ui/tests/test_section_reset_parent.py` and the panel section-reset tests (sounds, steering, lane changes, following, speed limit controller).
- Credits: BogPilot (the section reset rows).

## Section icons on the Gas / Brake and Steering pages, as in 0.9.7
- Platforms: all car types.
- Reference behavior: BogPilot 0.9.7 shows an icon on each section row of the longitudinal and lateral settings (`frogpilot/ui/qt/offroad/longitudinal_settings.cc`, `lateral_settings.cc`), from `frogpilot/assets/toggle_icons`.
- Our behavior: the same icons, copied unchanged (same bytes, same file names) into `openpilot/selfdrive/assets/icons/bogpilot/`, on the section rows only: Gas / Brake MANAGE rows (Advanced Longitudinal Tuning, Conditional Experimental Mode, Driving Personalities, Longitudinal Tuning, Quality of Life, Speed Limit Controller), the Lane Changes OPEN row under Steering, the Steering Tuning OPEN row under Steering, and the Advanced Lateral Tuning and Quality of Life switches on the Steering Tuning page. Rows inside a section get no icon. The 0.9.7 icons for Curve Speed Controller and Always On Lateral are mapped but have no row in this tree yet. 0.9.7 has no Steering Tuning row and maps no icon to one; this tree gives that row the 0.9.7 Lateral Tuning icon (`icon_lateral_tune.png`, same bytes), an addition made on request, not a 0.9.7 mapping. `button_item` and the switch + MANAGE row take an `icon`; the row keeps the icon's width free when it places its button, and a missing or unreadable icon file shows no icon instead of failing. The existing menu icons are unchanged.
- Why: match the 0.9.7 settings look.
- Safety-relevant: no; settings UI only.
- Tests: `openpilot/selfdrive/ui/tests/test_section_icons.py`, `openpilot/selfdrive/ui/tests/test_bogpilot_menu_097.py` (section icon tests).
- Credits: BogPilot 0.9.7 (the icons and their mapping).

## AP1 steering: bounded recovery from a latched EPAS EAC_ERROR_TMP_FAULT (code 4)
- Platforms: AP1 Model S and AP1 Model X (`opendbc/car/tesla_ap1/carcontroller.py`). Pre-AP is unchanged.
- Reference behavior: Tinkla (BogGyver/openpilot `501c7de`, `selfdrive/car/tesla/carcontroller.py:86-106`) sends 0x488 as ANGLE whenever engaged, at the measured wheel while lateral is not active, whatever the EPAS error code. BogPilot 0.9.7 (`selfdrive/car/tesla/actuator_plan.py` `ap1_hold_measured_angle`) also keeps the measured-wheel ANGLE hold while engaged and not EAC_ACTIVE. In both, a latched EPAS error clears on the next ANGLE frame.
- Previous behavior here: an EPAS that is INHIBITED or reports any error other than IDLE, HANDS_ON (3) or HIGH_ANGLE_REQ (6) is never sent ANGLE (`epas_gate.py`, `actuator_plan.py`), and code 4 is a temporary fault (`steer_fault.py`), so latActive stays false. The EPAS keeps code 4 latched while AVAILABLE and clears it only when a new EAC session is commanded, so one transient code 4 ended lateral control until the car was power cycled.
- Our behavior: `epas_gate.EpasTmpFaultRecovery` (every rule in that one class). A code 4 that appears while the EPAS is ACTIVE still drops lateral on that frame, as before. Only while openpilot is engaged, latActive is off, the EPAS has reported AVAILABLE with code 4 for 0.5 s in a row (settle: the recorded event went ACTIVE, INHIBITED, then AVAILABLE within 120 ms), hands are below level 2, the driver is not overriding, there is no EAC_FAULT, the car is moving at 2.2 m/s (about 5 mph, `MIN_ERR4_PROBE_SPEED`) or more, and a 0x214 EPB_epasEACAllow of 1 arrived within the last 200 ms (`ERR4_EPB_FRESH_FRAMES`; a car without 0x214, or with a stale one, gets no request and behaves as before; elsewhere in this port 0x214 stays optional): send ANGLE at the measured wheel (the existing soft-start hold, rate limited and clipped to the measured wheel +/- 20 deg, never the planner angle) for at most 0.3 s, then wait 2 s and settle again; at most 3 requests per engagement, counted again from zero on the next engagement. A refusing status (INHIBITED, FAULT, SNA), hands at level 2 or more, a driver override, EPB allow other than 1 or a stale 0x214, vEgo below 2.2 m/s, EAC_FAULT or any error code other than 4 and IDLE ends the request on that frame. If the EPAS clears to IDLE, the hold continues until latActive returns and the normal path resumes through the engage soft-start. Code 4 stays a temporary fault, so lateral is never resumed while the code is set. Each request and its result (cleared, timeout, abort reason) is logged.
- Panda: the AP1 safety mode allows ANGLE with error 4 only while the EPAS status is AVAILABLE or ACTIVE and an EPB_epasEACAllow of 1 arrived within the last 250 ms (see the panda entry for code 4). It does not limit retries; the count, length, spacing, speed and aborts are enforced on the car side.
- Must ship with that panda rule. A panda without it refuses every request frame (code 4 is a refusing error there), and once no ANGLE frame has been accepted for 100 ms its forward hook stops blocking the stock DAS 0x488 from the car side, so the stock steering frames reach the EPAS during each request. That is not the previous behavior. The package step fails the build when this recovery is present and the panda firmware identity is not the one with the rule (`tools/bogpilot/err4_panda_pairing.py`, run by `rc_package.py verify`; tests `tools/bogpilot/tests/test_err4_panda_pairing.py`).
- Speed gate: a replay of the recorded drive showed a request starting during a creep from a stop at 0.24 m/s, below controlsd's 0.3 m/s lateral floor (minSteerSpeed is 0 on this car, so that floor does not cover this path). Requests need 2.2 m/s or more, and a running request ends the moment vEgo drops below it.
- Why: a car-internal one-off code 4 turned into a lockout for the rest of the drive. Codes 3 and 6 on the same car clear within 30-70 ms of the first ANGLE frame, and a Pre-AP capture shows code 4 clearing the same way (AVAILABLE + code 4 from start-up, EAC_ACTIVE + IDLE on the first ANGLE frame).
- Stricter than both references: requests only with an AVAILABLE EPAS (never INHIBITED), above 2.2 m/s, with a recent EPB allow of 1, bounded in time and count, and aborted on any refusal, hands, override, speed or EPB signal.
- Safety-relevant: yes (when ANGLE is sent). Angle and rate limits are unchanged; requests are at the measured wheel only.
- Tests: `opendbc/car/tesla_ap1/tests/test_ap1_epas_tmp_fault_recovery.py` (state machine, planner, open-loop replay of a recorded 12 s window with the code 4 event, closed-loop clear and hand-back).
- Credits: Tinkla/BogGyver `501c7de` and BogPilot 0.9.7 (measured-wheel ANGLE while engaged).

## Conditional Experimental Mode off on every legacy Tesla
- Platforms: AP1 Model S, AP1 Model X and Pre-AP Model S (`openpilot/common/bogpilot_ap1_profile.py` `LEGACY_TESLA_PLATFORMS`). AP2 is not a platform in this tree, so nothing changes for it here. Every other car type is unchanged.
- Reference behavior: BogPilot ships Conditional Experimental Mode on (registry default `1`); the AP1 Model S profile from bogpilot-tesla `367e1fe` turns it off on that car only.
- Our behavior: Conditional Experimental Mode is off on every legacy Tesla in three places. Default: a one-time write at start-up (`apply_legacy_tesla_ce_off_once`, marker `LegacyTeslaCEOffApplied`) turns it off while the key is unset or still at the registry default; on an AP1 Model S whose AP1 profile already ran, only an unset key is written. Section reset: the Conditional Experimental Mode section reset writes its switch off (the car-type reset tables now carry `ConditionalExperimental` 0 for the AP1 Model X and Pre-AP rows; the AP1 Model S row already had it from the profile); the section's other rows keep their shipped defaults on the X and Pre-AP. Full reset: "Reset BogPilot Settings to Defaults" writes it off right after the shipped table, and clears the marker so the next start writes it again; "Reset to stock" already uses the stock value (off).
- Why: Conditional Experimental Mode does not work on these cars yet.
- Known limit: a driver who turned it on before this change cannot be told apart from an untouched device and is moved to off once; turning it on again afterwards is kept.
- Safety-relevant: no; settings defaults only. Car code and panda are unchanged.
- Tests: `openpilot/common/tests/test_legacy_tesla_ce_off.py`, `openpilot/selfdrive/ui/tests/test_section_reset_parent.py`, `openpilot/selfdrive/ui/tests/test_slc_legacy_profile.py`, `openpilot/selfdrive/ui/bogpilot/tests/test_phase3_system_utilities.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (AP1 Model S profile value).

## pandad.py cold start: polled wait, reflash only when needed, "Connecting to panda..." alert
- Platforms: all car types (the panda wrapper `openpilot/selfdrive/pandad/pandad.py` before `./pandad` starts).
- Reference behavior: upstream openpilot 0.11.2 `selfdrive/pandad/pandad.py` resets the internal panda, gives it 1 s to enumerate (`Panda.wait_for_panda(None, timeout=1)`), and if it is not found, or is in its bootstub or on other firmware, recovers it through DFU and reflashes it, then loops with another reset at once. No timing is logged and nothing is shown to the driver while it loops.
- Our behavior: the first look polls (every 0.1 s, the same `Panda.wait_for_panda`) for up to 10 s, later looks for up to 3 s, with a 0.5 / 1 / 2 / 4 s backoff between attempts. A panda that is found in its bootstub, on other firmware, or that cannot be read is reflashed at once, as upstream. A panda that is not found at all is recovered through DFU only after 3 misses in a row, so a dead panda is still recovered. Each step (reset, wait, flash, ready) is logged with its time and the total since the start (`pandad.timing`). The offroad alert "Connecting to panda..." (`Offroad_ConnectingPanda`) is shown once the panda has not answered within 2 s, or while a reflash or retry runs, and cleared as soon as it is ready. The car fingerprinting and VIN query are unchanged.
- Why: on some cold power-ups the wrapper took 27 s to 88 s before `./pandad` started (normally under 1 s), so the device stayed offroad. The step that took the time was not logged; the 1 s give-up followed by a DFU reflash is the most likely cause, so the wait is longer, the reflash is limited to the cases that need it, and every step is now timed.
- Safety-relevant: no change to the panda firmware, safety modes or what is flashed; only when a reflash is attempted and how long the wrapper waits.
- Tests: `openpilot/selfdrive/pandad/tests/test_pandad_cold_start.py`, `openpilot/selfdrive/pandad/tests/test_panda_firmware_record.py`.
- Credits: upstream openpilot 0.11.2 (structure of the wrapper loop).

## Panda (AP1): no active steering into a refusing EPAS, with a latched TMP_FAULT exception
- Platforms: AP1 Model S and Model X (`TESLA_FLAG_AP1`).
- Reference behavior: BogPilot 0.9.7 `panda/board/safety/safety_tesla.h` (0x370 RX and the 0x488 TX check) and
  Tinkla/BogGyver panda `board/safety/safety_tesla.h` do not read `EPAS_eacStatus` or `EPAS_eacErrorCode` at all.
  NAP `opendbc/safety/modes/tesla_legacy.h` only disengages on hands-on level 3 or INHIBITED with error 9. On the car
  side, BogPilot 0.9.7 `selfdrive/car/tesla/actuator_plan.py` (`ap1_hold_measured_angle`) keeps sending ANGLE at the
  measured wheel while the EPAS is not ACTIVE, whatever the error code.
- Our behavior: `opendbc/safety/modes/tesla_ap1.h` drops an active 0x488 frame (type 1 or 2) while the last 0x370
  says INHIBITED, FAULT or SNA, or carries an error other than IDLE, HANDS_ON (3) or HIGH_ANGLE_REQ (6). One
  exception: EAC_ERROR_TMP_FAULT (4) is let through while the same 0x370 frame says AVAILABLE or ACTIVE and the last
  EPB_epasControl (0x214, bus 0) said EPB_epasEACAllow = 1 less than 250 ms ago. controls_allowed, the angle rate
  table and every other check still apply.
- 0x214 is not an RX check. The panda only runs a mode's RX hook for messages in its RX-check list, and every entry
  in that list is required. So `safety.h` gets the optional `rx_all` hook from NAP (`opendbc/safety/safety.h`
  `safety_rx_hook`, `declarations.h` `safety_hooks.rx_all`) and BogPilot 0.9.7 (`panda/board/safety.h`): it is called
  for every received message, before the whitelist. It is NULL in every mode except Tesla, where only AP1 uses it to
  keep the last EPB_epasEACAllow value and its time. A missing or stale 0x214 never touches controls_allowed or the
  RX-check health; it only keeps code 4 blocked, as before this change. 0x214 has no checksum or counter, so the
  frame is used as received.
- Why: the EPAS keeps codes 3, 4 and 6 latched until it is commanded again. Blocking code 4 for good turned one
  transient EPAS fault into a lateral lockout for the rest of the drive. Every other code stays blocked, and
  INHIBITED/FAULT/SNA always block.
- Safety-relevant: yes. Stricter than BogPilot 0.9.7, Tinkla and NAP for every error and status value.
- Tests: `opendbc/safety/tests/test_tesla_ap1_epas_refusal.py`, `opendbc/safety/tests/test_tesla_ap1_epas_tmp_fault.py`.
- Credits: BogPilot 0.9.7; Tinkla/BogGyver; NAP (the `rx_all` hook).
