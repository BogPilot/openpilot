# bogpilot OSM Map Data (mapd) - slice 1

Producer side of the 0.9.7 "Map Data" speed-limit source. **No planner activation, no UI rows, nothing starts on a device**:
the `bogpilot_mapd` process only runs when the `Phase3MapDataEnabled` file marker is true, a region is selected and the
pinned mapd binary verifies. Nothing writes the marker in this slice.

| module | role |
|---|---|
| `mapd_manifest.json` | pins mapd v1.12.0 (what 0.9.7 ran): sha256, size, source tag/commit, MIT |
| `installer.py` | hash-verified install of that binary (0.9.7 downloaded "latest" and ran it) |
| `storage.py` | `/data/media/0/osm` layout, size, free-space reserve, guarded remove/reset |
| `regions.py` | nation/state catalog (mapd bounding boxes + 0.9.7 grouping), `MapsSelected`, 2x2-degree cell/size estimate |
| `downloads.py` | 0.9.7 schedule (Manually/Weekly Sunday/Monthly 1st), start/cancel/progress/completion |
| `gps_feed.py` | gpsLocation -> `LastGPSPosition` JSON for mapd (0.9.7 used liveLocationKalman, absent in 0.11.2) |
| `map_data.py` | validated reader of `MapSpeedLimit`/`NextMapSpeedLimit` + 0.9.7 lookahead swap |
| `memparams.py` | mapd's `/dev/shm/params/d` files (fixed key set) |
| `supervisor.py` | process entry: runs the verified binary with backoff and feeds GPS |

Licenses: mapd and the region boxes are MIT (Copyright 2023 Jacob Pfeifer, see `LICENSE.mapd`); the region grouping is from
BogPilot (MIT). Map data is OpenStreetMap-derived (ODbL): the UI slice must show "(c) OpenStreetMap contributors".
`catalog/*.json` are byte-copies from mapd tag v1.12.0.
