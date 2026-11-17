# hardwared: background device reads, fail-hot thermal staleness, slow-loop timer — divergences

References: NotAutopilot (NAP) openpilot nap-alpha `92b42f772` and nap-dev-0.11.2 `65b9c2878` (identical helper modules;
NAP pull requests #308 and #320):
`system/hardware/hardwared.py` (reader setup, cached reads in the publish loop, fail-hot status), `thermal_reader.py`,
`sysfs_reader.py`, `loop_timing.py`; NAP commits `00234a5f` (thermal zones off the loop, fail hot when stale), `48ee0dc2`
(hold the last status while stale; fail hot only if warm or stale > 60 s) and `160ebbcb` (power draw and the remaining
system-file reads off the loop). Tinkla/BogGyver and BogPilot 0.9.7 read inline like stock. Panda, safety and selfdrived are
unchanged. Code: `openpilot/system/hardware/bg_reads.py`, used by `openpilot/system/hardware/hardwared.py`. Applies to
every car and device (hardwared is generic).

## Why
- Stock hardwared makes every slow device read inline on its 2 Hz deviceState loop: thermal zones, free space, memory,
  CPU and GPU load, screen brightness, power draw, SoM power draw and the boot check. A sysfs read that stalls stops
  deviceState for as long as it stalls, and selfdrived raises commIssue (deviceState is checked for 1.6 Hz and 5 s alive).
- Pre-AP tester logs: deviceState at 0.83 Hz with gaps up to 14.4 s and 12.5 s while pandaStates stayed at 10 Hz;
  every disengage lined up with a commIssue. NAP's notes record single thermal and bms power reads blocking for
  12.6 to 12.7 s with the same commIssue, fixed by the same design.

## Ours (BogPilot implementation of NAP's design)
- Two daemon reader threads, one for the thermal zones and one for the other device reads, each running every 0.5 s.
  The deviceState loop only takes the latest cached values and never waits on a device read. A read that raises keeps
  its last value; a read that hangs only delays fresh values.
- Any single read over 0.25 s logs `hardwared slow read` (reader and read names, ms) or `hardwared slow thermal zone`
  (zone names, ms), so a stall names its source.
- Thermal staleness, matching NAP's thresholds: no fresh thermal reading for 10 s marks the temperatures stale
  (`hardwared thermal stale` / `hardwared thermal fresh again` are logged). While stale the last temperatures are kept
  (never zeroed), the fan runs at 100 %, and thermalStatus is raised to at least `overheated` if the last reading was
  already warm (status above ok, or max temperature at or above the overheated band's entry temperature, 88 C or 92 C on
  mici) or once it has been stale for 60 s (70 s after the last fresh reading). The band logic and the offroad danger rule still run on the held readings,
  so the status is never cooler than stock would give. `overheated` makes selfdrived raise its overheat event and blocks
  going onroad, as stock.
- Slow-loop timer: a loop iteration over 1 s logs `hardwared slow loop` with every step's duration in ms
  (`steps_ms`) and the total. Publishing and the loop rate are unchanged.
- The boot check is read on the background thread and latches once true, as the stock onroad condition already does.

## Divergences from NAP
1. One generic reader class (`BackgroundReads`, a lock and a per-read freshness time) serves both threads. NAP uses a
   queue for thermal snapshots and a separate cache class for the other reads. Same behavior: latest value, non-blocking.
2. New startup condition `thermal_read`: never go onroad before at least one real thermal reading. NAP has none and
   publishes empty temperatures until the first snapshot. Stricter; stock never published deviceState before its first
   read either. Startup waits up to 2 s for the first readings, as NAP does for thermal only.
3. Memory and CPU load come from this tree's `LinuxSystemStats` (as stock here), not psutil as in NAP.
4. Slow-loop log: one `steps_ms` dict (a step repeated in one iteration adds up) instead of NAP's flat `<step>_ms` fields;
   event names differ (`hardwared slow read` with a `reader` field instead of `hardwared slow sysfs read`).
5. Not ported (not approved or out of scope): NAP's 10 s deviceState/managerState commIssue window in selfdrived (ours
   keeps the stock checks), NAP's Force Offroad feature, and NAP's NetworkManager D-Bus read in hw_state_thread.
6. Still inline on the deviceState loop, as in stock and NAP: the offroad power integration (`PowerMonitoring.calculate`
   reads the current power draw with ignition off only), `HARDWARE.set_power_save` on a change of state, the
   `/dev/kmsg` engaged line when selfdriveState updates, Params reads and writes, and the panda/chestnut USB state
   handling. The device type is read once before the loop (it is constant), not every tick.
7. No temperatures before the first real thermal reading: the temperature filters are not fed (so they seed from the
   first real reading, like stock, instead of from 0 C), the fan runs at 100 % and thermalStatus is at least
   `overheated`, so the device can't go onroad on missing temperatures. NAP feeds empty temperatures until its first
   snapshot. Stricter than NAP and equal to stock once the reading lands.
8. Non-thermal device reads: before the first real read, free space is published as 0 % and memory as 100 %
   (fail-closed: going onroad and engaging are refused) instead of a healthy-looking 100 % / 0 %. A read with no success
   for 10 s keeps its last real value and logs `hardwared device reads stale` (and `... fresh again`). NAP holds its
   cached values without a staleness log.
9. **Decision pending: stale temperatures while engaged.** Both behaviors are built, chosen by one module
   constant read once when hardwared starts, `STALE_THERMAL_POLICY` in `openpilot/system/hardware/bg_reads.py`
   (logged at start as `hardwared stale thermal policy`; an unknown value falls back to strict):
   - `"strict"` (**default** until decided): as soon as the temperatures are stale (no fresh reading for
     10 s), thermalStatus is at least `overheated`, whatever the held reading. selfdrived then raises its stock
     `overheat` event: SOFT_DISABLE "System Overheated" when engaged (the stock 3 s soft-disable, then disengage) and
     NO_ENTRY otherwise; offroad it blocks going onroad. So an engaged car is disengaging within about 10.5 s of the
     last good reading (10 s plus one 0.5 s loop step). The device does not go offroad (only `critical` does that,
     as stock). Stock instead stopped deviceState, and selfdrived raised commIssue within 5 s.
   - `"nap"` (NAP's design): fan 100 % from 10 s; `overheated` at once if the held reading was warm (at or above the
     overheated band's entry temperature), otherwise after 60 s more of staleness (70 s after the last fresh reading). A thermal reader that hangs
     onroad with a cool last reading therefore allows up to about 70 s engaged without fresh temperatures.
   The hang is logged by name either way (`hardwared slow thermal zone`, `hardwared thermal stale`).
10. Logging for tester logs: a reader thread that dies logs `hardwared reader thread died` (reader, exception); a
   non-thermal read with no fresh value for 10 s logs a warning naming the read plus `hardwared device reads stale`;
   no thermal reading at the start logs `hardwared no thermal reading yet: offroad, fan 100 % until it arrives` once
   (and `hardwared first thermal reading` with the wait when it lands), and the existing stock
   `Offroad_TemperatureTooHigh` alert shows "no reading" instead of a temperature (no new UI).
11. Limitation: stale non-thermal values (free space, memory, CPU/GPU load, brightness, power draw) are held and
   logged, not failed: a reader that hangs after its first read keeps the last real free space and memory, so
   selfdrived's outOfSpace/lowMemory checks see the held values until it recovers. Still on the deviceState loop (as
   in NAP; the 1 s step timer covers them): the `/dev/kmsg` write, the IsEngaged Params write, the offroad power read
   and `set_power_save`. Contention for the Python interpreter lock between the reader threads and the loop is not
   covered by these changes.

## Safety
- Held readings keep driving the bands, a warm device fails hot as soon as its readings go stale, a cool one fails
  hot after 60 s more, and the fan runs at full the whole time. Before the first reading the device is held offroad
  with the fan at full. Stock instead stopped publishing, which selfdrived treated as commIssue within 5 s; the one
  path that can be slower than stock is divergence 9 with the `"nap"` policy (strict is the default).
- No change to panda safety, CAN, controls, selfdrived's checks or any cereal schema.

## Tests
- `openpilot/system/hardware/tests/test_hardwared_loop_rate.py`: the real `hardware_thread` with fake messaging and fake
  device reads. A 12 s SoM power-draw read and a 12 s thermal-zone read each keep deviceState at >= 1.9 Hz with no gap
  over 0.6 s and the last values held; thermal stale and warm goes `overheated` with a full fan; stale and cool holds,
  then goes `overheated` after the fail-hot time; fresh stays normal; a 1.3 s iteration logs every step; the loop makes
  no direct device reads. The rate, stale and timer cases fail on the inline build.
- Also end to end: a first thermal read slower than the 2 s startup wait at 85 C (first published temperature is the
  real one, fan 100 % before it, no onroad until the filtered temperature is below the offroad danger temperature); no
  thermal reading at all (never onroad, fan 100 %, at least `overheated`); the thermal reader thread dying (stale, fan
  100 %, then `overheated`); device reads hung from the start (fail-closed free space and memory, never onroad,
  stale log); the boot check latch.
- `openpilot/system/hardware/tests/test_bg_reads.py`: reader cache and error handling, a hung read never blocks,
  thermal zones match `ThermalConfig.get_msg()`, the real 10 s / 60 s thresholds (also after a reader thread dies, with
  an injected monotonic clock), device-read staleness, and the loop timer.
- Credits: NAP (design, thresholds and the fail-hot rule).
