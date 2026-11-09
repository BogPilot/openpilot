# BogPilot on comma 3X (AGNOS 19.9)

**Status:** research / do-not-use candidate (t994 integration build). Not a release product. Stationary
offroad validation only unless a later note says otherwise. You are responsible
for local laws and for staying attentive behind the wheel.

This page is the install and onboarding guide for the **openpilot 0.11.2 /
AGNOS 19.9** BogPilot comma 3X line. It exists because GitHub's default branch
for this fork is still an older tree and is easy to install by mistake.

## Install the correct branch

| What you want | Branch | Approx tip (Nov 2026) | AGNOS | openpilot base |
|---|---|---|---|---|
| **BogPilot comma 3X (this guide)** | **`bogpilot-c3x-donotuse`** | see branch head | **19.9** | **0.11.2** |
| Do **not** use for 3X AGNOS 19.9 | `bogpilot-tesla` (GitHub default) | `04d560f3…` | 10.1 era | 0.9.7 |

- Public tree: https://github.com/BogPilot/openpilot/tree/bogpilot-c3x-donotuse
- Custom-software installer URL (comma setup / Software panel):

```text
installer.comma.ai/BogPilot/bogpilot-c3x-donotuse
```

### Wrong-branch warning

`bogpilot-tesla` is the repository default. It is an older 0.9.7 / AGNOS ~10.1
line with **no shared history** with `bogpilot-c3x-donotuse`. Installing it on a
comma 3X that is already on AGNOS 19.9 will not give you this feature set and
can leave you on the wrong OS pin. Always enter the **`bogpilot-c3x-donotuse`**
installer URL above (or flash a package built from that tip).

`BogPilot-donotuse` as a branch name does **not** exist. The published name is
lowercase `bogpilot-c3x-donotuse`.

## Hardware assumptions

- Device: **comma 3X**
- OS: **AGNOS 19.9** (see `launch_env.sh`: `AGNOS_VERSION="19.9"`)
- Supported research target for this tip: Tesla **AP1 Model S** (`TESLA_AP1_MODELS`)
- Signed TRES/H7 panda firmware in the tip is left byte-identical; do not flash
  alternate panda firmware from this guide

## Car detection (AP1)

AP1 has **empty `FW_VERSIONS`**. There is no ECU firmware table row that can
select the car by itself. Detection therefore works like this:

1. **Preferred — live CAN signature** via `match_ap1_chassis` (wired in
   `opendbc.car.car_helpers.get_car` when no other candidate matches):
   - **bus0 / chassis** must present all of: `0x45` (8), `0x118` (6), `0x370` (8), `0x20A` (8)
   - **bus2 / autopilot_chassis (stock Mobileye)** must present all of: `0x399` (8), `0x2B9` (8), `0x488` (4)
   - Chassis alone is not enough; Mobileye bus-2 must match too
2. **Developer fixed fingerprint** — `get_car` honours the process environment
   variable `FINGERPRINT=TESLA_AP1_MODELS` (standard openpilot fixed-fingerprint
   path). Use only when you intentionally bypass CAN selection (bench harness
   debugging, etc.)
3. **Car Selection (saved CarModel / ForceFingerprint)** — Vehicle Settings has a
   Car Selection page that saves `CarMake` / `CarModel` / `ForceFingerprint`. `get_car`
   uses the saved model **only as a fallback when no car was positively detected**
   (CAN signature or env `FINGERPRINT` win). A saved choice can never override a
   detected different car. With no car attached and no saved choice, the result is
   still "no car / MOCK"

If the device is on a bench **without** a car / harness, or CAN is incomplete,
**"no car detected" / MOCK is expected** for this codepath. Vehicle Controls
rows stay hidden until the fingerprint is `TESLA_AP1_MODELS`.

## Menu map

Top-level settings on the t994 integration build:

| Top-level | Role |
|---|---|
| Device / Network / Toggles / Software / Developer | Stock-style panels |
| **BogPilot** | Active BogPilot feature shell |
| **Visuals** | Separate BogPilot onroad visuals panel (not renamed into BogPilot) |

### BogPilot

Active-only shell: empty groups are omitted. Every row has a real consumer and a
UI -> store -> consumer test.

- **Alerts and Sounds**
  - Alert Volume Controller (live reload in `soundd`; Prompt, Prompt Distracted and Warning alerts have a 25% audible floor in both the UI and soundd and cannot be muted; Engage/Disengage/Refuse can be muted)
  - BogPilot Alerts: **Green Light** and **Lead Departed** only (fresh default ON). Goat Scream is not shipped
- **Driving Controls**
  - Gas / Brake (needs openpilot longitudinal; edits only offroad): Advanced Longitudinal Tuning (actuator delay, max acceleration, Stop Acceleration and Stopping Rate; Stop Acceleration is limited to -0.5 m/s² or lower and Stopping Rate to 0.1 m/s³ or higher in the UI and again in LongControl, so a stale saved value is clamped; defaults equal stock stopping, and a saved 0.9.7 value stays dormant until you change that row), Conditional Experimental Mode, Longitudinal Tuning (acceleration/deceleration profile, Human-Like Acceleration), Quality of Life (force stop at detected stops, increased stopped distance). Everything is stock-equivalent until you explicitly turn a group on offroad; saved legacy values do not activate on their own. Turning a group on applies the values shown in its rows (for example Sport acceleration), so review them first
  - Settings reset (Utilities) restores the fresh-install table and clears all 13 Phase3 adoption markers, so gas/lane-change consumers return to stock until re-adopted.
  - Steering Tuning: Advanced Lateral Tuning parent, Actuator Delay, Steer Ratio, Pause Steering Below, Turn Signal Only (all default OFF/unset = stock steering; friction / lateral-accel rows appear only on torque-controlled cars). Lane Changes (Driving Controls > Lane Changes: Lane Changes, Automatic Lane Changes, delay, minimum speed, minimum lane width, one change per signal) is registered; Automatic (nudgeless) and One-per-signal stay dormant until you change a row offroad (saved legacy values never activate on their own). Blind-spot SNA, stale (>1.5 s without a good 0x399 frame) or invalid data counts as OCCUPIED and blocks lane changes. Human-Like Lane Changes and Turn Desires have no menu row in this build and stay dormant. Speed Limit Controller is **not** in this build (held, see below)
- **Vehicle Settings**
  - Car Selection (fallback only, see above)
  - Vehicle Controls: three AP1 toggles, only when fingerprint is `TESLA_AP1_MODELS`: Disable openpilot Longitudinal; Dash Cluster Integration; Earlier, Gentler Regen Stops
  - Stalk Controls (replaces "Wheel Controls"): twist follow, experimental pull/push with a hold time of 1.10-5.00 s, **default 1.23 s**
  - Vehicle Info: read-only last-detected / UNVERIFIED CarParams text
- **System Settings**
  - Data: delete driving data / error logs (confirm), screen recordings, storage use, toggle backups, BogPilot Stats view/reset (reset takes a durable backup first; Stats export is hidden)
  - Device Controls: shutdown timer, low-voltage cutoff, screen brightness/timeout/standby. Fresh-install defaults equal stock openpilot power behaviour (30 hour shutdown, 30 s offroad / 10 s onroad screen timeout, stock voltage cutoff); the compiled 0.9.7 defaults (6 hour, 30 s) are moved to stock once at manager startup, saved choices are preserved, and the adjustable ranges are unchanged
  - Utilities: debug mode, Reset BogPilot Settings to Defaults (restores shipping defaults after a backup), Reset Toggles to Stock, clear caches, local debug report

### Visuals

Separate top-level panel. Existing rows: Adjacent Lead Speed Boxes (default ON),
Blind Spot Lane Fill, Blind Spot Border, Driving Personality Button, Pedals on
Screen, Screen Recorder Button, Show Driver Camera When In Reverse. Added rows
(each with a consumer): Dynamic Pedals, Swap Speed Graph, Fahrenheit, Numerical
Temperature, Show CPU, Show Memory Usage, Navigation/Speed-limit display, and the
parent toggles that gate them.

### Not in this build

| Area | State |
|---|---|
| Speed Limit Controller / Following | Held: high-risk longitudinal control, not integrated yet |
| Lane Changes (automatic/nudgeless) | Integrated with adoption markers and BSM fail-closed; Human-Like Lane Changes / Turn Desires consumers present but no menu row (dormant) |
| Drive stats producer (`trackd`) | Present but needs owner authorization before relying on it |
| Model Selector | **Paused** (stock models only) |
| Always-On Lateral (AOL) | **Blocked** (safety findings); out of runtime |
| The Bog | Not restored unless newly authorized |

## Known limits

- Research / do-not-use: no claim of road or full-release acceptance from this doc
- Missing menus on a fresh install are often **by design** of the active-only build, not a failed publish
- No physical validation of alert audio, reverse camera or on-road behavior has been done; stationary offroad bench only
- AP1 fingerprint needs the CAN signature (or developer `FINGERPRINT`); empty FW table
- Drive Stats producer needs explicit owner authorization before you rely on it
- AOL core excluded; Model Selector paused; Goat Scream skipped
- Telemetry: the tip's own cloud/uploader toggles default OFF and are audited by tests; no claim beyond what those tests prove (see README User Data section)
- Lineage note: Pre-AP signal **data values** may come from an **upstream legacy port** (data only). BogPilot does not ship that port's code. Tinkla and BogPilot's own code are primary; NotAutopilot is contrast / fill only

## After install checklist

1. Confirm Software / branch shows **`bogpilot-c3x-donotuse`** (not `bogpilot-tesla`)
2. Confirm device is on **AGNOS 19.9**
3. Connect harness + car (or set developer `FINGERPRINT` only if you know why)
4. Expect Vehicle Controls only after AP1 fingerprint
5. Expect BogPilot (Alerts and Sounds, Driving Controls > Steering Tuning, Vehicle Settings, System Settings) + Visuals as above; Lane Changes is present, Speed Limit Controller is not

## Related docs in this tree

- `docs/bogpilot_c3x_provenance.md` — authorship / provenance audit
- `docs/c3x_startup_smoke.md` — startup lifecycle sandbox smoke
- `docs/c3x_settings_backup.md` / `docs/c3x_toggle_reset.md` — settings backup & reset
- `docs/rc_startup_gate.md` — RC startup gate
