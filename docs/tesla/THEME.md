# BogPilot theme

BogPilot ships its own theme pack, named **BogPilot**, as a full copy of the
current default FrogPilot theme. It is selected by default. The original
FrogPilot theme stays available in the theme picker.

## How themes work here

Theme assets are files under `/data/themes`, selected by existing params and
linked at runtime by `frogpilot/assets/theme_manager.py`:

| Param | Asset | Default |
| --- | --- | --- |
| `CustomColors` | `theme_packs/<name>/colors` | `BogPilot` |
| `CustomIcons` | `theme_packs/<name>/icons` | `BogPilot` |
| `CustomSounds` | `theme_packs/<name>/sounds` | `BogPilot` |
| `CustomSignals` | `theme_packs/<name>/signals` | `BogPilot` |
| `CustomDistanceIcons` | `theme_packs/<name>/distance_icons` | `BogPilot` |
| `WheelIcon` | `steering_wheels/<name>.png` | `BogPilot` |

On boot, `ThemeManager.copy_default_theme()` still installs the FrogPilot
`frog` / `frog-animated` packs (from `holiday_themes/world_frog_day`), and
additionally installs the BogPilot pack from
`frogpilot/assets/bogpilot_theme/` into `/data/themes`.

The theme picker in the prebuilt UI lists packs by scanning
`/data/themes/theme_packs` (and holiday themes / Stock). Because BogPilot is
installed there as a real pack, it appears as **BogPilot** without a UI
rebuild. No new param keys were added (the July `params_pyx.so` would reject
them).

## Editing BogPilot colors later

Edit the source copy, then reboot (or re-run theme install) so it is copied
into `/data/themes`:

```
frogpilot/assets/bogpilot_theme/colors/colors.json
```

Keys: `LaneLines`, `LeadMarker`, `Path`, `PathEdge`, `Sidebar1`, `Sidebar2`,
`Sidebar3` (each with `red` / `green` / `blue` / `alpha`).

Other assets live under the same folder:

- `icons/` — sidebar / home / settings icons
- `sounds/` — engage / disengage wavs
- `signals/` — turn-signal frames
- `distance_icons/` — follow-distance button icons
- `steering_wheel/wheel.png` — top-right wheel icon

Do not edit `/data/themes/...` alone; that tree is overwritten from
`bogpilot_theme` on boot.

## Startup alert is not part of themes

The boot splash ("Your m∞v" / "Hands present, mind at ease" and its dark
background) is **not** controlled by theme packs. It comes from:

- `selfdrive/controls/lib/events.py` (`customStartupAlert`)
- `frogpilot/common/frogpilot_variables.py` (`STARTUP_MESSAGE_*`,
  `migrate_startup_messages`)
- `system/manager/manager.py` (boot migration)

See commit `4759e262` for the prebuilt-device startup alert fix.

## Migration

On first boot of a build that includes this theme, devices whose theme params
are still the stock FrogPilot defaults (`frog`, `frog-animated`, `stock`
distance icons) are moved to `BogPilot`. A one-time marker
`/data/themes/.bogpilot_theme_migrated` prevents that from happening again, so
choosing FrogPilot later keeps FrogPilot. A non-default theme the user already
picked is left alone.
