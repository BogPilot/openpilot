# Pre-AP: Ignore radar HWFail (Vehicle Settings, or ssh)

Pre-AP Model S with the retrofit Bosch radar only. AP1 and every other car ignore this setting
(`opendbc_repo/opendbc/car/tesla_ap1/radar_interface.py`: it is read only inside the Pre-AP branch).

Default: **off**. With it off, a radar that reports `RADC_HWFail` raises radarFault (no entry, soft disable;
the alert is "Radar Error: Restart the Car"). With it on, `RADC_HWFail` is advisory only: the radar points
are kept out of speed control (camera leads are used) and the one "Radar not ready - using camera lead"
warning shows, with no radarFault. Turn it on only for a radar that reports HWFail while otherwise working;
it is NAP's NAPRadarIgnoreHwFail.

## Vehicle Settings (normal way)

On a detected Pre-AP Model S, with Bosch Radar turned on, Vehicle Settings shows
"Ignore Radar Hardware Fault (Pre-AP)". The row is hidden on AP1 and while the car is not yet identified.
Change it while the car is off. The radar code reads it live (the next radar cycle); no restart is needed.

## What it is

- Name: `TeslaRadarIgnoreHwFail` (`opendbc_repo/opendbc/car/tesla_ap1/preap/params.py`, `PreApParamKeys.RADAR_IGNORE_HW_FAIL`).
- Storage: a plain file, `/data/params_bogpilot/TeslaRadarIgnoreHwFail` (`PARAMS_DIR` in the same file). It is not an
  openpilot Params key, so `/data/params/d/` and the params tools do not show it.
- Type: boolean text. `1`, `true` or `on` mean on; `0`, `false` or `off` mean off; a missing, empty or other value is the
  default, off (`get_bool` in the same file).

## Turn it on or off over ssh (fallback)

On the device, if the Vehicle Settings row is not available:

```
# on
echo 1 > /data/params_bogpilot/TeslaRadarIgnoreHwFail
# off
echo 0 > /data/params_bogpilot/TeslaRadarIgnoreHwFail
```

These write a file the car code reads; they change nothing else.

## Live or restart

Live: the radar code reads it every radar cycle through card's in-memory params snapshot, which reloads the file every
0.1 s (`StepCache.REFRESH_S`). No restart is needed; the change takes effect within about a second, onroad or offroad.

## Check it

```
cat /data/params_bogpilot/TeslaRadarIgnoreHwFail
```

`1` means on. Onroad with a radar that reports HWFail: with it on there is no radar fault alert and the
"Radar not ready - using camera lead" warning shows instead; with it off the radar fault alert shows.
