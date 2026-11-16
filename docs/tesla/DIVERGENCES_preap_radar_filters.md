# Pre-AP Bosch radar retrofit: radar point filters — divergences

References: Tinkla/BogGyver `501c7de`, NotAutopilot (NAP) openpilot `e99f4dc75` / opendbc `cc39c7fa`, BogPilot 0.9.7
`026cfb3` (no Pre-AP radar). Panda safety is unchanged. Every filter below runs on Pre-AP only (`is_preap`); AP1
Model S / Model X behavior is unchanged. Code: `opendbc_repo/opendbc/car/tesla_ap1/preap_radar_filters.py`, used by
`tesla_ap1/radar_interface.py` and `openpilot/selfdrive/controls/radard.py`.

## Measured basis
- One Pre-AP retrofit drive (8 segments, 425 s of radar at 16.66 Hz, `tesla_radar_bosch` DBC on bus 1).
  `RADC_SGUFail` (TeslaRadarSguInfo 0x301, bit 46) was set 6.1 s after the radar started and stayed set to the end;
  `RADC_HWFail` and `RADC_SensorDirty` stayed 0.
- Four tracks (RadarPoint slots 0/1/2/4) held LongDist fixed between 16.4 and 53.4 m (std <= 0.011 m), LongSpeed 0
  and ProbExist 96.875 % for the whole drive while ego speed changed. radard used them as leadOne in 3964 of 7079
  radarState frames: 1941 matched to a camera lead (modelProb >= 0.5) and 2022 from the low-speed override. All
  four longActive spans of the drive (0.66 s in total) had one of them as the lead.
- AP1 (806 segments with TeslaRadarSguInfo, 12.76 h): `RADC_SGUFail` was seen in 3 segments, only at radar power-up
  while parked (4.5 to 18.4 s), never while driving.
- Offline replay: lead selection is this tree's `get_lead`, the filters are this module. The Pre-AP drive has no
  modelV2, so there the logged leads are checked against the filters; AP1 drives are re-selected with their modelV2.

## (1) SGUFail held: camera only, no fault, no alert
- Reference: Tinkla ignores SGUFail on PREAP and keeps the points (`selfdrive/car/tesla/radar_interface.py:89-111` @
  `501c7de`). NAP faults on HWFail only and keeps the points (`opendbc/car/tesla/radar_interface.py:85-88` @ `cc39c7fa`).
- Ours: once `RADC_SGUFail` has been set for 1.0 s of CAN time (`SGUFAIL_HOLD_S`), the Pre-AP radar interface
  publishes RadarData with no points and no error, so radard runs camera only and nothing is shown to the driver.
  Points come back (with new track ids) after SGUFail has been clear for 1.0 s. HWFail still faults, and canError and
  the silent-radar fail-closed rule are unchanged.
- Why 1.0 s: SGUFail never toggled on the Pre-AP drive (set once, never cleared) and on AP1 it only appeared at
  power-up while parked, so there is no on/off data to tune against. 1.0 s ignores a single bad cycle (7 radar cycles
  at the slowest measured 7.4 Hz). On the Pre-AP drive, fixed-track lead frames left with this filter alone: 106
  (0.5 s), 114 (1.0 s), 131 (2.0 s), 181 (5.0 s); 97 of them come before SGUFail was first set. AP1 as if it ran there:
  196 lead frames (all parked at power-up, 0 engaged). Revisit with more Pre-AP drives.
- Divergence: stricter than Tinkla and NAP, which both keep using the points while SGUFail is set.

## (2) Stuck tracks: range fixed while ego speed changes
- Reference: none. Tinkla, NAP and 0.9.7 use every tracked point; this is new BogPilot behavior.
- Ours: radard drops a track when, over the last 5 s, its dRel moved <= 0.2 m, |vRel| <= 0.13 m/s on every sample, and
  ego speed changed by >= 3 m/s. The track is released when its range moves > 0.5 m within the window or it goes away.
- Data: on the Pre-AP drive this filter alone leaves 251 fixed-track lead frames (the first 20 s, before ego speed
  had changed by 3 m/s), and removes all 1941 frames where a fixed track had replaced a camera lead. AP1 as if it ran
  there: 0 lead frames lost on 536 replayed segments (813 held). An earlier 3 s / 0.15 m std detector without the
  vRel test flagged 18 AP1 tracks and lost 1.5 % of AP1 radar-lead frames.
