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

## Onroad UI: lead and adjacent-lead boxes engaged or not, and under alerts
- Platforms: all (onroad UI only; comma 3X wide layout and comma 4).
- Reference behavior: BogPilot daily `annotated_camera.cc` draws leadOne and the adjacent leads (`leadLeft` /
  `leadRight`) whenever openpilot longitudinal is available, radarState is from this drive and `HideLeadMarker` is
  off; engagement is not a condition, and the alerts are painted over them. The earlier 0.11.2 port also required
  the car to be engaged and skipped the boxes under a full-screen alert.
- Our behavior: the boxes and the lead speed labels are drawn engaged or disengaged, and under every alert size (the
  alert is still painted last, on top). The boxes keep clear of the HUD, the driver monitor and the personality
  button but not of the alert; the speed labels still keep clear of the alert. Unchanged gates: RedesignUI,
  openpilot longitudinal, `HideLeadMarker` (default off) and `AdjacentLeadsUI` (default on). Unchanged data checks:
  fresh valid radarState / bogpilotRadarState / modelV2 / carState / selfdriveState / calibration, a present lead
  with finite distance, and a clean on-screen calibrated projection. No lead means no box. The personality button
  stays hidden under a full-screen alert. The gate lives in the shared core (`lead_lockon.LeadLockOn`), so every
  layout that uses it behaves the same.
- Why: the maintainer wants the lead and adjacent-lead boxes always on, engaged or not.
- Safety-relevant: minor. Display only; alerts are still drawn on top and nothing in controls reads it.
- Tests: `openpilot/selfdrive/ui/onroad/bogpilot/tests/test_lead_lockon.py`, `test_adjacent_leads_bsm.py`,
  `test_hud_compose.py`; `openpilot/selfdrive/ui/tests/test_bogpilot_labels.py`.
- Credits: BogPilot (drawLead gating and order).

## Panda safety (Pre-AP): stalk message 0x45 (STW_ACTN_RQ) is cancel-only on TX
- Platforms: Pre-AP Model S (`TESLA_FLAG_PREAP` on SAFETY_TESLA, `opendbc_repo/opendbc/safety/modes/tesla_preap.h`).
- Reference behavior: NAP (opendbc `cc39c7fa252e`) `opendbc/safety/modes/tesla_preap.h` whitelists 0x45 on bus 0
  (line 589) and `tesla_preap_tx_hook` (lines 458-550) has no 0x45 content check, so any lever value can be sent.
  BogPilot `bogpilot-na-preap` (`568fea947`) `panda/board/safety/safety_tesla_preap.h` is the same: whitelisted
  (line 80) with no 0x45 check in `tesla_preap_tx_hook` (lines 431-493). Tinkla / BogGyver (panda `f7751e4cf54d`)
  `board/safety/safety_tesla.h` whitelists 0x45 for Pre-AP (line 169); its cancel-only check (lines 1113-1121) is
  commented out and applied only with AP hardware.
- Our behavior: `tesla_preap_tx_hook` rejects any 0x45 frame whose lever field (`data[0] & 0x3F`) is not 1 (cancel)
  (lines 237-242), and 0x45 is whitelisted on bus 0 only (line 281). Engage stays a driver stalk pull read on RX.
- Why: openpilot never needs to send anything but cancel on the stalk message, so the panda blocks the rest.
- Safety-relevant: yes; stricter than all three references. Keep it.
- Tests: `opendbc_repo/opendbc/safety/tests/test_tesla_preap.py` (`test_stalk_is_cancel_only`).
- Credits: BogPilot `bogpilot-na-preap`; Tinkla/BogGyver; NAP.

## Panda safety and host (Pre-AP): rules stricter than the references
- Platforms: Pre-AP Model S (`TESLA_FLAG_PREAP` on SAFETY_TESLA). Summarised in the header of
  `opendbc_repo/opendbc/safety/modes/tesla_preap.h` (lines 11-13). References: NAP (opendbc `cc39c7fa252e`)
  `opendbc/safety/modes/tesla_preap.h`, BogPilot `bogpilot-na-preap` (`568fea947`) `panda/board/safety/safety_tesla_preap.h`
  and `selfdrive/car/tesla/`.
- Our behavior, each stricter than those references:
  1. The panda reads the brake: `brake_pressed` is BrakeMessage (0x20A) driverBrakeStatus != NOT_PRESSED or
     DI_torque2 (0x118) DI_brakePedal (`tesla_preap.h` lines 158-165). NAP and `bogpilot-na-preap` set
     `brake_pressed = false`. Tests: `test_brake_message_drops_controls`, `test_di_brake_pedal_drops_controls`,
     `test_brake_from_one_source_is_not_cleared_by_the_other`.
  2. EAC_FAULT (EPAS_eacStatus 3) drops controls like an EPAS refusal (`tesla_preap.h` lines 53-54); neither NAP nor
     `bogpilot-na-preap` drops on it. Tests: `test_epas_fault_drops_controls`, `test_a_held_pull_also_cannot_survive_an_eac_fault`.
  3. DAS_control (0x2B9) is not on the TX whitelist (`tesla_preap.h` lines 278-284); NAP whitelists it.
     Test: `test_tx_whitelist_without_the_pedal_flag`.
  4. STW_ACTN_RQ (0x45) may only send CANCEL; see the 0x45 entry above.
  5. An enabled Comma Pedal command (0x551) is rejected while the brake is pressed or above raw 2500
     (`tesla_preap.h` lines 248 and 253-254); neither reference has these limits. The 2500 cap is described in
     `docs/tesla/PREAP_PORT.md`. Tests: `test_enabled_pedal_is_bounded` (the cap);
     `opendbc_repo/opendbc/safety/tests/test_tesla_preap_pedal_brake.py` (the brake rule).
  6. The pedal sensor (GAS_SENSOR, 0x552) bus is latched to the first bus it is seen on, and the other bus never drives
     gas (`opendbc_repo/opendbc/car/tesla_ap1/preap/carstate.py` lines 129-146, mirroring the panda). NAP and
     `bogpilot-na-preap` record the first bus but still drive gas from every 0x552. Also in
     `docs/tesla/DIVERGENCES_preap_nap_fsm.md`. Tests: `test_pedal_on_the_other_bus_never_drives_gas_pressed`,
     `test_latch_resets_on_init`.
  7. The pedal scale floor is 0.82 (`opendbc_repo/opendbc/car/tesla_ap1/preap/calib.py` line 60, `FACTOR_MIN`);
     `bogpilot-na-preap` `calib.py` uses 0.4. Described in `docs/tesla/PREAP_PORT.md`.
     Test: `opendbc_repo/opendbc/car/tesla_ap1/tests/test_preap_pedal_limit.py`.
- Note on 0x488 (DAS_steeringControl): the car sends it at 50 Hz, every second control frame
  (`opendbc_repo/opendbc/car/tesla_ap1/preap/carcontroller.py` lines 156-158). The `frequency = 50U` field in
  `tesla_preap.h` (line 210) is unused on this path: `steer_angle_cmd_checks_with_lateral_permission`
  (`opendbc_repo/opendbc/safety/lateral.h` lines 204-243) does not read it, so there is no 0x488 message-rate check.
  No panda source change.
- Safety-relevant: yes; every rule above is stricter than the references. Keep them.
- Credits: NAP; BogPilot `bogpilot-na-preap`; Tinkla/BogGyver.

## Panda safety (Pre-AP): steering stays armed through a brake press (1 s freshness)
- Platforms: Pre-AP Model S (`TESLA_FLAG_PREAP` on SAFETY_TESLA, `opendbc_repo/opendbc/safety/modes/tesla_preap.h`).
- Reference behavior: NAP (opendbc `cc39c7fa`) `opendbc/safety/modes/tesla_preap.h` lines 399-402 sets `brake_pressed = false`
  on BrakeMessage (0x20A), so a brake never clears `controls_allowed`, and it has no steer-through-brake latch; an enabled Comma
  Pedal command (0x551) is gated only by the pedal flag and `get_longitudinal_allowed()` (lines 526-535). BogPilot
  `bogpilot-na-preap` (`568fea947`) `panda/board/safety/safety_tesla_preap.h` lines 341-342 and 473-486 does the same.
  Tinkla/BogGyver (`501c7de`) handles Pre-AP inside `panda/board/safety/safety_tesla.h` and has no such latch. BogPilot 0.9.7
  has no Pre-AP panda mode.
- Our behavior: a stalk pull in D with the doors closed arms the latch (`tesla_preap.h` lines 102-110). A brake press still
  clears `controls_allowed` (`opendbc_repo/opendbc/safety/safety.h` lines 359-362: a rising edge always, a held brake only while
  moving; moving is ESP_B (0x155) speed above 0.139 m/s, `tesla_preap.h` lines 147-152). While armed, a brake press marks the
  latch (lines 89-91), and `tesla_preap_steer_allowed()` (lines 78-93) then allows ANGLE on 0x488 (lines 216, 220-223) although
  `controls_allowed` is false. The latch never sets `controls_allowed` and never allows longitudinal: an enabled 0x551 is
  rejected while `brake_pressed` or `!get_longitudinal_allowed()` (lines 244-257).
  It stays armed only while the car is in D, the doors are closed, the RX checks are valid, and every required RX message has
  been seen, is not lagging and is at most 1 s old (lines 79-84; with the pedal flag this includes GAS_SENSOR 0x552). It is
  disarmed when any of these fails (lines 85-88, checked on every RX frame, line 187, and on every 0x488), by a cancel outside
  the 600 ms echo window (lines 114-120), by hands on (EPAS_handsOnLevel 3), an EPAS refusal (EPAS_eacStatus 0 with error code
  6-9) or EAC_FAULT (EPAS_eacStatus 3) (lines 46-59), and by a safety-mode init (lines 273-274). Only a new pull arms it again.
  A gas press does not disarm it. While hands are on or the EPAS is refusing, ANGLE is also rejected (lines 217-219). Angle rate
  limits and the 360 degree cap still apply (lines 199-223).
  Note: the comment at `tesla_preap.h` lines 76-77 says hands on and an EPAS refusal do not disarm the latch; the code at
  lines 54-59 does disarm on both. This entry describes the code.
- Why: the Model S has no brake control, so a brake press should stop the pedal without also taking the wheel away. A gas press
  after a brake tap used to disarm the latch while openpilot still showed engaged, silently blocking steering for 34 s; gas has
  no bearing on steering and the pedal has its own gas rule (`tesla_preap.h` lines 29-38; `docs/tesla/PREAP_PORT.md` lines 84-96).
- Safety-relevant: yes. Condition by condition, against NAP and `bogpilot-na-preap`:
  - Brake sampling: stricter. BrakeMessage (0x20A) driverBrakeStatus != NOT_APPLIED or DI_torque2 (0x118) DI_brakePedal sets
    `brake_pressed` (lines 158-165); the references force it false.
  - `controls_allowed` on a brake: stricter. It is cleared as above; in the references a brake never clears it.
  - Steering through a brake: same outcome as NAP (which keeps `controls_allowed`), reached by a bounded steer-only exception
    after `controls_allowed` is cleared.
  - Bound on that exception: the 1 s freshness, lag, unseen streams, gear, doors, cancel, hands on, EPAS refusal and EAC_FAULT.
  - Enabled 0x551 during a brake: stricter. Rejected while the brake is pressed, and capped at raw 2500.
- Tests: `opendbc_repo/opendbc/safety/tests/test_tesla_preap_brake_steer.py` (`test_brake_press_keeps_steering_and_blocks_the_pedal`,
  `test_held_brake_for_seconds_keeps_steering_while_streams_stay_fresh`, `test_cancel_disarms`, `test_hands_on_disarms_the_brake_latch`,
  `test_epas_refusing_disarms_the_brake_latch`, `test_epas_fault_disarms`, `test_leaving_drive_disarms`, `test_door_open_disarms`,
  `test_stale_stream_disarms`, `test_gas_press_does_not_disarm`, `test_safety_mode_change_removes_the_permission`,
  `test_model_3_y_and_ap1_still_lose_steering_on_a_brake_press`); `test_tesla_preap_pedal_brake.py` (the pedal side).
- Credits: BogPilot (this port). NAP, BogPilot `bogpilot-na-preap` and Tinkla/BogGyver were compared; none has this latch.

## Panda safety (Pre-AP): optional Bosch radar gateway, off by default
- Platforms: Pre-AP Model S only (`TESLA_FLAG_PREAP` on SAFETY_TESLA, `opendbc_repo/opendbc/safety/modes/tesla_preap.h`
  and `tesla_preap_radar.h`). AP1 and stock Tesla modes ignore flags 128 and 256.
- Reference behavior: NAP (opendbc `cc39c7fa`) `opendbc/safety/modes/tesla_preap.h` (`tesla_preap_gtw_emulation`,
  lines 183-316, called from `.rx_all` at line 635) gateways a fixed list of chassis frames from bus 0 onto bus 1
  when its radar-emulation flag is set, and synthesizes DI_espControl (0x1A9, length 5) and ESP_wheelSpeeds
  (0x169, length 8) on bus 1 only. The behind-nosecone flag only sets GTW_carConfig radar_position. NAP does not
  put those synthetics on bus 0, does not whitelist radar IDs for host TX, and does not blanket-forward bus 0 to
  bus 1. Tinkla/BogGyver (panda `f7751e4`) has a radar-emulation path that also injects 0x1A9 on bus 0 and includes
  VIN-learn and diagnostic forwarders. BogPilot 0.9.7 has no Pre-AP radar flag.
- Our behavior: two flags on SAFETY_TESLA, numbered as NAP `TeslaSafetyFlags` (no new safety ordinal): 256
  (`TESLA_FLAG_PREAP_RADAR_EMULATION`) and 128 (`TESLA_FLAG_PREAP_RADAR_BEHIND_NOSECONE`). Flag 256 is applied only
  in Pre-AP init. Flag 128 without 256 is a no-op. When 256 is set, `tesla_preap_radar_rx_all` repeats the NAP map
  onto bus 1: 0x45 to 0x219, 0x108 to 0x109, 0x145 to 0x149, 0x20A to 0x159, 0x308 to 0x209, 0x30A to 0x2D9,
  0x405 to 0x2B9 (VIP_405HS on bus 1, not DAS_control), patched 0x398 to 0x2A9, 0x0E to 0x199, plus the 0x115 to
  0x129 and 0x118 to 0x119 re-addresses and the two synthetics on bus 1. Patches, checksums and the 0x169 speed
  formula follow NAP `cc39c7fa` line-for-line. Frames are sent with `can_send(..., bus 1, skip_tx_hook=true)`, so
  they are firmware TX, not host TX. The host TX allowlist is unchanged: still no bus-0 0x2B9, and no radar IDs.
  `disable_forwarding` stays true; `tesla_fwd_hook` still returns -1. Park-ultrasonic 0x32E / 0x33E are not copied.
  Flags off leave the hooks byte-identical to today.
- Deliberately not copied: Tinkla's bus-0 synthetic 0x1A9; Tinkla / NAP VIN-learn; any UDS or diagnostic forwarder;
  a blanket 0-to-1 or 1-to-0 forward; NAP's 0x631 / 0x300 radar-status machine (informational, not on the gateway
  list); Tinkla's FLAG_TESLA_NEED_RADAR_EMULATION bit 32, which is already `TESLA_FLAG_PREAP` here.
- Why: a Bosch radar retrofit on the Pre-AP Model S needs the same chassis view NAP already builds on bus 1. Off
  remains the default, so a car without the retrofit is unchanged.
- Safety-relevant: yes, but only when flag 256 is set. The added bus-1 traffic is one rewritten frame per source
  (plus one synthetic on 0x115 and 0x118). Known source rates (0x45 at 10 Hz, 0x108 at 100 Hz, 0x20A at 50 Hz,
  0x118 at 100 Hz plus its synthetic) are 360 frames/s; even if every other mapped ID were also 100 Hz, the total
  would stay around 1160 frames/s, well under the 16000 irq/s interrupt-rate cap on that bus. The firmware still
  does not clear a sticky interrupt-rate fault until reboot.
- Tests: `opendbc_repo/opendbc/safety/tests/test_tesla_preap_radar.py` (flag off, flag 128 alone, flag 256 mappings
  and bytes, behind-nosecone, one TX per source, no bus-0 frames, allowlist unchanged, bus-0 0x2B9 still blocked,
  0x32E not forwarded, flags ignored without PREAP). Existing `test_tesla_preap.py`,
  `test_tesla_preap_brake_steer.py`, `test_tesla_preap_gas_threshold.py` and `test_tesla_preap_pedal_brake.py`
  stay on the flag-off param.
- Credits: NAP (opendbc `cc39c7fa`); Tinkla/BogGyver compared, not copied for the items listed above.


## Pre-AP car port: Bosch radar retrofit toggles (host half), off by default
- Platforms: Pre-AP Model S only. AP1 Model S / Model X ignore both keys (rows hidden, CarParams unchanged).
- Reference behavior: NAP (openpilot `e99f4dc75`, opendbc `cc39c7fa`) has `NAPRadarEnabled` and
  `NAPRadarBehindNosecone` (`common/params_keys.h:147-148`), shown as "Radar Enabled" / "Radar Behind Nosecone",
  offroad only, reboot to apply (`selfdrive/ui/layouts/settings/nap.py:160-175`). Its Pre-AP interface sets
  `radarUnavailable = not radar_enabled` (`opendbc/car/tesla/preap/interface.py:54`) and ORs the emulation and
  nosecone flags independently (`:46-49`); its Bosch radar faults on `RADC_HWFail` only (`opendbc/car/tesla/radar_interface.py:86-88`).
  Tinkla/BogGyver (`501c7de`) uses `TinklaUseTeslaRadar` (`selfdrive/car/interfaces.py:262`), `radarOffCan` for
  PREAP (`selfdrive/car/tesla/interface.py:125-126`), and ignores SGUFail on PREAP and SensorDirty behind the
  nosecone (`selfdrive/car/tesla/radar_interface.py:89-111`). BogPilot 0.9.7 (`04d560f3`) has no Pre-AP radar.
- Our behavior: two file-backed keys under the BogPilot params dir, both default off: `TeslaRadarEnabled` and
  `TeslaRadarBehindNosecone` (`tesla_ap1/preap/params.py`). Vehicle Settings shows "Pre-AP: Bosch Radar" on Pre-AP
  only, and "Pre-AP: Radar Behind Nosecone" only while the radar toggle is on; both are offroad edits and take
  effect the next time the car starts. With the radar toggle on, `radarUnavailable` is false, the Bosch parser
  reads bus 1 (`tesla_radar_bosch_generated`), and the safety param gains 256 (plus 128 only when the nosecone
  toggle is also on), through `flags_for_preap` (panda half above). Radar leads then feed radard, the pedal
  planner and Human-Like Following (still the driver's Following toggle). With the radar on at car start, Human-Like
  Following and Human-Like Lane Changes default On (maintainer decision; unset values only, a saved Off is kept, nothing
  is written to Params); with it off both are effectively Off. Toggle off: CarParams bytes and the safety param (96 / 32) are identical to the build before.
- Divergences from NAP: (1) the nosecone bit is only sent with the radar bit (NAP sends it on its own; the panda
  ignores it without 256 anyway). (2) Fail closed when the radar is silent: with the toggle on and no radar cycle
  for 0.5 s, the radar interface publishes canError at 20 Hz instead of nothing, so radarState goes invalid and
  openpilot will not engage (radar CAN error / commIssue). NAP returns nothing until the radar answers.
  (3) Radar status faults (maintainer decision): Pre-AP ignores `RADC_SensorDirty`, following NAP; Tinkla faults on it
  unless the radar is behind the nosecone; `RADC_HWFail` remains the only fault. NAP's Bosch rule is HWFail-only
  on every car (`opendbc/car/tesla/radar_interface.py:85-88` @ `cc39c7fa`). Tinkla faults on HWFail, on SGUFail
  except on PREAP, and on SensorDirty unless PREAP with the radar behind the nosecone
  (`selfdrive/car/tesla/radar_interface.py:89-111` @ `501c7de`). Here Pre-AP faults on HWFail only, so SGUFail and
  SensorDirty never fault, nosecone or not (`opendbc_repo/opendbc/car/tesla_ap1/radar_interface.py`); AP1 keeps
  HWFail, SGUFail and SensorDirty. A CAN error or a silent radar still fails closed as in (2).
- Backup and resets (maintainer decision): both keys are in the durable settings backup and Toggle Backups (restore),
  and are not in Reset to Stock or Reset to Defaults, so a reset never turns the retrofit off.
- Why: drivers moving from NAP have the retrofit; off by default leaves every other Pre-AP car unchanged.
- Safety-relevant: yes when on (radar leads drive the pedal planner). No host TX added; the panda gateway is
  firmware TX on bus 1. No VIN learn, no UDS.
- Tests: `opendbc_repo/opendbc/car/tesla_ap1/tests/test_preap_bosch_radar.py`,
  `openpilot/system/bogpilot/tests/test_preap_radar_backup_reset.py`, and radar cases in
  `test_phase3_system_feature_archive.py`, `test_phase3_system_utilities.py` and `test_preap_pedal_cal.py`.
- Credits: NAP (openpilot `e99f4dc75`, opendbc `cc39c7fa`), including the HWFail-only radar fault rule
  (`opendbc/car/tesla/radar_interface.py:85-88` @ `cc39c7fa`); Tinkla/BogGyver (`501c7de`) compared, including its
  PREAP SGUFail / nosecone SensorDirty rule (`selfdrive/car/tesla/radar_interface.py:89-111` @ `501c7de`).


## Human-Like Lane Changes: onroad toggle and lane-change runtime disagree below Advanced (known item)
- Platforms: every car with radar and openpilot longitudinal control (AP1 Model S, Pre-AP Model S with the Bosch
  radar retrofit on). Pre-existing; not changed by this build.
- Reference behavior: BogPilot 0.9.7 reads `HumanLaneChanges` above the tuning level gate, so its registry default On
  applies at every level (`frogpilot/common/frogpilot_variables.py:1003` @ `04d560f3`).
- Our behavior: the onroad toggle (`openpilot/common/bogpilot_onroad_toggles.py`, the :1003 line) follows 0.9.7 and
  has no tuning-level or adoption-marker gate, so it reads On at the Minimal and Standard levels (L0/L1). The
  lane-change runtime and the panel row (`read_settings`, `openpilot/selfdrive/controls/lib/phase3_lanechange.py`)
  only honour the row at Advanced, Developer or an unconfirmed level, so at L0/L1 they read Off. The onroad value
  only decides whether radard tracks the adjacent leads (`leadLeft` / `leadRight`); lane-change lead choice follows
  `read_settings`. The AP1 Model S and a Pre-AP Model S started with the Bosch radar on default On in `read_settings`;
  other cars need a row change (adoption marker).
- Why: left as is so no driver-visible behavior changes outside the requested Pre-AP default; the onroad line is
  shared by every car.
- Safety-relevant: no. It only changes which radar tracks are computed and shown, not steering, gas or brake limits.
- Tests: `openpilot/selfdrive/controls/tests/test_preap_radar_human_lane_changes.py` (180-case matrix: changes only
  on Pre-AP with the radar on).
- Credits: BogPilot 0.9.7 (`frogpilot_variables.py:998` and `:1003` @ `04d560f3`).


## Onroad UI: Blind Spot Border alone controls the red blind-spot half-border
- Platforms: AP1 Model S only, the one car whose carstate fills blind spot data (`bsm_state.has_bsm`); onroad UI
  only. AP1 Model X and Pre-AP never paint the blind-spot half.
- Reference behavior: BogPilot 0.9.7 painted the blind-spot half red only when both the parent `BorderMetrics`
  ("Border Metrics") and `BlindSpotMetrics` were on, or `DebugMode` (`frogpilot/common/frogpilot_variables.py:885`,
  `frogpilot/ui/qt/onroad/frogpilot_onroad.cc:24` @ `04d560f3`).
- Our behavior: `BlindSpotMetrics` ("Blind Spot Border") alone decides, on a car that reports blind spot data, or
  `DebugMode` (`openpilot/selfdrive/ui/onroad/bogpilot/hud_compose.py`). The separate Status Border row and its help are
  gone from Visuals, and Blind Spot Border is a top-level row. `BorderMetrics` stays registered with its default; a
  stored value is left in place and unread (no migration, no delete), and backups, restores, Reset to Defaults and
  Reset to Stock still carry and reset it as before. The green engaged, gray override, dark blue disengaged, Traffic
  Mode red and flashing lane-keep fault borders are unchanged.
- Why: one switch for one visible effect; the parent row only gated the blind-spot half.
- Safety-relevant: display only. The lane-keep fault border, full-screen alerts and critical alerts still take the
  whole border over the blind-spot half. Lane-change blocking on blind spot data is unchanged.
- Tests: `openpilot/selfdrive/ui/onroad/bogpilot/tests/test_border_dm_button.py`,
  `openpilot/selfdrive/ui/tests/test_phase2_visuals_theme.py`, `openpilot/selfdrive/ui/tests/test_bogpilot_nesting.py`,
  `openpilot/system/bogpilot/tests/test_toggle_reset.py`, `openpilot/selfdrive/ui/tests/test_phase3_system_feature_archive.py`
  and `openpilot/selfdrive/ui/bogpilot/tests/test_phase3_system_utilities.py`.
- Credits: BogPilot 0.9.7 for the blind-spot half-border; dropping its parent switch is a BogPilot UI decision.

## Onroad UI: confidence ball on the big (C3X) driving screen
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

## Onroad UI: confidence ball drawn under alerts
- Reference behavior: BogPilot 0.9.7 raises the ball widget above `OnroadAlerts` (`onroad_home.cc`, `confidence_ball.h`
  `raise()`), so it can cover the edge of a full-screen alert.
- Our behavior: every alert paints over the ball, and the ball is hidden while a full-screen alert is showing.
- Why: IC/onroad changes must never hide stock alerts. Stricter than the reference.
- Safety-relevant: yes; stricter.
- Tests: `test_confidence_ball.py` (view order, full-alert order).
- Credits: BogPilot 0.9.7.

## Settings: confidence ball rows
- Reference behavior: BogPilot 0.9.7 has one Off / Left / Right control (`frogpilot/ui/qt/offroad/visual_settings.cc`).
- Our behavior: two rows at the top of Appearance, "Confidence Ball" (on/off, default on) and "Confidence Ball Side"
  (Left / Right, default Left), same files `/data/params_bogpilot/ConfidenceBall` and `ConfidenceBallSide`;
  reset returns the side to Left.
- Why: raylib list items have no three-way row.
- Safety-relevant: no.
- Tests: `test_confidence_ball.py`, `openpilot/selfdrive/ui/tests/test_bogpilot_nesting.py`.
- Credits: BogPilot 0.9.7.

## Onroad UI: confidence ball edge switch
- Reference behavior: BogPilot 0.9.7 moves the ball to the other edge while the map panel covers its side.
- Our behavior: 0.11.2 has no map panel here; the ball moves to the other edge while a blind-spot flame track burns on
  its side, and hides if both sides burn.
- Why: never paint over a flame track.
- Safety-relevant: no.
- Tests: `test_confidence_ball.py`.
- Credits: BogPilot 0.9.7.

## Onroad UI: confidence ball always shown, engaged palette only while engaged
- Reference behavior: stock (`mici/onroad/confidence_ball.py`) and BogPilot 0.9.7 (`confidence_ball.h`) drive the ball to
  -0.5 while disengaged, so it slides out below the screen; 0.9.7 keeps the widget visible but the ball is off screen.
  0.9.7 uses the engaged palette for every status except disengaged / override.
- Our behavior: shown in every state while the toggle is on; the height always follows the model. The engaged palette
  (green / orange / red) is used only while ENGAGED. OVERRIDE uses the stock white-to-grey ball and DISENGAGED a
  slate-to-white ball, so the colour never reads as openpilot active; engagement is shown by the border. Missing
  model data: bottom position, stock red while engaged, white while disengaged.
- Why: maintainer request (always visible), with the colour rule required by the safety review.
- Safety-relevant: display only; no control path reads it.
- Tests: `test_confidence_ball.py` (always shown, never engaged palette when not engaged).
- Credits: comma.ai openpilot (MIT); BogPilot 0.9.7.

## Onroad UI: disengaged confidence ball goes from slate grey to white
- Reference behavior: stock (`mici/onroad/confidence_ball.py:72-74`) and BogPilot 0.9.7 (`confidence_ball.h:123`) draw
  the disengaged ball in one fixed dark gradient, (50,50,50) to (13,13,13), whatever the confidence; only its height moves.
- Our behavior: the DISENGAGED ball is one flat colour that follows the smoothed confidence x: slate grey (112,128,144)
  at x >= 1, white (255,255,255) at x <= 0, and a straight per-channel blend in between, rounded per channel
  (`confidence_ball_logic.disengaged_color`). Each channel only gets darker as confidence rises. ENGAGED (green / orange /
  red) and OVERRIDE colours are unchanged; any other status keeps the stock dark ball.
- Why these values: slate grey is the standard named colour "SlateGray". It is a blue grey, the same family as the
  disengaged border `BORDER_COLORS[DISENGAGED]` (18,40,57) in `augmented_road_view.py`, and much lighter, so the ball
  still stands out on the border. No slate constant exists in the tree; the nearest stock grey, `COLORS.DISENGAGED`
  (145,155,149) in `hud_renderer.py`, is a lighter green grey and would leave less room between the two ends. White at low
  confidence makes the low end the brightest and easiest to notice. Shaded top to bottom like stock: the bottom colour
  is the top colour times 82/255 per channel (`confidence_ball_logic.shade`), the ratio of the stock OVERRIDE ball,
  (255,255,255) to (82,82,82) (`mici/onroad/confidence_ball.py:68-70`, drawn by `draw_circle_gradient` at `:10-13`).
  Maintainer choice after comparing flat and shaded renders. At confidence 0 the disengaged ball therefore has the same two
  colours as the OVERRIDE ball; the border still tells the two states apart.
- Why: requested UI change (confidence readable while disengaged); display only.
- Safety-relevant: display only; no control path reads it. Neither end is in the engaged palette.
- Tests: `test_confidence_ball.py` (TestDisengagedSlateToWhite: slate at high, white at low, monotonic, engaged colours
  unchanged; the native pixel test checks the drawn colour).
- Credits: comma.ai openpilot (MIT); BogPilot 0.9.7.

## Settings: gated list_view actions
- Platforms: all (settings UI only).
- Reference behavior: stock v0.11.2 dual- and multiple-button list actions stay enabled and accept taps even when the row is locked.
- Our behavior: UI gated actions subclass the stock dual- and multiple-button actions. Their stock classes in `list_view.py` (and the other stock action classes) are unchanged from v0.11.2 `f7db927c7`; BogPilot's edits to that file are in `ListItem` and `button_item` only: a help key, a Tuning Level gate and an indent on `ListItem`, the inline description closes when the row is hidden, icons load on first draw and a missing icon file draws nothing, the title clip leaves room for the icon, and `button_item` takes an optional icon. Locked rows are dimmed and ignore taps. The SLC and weather choice rows re-read the stored value. Unlocked rows behave as stock. Locked writes are still refused onroad by the existing editor checks.
- Why: locked BogPilot settings rows should look and act locked, without changing the stock list widget.
- Safety-relevant: no. UI only; no control or panda path.
- Tests: `openpilot/selfdrive/ui/tests/test_bogpilot_gated_actions.py`.
- Credits: stock v0.11.2; the locked-row audit of the previous release baseline. Full write-up: `docs/tesla/UI_GATED_ACTIONS.md`.
- Value rows: the shared value row adds a grey default hint, a changed-value highlight and one confirmed "Reset section to defaults" row per section, built on the same gated actions. Credits: BogPilot Alert Volume row and stock v0.11.2 `list_view.py` / `confirm_dialog.py`. See "Value rows" in `docs/tesla/UI_GATED_ACTIONS.md`.
- Steering Tuning: no per-row RESET. The Advanced and Quality of Life section Resets write the whole section back: the value rows to their defaults (numeric defaults from `numeric_rows`; `PauseLateralSpeed` default 0), then the section's toggles (Force Auto-Tune Off / On; Turn Signal Only) and its switch (`AdvancedLateralTune` off, `QOLLateral` on) to their shipped defaults, the switch last, with a car-type profile value used where that profile sets one (`phase3_steering_tuning.py:266-291`). Override Sensitivity is in neither section and has no reset. The unlabeled level-0 -/+ row for Pause Steering Below is hidden. Credits: BogPilot and stock v0.11.2. Details in `docs/tesla/UI_GATED_ACTIONS.md`.

## Cluster / DBC: AP1 AutopilotStatus (0x399) bits 27-36 follow BogPilot, not Tinkla
- Platforms: AP1 and pre-AP (legacy `tesla_ap1_can.dbc` `AutopilotStatus`, address 921 / 0x399, DLC 8).
- Reference behavior: BogPilot bogpilot-tesla `04d560f3` and na-preap `568fea947` `tesla_can.dbc:669` `AutopilotStatus` are byte-identical to this tree's `tesla_ap1_can.dbc:674` (every start|len@endian, sign, scale, and signal name; packing at `:675-700`). In bits 27-36 that layout is `DAS_summonFwdLeashReached` 28|1, `DAS_summonRvsLeashReached` 29|1, `DAS_sideCollisionAvoid` 30|2, `DAS_sideCollisionWarning` 32|2, `DAS_sideCollisionInhibit` 34|1, `DAS_csaState` 35|2 (all Intel `@1+`). Tinkla opendbc `9c0b6fe3` `tesla_can.dbc:649` uses the same address under the name `DAS_status`, but bits 27-36 differ (`DAS_lssState` 29|3, shifted side-collision, and no `DAS_csaState` at 35|2).
- Our behavior: the port follows the BogPilot / na-preap `AutopilotStatus` packing, not the Tinkla mid-frame packing, and not Model 3/Y `DAS_status` at 0x39b.
- Why: keep the legacy 0x399 cluster status layout that matches both BogPilot revisions.
- Safety-relevant: yes; cluster status, side-collision, and CSA bits.
- Tests: no automated test covers bits 27-36; the layout was compared against the cited DBC lines.
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
- History: it had its own divergence note and tests, which were removed with it.

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
- Upgrades: the profile writes once per device (`LegacySlcDefaultsApplied2` marker) and only keys still at the table default (or the settings UI's km/h conversion of it). A device from an earlier build has only the earlier `LegacySlcDefaultsApplied` marker (it was offered the priorities and look-ahead only): it is offered the keys added since (Offset1-7 and Override) once, with the same still-at-default rule, and its priorities and look-ahead are left as they are. A device with the new marker keeps its current values; Reset BogPilot Settings clears both markers, so the next start applies the whole profile again. Known limit: a driver who explicitly picked the table value of an added key (for example Override 1, gas latches) after the earlier build cannot be told apart from an untouched device and is moved to the profile value once.
- Why: the AP1 speed settings are known to work well and Pre-AP uses the same SLC.
- Safety-relevant: no; settings defaults only. Car code and panda are unchanged.
- Tests: `openpilot/selfdrive/ui/tests/test_slc_legacy_profile.py`, `openpilot/selfdrive/ui/tests/test_slc_ap1_section_reset.py`.
- Credits: BogPilot bogpilot-tesla `367e1fe` (AP1 profile speed values).

## Pre-AP Model S Speed Limit Controller page without the map source rows
- Platforms: Pre-AP Model S with the pedal (`TESLA_PREAP_MODELS` with openpilot longitudinal control). AP1 Model S keeps its page unchanged; AP1 Model X has no openpilot longitudinal control and gets no page.
- Reference behavior: BogPilot 0.9.7 (`04d560f3`) shows every Speed Limit Controller row, including the source priority and look-ahead rows, by tuning level only; the one car-dependent row is Match Speed Limit on Engage, hidden with stock cruise control (`frogpilot/ui/qt/offroad/longitudinal_settings.cc:966-1048`, `:984-985`).
- Our behavior: the page is mounted on Pre-AP with the pedal (`slc_page_supported` in `openpilot/selfdrive/ui/bogpilot/phase3_gas_brake_mounts.py`) with its switch, Fallback Speed, Override Speed, Speed Limit Offsets, Quality of Life (including Match Speed Limit on Engage) and Visual Settings. Priority 1-3 and Look-ahead are hidden there (`CAR_GATED` / `car_row_allowed` in `openpilot/selfdrive/ui/layouts/settings/phase3_speed_control_settings.py`): the dashboard limit is the only source on Pre-AP and there is no map look-ahead, so those rows would change nothing. Saved values are kept. Turning the switch off stops the controller on Pre-AP (onroad toggle `speed_limit_controller`); the one-time legacy SLC profile never writes the switch.
- Why: the controller is on by default on Pre-AP, so it needs a page to turn it off; rows that do nothing there are not shown.
- Safety-relevant: no; settings page only. Planner, car code and panda are unchanged.
- Tests: `openpilot/selfdrive/controls/tests/test_gas_brake_mounts.py`, `openpilot/selfdrive/ui/tests/test_phase3_speed_control_settings.py`.
- Credits: BogPilot 0.9.7 (`04d560f3`, the Speed Limit Controller rows).

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
- Our behavior: `epas_gate.EpasTmpFaultRecovery` (every rule in that one class). A code 4 that appears while the EPAS is ACTIVE still drops lateral on that frame, as before. Only while openpilot is engaged, latActive is off, the EPAS has reported AVAILABLE with code 4 for 0.5 s in a row (settle: the recorded event went ACTIVE, INHIBITED, then AVAILABLE within 120 ms), hands are below level 2, the driver is not overriding, there is no EAC_FAULT, the car is moving at 2.2 m/s (about 5 mph, `MIN_ERR4_PROBE_SPEED`) or more, and a 0x214 EPB_epasEACAllow of 1 arrived within the last 200 ms (`ERR4_EPB_FRESH_FRAMES`; a car without 0x214, or with a stale one, gets no request and behaves as before; elsewhere in this port 0x214 stays optional): send ANGLE at the measured wheel (the existing soft-start hold, rate limited and clipped to the measured wheel +/- 20 deg, never the planner angle) for at most 0.3 s, then wait 2 s and settle again; a request never starts less than 2 s after the previous one started, whatever its result (a cleared request included); at most 3 requests per engagement, counted again from zero on the next engagement. A refusing status (INHIBITED, FAULT, SNA), hands at level 2 or more, a driver override, EPB allow other than 1 or a stale 0x214, vEgo below 2.2 m/s, EAC_FAULT or any error code other than 4 and IDLE ends the request on that frame. If the EPAS clears to IDLE, the hold continues until latActive returns and the normal path resumes through the engage soft-start. Code 4 stays a temporary fault, so lateral is never resumed while the code is set. Each request and its result (cleared, timeout, abort reason) is logged.
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
- Superseded: Conditional Experimental Mode is now removed on every car (entry "Conditional Experimental Mode removed" below); these writes still run and stay harmless.

## pandad.py cold start: polled wait, reflash only when needed, "Connecting to panda..." alert
- Platforms: all car types (the panda wrapper `openpilot/selfdrive/pandad/pandad.py` before `./pandad` starts).
- Reference behavior: upstream openpilot 0.11.2 `selfdrive/pandad/pandad.py` resets the internal panda, gives it 1 s to enumerate (`Panda.wait_for_panda(None, timeout=1)`), and if it is not found, or is in its bootstub or on other firmware, recovers it through DFU and reflashes it, then loops with another reset at once. No timing is logged and nothing is shown to the driver while it loops.
- Our behavior: the first look polls (every 0.1 s, the same `Panda.wait_for_panda`) for up to 10 s, later looks for up to 3 s, with a 0.5 / 1 / 2 / 4 s backoff between attempts. A panda that is found in its bootstub, on other firmware, or that cannot be read is reflashed at once, as upstream. A panda that is not found at all is recovered through DFU only after 3 misses in a row, so a dead panda is still recovered. Each step (reset, wait, flash, ready) is logged with its time and the total since the start (`pandad.timing`). The offroad alert "Connecting to panda..." (`Offroad_ConnectingPanda`) is shown once the panda has not answered within 6 s (`ALERT_AFTER_S`), or while a reflash or retry runs, and cleared as soon as it is ready. The car fingerprinting and VIN query are unchanged.
- Why: on some cold power-ups the wrapper took 27 s to 88 s before `./pandad` started (normally under 1 s), so the device stayed offroad. The step that took the time was not logged; the 1 s give-up followed by a DFU reflash is the most likely cause, so the wait is longer, the reflash is limited to the cases that need it, and every step is now timed.
- Alert time: `ALERT_AFTER_S` was 2 s, which showed the alert on 16 of 82 measured AP1 boots, 8 of them normal starts. The 82 boots are one AP1 car, 67 on 0.9.7 and 15 on 0.11.2; the 8 normal starts over 2 s were all on 0.9.7, and on 0.11.2, 12 of the 15 boots started in 0.78 s or less while the other 3 were slow cold power-ups (27 s to 88 s). Measured from the wrapper start to the `./pandad` start (the reset and firmware check included): p50 0.72 s, p90 2.98 s, then nothing between 3.02 s and 7.51 s; the 8 longer ones are the slow cold power-ups above (p95 26.7 s, p99 82.0 s, max 87.7 s). 6 s is twice the slowest normal start and still below the quickest slow one. Since the 3 s retry looks end before 6 s, a retry is one poll; the alert is already on by then (every retry sets it).
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

## AP1 dashboard speed limit: a rise the car's base map does not know is checked against the camera limit
- Platforms: AP1 Model S and AP1 Model X (`opendbc/car/tesla_ap1/carstate.py`, `opendbc/car/tesla_ap1/speed_limit.py`). Pre-AP is unchanged (no Mobileye, four-argument call).
- Reference behavior: BogPilot 0.9.7 (`selfdrive/car/tesla/speed_limit.py:98-111`, `selfdrive/car/tesla/carstate.py:220-224`) fills the dashboard limit from Mobileye `DAS_fusedSpeedLimit` first, then GTW `UI_mapSpeedLimit`, then `UI_mppSpeedLimit`, with a check only for a fused limit far above the map. Tinkla/BogGyver and NAP read the same fields with no further check. None of them reads `DAS_visionOnlySpeedLimit` or `UI_baseMapSpeedLimitMPS`.
- Signals: `DAS_visionOnlySpeedLimit` (AutopilotStatus 0x399, 16|5, factor 5, 31 = NONE, 0 = UNKNOWN_SNA) and `UI_baseMapSpeedLimitMPS` (UI_driverAssistRoadSign 0x238, multiplexor `UI_roadSign` 3, 8|8, factor 0.25 m/s), both already in `tesla_ap1_can.dbc` (`:682`, `:584`), the same definitions as BogPilot 0.9.7 `opendbc/tesla_can.dbc:677` and `:584` and Tinkla/BogGyver opendbc `9c0b6fe3` `tesla_can.dbc:657` and `:349`. Both were present and live in a recorded AP1 Model S drive.
- Previous behavior here: as in 0.9.7. A recorded drive had the GTW map / mpp limit and then the fused limit go from 25 to 55 while the base map limit read 0 (the map did not know the road) and the camera-only limit still read 25. The dashboard limit became 55 and SLC raised the target to 55 + offset (62 mph) at once; with a car-reported 55 the previous-limit fallback never applies.
- Our behavior: carstate also reads `DAS_visionOnlySpeedLimit` (from the fused frame, stale = no camera limit) and `UI_baseMapSpeedLimitMPS` (only from frames whose `UI_roadSign` is 3; the parser decodes every multiplexed signal of every frame). The base map counts as unknown when it reads 0 or no mux 3 frame arrived within `LIMIT_MAX_AGE_S` (3 s; mux 3 arrives about 2.5 times a second). With the base map unknown, `dashboard_speed_limit_ms`:
  - returns the camera limit when the fused / map candidate is more than 10 mph (15 km/h) above a valid camera limit (`VISION_RISE_TOL_MPH` / `_KPH`). The camera limit is used rather than 0 (unknown) because 0 hands the choice to the SLC fallback setting, and the fallbacks other than Previous Limit go back to the set speed or Experimental Mode, which can be higher; the camera limit is the lower, car-confirmed value with any setting;
  - with no camera limit, ignores a value that comes only from the GTW map / mpp: the limit published on the previous step is kept, except that a lower map value is taken at once. With nothing published yet (0), the map value is taken as before, never 0;
  - leaves a candidate at or below the camera limit, or within the tolerance, unchanged. A lower limit always wins.
  With the base map known (> 0) the result is the previous one. A car that never sends a mux 3 frame in the drive keeps the previous result (the guard needs the base map to have been seen), so a car without that frame does not lose map-only limits. The engage set (pull at limit + offset) uses the same guarded value.
- Never-sent base map, kept lenient on purpose: treating a car that never sends 0x238 mux 3 as "base map unknown" would be stricter, but it would change the dashboard limit on such a car (map-only limits would be held or dropped) with no request for that change, and no AP1 Model X drive log is available to check how often that frame is missing there. Only a base map that the car has sent in the drive and that then reads 0 or goes stale turns the guard on.
- Why: a map default of 55 that the car's own base map called unknown, and that the camera contradicted, raised the set by 37 mph with no driver action.
- Safety-relevant: yes (planner speed target). Stricter than 0.9.7, Tinkla and NAP: the result is never above the previous rule's, and never 0 (no limit, which hands over to the SLC fallback) where the previous rule has a limit. No planner, panda, safety, TX or cereal change.
- Tests: `opendbc/car/tesla_ap1/tests/test_ap1_speed_limit_base_map_guard.py` (function rules, unchanged four-argument callers over an input grid, real CANParser frames on Model S and X, staleness, other mux frames), `openpilot/selfdrive/controls/tests/test_phase3_slc_base_map_guard.py` (real CarState into Ap1SpeedControl: at or below 30 mph; the same frames without the guard reproduce 62; a real-Params variant).
- Credits: BogPilot 0.9.7 and Tinkla/BogGyver (DBC definitions, source order and the fused-over-map check).

## Steering: Override Sensitivity ships at 2, one step firmer than the unscaled level 3
- Platforms: AP1 Model S, AP1 Model X, Pre-AP Model S (the only cars with the row).
- Reference behavior: earlier builds of this port shipped level 3, the level whose numbers are the detector constants
  (`override.py`: fire torque 2.0 Nm, torque with a fast wheel 1.0 Nm, fire rate 30 deg/s, release 1.0 Nm / 30 deg/s).
- Our behavior: the default (`SENSITIVITY_DEFAULT`, `preap/params.py` DEFAULTS) is 2: scale 1.125, fire torque 2.25 Nm,
  torque with a fast wheel 1.125 Nm, fire rate 31.875 deg/s, release 1.125 Nm / 31.875 deg/s. A missing or bad saved value
  is also 2. What each level 1 to 5 means is unchanged (level 3 is still the unscaled numbers), and so are the clamps, the
  hands flag, the angle error signal, the debounce counts and the panda limits; the panda does not read this setting.
- Saved values: the setting is a file and no install profile, section Reset or full Reset writes it, so a device that
  already saved a level (3 included) keeps it; only a device without the file reads the new default. No migration.
- Why: requested default change.
- Safety-relevant: driver override detection only; a higher torque threshold means a slightly firmer push to take over
  (2.25 Nm, inside the existing 1.5 to 2.5 Nm clamp; level 1 already allowed 2.5 Nm).
  The EPAS hands-on flag still counts as a takeover at any level, and the panda steering limits are unchanged.
- Tests: `test_override_sensitivity.py`, `test_ap1_override_detector.py`, `test_override_sensitivity_row.py`,
  `test_override_sensitivity_default_paths.py`.
- Credits: BogPilot (driver-override detector).

## Sidebar: the onroad Vehicle Online box can show CPU instead
- Platforms: all (UI only).
- Reference behavior: onroad, the sidebar's middle box is the vehicle status (VEHICLE ONLINE, or NO PANDA in red) and
  cannot be changed; CPU usage is only on the offroad sidebar, so CPU and RAM cannot both be seen while driving.
- Our behavior: tapping that onroad box switches it between the vehicle status (default) and CPU, and back. CPU is the
  same reading and look as the offroad CPU box: mean of the per-core `cpuUsagePercent` values, white below 70 %, yellow
  from 70 %, red from 85 %, gray "--" on stale data (`sidebar_metrics.py` `_usage` / `device_readings`). The choice is the
  file `SidebarVehicleSlot` ("vehicle" or "cpu"; a missing or unknown value is "vehicle"), read with the other sidebar
  metrics, not every frame. NO PANDA always takes the box back, whatever was chosen, so a missing panda is never hidden.
  While NO PANDA shows, a tap on the box is ignored and the file is not written; when the panda is back the box shows
  the saved choice again, and taps switch it as before.
  Offroad and the default onroad sidebar are unchanged (the default render is pixel-identical).
- Saved values and resets: the full Reset (stock and shipping tables, the Utilities reset) writes "vehicle", and the
  settings backup covers the file. The sidebar has no menu rows, so no section Reset owns it, as with the other
  tap-to-choose sidebar boxes; the AP1 install profile and the legacy speed-limit fill never write it, so a device without
  the file shows the vehicle status.
- Why: requested so CPU and RAM can be seen together while driving.
- Safety-relevant: no (display only; no planner, controls, panda, TX or cereal change). The NO PANDA warning keeps priority.
- Tests: `openpilot/selfdrive/ui/tests/test_sidebar_vehicle_cpu_slot.py`.
- Credits: BogPilot (sidebar metrics).

## Onroad pedals: a 3-bar gauge (brake pedal, regen kW, accel request) replaces the pedal icons
- Platforms: all legacy Tesla with openpilot longitudinal (UI, plus car-state inputs on AP1 Model S / X and Pre-AP).
- Reference behavior: daily's pedal icons (bogpilot-tesla paintPedalIcons): a brake and a gas pedal whose opacity follows
  measured `aEgo` (Dynamic) or turns on / off (Static), in a 2 x 60 x 120 rect under the accel graph on the driver side.
  Tinkla and NAP have no pedal gauge.
- Our behavior: three vertical bars, 36 / 6 / 36 / 6 / 36 design px in the old 120 x 120 footprint, fill alpha 191 with a
  1 px white outline around each filled segment. RHD mirrors the position and keeps the order. One behaviour, gated by
  openpilot longitudinal, CustomUI and Pedals on Screen (`pedals.policy_from_store`).
  - LEFT, friction brake pedal only: `CarState.deprecated.brake`, 0..1, set by the car state (AP1: the 0x39D rod stroke
    level, section below; Pre-AP: 1.0 / 0.0 from `brakePressed`, or the iBooster swap pedal position, section below).
    Negative = missing -> empty. It is never `aEgo` and never a residual such as max(0, -aEgo - regen).
  - CENTER, regen power: kW = DI_torqueMotor (Nm) x DI_motorRPM x pi / 30000 from DI_torque1 (0x108,
    `tesla_ap1_can.dbc` SG_ DI_torqueMotor 16|13@1- (0.25), DI_motorRPM 32|16@1- (1)), the same mechanical power as
    `regen_aware.regen_power_kw`, kept signed. Regen is negative; the bar fills from 0 to the per-model full scale
    (`REGEN_FULLSCALE_KW_AP1_S`, `_AP1_X`, `_PREAP` = -55 kW each, `pedal_gauge3.py`). Drive power, SNA (-1024 Nm,
    -32768 rpm), NaN or a stale `bogpilotCarState` -> empty (fail closed).
  - RIGHT, acceleration request: the driver's DI_pedalPos (`CarState.deprecated.gas`) while pressed, else OP's
    `carControl.actuators.accel` / `OP_ACCEL_FULL_SCALE` while `longActive`. The driver's pedal wins.
- Colours (`GAUGE3_PALETTE`, requested): driver / not controlling speed: brake #C62828, regen #2E8BFF, accel #3DDC97;
  openpilot: brake #B5838D, regen #8FB3E0, accel #5E8A72. Regen uses the openpilot colour while `longActive`; accel while
  OP's request drives the bar; brake only on AP1 while OP applies the iBooster (`longActive` AND
  `bogpilotCarState.ap1BrakePedalState` == ON AND NOT `brakePressed`, `op_ibooster_applied`). A driver press always
  wins. A colour change needs `SOURCE_HOLD_S` = 0.25 s of steady request, except a change to an active driver input.
  The former blended / share colours (violet, lavender, rose) and the decel scales are removed.
- Regen deadband and smoothing (proposal, UI only): below `REGEN_DEADBAND_KW` = 1 kW of regen the bar is empty (the
  torque decode is within about 1 Nm, about 0.5 kW at highway motor speed); `RegenSmoother` is a first-order low-pass with
  `REGEN_TAU_S` = 0.15 s, reset by a missing sample or a gap over 1 s. Peak regen seen in AP1 drive logs is about 26 kW,
  so plain regen reads about half the bar at -55 kW full scale.
- Dynamic / Static removed: `DynamicPedalsOnUI` and `StaticPedalsOnUI` are no longer read or shown (no child rows, no
  help entry; `phase2_visuals_theme.OMITTED` lists the Dynamic key). Both stay registered, and backup, restore and the
  toggle resets still carry them, so a stored choice survives a downgrade.
- Placement (requested): the footprint is centred on the record / personality column (`pedals.COLUMN_CX` =
  `style.REC_CX` = 126 screen px from the driver-side content edge) at the old height: on the 3X content rect
  (30, 30, 2100, 1020), screen x 99.3 .. 212.7, y 489.0 .. 602.3. `pedal_rect(widget_w, rhd, scale)` returns it in design
  space; the HUD keepout uses the same rect (`pedals.screen_rect`).
- Shared state function (for other screens): `pedal_gauge3.gauge_state(brake_frac, regen_kw, accel_frac, engaged, *,
  full_scale_kw, brake_by_op, accel_by_op, deadband_kw) -> Gauge3` and `paint_gauge3(rect, g, scale)`. The module does
  not import pyray at import time; only the painter does.
- Accel divisor: `OP_ACCEL_FULL_SCALE = interfaces.ACCEL_MAX` (2.0), the clip controlsd applies on every car
  (`get_pid_accel_limits` in `interfaces.py`); tesla_ap1 does not override it, so a full bar is the most OP can command.
- Driver pedal source: `CarState.deprecated.gas` = DI_pedalPos / 100, set in `tesla_ap1/carstate.py` and
  `tesla_ap1/preap/carstate.py` via `tesla_ap1/pedal_signals.py`. DI_pedalPos SNA (raw 255, 102 %) or anything outside
  0..100 % is -1 (missing) and the bar reads 0; before, SNA clamped to a full bar. `gasPressed` is unchanged. The
  deprecated slot keeps the feature modular with no compiled schema change; the desktop replay plot
  (`tools/replay/ui.py`, "gas") is its one other reader.
- Motor torque and RPM on every legacy platform: `bogpilotCarState.ap1MotorTorqueNm` / `ap1MotorRpm` (field names keep
  the ap1 prefix; no schema change) are now filled on AP1 Model X and Pre-AP too, from the same 0x108 signals (Pre-AP
  uses the same chassis DBC). The AP1 planner's regen estimate runs only on `TESLA_AP1_MODELS` (`ap1_planning.py`), so
  publishing the fields on X and Pre-AP changes no control path.
- Stale or missing carState: all bars empty and the colour state resets.
- Why: requested redesign of the onroad pedals (bars, colours and placement chosen by the maintainers).
- Safety-relevant: no (display only; no planner, controls, panda or TX change; the car state only fills unused fields).
- Tests: `openpilot/selfdrive/ui/onroad/bogpilot/tests/test_pedal_gauge3.py`, `test_pedal_bars.py`,
  `test_onroad_hud_features.py` (TestPedals), `test_record_button_placement.py`;
  `openpilot/selfdrive/ui/tests/test_pedals_toggle.py`; `opendbc_repo/opendbc/car/tesla_ap1/tests/test_pedal_gauge_signals.py`,
  `test_pedal_pos_published.py`.
- Credits: BogPilot (pedals widget, regen estimate); stock openpilot (accel limits).

## AP1 brake booster rod stroke (0x39D) for the onroad decel bar
- Platforms: AP1 Model S / X only (DBC, carstate). Pre-AP unchanged (its parser does not register the frame).
- Reference behavior: no BogPilot or NAP definition of 0x39D on these cars. Tinkla/BogGyver opendbc `tesla_can.dbc`
  defines `BO_ 925 IBST_status` (4 bytes, `IBST_brakeInputStroke` 20|10, x0.05, -0.5 mm); that layout differs from the
  16|16 raw stroke used here and is unverified against our logs, so it is not used. The 5-byte Model 3 `IBST_status`
  layout does not match these frames and is not used either.
- Our behavior (from drive-log evidence): `BrakeBoosterStroke` (0x39D) in `tesla_ap1_can.dbc`, chassis bus 0, 4 bytes,
  25 Hz. Byte 0 `brakeBoosterChecksum` = (0x9D + 0x03 + byte 1 + byte 2 + byte 3) & 0xFF (the Tesla sum checksum);
  byte 1 low nibble `brakeBoosterCounter` (+1 mod 16, high nibble always 0); bytes 2-3 `brakeRodStroke`, a unitless
  16-bit little-endian rod stroke. Evidence: every logged AP1 frame (about 6 M) passed that checksum with DLC 4; a replay
  window rechecked here gave 100 % checksum pass, no counter skips, 25.0 Hz, rest mode 174 and a peak of 5470.
- Capture: derived from maintainer drive logs (AP1 Model S); the capture list (which drives) is kept privately by the maintainers.
- Carstate: `CarState.deprecated.brake` = clamp((stroke - `BRAKE_STROKE_REST`) / (`BRAKE_STROKE_TOP` - REST), 0, 1) in
  `tesla_ap1/brake_level.py`, REST = 174 (the rest mode; 168 was also seen and clamps to 0), TOP = 5631 (21 x 256 + 255,
  the top of the hardest logged press). -1 (`BRAKE_LEVEL_MISSING`) when the frame is missing, older than 0.5 s or fails
  the checksum, which is checked in Python because the parser has no checksum hook for this DBC (registering one would
  also start checking the existing DAS frames; not done). Registered with frequency 0, so a car without the frame does
  not trip `canValid`. The deprecated slot avoids a compiled schema change; nothing else reads it.
- Not known: no calibrated unit (pressure or mm), and a panic / ABS stop may exceed TOP (the bar then pegs).
- Why: requested. The 3-bar gauge's left (brake pedal) bar height is this level; missing or stale leaves it empty.
- Safety-relevant: no. Receive only, display only: no controls, planner, panda safety or TX change; the panda safety
  modes do not reference 0x39D.
- Tests: `opendbc_repo/opendbc/car/tesla_ap1/tests/test_ap1_brake_booster_stroke.py`, `test_pedal_bars.py`.
- Credits: drive-log evidence (BogPilot); Tesla sum checksum as in opendbc's Tesla checksum helper.

## Pre-AP iBooster swap (0x554) for the onroad brake bar
- Platforms: Pre-AP Model S only, with the new Vehicle Controls toggle "Pre-AP: iBooster Swap" (`TeslaHasIBooster`,
  file-backed in the Pre-AP params, default off; hidden on AP1, which has the factory iBooster and 0x39D).
- Reference behavior: Tinkla / BogGyver openpilot `501c7de` `selfdrive/car/tesla/carstate.py` lines 115, 212-215 and
  653-662: with `TinklaHasIBooster` it subscribes ECU_BrakeStatus on bus 0 with frequency 0 and sets the panda iBooster
  flag, but `ret.brake` stays 0, so the level is never shown. Layout from BogGyver opendbc `9c0b6fe` `tesla_can.dbc`
  lines 917-924 and 1380-1383: BO_ 1364 ECU_BrakeStatus, 5 bytes; BrakePedalPosition 20|12@1+ (0.015625,-5) [0|47] mm,
  BrakeOK 16, DriverBrakeApplied 17, BrakeApplied 18, Status 12|4, Brake_Counter 8|4, Brake_Checksum 0|8.
  NAP `e99f4dc75` `nap_params.py` lines 31-32 define `NAPiBoosterEnabled` and `NAPBrakeFactor`, but nothing reads them;
  neither is used or migrated here.
- Our behavior: the same message, copied without changes, in `tesla_ap1_can.dbc` (BO_ 1364 plus its VAL_ lines). With the
  toggle off the brake bar is binary (1.0 while pressed). With it on, `preap/carstate.py` adds ECU_BrakeStatus to the
  chassis parser as OPTIONAL (no `canValid` effect) and the bar is clamp(BrakePedalPosition /
  `IBOOSTER_PEDAL_FULL_MM`, 0, 1) (`preap/ibooster.py`). Missing, older than `IBOOSTER_MAX_AGE_S` = 0.5 s, BrakeOK = 0 or
  Status != 0 -> -1 (empty bar). `brakePressed` still comes from BrakeMessage / DI_brakePedal only. The checksum is not
  checked (display only; the parser has no checksum hook for this DBC).
- Provisional: `IBOOSTER_PEDAL_FULL_MM` = 47 (the top of the reference DBC range) and the 0.5 s age, until a capture from
  a swapped car exists.
- Not done: no panda flag, panda safety or TX change (Tinkla's `FLAG_TESLA_HAS_IBOOSTER` is not ported).
- Why: requested, so a Pre-AP car with an iBooster swap shows a proportional brake bar.
- Safety-relevant: no. Receive only, display only; the message is parsed only with the toggle on.
- Tests: `opendbc_repo/opendbc/car/tesla_ap1/tests/test_pedal_gauge_signals.py`,
  `openpilot/selfdrive/ui/tests/test_preap_pedal_cal.py` (vehicle row), `test_phase3_system_feature_archive.py`.
- Credits: Tinkla / BogGyver (message layout, TinklaHasIBooster).

## Onroad record button: one fixed spot between the pedal bars and the personality label
- Platforms: all (UI only).
- Reference behavior: the record button sits at design y 696 on the driver side, x aligned with the stock DM corner.
- Our behavior: one fixed spot. The button centre sits halfway between the pedal bars' bottom edge (`pedals.pedal_rect`,
  the bars' layout rect, used whether or not the bars are drawn) and the cap top of the driving-personality label
  (`style.record_center_y`, from the label placement hud_compose and paint_personality use: DM_CORNER_OFF, CLUSTER_D,
  PILL_LABEL_SPACE / PAD / SIZE), so the gaps above and below the button are equal (about 49 px on the 2160 x 1080
  screen, 26 px lower than before). The position takes no pedals-gate input, so the button does not move when the bars
  are switched on or off. x, size and RHD mirroring are unchanged. One rect (`style.record_hit_rect`) is the tap target,
  the drawn box and the lead-label keepout.
- Why: requested placement.
- Safety-relevant: no (display / tap position only).
- Tests: `openpilot/selfdrive/ui/onroad/bogpilot/tests/test_record_button_placement.py`.
- Credits: BogPilot (record button, personality cluster).

## Conditional Experimental Mode removed
- Reference behavior: BogPilot 0.9.7 ships Conditional Experimental Mode (CEM): the planner turns Experimental Mode on by itself when set conditions hold (speed, curves, leads, a predicted stop, a turn signal), publishes the reason in `CEStatus`, shows an onroad status badge, and the AP1 stalk hold flips the `CEStatus` override instead of Experimental Mode while CEM is on. Upstream 0.11.2 has no CEM.
- Our behavior: CEM is removed on every car. The full port is maintained separately, with a list of its files, params and call sites, for a possible 0.11.0 LTS port. On this branch:
  - Settings: no "Conditional Experimental Mode" entry on the Gas / Brake page (`phase3_gas_brake.root_entries`, `phase3_long_accel_settings.gas_accel_entries`), and `ConditionalExperimental` is no longer one of the page's controls.
  - Planner: `phase3_long_accel.CEM_REMOVED` makes `Conditions.read` return None, so `LongAccelPort.update` never returns a conditional flag, `cem.red_light` stays off and the force-stop observer uses its own model filter, as it already did with CEM off. `publish_status` never writes `CEStatus`.
  - Stalk: `phase3_stalk_controls.cem_is_on` is always False, so the hold always flips the regular `ExperimentalMode`.
  - Onroad: the CEM status badge (`phase3_cem_status.read_status`) is always hidden.
  - Params: every `CE*` key, `CEStatus` and `ShowCEMStatus` stays registered and the `Phase3CEMEnabled` marker stays a known file key, so a value saved on a device, a restored backup, or a reset that writes `ConditionalExperimental` 0 stays harmless. Nothing reads them for driving.
  - Regular Experimental Mode is unchanged: the toggle, the planner's model input (`selfdriveState.experimentalMode`), camera switching and the icons.
- Why: the CEM port is not wanted on this build; it was already off on every legacy Tesla (entry "Conditional Experimental Mode off on every legacy Tesla" above).
- Safety-relevant: no new behaviour. With the shipped legacy Tesla settings (CEM off) the planner inputs are identical before and after; with CEM saved on, Experimental Mode only follows the driver's own toggle.
- Tests: `openpilot/selfdrive/ui/tests/test_cem_removed.py`, `openpilot/selfdrive/ui/tests/test_stalk_gaps.py`, `openpilot/selfdrive/controls/tests/test_gas_brake_mounts.py`, `openpilot/selfdrive/controls/tests/test_gas_brake_stop_defaults.py`; CEM behaviour tests in `test_phase3_long_accel.py` and `test_phase3_long_accel_settings.py` are skipped while `CEM_REMOVED` is set.
- Credits: BogPilot (CEM port, maintained separately).

## Sidebar home mark: ring top rebuilt from the mark's own bottom half
- Reference behavior: the sidebar home button draws the BogPilot theme mark `bogpilot/button_home.png` (360 x 360) at HOME_BTN (180 x 180), scale 0.5, bilinear.
- Our behavior: the sidebar draws `bogpilot/button_home_ring.png`, made from `button_home.png` only: inside the ring band (radius 140 px and out from the centre; the road art ends at 136.9 px) the top half is the vertical mirror of the bottom half. Every other pixel is the shipped file's, which stays unchanged in the tree and is the fallback.
- Why: in the shipped file the ring is thinner and hard-edged at the top (6 px over half alpha with a 1 px outer edge, against 8 px and a 3 px edge at the bottom). Drawn at 2160 x 1080 that is 3.06 px against 3.53 px with no edge softening, which looks like a clipped, aliased top. The draw path is not the cause: the asset has 25-27 px of transparent padding, the draw is exactly 2:1 at integer positions (the render matches an ideal 2 x 2 box downscale within 0.5/255), there are no mipmaps to blur it, and no scissor covers the button (the metric boxes' scissors stop at y 780; the logo starts at y 872). After the change the ring is 3.53 px top and bottom with the same edge, and the logo keeps 12-13 px inside the button and 52 px above the screen bottom.
- Safety-relevant: no (display only).
- Tests: `openpilot/selfdrive/ui/tests/test_sidebar_logo_ring.py`.
- Credits: BogPilot theme (the mark).

## Onroad Camera View: Auto, Standard and Wide (no Driver)
- Platforms: all car types (UI only).
- Reference behavior: BogPilot 0.9.7 / 367e1fe offers Camera View Auto, Driver, Standard and Wide (`CameraView` 0, 1, 2, 3). Driver (1) shows the cabin camera as the onroad view. Its Auto switches to the wide camera below 10 m/s and back above 15 m/s. Upstream openpilot 0.11.2 has no setting; it always does what Auto does here, with 5 m/s and 10 m/s.
- Our behavior: the options are Auto, Standard and Wide (`toggle_metadata.py` CameraView, with a `value_map` so the stored codes stay 0, 2 and 3). Driver is not offered. A saved 1, or any value that is not 0, 2 or 3, reads as Auto through `selfdrive/ui/bogpilot/camera_view.normalize`; nothing is written back. Auto is upstream 0.11.2 unchanged (`onroad/augmented_road_view.py` `WIDE_CAM_MAX_SPEED` 5.0 m/s, `ROAD_CAM_MIN_SPEED` 10.0 m/s, only in Experimental Mode and with the wide stream available, current stream kept in between; narrow otherwise).
- Settings > Visuals has a "Camera View" row (Auto / Standard / Wide) under Quality of Life Visuals (`layouts/settings/bogpilot_visuals.py`; `toggle_metadata.py` is still not rendered). Onroad, `augmented_road_view._switch_stream_if_needed` reads it through `camera_view.selected_view` (ParamStore, 2 s cache): Standard holds the narrow road camera, Wide the wide one (narrow if there is no wide stream), Auto is the upstream code above. Quality of Life Visuals off, a missing store or a read error means Auto. The setting is not tuning-level gated (the row is always shown under its parent).
- Registered default: `CameraView` registers 0 (Auto, the stock behavior; 367e1fe registers 3, Wide), in `common/bogpilot_params.py`, the generated `params_keys_bogpilot.h`, `ui/bogpilot/bogpilot_defaults.py` and the feature spec. The manager stores it on first boot, so a fresh install of any car starts on Auto, and both settings resets write 0 (the shipping reset takes the registered default, the stock reset the stock 0). A value already saved on a device is kept: 2 stays Standard and 3 stays Wide, which includes a 3 stored by an earlier build's default on a car the AP1 profile does not cover (Pre-AP, Model X, non-Tesla). A saved 1 (Driver) still reads as Auto. The AP1 profile's one-time Auto write is unchanged.
- The cabin camera is still shown in reverse (`QOLVisuals` and `DriverCamera`; `layouts/main.py` `_update_reverse_camera`, `bogpilot/reverse_camera.py`, `onroad/reverse_camera_view.py`) and from Settings > Device > Cabin Camera (PREVIEW). Neither reads `CameraView`.
- Why: the maintainer asked for Driver to go from the onroad choices. The cabin view stays where it is used: in reverse and in the Settings preview.
- Safety-relevant: no. Display only; nothing in controls or monitoring reads `CameraView`.
- Tests: `openpilot/selfdrive/ui/tests/test_camera_view_options.py`, `openpilot/selfdrive/ui/tests/test_reverse_camera.py`.
- Credits: BogPilot 0.9.7 / 367e1fe (options and codes), upstream openpilot 0.11.2 (Auto switching and its default), BogPilot (the wiring: Standard / Wide hold one stream, Driver aside).

## Longitudinal: legacy Tesla cruise accel uses the 0.9.7 acceleration profiles by default
- Platforms: AP1 Model S, AP1 Model X and Pre-AP Model S (`openpilot/common/bogpilot_ap1_profile.py:552` `LEGACY_TESLA_PLATFORMS`). Every other car keeps the stock cruise limit unless the driver adopts the profiles in the Gas / Brake page.
- Reference behavior: stock openpilot 0.11.2 caps cruise acceleration at [1.6, 1.2, .8, .6] m/s^2 over 0 / 10 / 25 / 40 m/s (`selfdrive/controls/lib/longitudinal_planner.py:32-33` `A_CRUISE_MAX_VALS` / `A_CRUISE_MAX_BP`). BogPilot 0.9.7 applies its acceleration profiles instead (`04d560f3e` `bogpilot_acceleration`).
- Our behavior: on the legacy Tesla platforms the Acceleration / Deceleration / Human-Like group is live without a UI re-select (`selfdrive/controls/lib/phase3_long_accel.py:63-68` `profiles_default_on`, used by `profiles_adopted` at `:71-72`), while Longitudinal Tuning stays on (registry default `1`, `common/bogpilot_params.py:229`). The cruise maximum then comes from `Profiles.limits` (`phase3_long_accel.py:102-109`):
  - Standard (0): [2, 1.6, .8, .6] over 0 / 10 / 25 / 40 m/s (`:109`).
  - Eco (1): [2, 1.5, 1, .8, .6, .4, .2] over 0 / 5 / 10 / 15 / 20 / 25 / 40 m/s (`:103`).
  - Sport (2), the default: [3, 2.5, 2, 1.5, 1, .8, .6] over 0 / 5 / 10 / 15 / 20 / 25 / 40 m/s (`:105`). It is the registry default (`common/bogpilot_params.py:42` `AccelerationProfile` `2`) and the value the one-time legacy Tesla write uses (`common/bogpilot_ap1_profile.py:559`). Sport is higher than Standard and stock below 25 m/s and the same as both at 25 m/s and above.
  - Sport+ (3): [4, 4, 2] over 0 / 5 / 20 m/s (`:107`).
  - Human-Like Acceleration is on by default (`common/bogpilot_params.py:193`). It lowers that maximum at low set speeds and small speed errors (`phase3_long_accel.py:110-112`), so the cruise plan only goes above the stock cap where a large speed error allows it.
- Why: the maintainer drove these cars on 0.9.7 with these profiles, so the legacy Tesla platforms keep that acceleration. It is intentional, not a planner regression: a Pre-AP planner's cruise acceleration goes past the stock cap during a large speed error.
- Safety-relevant: comfort only; it sets the cruise acceleration ceiling, not braking. Car code and panda are unchanged. Turning Longitudinal Tuning off (also what "Reset to stock" writes) returns these cars to the stock limit.
- Tests: `openpilot/selfdrive/controls/tests/test_phase3_long_accel.py`; `openpilot/selfdrive/controls/tests/test_gas_brake_stop_defaults.py` keeps its stock-equality planner checks on a non-legacy car for this reason.
- Credits: BogPilot 0.9.7 (`04d560f3e`, the profile tables); comma.ai openpilot (MIT) for the stock cruise limit.

## Onroad UI: 88 mph flame tracks start at the passing car and run down the lane
- Platforms: all cars with an adjacent-lane radar lead source (`bogpilotRadarState`); UI only.
- Reference behavior: BogPilot `selfdrive/ui/qt/onroad/bsm_flame_tracks.h` `paintTracks` lights the adjacent lane from its near end and runs the front away from our car over the first 0.6 s (its lane polygon puts the near edge first), then fades the tracks out over the last 1.2 s. Neither it nor the earlier 0.11.2 port (`paint_tracks`, which indexes the 0.11.2 polygon from its far end) starts at the passing car.
- Our behavior: the trigger, 3 s burn, toggle (`BSMFlameTracks`) and palette are unchanged. When the burn starts, the tracks are anchored on the passing car: the adjacent lead's screen point from `BlindspotOverlay._bp_adjacent_points` (`onroad/bogpilot/bogpilot_model.py`, the same calibrated projection and checks as the adjacent lead box in `lead_lockon.py`). A ring flashes at the car, the twin tracks run down the lane to the bottom of the screen in 0.5 s with flame tongues streaming down, and they burn out from the car end downward over the last 1.2 s (`flame_tracks.paint_trail_from_car`). The top of the trail follows the car while it burns (`TRAIL_FOLLOWS_CAR`). If the car is so low on screen that fewer than two lane points are below it, the two nearest lane points are extended down instead.
- Fail-closed: no car point at ignition means the earlier `paint_tracks` draws that whole burn; a frame without a finite car point draws `paint_tracks` for that frame. Toggle off draws nothing. No new signal: the anchor is the existing `bogpilotRadarState` lead position.
- Known, unchanged: `paint_tracks` (now only the fallback) keeps its far-end indexing, so its distance fade is reversed relative to the Qt reference.
- Why: the maintainer asked for the flames to start where the car actually is when they light and to head toward the bottom of the screen.
- Safety-relevant: no. Display only; nothing in controls reads it.
- Tests: `openpilot/selfdrive/ui/onroad/bogpilot/tests/test_flame_trail_from_car.py`, `test_flame_tracks_logic.py`, `test_adjacent_leads_bsm.py`, `test_release_adapters.py`.
- Credits: BogPilot (`bsm_flame_tracks.h`: trigger, burn timing, track geometry and palette); BogPilot (anchor on the passing car, down-lane direction).

## radard: AP1 Bosch radarTracks frequency floor is 6.69 Hz
- Platforms: AP1 Model S and AP1 Model X only (`is_ap1_family`). Pre-AP and every other car stay at the stock 8.0 Hz floor.
- Reference behavior: none of the three references puts an average-rate floor on the Bosch radar. BogPilot 0.9.7
  excludes `radarState` from controlsd's avg-freq check (`selfdrive/controls/controlsd.py:117`) and drives radard
  from the radar itself. Tinkla/BogGyver radard cannot check average frequency because the radar sets the timing
  (`selfdrive/controls/radard.py:199`). NAP excludes `liveTracks` from `all_checks` because it arrives at radar
  rate, 8 Hz for Bosch, not the 20 Hz SubMaster (`selfdrive/controls/radard.py:233-236`).
- Our behavior: radard keeps the SubMaster alive window (0.5 s), `valid`, max 24 Hz, `canError`, `radarFault`,
  the CANParser timeouts and the Pre-AP fail-closed path unchanged. On AP1 only, it lowers the radarTracks
  FrequencyTracker `min_freq` from 8.0 Hz to `AP1_RADARTRACKS_MIN_FREQ_HZ` (6.69 Hz), a lower-only override in
  SubMaster. `cereal/services.py` is not changed, so the alive window stays 0.5 s for every car. The AP1 Bosch
  radar was measured at 7.4-12.6 Hz depending on track count (about 12 Hz below 10 tracks, 7.4-7.8 Hz at 28-30
  tracks); the stock 8.0 Hz floor was raising commIssue in dense traffic while the radar was still publishing.
- Measured basis for 6.69 Hz: across a 42-route, 14-day set of AP1 bench drives, the slowest 20-sample
  FrequencyTracker average (the recent window radard checks) was 6.996 Hz, while engaged with 28 tracks. The
  slowest 200-sample average was 7.602 Hz. 6.69 Hz leaves about 0.31 Hz of margin under the worst 20-sample
  average. The owner chose 6.69 Hz over 5.0 Hz (more margin) and 7.0 Hz (no margin). Replaying that set,
  the stock 8.0 Hz floor raised 3 engaged invalid spans (8.24 s); 6.69 Hz and 5.0 Hz raised none.
- Why: a healthy AP1 radar can sit between 7.0 and 8.0 Hz with a full track list, which is not a dropout. A
  sustained 6 Hz or slower stream still goes invalid (unlike ignoring the average-frequency check). A 0.5 s gap
  is still a fail.
- Safety-relevant: yes, a liveness check. The 6.69 Hz floor is stricter than all three references, which have
  no radar rate floor. Panda safety is unchanged.
- Tests: `openpilot/cereal/messaging/tests/test_min_freq_override.py`,
  `openpilot/selfdrive/controls/tests/test_ap1_radartracks_min_freq.py`; Pre-AP missing-radar canError remains
  in `opendbc_repo/opendbc/car/tesla_ap1/tests/test_preap_bosch_radar.py`.
- Credits: BogPilot 0.9.7 (controlsd.py radarState `ignore_avg_freq`); Tinkla/BogGyver (radard.py radar-timed
  SubMaster); NAP (radard.py excluding liveTracks from all_checks); measured AP1 Bosch rate.
