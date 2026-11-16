# Pre-AP Bosch radar: donor VIN, config gate, 0x2A9 byte 7, Read Radar VIN

References: NAP `naponsp-alpha-prebuilt` `7eb09d2a7` (opendbc `5dbe36d37`, panda `a8f6ff22d`), NAP commits `347ac59b` /
`edd064aa` (donor VIN + F190), `604b9c49` (config gate), `f00c8cb9` (position from the donor config), `a2cdda8e` (no byte-7
checksum); BogPilot na-preap `c68fda744`; Tinkla/BogGyver `501c7de`.

## 1. 0x2A9 byte 7 (now matches all references)
- Before: the panda overwrote 0x2A9 byte 7 with an address + data byte sum (ported from NAP `cc39c7fa`), which also changed
  GTW_autopilot and the other byte-7 bits.
- Now: no checksum. Byte 7 = (car 0x398 byte 7 & 0xCF) | 0x10, i.e. GTW_autopilot = 1. Bosch BO_681 is "all fixed bytes, no
  checksum" (`opendbc/dbc/generator/tesla/tesla_radar_bosch.py:158,249`). Same as NAP `a2cdda8e`
  (`opendbc/safety/modes/tesla_preap.h:346-367` @ `5dbe36d37`), na-preap `c68fda744` and Tinkla (`safety_tesla.h:462-484`).

## 2. Host 0x560 donor config and the config gate (NAP, one rule stricter)
- 0x560 is host to panda only: on the TX list as {0x560, bus 0, 8}, the tx hook consumes it and returns false, so it never goes
  on the car. Three records: 0 = useRadar, position (0..2), EPAS type, VIN[0:3]; 1 = VIN[3:10]; 2 = VIN[10:17]
  (NAP `tesla_preap.h:199-228`, `teslacan.py:83-97`).
- Gate (NAP `604b9c49`, `tesla_preap.h:178-184`): with flag 256 the panda sends no radar-bus GTW frame until all three records
  have arrived with useRadar set. All donor state is cleared on every safety init.
- Stricter than NAP: 0x560 is ignored without flag 256 and while controls are allowed or the steering latch is armed, so the radar
  contract cannot change mid-engagement (NAP accepts it at any time).
- Host stream (ours): one record every 10 frames, only with flag 256, only while openpilot is disengaged and the car is not in
  Drive. NAP streams it all the time. Reason: the panda counts every consumed 0x560 as a blocked TX
  (`panda/board/drivers/can_common.h:169`), and the Pre-AP pull FSM reads a blocked TX as a pedal refusal and drops FULL to
  steering only (`selfdrive/car/card.py`, `tesla_ap1/preap/carstate.py`). The car starts in Park, so the config is complete about
  0.3 s after start. Limit: if the panda re-inits its safety mode while the car is in Drive, the radar stays silent until the
  car is next out of Drive.

## 3. Donor VIN substitution (NAP)
- `TeslaRadarDonorVin` (BogPilot params dir, empty by default). Empty = 17 spaces = this car: no substitution, the car's own
  0x405 VIN records reach the radar on 0x2B9 as before.
- With a donor VIN: 0x405 records 0x10 / 0x11 / 0x12 go to the radar on 0x2B9 with the donor VIN, and 0x2A9 declares 4WD when
  donor VIN character 8 is '2' or '4' (NAP `tesla_preap.h:346-389`). Still firmware-originated on bus 1 only; host 0x2B9 / 0x2A9
  stay blocked; nothing is forwarded (`disable_forwarding` stays on).

## 4. Radar position
- Before: position = 1 when flags 256 and 128 are both set (`tesla_preap.h:276` @ `8636c8044`), so a nosecone install with the
  radar on (safety param 480 = 32 | 64 | 128 | 256) sent 1. Tinkla sets 1 for its behind-nosecone flag; na-preap the same.
- NAP `f00c8cb9` takes the position from 0x560 record 0 (its Donor Radar Position setting, 0 pre-facelift S, 1 post-facelift S,
  2 Model X, default 0) and keeps the nosecone flag only as a leftover bit.
- The references disagree on what the field means. Tinkla `501c7de` (`safety_tesla.h:1355-1357`, its behind-nosecone flag) and
  na-preap treat it as the mounting: 1 behind the nosecone. NAP `@7eb09d2a7` treats it as the donor car type: `NAPRadarPosition`
  (`nap_conf.py:41,256-261`, default 0), shown as 0 pre-facelift Model S, 1 facelift Model S, 2 Model X (sunnypilot
  `nap.py:287-288`).
- Now (as NAP): a separate Radar Donor Type setting (`TeslaRadarDonorType`, /data/params_bogpilot, 0 / 1 / 2, default 0, a bad
  value is 0) goes in 0x560 record 0, and the panda takes the position from 0x560. The nosecone toggle and flag 128 no longer
  pick the value (the panda init value from flag 128 is replaced by record 0 before the gateway opens). No panda C change was
  needed for this: the panda already took position from 0x560 (only its comments were updated to say so).
- Radar Behind Nosecone is hidden from Vehicle Settings (owner decision), since it has no effect on the car any more. Its stored
  value (`TeslaRadarBehindNosecone`) is kept as is, not deleted or migrated: it still sets flag 128, which nothing reads except
  the replaced init value (NAP keeps its nosecone bit as a leftover too). Divergence from NAP and Tinkla, which both show it.
- Behavior change: before, a nosecone install with the radar on (480) sent 1; with the default it now sends 0. A car whose radar
  wants 1 must pick "Model S facelift". Same disengaged-only rule as the rest of 0x560.

## 5. Radar UDS: read-only F190 and the Read Radar VIN button
- Panda: {0x641, bus 1, 8} on the TX list; the tx hook allows only NAP's six exact frames (tester present, default and extended
  session, read DID F190, flow control, tester present without reply), only with flag 256 and only while controls are not
  allowed and the steering latch is not armed (NAP `tesla_preap.h:137-172`; NAP also checks its lateral-only flag, we check the
  latch). No write, routine or security access frame can pass. 0x641 on bus 0 / 2 and any other UDS address stay blocked.
- Host: NAP's F190 reader (`radar_donor_vin.py`) without its Commissioner: no automatic start (NAP starts a read by itself on the
  0x501 vinValidity alarm). It starts only from Vehicle Settings > "Pre-AP: Read Radar VIN" (car on, not engaged, radar on).
  Engaging, lateral, the panda reporting controls allowed, or missing pandaStates stop it at once.
- The VIN read is stored only in `TeslaRadarDonorVin` and used from the next car start. It is shown on the device under the button
  only. It is kept out of log text (carlog / cloudlog / print), crash reports, the status text (NAP `card.py:216` puts it there;
  not ported), openpilot Params (so never in the initData params snapshot), settings backups and the settings dump. It IS present
  in raw CAN in the drive logs, as below. Accepted by the owner: the donor VIN in raw CAN is treated like the car's own VIN on
  0x405, so the 0x560 path is kept and the panda does not store it any other way.
- Raw CAN in the drive logs does carry VIN bytes. The car's own VIN is on 0x405 on every Tesla. The radar's 0x651 reply and the
  panda's 0x2B9 frames are raw bus-1 traffic. The host's 0x560 frames, which carry the donor VIN, are logged in `sendcan`
  (`cereal/services.py:39`, logged), and the panda consumes each one and returns it as a rejected echo in `can` (src + 0xC0;
  `panda/board/drivers/can_common.h:169-175`, `selfdrive/pandad/panda.cc:265-266`).
- Not ported: NAP's radar VIN-learn tool (`vin_learn_radar.py`), which reprograms the radar.
