# BogPilot theme

BogPilot ships its own theme pack, named **BogPilot**. It is selected by
default. The original FrogPilot theme stays available in the theme picker.

## What the BogPilot theme looks like

Since the AP1 defaults update (October 2026) the BogPilot theme renders like
the stock openpilot look, matching the maintainer's own device:

| Component | BogPilot theme renders as | Before |
| --- | --- | --- |
| Colors (path, lane lines, lead marker, sidebar) | stock openpilot | FrogPilot green |
| Sidebar icons (home / flag / settings) | stock openpilot | animated frog icons |
| Engage / disengage sounds | stock openpilot | FrogPilot frog sounds |
| Turn-signal animation | none | FrogPilot frog animation + blind-spot frame |
| Steering wheel icon | stock openpilot wheel | frog wheel |
| Follow-distance icons | BogPilot icons (unchanged) | BogPilot icons |

Two parts make that work, both Python or assets, so no UI rebuild is needed:

1. `frogpilot/common/frogpilot_variables.py` (`BOGPILOT_THEME_RESOLVES_TO`,
   `resolve_bogpilot_theme`): when a theme param is `BogPilot`, the toggle the
   UI and soundd read is `stock` (or `none` for turn signals). The prebuilt UI
   only uses its built-in stock rendering (stock path gradient, red lead
   chevron, stock wheel with the experimental-mode icon) when the value is
   literally `stock`, which a colors.json cannot reproduce.
2. The pack itself (`frogpilot/assets/bogpilot_theme`) now carries the stock
   assets, so the picker, random themes and The Pond see the same look:
   `colors/colors.json` is the stock color file, `icons` and `sounds` link to
   `selfdrive/assets/images` and `selfdrive/assets/sounds`,
   `steering_wheel/wheel.png` links to the stock wheel, and `signals/` holds no
   frames.

Holiday themes still take over during holiday weeks when "Holiday Themes" is on.

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

- `icons/` — sidebar / home / settings icons (link to the stock images)
- `sounds/` — engage / disengage wavs (link to the stock sounds)
- `signals/` — turn-signal frames (empty: no animation)
- `distance_icons/` — follow-distance button icons
- `steering_wheel/wheel.png` — top-right wheel icon (link to the stock wheel)

Colors, icons, sounds, signals and the wheel are also mapped to stock in
`BOGPILOT_THEME_RESOLVES_TO`; to give BogPilot its own colors or sounds again,
remove that component from the map as well as editing the files here.

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
