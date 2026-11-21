# Pre-AP Model S (Comma Pedal): port notes

Pre-AP Model S cars have no Autopilot ECU. BogPilot steers through the EPAS and drives speed through a Comma Pedal that stands in
for the accelerator. There is no brake control: anything beyond what the pedal's regen gives is the driver's foot on the brake.
Code: `opendbc_repo/opendbc/car/tesla_ap1/preap/`, panda mode `opendbc_repo/opendbc/safety/modes/tesla_preap.h`.

## Changelog

### Curve speed control with the pedal (vision-only)
- With a calibrated Comma Pedal and openpilot long, the curve speed controller is back as in 0.9.7: it slows for curves the
  camera sees ahead, only lowers the set speed, and controls speed only in speed control (double pull). Steering only never
  slows the car for a curve. Never on a car without the pedal. See DIVERGENCES_preap_csc.md.

### NAP-style double pull: a single pull steers, a double pull adds speed control
- A single pull engages steering only; a double pull adds speed control. From speed control a brake press or a single pull
  goes back to steering only (speed-off chime, "Steering only" banner, blue path); hands on or an EPAS refusal disengages and needs a
  fresh pull. Without the pedal a single pull cancels a stock cruise it armed and the driver's double pull re-arms it.
- The pedal is enabled only in speed control, never while braking or with the accelerator pressed, and at a stop it holds at 0 until
  the accelerator is pressed and released while moving. See DIVERGENCES_preap_nap_fsm.md.

### Pedal scale window and the pedal command limit
- The panda drops every enabled Comma Pedal command (0x551) whose raw value is above `max_enabled_raw_gas_cmd` (2500 in
  `tesla_preap.h`). The pedal then hears nothing from openpilot and falls back to the real pedal (foot off, so the car regens).
- Calibration used to accept a pedal scale from 0.4 to 3.0. Below about 0.85 a normal full pedal command was over that cap.
- One shared limit now lives in `preap/pedal_can.py` (`PANDA_MAX_ENABLED_RAW_GAS_CMD`, `PEDAL_RAW_MARGIN`, `PEDAL_ENABLED_RAW_LIMIT`).
  Both the calibration check (`preap/calib.py`) and the command encoder (`create_pedal_command`) use it, and a test reads
  `tesla_preap.h` and fails if the two numbers ever differ.
- Math. Pedal scale = 100 / (full-throttle reading - zero reading). A planner pedal position `di` becomes the command
  `zero - 1/scale + di/scale`, and the planner never goes above `PEDAL_DI_MAX` = 90. The limit is raw 2450, which is a command of
  about 101.59 (50 raw below the panda cap).
- The accepted pedal scale window is a **fixed 0.82 to 3.0** (`FACTOR_MIN`, `FACTOR_MAX`; maintainers' decision). An earlier pass first derived the
  floor from the limit (about 0.88 to 0.89), so that the highest normal command always fitted under it. The floor is now looser on
  purpose: the encoder clamps every enabled command at the shared limit, so a low-scale pedal can no longer cause a dropped frame. It only
  loses some top-end acceleration. A planner position above `max_reachable_di = 1 + scale * (101.59 - zero)` sends the same (clamped)
  command. At scale 0.82 that is 84.3 with a zero reading of 0 and 83.7 at 0.8, so the top 6 or 7 points of the 0-90 range (about 7 %)
  are flat. A scale of 0.89 or more loses nothing. A real measured press (scale about 0.94) loses nothing.
  **The bounds will be revisited after the tester's 0.11.2 calibration and first-drive rlogs.**
- A pedal scale saved outside the window (below 0.82 or above 3.0) is shown as "Recalibrate: scale out of range" and pedal
  longitudinal stays off until the driver calibrates again. The saved values are never rewritten or deleted. A saved scale from 0.82
  up is accepted as it is.
- The encoder clamps every enabled command at the limit, so a frame we build is never one the panda would drop.
- The calibration failure messages are plain driver words (pedal scale, accelerator), for example
  "Pedal scale 0.718 is out of range (0.82 to 3.00). Check the Comma Pedal wiring and try again."

### Pedal calibration: zero where the car first sees throttle
- Step 1 (feet off): a 200-frame window (about 2 s) while the car reads DI_pedalPos = 0, accepted when the medians of its two halves
  agree within 1.0 and the peak-to-peak is under 10.0. The rest mean is saved as `PedalCalibMin`; the 99th percentile sets the noise floor.
- Step 2 (one slow press to the floor): the pedal reading at the first frame with DI_pedalPos >= 0.4 % is `PedalCalibZero`, the reading at
  the first frame with DI_pedalPos >= 99.6 % is `PedalCalibMax`, and the scale is 100 / (max - zero), as in Tinkla calibratePedal.py.
- The zero is never below the rest p99 + 0.25. An onset reading under that is raised to it; an onset reading below the rest mean fails
  ("The car saw the accelerator before the Comma Pedal reading moved. ...").
- A twitch (back to DI 0 before 5 %) is ignored. A press let go before 99.6 %, or still short of it after about 5 s, fails with "The
  accelerator was not pressed all the way down. Press it slowly to the floor, then let go and try again." Cancel, a timeout, or losing
  the pedal mid-press saves nothing.
- The guided screen says "Press the accelerator pedal fully once, then let go" and, in the detail line, to press slowly all the way down.
- See the DIVERGENCES.md entry "Pre-AP pedal calibration: the zero is read where the car first sees throttle".

### "Pedal Not Responding" alert
- When pedal longitudinal is on and the Comma Pedal stream (GAS_SENSOR, 0x552) is missing, or its counter has not moved for
  0.5 s, `carState.bogpilot.preapPedalNotResponding` is set and `ap1_events.py` raises the new event `pedalNotResponding`.
  It replaces the generic "Cruise Mode Disabled" because that is the specific cause.
- Engaged: immediate disable, "TAKE CONTROL IMMEDIATELY / The Comma Pedal is not responding". Not engaged: a permanent notice
  "Pedal Not Responding / Check the Comma Pedal wiring" (after 1 s) and the same text when you try to engage.
- It is never raised when pedal longitudinal is off (stock cruise, or "Disable Pedal Longitudinal" on).

### Engage problems from a tester drive review
- **"Cruise didn't arm / Pull the stalk again"**: openpilot enabled on a Pre-AP car while the panda is not armed (`controlsAllowed` false)
  for 0.3 s (`selfdrived/preap_arm.py`, `EventName.preapNotArmed`, disengages). Before, the first words came from `controlsMismatch` after 2 s.
  Other cars keep the 2 s check. A deliberately unarmed panda (the steer-through-brake latch) must pass `dropped_on_purpose` to
  `PreapArmWatch.update`; selfdrived does, via `dropped_on_purpose`.
- **Pedal acquisition is retried, not latched.** `PedalAuthority` waits 0.5, 1, 2, then 3 s between tries while openpilot still wants the
  pedal, and keeps the cause (`PedalFailCause`: no pedal signal, state fault, counter/state mismatch, counter stuck, command error).
  A pedal stuck in a clearable STARTUP/TIMEOUT fault is reported after 3 s as a state fault (it used to be silent). A command error stays until
  the next engage. `cruiseState.available` no longer includes the failed-pedal flag: that was a latch (wrongCarMode blocked the engage that
  would have cleared it).
- The cause reaches the driver through `carState.bogpilot.preapPedalFailCause` and a warning that does not disengage,
  "Pedal Not Responding" with one of: "No pedal signal: check the wiring. Retrying", "The pedal reports a fault. Retrying",
  "Pedal counter and state mismatch. Retrying", "The pedal counter is not moving. Retrying", "The pedal is not answering. Retrying",
  "Pedal command error. Pull the stalk again". The missing-stream alert above is unchanged.
- **Vehicle screen** (Pre-AP): read-only "Software" (`0.11.2 (short git commit)`, "+ local edits" when the tree was changed) and "Panda Firmware"
  (what pandad found: the version, "(out of date)", "(bootloader only)", "Not found", or "Not reported yet"). pandad writes the file-backed
  param `PandaFirmwareVersion` (`/data/params_bogpilot`).
- Not done (follow-ups): a firmware/DBC self-check gate that refuses to engage on a mismatched panda or DBC, pedal pre-warm while the
  driver is gas-overriding, and narrowing the stock-cruise spoof.

### Brake press keeps steering, cuts only the pedal
**Status: Reviewed and approved by the BogPilot maintainers, November 2026.**

Pressing the brake while engaged on a Pre-AP Model S now stops the pedal only. Steering carries on.
(The Model S has no brake control; the driver's foot is the brake, and regen is the only thing the pedal can do below it.)
- Panda (`tesla_preap.h`): a stalk pull arms a steering latch. A brake press still drops `controls_allowed`, which is what blocks the
  pedal, and an enabled 0x551 frame is also refused whenever the brake is pressed. If the session was armed by a pull and a brake press
  happened since, steering (0x488) keeps its permission. The latch never opens longitudinal. It is dropped by a cancel (outside the
  600 ms echo window), hands on, EPAS refusing, leaving D, a door, a monitored stream older than 1 s (the Comma Pedal stream included),
  and any safety-mode reset. A gas press does not drop it: in a tester log a gas press after a brake tap used to disarm the latch
  while openpilot stayed engaged, so steering was silently blocked for 34 s; gas has no bearing on steering and the pedal has its own gas
  rule. Only a new pull arms it again. Angle rate limits and the 360 degree cap still apply. The shared
  rule is `steer_angle_cmd_checks_with_lateral_permission` (same helper as the Always On Lateral steer-through-brake design).
- Car side (`preap/engagement.py`): a brake press while engaged becomes lateral-only (`preapLatOnly`); the pedal comes back on the next
  pull with the brake free. A pull with the foot still on the brake changes nothing.
- selfdrived (`preap_brake.py`): a press that only drops longitudinal does not disengage, and the panda's deliberate `controls_allowed`
  drop is not counted as a controls mismatch. Every other car is untouched (the flag is always False).
- Tests: `opendbc/safety/tests/test_tesla_preap_brake_steer.py`, `tesla_ap1/tests/test_preap_brake_steer.py`, `test_preap_engagement.py`,
  `selfdrive/selfdrived/tests/test_preap_brake.py`.

### Stock cruise: no engage until the panda has seen a fresh pull
On a Pre-AP car without the Comma Pedal (stock TACC, `pcmCruise`), openpilot engages on the rising edge of stock cruise. After a
hands-on takeover, an EPAS refusal or an EPAS fault, the panda keeps controls off until it sees a fresh stalk pull
(`tesla_preap_need_fresh_pull` in `tesla_preap.h`). If stock TACC came back on without such a pull (for example a pull held through
the takeover), openpilot used to engage while the panda stayed off, and only "preapNotArmed" caught it 0.3 s later.
- Car side (`preap/carstate.py`): `preap_fresh_pull_pending` mirrors `tesla_preap_need_fresh_pull`: set by every EPAS drop, cleared by
  a pull in D with the doors closed, except a pull held through the drop. With stock cruise it is reported as `blockPcmEnable`, which
  stops only the pcmEnable rising edge. `cruiseState.enabled`, pcmDisable and every disengage path are unchanged, and there is no new
  alert: openpilot simply does not engage. The pull that turns TACC back on is a fresh pull, so the panda re-arms and openpilot engages
  on the same tick. If TACC came on while blocked, stock TACC has to be cycled once more (cancel, then a pull).
- The pedal mode (engages from the pull itself) and AP1 (a different car state) are unchanged. No panda change.
- Tests: `tesla_ap1/tests/test_preap_fresh_pull_gate.py`, `test_preap_fresh_pull_libsafety.py` (against the compiled panda code), the
  mirror parity check in `test_preap_g1_parity.py`,
  `selfdrive/car/tests/test_preap_reengage.py`.
- How the references differ:
  - NAP (opendbc `preap/carstate.py:139`, `preap/engagement.py:67-78` @ cc39c7fa, NAP @ e99f4dc75): `cruiseState.enabled` is
    NAP's own flag, set only by a stalk pull rising edge and cleared by a steering disengage (`engagement.py:40-54`), a cancel
    (`engagement.py:186-196`) or a blocked engage (`engagement.py:114-124`). Stock TACC turning on by itself never engages, and no
    event is raised. BogPilot keeps stock cruise as the engage signal and blocks only its rising edge while the panda waits for a pull.
    The outcome is the same: no engage without a pull the panda saw, and no new alert.
  - BogPilot na-preap (@ 568fea947): without the pedal, `cruiseState.enabled` follows stock cruise
    (`selfdrive/car/tesla/carstate.py:205-207`) with no gate and no event, and its panda (`safety_tesla_preap.h:366-376`) re-arms on
    any rising pull with no held-pull rule. That port would engage on such a TACC edge; this port does not (stricter).
  - One car-side difference from the panda, in the stricter direction: carstate decides the drop from the latest EPAS_sysStatus
    values. A pull in the same 10 ms update as a drop, or a pull while EPAS frames are missing after a drop, leaves carstate pending
    until a release and a new pull, even though the panda may already have cleared. The parity check allows only this direction.
    This only errs stricter, costing at most one extra stalk pull, and carstate is never clear while the panda is pending.

### Stock DI_pedalPos gas-pressed threshold

On Pre-AP stock (no Comma Pedal interceptor), `CarState.gasPressed` is `di_gas > 0.02`. `di_gas` is still `DI_pedalPos / 100.0` and is unchanged (calibration reads it). The 2% threshold matches NAP `PEDAL_DI_PRESSED = 2` in `nap_conf.py:43` and NAP `preap/carstate.py:36-37` (`DI_pedalPos > PEDAL_DI_PRESSED`). Packed on the real DBC (`DI_pedalPos` factor 0.4), that means raw 0 and raw 5 (2.0%) are not pressed, and raw 6 (2.4%) is pressed. The interceptor override (`pedal.gas_pressed`) is unchanged. AP1 is unchanged (`gas > 0`, so raw 1 is still pressed).

Panda (`tesla_preap.h` / `tesla_ap1.h`) still treats any raw `DI_torque1` byte 6 != 0 as pressed. At raw 1-5 the Pre-AP stock host says not pressed, and the panda still inhibits longitudinal (`get_longitudinal_allowed` is false, which blocks gas TX). That stricter panda side is intentional.

## CAN ID clashes across buses

Some CAN IDs are reused for two different messages, one on the chassis bus (bus 0) and one on the radar bus (bus 1). Matching by ID alone will mix them up.

| ID | Bus 0 (chassis, `tesla_ap1_can`) | Bus 1 (radar, `tesla_radar_bosch_generated`) |
|---|---|---|
| 0x32e (814) | PARK_sensorStatusFront — 5 bytes, 4 Hz, front corner ultrasonic distances in cm (255 = no reading) | RadarPoint10_A — 8 bytes, measured 7.4-12.6 Hz depending on track count, Bosch radar track 10 |
| 0x33e (830) | rear park corners — 5 bytes, 4 Hz | RadarPoint15_B — 8 bytes, measured 7.4-12.6 Hz depending on track count |

The radar rates are the measured Bosch radar cycle; the radar parser still lists 16 Hz for these frames so its point timeout is unchanged (`opendbc_repo/opendbc/car/tesla_ap1/radar_interface.py` `get_radar_can_parser`). The AP1 / Pre-AP radar interface builds a `CANParser` on `CANBUS.radar` (bus 1) only, so it never reads the chassis park frames. The Pre-AP panda sets `disable_forwarding`, so those chassis frames are not forwarded onto the radar bus either. There is no radar glitch from this clash today.

Do not apply an ID-only filter for 0x32e or 0x33e. That would drop a real radar track (`RadarPoint10_A` / `RadarPoint15_B`). The chassis DBC does not yet define the park frames; they are noted here so coverage maps and future DBC work do not treat bus-0 0x32e as radar.

## Credits
- Beta tester **IRIT-able** (GitHub, fork `github.com/IRIT-able/bogpilot-openpilot`) found and fixed, on Nov 5 2026, the same Pre-AP
  problems that BogPilot's Pre-AP work fixes: the Comma Pedal sensor bit layout (GAS_SENSOR state and counter nibbles), engaging only on a
  stalk pull, and re-arming on a new pull. Thank you. The Pre-AP code in this repository is BogPilot's own; no code from that fork
  was copied.

## AP1 stalk retrofit auto-detect (follow-distance dial)

A Pre-AP car with an AP1 cruise stalk sends the same up / down / cancel / engage as a stock stalk; the retrofit only adds the
follow-distance twist (`DTR_Dist_Rq` on `STW_ACTN_RQ`). There is no menu row and no saved setting. The twist is ignored until it is
seen: two different valid detents (0, 33, 66, 100, 133, 166, 200) each held for 25 consecutive `STW_ACTN_RQ` frames (2.5 s at 10 Hz,
counted from the CAN frame timestamp, not the 100 Hz loop). SNA, a missing frame or an off-detent value restarts the count. A stock
stalk keeps the field at a constant 0, so it never latches. Once latched the dial is followed from then on: the first latch is saved once in the hidden file-backed key `PreAPStalkRetrofitDetected`
(default 0, no menu row, not backed up; written off the 100 Hz loop through the params thread), and a saved 1 makes the next start read the dial from
the first frame with no detection. Reset Hardware Settings clears it. It then drives the same follow time, Traffic Mode and personality sync as AP1, with pedal longitudinal only.
To confirm on a car: after starting a drive, turn the dial to a different position than it started in and hold it for about 3 s.
