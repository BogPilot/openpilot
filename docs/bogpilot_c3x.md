# BogPilot on comma 3X (AGNOS 19.9)

This is the comma 3X build of BogPilot, published as `bogpilot-tesla`. BogPilot is a
community fork, not a comma product. See the README's testing status for what has
been tested. You are responsible for local laws and for staying attentive behind the wheel.

This page is the install and onboarding guide for the **openpilot 0.11.2 /
AGNOS 19.9** BogPilot comma 3X line. `bogpilot-tesla` is the repository's default
branch, and the release is tagged `bogpilot-tesla-c3x-0.11.2`.

## Install the correct branch

| What you want | Branch | Approx tip (Nov 2026) | AGNOS | openpilot base |
|---|---|---|---|---|
| **BogPilot comma 3X (this guide)** | **`bogpilot-tesla`** | see branch head | **19.9** | **0.11.2** |
| BogPilot for comma 3 (Model S AP1) | `bogpilot-tesla-0.9.7` | see branch head | 10.1 | FrogPilot 0.9.7 |

- Public tree: https://github.com/BogPilot/openpilot/tree/bogpilot-tesla
- Custom-software installer URL (comma setup / Software panel):

```text
installer.comma.ai/BogPilot/bogpilot-tesla
```

### Wrong-branch warning

- **On a comma 3, do not install `bogpilot-tesla`.** comma does not officially support AGNOS 19.9 on comma 3
  hardware. With a comma 3 and a Model S AP1, use `installer.comma.ai/BogPilot/bogpilot-tesla-0.9.7` (AGNOS 10.1).
- The older 0.9.7 / AGNOS 10.1 line on `bogpilot-tesla-0.9.7` has **no shared history** with this tree. Installing it
  on a comma 3X that is already on AGNOS 19.9 will not give you this feature set and reflashes the OS down to 10.1.
- A 0.11.0 / AGNOS 17.2 LTS version will be backported from 0.11.2 once the full legacy Tesla integration is complete
  in v0.11.2.

## Hardware assumptions

- Device: **comma 3X**
- OS: **AGNOS 19.9** (see `launch_env.sh`: `AGNOS_VERSION="19.9"`)
- Tesla **AP1 Model S** (`TESLA_AP1_MODELS`): the only drive-tested car (see the README's testing status)
- Tesla **AP1 Model X** (`TESLA_AP1_MODELX`): manual selection, and strict marker auto-detect. Lateral only, stock ACC, unverified on a car
- Tesla **Pre-AP Model S** (`TESLA_PREAP_MODELS`): lateral through the Pre-AP safety flag, longitudinal only with a Comma Pedal; no engaged drive logs yet
- Tesla **Model S / X AP2**: not supported yet, planned for a future release once we have AP2 rlogs. Today there is no second-panda / powertrain safety path, and Tinkla's AP2 Model X fingerprint is an identical copy of the AP1 Model X fingerprint
- Signed TRES/H7 panda firmware in the tip is left byte-identical; do not flash
  alternate panda firmware from this guide

## Car detection (AP1)

AP1 has **empty `FW_VERSIONS`**. There is no ECU firmware table row that can
select Model S or Model X by itself. Detection therefore works like this:

1. **Preferred — live CAN** via `detect_ap1_candidate` (wired in
   `opendbc.car.car_helpers.get_car` when no other candidate matches):
   - **Model S AP1** when `match_ap1_chassis` is true and there is no Model X marker. This is the same rule as before:
     - **bus0 / chassis** must present all of: `0x45` (8), `0x118` (6), `0x370` (8), `0x20A` (8)
     - **bus2 / autopilot_chassis (stock Mobileye)** must present all of: `0x399` (8), `0x2B9` (8), `0x488` (4)
     - Chassis alone is not enough; Mobileye bus-2 must match too
   - **Model X AP1** only when that same chassis + Mobileye signature matches, at least one Model X-only marker is present, no Model S-only message is present, and every standard bus-0 frame matches Tinkla's Model X capture. An X-looking capture that is not a clean Model X (including an S/X conflict) is left undetected. Model S detection is unchanged when no X marker is present.
2. **Developer fixed fingerprint** — `get_car` honours the process environment
   variable `FINGERPRINT=TESLA_AP1_MODELS` or `FINGERPRINT=TESLA_AP1_MODELX` (standard openpilot fixed-fingerprint
   path). Use only when you intentionally bypass CAN selection (bench harness
   debugging, etc.)
3. **Car Selection (saved CarModel / ForceFingerprint)** — Vehicle Settings has a
   Car Selection page that saves `CarMake` / `CarModel` / `ForceFingerprint` for Auto, Tesla AP1 Model S, or Tesla AP1 Model X. `get_car`
   uses the saved model **only as a fallback when no car was positively detected**
   (CAN signature or env `FINGERPRINT` win). A saved choice can never override a
   detected different car. With no car attached and no saved choice, the result is
   still "no car / MOCK". Model X AP1 from this menu is lateral only, stock ACC, and unverified on a car.

Model X AP2 is not a platform. AP2 needs the powertrain bus and a second panda, and the signed AP1 safety mode does not implement that path. Tinkla's AP2 Model X fingerprint dict is an identical copy of the AP1 Model X dict, so it cannot be told apart on CAN. Pre-AP Model S is supported but untested on a car: no engaged drive logs exist yet (see the README's testing status).

If the device is on a bench **without** a car / harness, or CAN is incomplete,
**"no car detected" / MOCK is expected** for this codepath. Vehicle Controls
rows stay hidden until the fingerprint is `TESLA_AP1_MODELS` or `TESLA_PREAP_MODELS`. Model X does not show those rows.

## Menu map

Top-level settings in this release:

| Top-level | Role |
|---|---|
| Device / Network / Toggles / Software / Developer | Stock-style panels |
| **BogPilot** | BogPilot menu in the 0.9.7 layout: Alerts and Sounds, Driving Controls, Navigation, System Settings, Appearance, Vehicle Settings |

There is no separate Visuals panel: the onroad visuals are under **BogPilot > Appearance** (and the two navigation
widgets under BogPilot > Navigation).

### BogPilot

Active-only shell: empty groups are omitted. Every row has a real consumer and a
UI -> store -> consumer test.

- **Alerts and Sounds**
  - Alert Volume Controller (live reload in `soundd`; Prompt, Prompt Distracted and Warning alerts have a 25% audible floor in both the UI and soundd and cannot be muted; Engage/Disengage/Refuse can be muted)
  - BogPilot Alerts: **Green Light** and **Lead Departed** only (fresh default ON). Goat Scream is not shipped
- **Driving Controls**
  - Driving Model: the stock **Default (stock)** model is the only one shipped. A model you install yourself is checked
    (hashes and 0.11.2 compatibility) before it can be selected; see `tools/bogpilot/BOGPILOT_MODEL_SELECTOR.md`
  - Gas / Brake (needs openpilot longitudinal; edits only offroad): Advanced Longitudinal Tuning (actuator delay, max acceleration, Stop Acceleration and Stopping Rate; Stop Acceleration is limited to -0.5 m/s^2 or lower and Stopping Rate to 0.1 m/s^3 or higher in the UI and again in LongControl, so a stale saved value is clamped; defaults equal stock stopping, and a saved 0.9.7 value stays dormant until you change that row), Conditional Experimental Mode, Longitudinal Tuning (acceleration/deceleration profile, Human-Like Acceleration), Quality of Life (force stop at detected stops, increased stopped distance). Not everything starts stock-equivalent: on the legacy Teslas (AP1 Model S / X, Pre-AP Model S) the Longitudinal Tuning group (acceleration/deceleration profile, Human-Like Acceleration) is live from the first drive with its shown defaults (Sport, Human-Like Acceleration on) until you turn Longitudinal Tuning off, and Driving Personalities, Human-Like Following and the lead detection threshold use their saved or default values from the first drive. Advanced Longitudinal Tuning, Conditional Experimental Mode and Quality of Life stay stock-equivalent until you explicitly turn that group on offroad; their saved legacy values do not activate on their own. Turning a group on applies the values shown in its rows (for example Sport acceleration), so review them first
  - Settings reset (Utilities) restores the fresh-install table and clears all 13 Phase3 adoption markers, so gas/lane-change consumers return to stock until re-adopted.
  - Steering Tuning: Advanced Lateral Tuning parent, Actuator Delay, Steer Ratio, Pause Steering Below, Turn Signal Only (all default OFF/unset = stock steering; friction / lateral-accel rows appear only on torque-controlled cars). Lane Changes (Driving Controls > Lane Changes: Lane Changes, Automatic Lane Changes, delay, minimum speed, minimum lane width, one change per signal) is registered; Automatic (nudgeless) and One-per-signal stay dormant until you change a row offroad (saved legacy values never activate on their own). Blind-spot SNA, stale (>1.5 s without a good 0x399 frame) or invalid data counts as OCCUPIED and blocks lane changes. Human-Like Lane Changes has a row on Driving Controls > Gas / Brake > Longitudinal Tuning, right after Human-Like Following. It shows only when the car has openpilot longitudinal control and radar is not marked unavailable, Disable openpilot Longitudinal is off, Longitudinal Tuning is on, and the tuning level is Advanced or Developer (an unconfirmed tuning level counts as Developer). In this port that means an AP1 Model S with openpilot longitudinal, or a Pre-AP Model S with the pedal and the optional Bosch radar retrofit turned on (Vehicle Settings > Pre-AP: Bosch Radar, `TeslaRadarEnabled`, default Off). Without that toggle Pre-AP is marked radar-unavailable, and AP1 Model X has no openpilot longitudinal, so neither shows the row. It can be changed only offroad. It is on by default on the AP1 Model S, as in 0.9.7, and on a Pre-AP Model S that started with the Bosch radar on (decided at car start; a saved Off is kept); turning it off keeps the normal lead choice during lane changes. Turn Desires has no menu row in this build and stays dormant. Speed Limit Controller settings are under Driving Controls > Gas / Brake on an AP1 Model S with openpilot longitudinal control and on a Pre-AP Model S with the pedal; AP1 Model X has no openpilot longitudinal control, so the controller does not run there and has no settings. On those two cars it is on by default (Speed Limit Controller switch, default On) and the switch turns it off. The set speed follows the dashboard speed limit plus the offset for that speed band, with Fallback Speed, Override Speed and limit confirmation; AP1 Model S also has source priority and a map-data look-ahead toward a lower upcoming limit, and Pre-AP adds Match Speed Limit on Engage. The look-ahead needs offline map data that is not included in this build, and this build has no page to download it, so it does nothing on a normal install.
- **Vehicle Settings**
  - Car Selection (fallback only, see above)
  - Vehicle Controls (only on a detected AP1 Model S or Pre-AP Model S; Model X does not show these rows):
    - AP1 Model S: Disable openpilot Longitudinal Control; Dash Cluster Integration; Earlier, Gentler Regen Stops (with openpilot longitudinal)
    - Pre-AP Model S: Disable Pedal Longitudinal; Bosch Radar (retrofit, default Off) and Radar Behind Nosecone (while Bosch Radar is on); Software and Panda Firmware (read-only); with pedal longitudinal, Comma Pedal status and Calibrate Pedal. Double Pull to Engage Pedal Longitudinal stays hidden while Always On Lateral is unavailable
  - Wheel Controls > Stalk Controls: twist follow, experimental pull/push with a hold time of 1.10-5.00 s, **default 1.23 s**
  - Vehicle Info: read-only last-detected / UNVERIFIED CarParams text
- **System Settings**
  - Data: delete driving data / error logs (confirm), screen recordings, storage use, toggle backups, BogPilot Stats view/reset (reset takes a durable backup first; Stats export is hidden)
  - Device Controls: shutdown timer, low-voltage cutoff, screen brightness/timeout/standby, the Screen Recorder Button. Fresh-install defaults equal stock openpilot power behaviour (30 hour shutdown, 30 s offroad / 10 s onroad screen timeout, stock voltage cutoff); the compiled 0.9.7 defaults (6 hour, 30 s) are moved to stock once at manager startup, saved choices are preserved, and the adjustable ranges are unchanged
  - Utilities: debug mode, Reset BogPilot Settings to Defaults (restores shipping defaults after a backup), Reset Toggles to Stock, clear caches, local debug report

### Appearance (BogPilot > Appearance)

Rows: Confidence Ball and Confidence Ball Side, Adjacent Lead Speed Boxes (default ON),
Blind Spot Lane Fill, Blind Spot Border, Bog to the Future, Driving Personality Button,
Pedals on Screen, Show Driver Camera When In Reverse, Camera View, the parent toggles
Quality of Life Visuals and Driving Screen Widgets, Dynamic Pedals, Lower Speed Limits Box,
and the developer rows (Show Accel Graph, Developer HUD, FPS Display, Developer Sidebar,
Show IP in Sidebar). The blind spot rows and Bog to the Future are hidden on a Pre-AP
Model S, which reports no blind spot data. Navigation Widgets and Show Speed Limits are
under BogPilot > Navigation. Temperature units, CPU and memory are not menu rows: tap the
sidebar box to cycle them. Defaults and details are in the README's Features and defaults.

### Not in this build

| Area | State |
|---|---|
| Lane Changes (automatic/nudgeless) | Integrated with adoption markers and BSM fail-closed; Human-Like Lane Changes has a row under Gas / Brake > Longitudinal Tuning only on an AP1 Model S with openpilot longitudinal (gated as described under Driving Controls above) and is on by default there, as in 0.9.7; the Turn Desires consumer is present but has no menu row (dormant) |
| Drive stats producer (`trackd`) | Present but needs extra verification before relying on it |
| Driving Model | Stock model only ships; user-installed models are validated before they can be selected |
| Always-On Lateral (AOL) | **Blocked** (safety findings); out of runtime |
| The Bog | Not restored |

## Known limits

- Missing menus on a fresh install are often **by design** of the active-only build, not a failed publish
- Testing is as listed in the README's testing status: AP1 Model S only, and no other driver or car has tested this build
- AP1 fingerprint needs the CAN signature (or developer `FINGERPRINT`); empty FW table
- Drive Stats producer needs extra verification before you rely on it
- AOL core excluded; only the stock driving model ships; Goat Scream skipped
- Telemetry: the tip's own cloud/uploader toggles default OFF and are audited by tests; no claim beyond what those tests prove (see the README's Privacy section)
- Lineage note: Pre-AP signal definitions come from BogPilot 0.9.7, Tinkla / BogGyver and NotAutopilot (NAP). Tinkla and BogPilot's own code are primary; NotAutopilot is contrast / fill only

## After install checklist

1. Confirm Software / branch shows **`bogpilot-tesla`**
2. Confirm device is on **AGNOS 19.9**
3. Connect harness + car (or set developer `FINGERPRINT` only if you know why)
4. Expect Vehicle Controls only after an AP1 Model S or Pre-AP Model S fingerprint
5. Expect the BogPilot menu as above (Alerts and Sounds, Driving Controls, Navigation, System Settings, Appearance, Vehicle Settings); Lane Changes is under Driving Controls > Steering

## Related docs in this tree

- `docs/bogpilot_c3x_provenance.md` — provenance and credits
- `docs/c3x_startup_smoke.md` — startup lifecycle sandbox smoke
- `docs/c3x_settings_backup.md` / `docs/c3x_toggle_reset.md` — settings backup & reset
- `docs/rc_startup_gate.md` — RC startup gate
