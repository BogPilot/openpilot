# bogpilot-na-preap — tester notes (2026-11-05, America/New_York)

Bundle for testers on `bogpilot-na-preap`. Base `27b484ddd`. UI and firmware tip before these notes: `2149836b2`.

This is one bundle for Pre-AP testers: pedal timeout recovery, correct pedal STATE decode, Pre-AP engage/disengage chimes, panda arm-on-pull with matching openpilot behavior, safer driver-press calibration, rebuilt panda DEBUG firmware, and rebuilt AGNOS 10.1 UI. Radar frozen-track filtering is not in this build.

## What should feel different

- The comma pedal should leave timeout (STATE 5 or 4) and return to no-fault after openpilot keeps sending zero-gas `0x551` keepalives. Once healthy, it can accept `ENABLE=1` and actually add gas. Earlier logs showed almost no `0x551`, then four resets and give-up, plus STATE and IDX read from the wrong nibbles.
- First stalk pull latches steering (Always On Lateral / lat-only). Second pull adds the pedal. Brake drops the pedal and keeps steering. Stalk forward cancels both.
- Only a pull may enable. Accel and decel on the stalk will not request enable, because the panda will not arm on those.
- After a Controls Mismatch / panda drop, a later pull should be able to re-arm. Previously `cruise_engaged_prev` could stay stuck so another pull did nothing until a power cycle.
- Openpilot cancels and clears the double-pull latch when the panda would drop you (hands-on at 3 or more, or the existing EPAS rejects).
- Pre-AP cars get BogPilot engage and disengage chimes again (FrogPilot auto, 101) if those volumes were still muted. AP1 and AP2 stay muted, because those cars already chime. A Pre-AP driver who mutes again after this migration is left alone. There may also be optional lat-latch chimes on first pull / lat drop.
- Pedal calibration no longer saves Ready from a tiny twitch. Coast is recorded only when the interceptor is quiet and the car’s DI gas is near zero. Press is recorded only when DI gas rises with the interceptor (a real foot). A span under 10, or a scale factor outside a sane range, fails validation instead of writing Ready. That rejects the known-bad 0.762 to 6.451 capture (span 5.69, factor about 17.6) and expects a factor nearer the ~0.94 seen on a real press.
- The UI should show Calibrating and Failed (not just Ready). This build includes a rebuilt AGNOS 10.1 `selfdrive/ui/ui` for those strings.
- This build includes panda DEBUG firmware `DEV-328a9d92-DEBUG`, rebuilt here. Testers need that firmware flashed. This is not a software-only update like the pedal-keepalive slice would have been.
- The intentional Pre-AP `brake_pressed=false` on `0x20A` (so steering can stay up under brake) is unchanged.
- There is no `SAFETY_ALLOUTPUT` calibration mode and no software-commanded gas sweep.

## What we did not change yet

- No radar frozen-track filter. Please collect rlogs from this build if tracks look stuck; we will look at that next.
- No other AP1 daily-driver or `bogpilot-tesla` changes.

## Suggested check on the car

1. Install this branch after it is published, and flash the included panda DEBUG firmware.
2. Reboot so Pre-AP chime migration can run if volumes were still muted.
3. Confirm a timed-out pedal recovers (keepalives, STATE back to 0) and then drives on the second pull.
4. First pull: steering only. Second pull: pedal adds gas. Brake: pedal drops, steering stays. Stalk forward: everything cancels.
5. If you get a take-control / mismatch, try another pull and see whether it re-arms instead of staying stuck.
6. Recalibrate the pedal with a real press. A light twitch should fail; a firm press should succeed.
7. Upload rlogs with the Debug pack tab (not the Fingerprint tab). Defaults are fine: one segment at a time, interest-only CAN off, Force unchecked. Stay under the 222 MB cap.

## Commits in this bundle (`27b484ddd`..`2149836b2`)

- `80ce2b72f` keep sending `0x551` while the pedal reports FAULT_TIMEOUT / FAULT_STARTUP
- `b21a15d3e` correct GAS_SENSOR STATE/IDX nibbles; restore Pre-AP engage/disengage chimes
- `328a9d924` panda and userspace: arm only on stalk pull; match cancel/latch behavior
- `7bbed7426` panda DEBUG firmware `DEV-328a9d92-DEBUG` (built here)
- `89e205d43` safer driver-press calibration (no ALLOUTPUT)
- `2149836b2` rebuild AGNOS 10.1 UI for Calibrating / Failed pedal status
