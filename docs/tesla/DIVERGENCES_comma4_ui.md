# Divergences: BogPilot driving screen on the comma 4

Entries in the `docs/tesla/DIVERGENCES.md` style, kept in their own file so they can be folded into `DIVERGENCES.md`.

Scope: the comma 4 driving screen only (device type `mici`, 536 x 240, the camera view is the 476 x 240 content rect
left of the stock side panel). The gate is `c4_layout.comma4_device()`; the 3X driving screen does not run any of this
code. Display only: no CAN, panda, car state, controls or Params
writes, except the personality tap described below (the same Param the stock stalk / settings write).

Sources used: stock openpilot 0.11.2 comma 4 UI (`selfdrive/ui/mici/onroad`: HUD order, torque bar geometry, turn
intent, driver-monitor icon and its AlwaysOnDM rule, alerts, `turn_signal_left.png`); BogPilot (redesign cluster: speed
pill, personality stripes, record ring, lead lock-on boxes and speed labels, steering arc colours, status / BSM border
colours, flame tracks, 3-bar pedal gauge); Tinkla/BogGyver (blind-spot border half, Traffic Mode border red, from the
earlier `bg_colors` table). NAP: no comma 4 or onroad UI path, nothing taken. No signal was added; every input below is
an existing message field.

Code: `openpilot/selfdrive/ui/onroad/bogpilot/c4_layout.py` (geometry, gate, visibility), `c4_paint.py`,
`c4_leads.py`, `c4_arc.py`, `bogpilot_hud.py` (`BogPilotMiciHudRenderer`), `mici/onroad/augmented_road_view.py`
(three hook calls and the tap routing). Tests: `onroad/bogpilot/tests/test_c4_layout.py`, `test_c4_hud.py`,
`test_c4_gauge_arrows_record.py`, `test_c4_leads_dm.py`, `test_c4_arc_border.py`.

### comma 4: no stock wheel icon, one speed pill
- Reference behavior: stock comma 4 draws a set-speed box and a steering wheel icon (with its turn-intent arrows and
  the red "critical" wheel during steerRequired alerts). BogPilot 3X uses the redesign cluster.
- Our behavior: no wheel icon and no stock set-speed box. One pill at (6, 6)-(174, 58) holds the set speed (MAX),
  the current speed with its unit and the speed-limit tile (shown under the same speed-limit display policy as the
  3X). Nothing is drawn to the right of the pill. Take-control is shown on the personality button instead of the wheel.
- Why: the comma 4 layout design; the 3X cluster does not fit 240 px.

### comma 4: the personality button is the personality indicator
- Our behavior: a 40 px disc at (28, 212), lower left, with the BogPilot personality stripes from
  `selfdriveState.personality` (Traffic Mode colour when Traffic Mode is on). During a take-control alert (the stock
  steerRequired visual alert) it turns the stock critical-wheel orange, the stripes go white and a red "!" with a white
  border sits over it. A tap steps the personality the way the stalk does (relaxed -> standard -> aggressive ->
  relaxed) by writing `LongitudinalPersonality`; with Traffic Mode on, or no fresh personality, the tap is consumed and
  nothing is written. The stock turn-intent arrow is drawn over this button (its filters are driven by the stock
  onroadEvents code).
- Known drawing difference: the "!" and the stripes are 1 px smaller than the design (inclusive vs exclusive rects),
  and the design's radial shade on the disc is not reproduced.

### comma 4: 3-bar pedal gauge (shared module)
- Our behavior: the shared BogPilot 3-bar gauge (`pedal_gauge3.py` state, palette, regen kW smoothing and painter, fed
  by `pedals.PedalGauge` with the same inputs as the 3X) drawn at (8, 112), 40 x 76 px, hard left above the personality
  button, with design scale 0.5 (2 px fill inset). Shown under the same pedal display policy as the 3X.
- Divergence from the design: the track, its edge and the fill opacity come from the shared painter (darker track,
  2 px edge, 75 % fill) instead of the design's lighter track; the colours are the shared palette (the same hex values
  as the design). Kept so the comma 4 and the 3X use one gauge.

### comma 4: lane-change arrows from lane-change events only
- Reference behavior: the stock comma 4 shows the turn intent on the wheel icon from `preLaneChange*` / `laneChange`.
- Our behavior: a green stock turn-signal arrow under the pill (left) or under the driver-monitor icon (right), only
  while `preLaneChangeLeft/Right` or `laneChange` is in `onroadEvents` (direction from the event or
  `modelV2.meta.laneChangeDirection`). The blinkers are not read.
- The stock lane-change alert is on screen at the same moments and the left arrow overlaps it. Default
  `ARROWS_WITH_STOCK_LC_ALERT = "overlap"` (both drawn); `"hide"` hides the arrows while that alert shows.

### comma 4: record button in the side panel
- Our behavior: the BogPilot record ring scaled to a 40 px disc at (508, 212), in the stock side panel under the
  confidence ball. Shown and tapped under the same screen-recorder rule as the 3X.

### comma 4: lead and adjacent-lead boxes always on, speeds only
- Reference behavior: stock comma 4 draws no lead chevron; BogPilot 3X shows the lock-on boxes with speed and distance
  under its lead-marker policy.
- Our behavior: the shared lock-on core (`lead_lockon.LeadLockOn`) scaled to the comma 4 view draws the lead and the
  adjacent-lead boxes, engaged or not, with the lead speed above the box and no distance label. The adjacent boxes are
  sized by the core (distance and lateral offset), which differs from the design's fixed sizes by up to 1-2 px.
- Labels keep clear of the gauge, the turn-intent arrow's rotated footprint and one alert text zone (4, 0)-(472, 118):
  a label that would sit under a stock alert moves below its box (the design kept it above in the driver-distracted
  frame, 9.7 px higher).

### comma 4: what hides during alerts
- Our behavior: during any stock alert the pill, the gauge and the driver-monitor icon hide (the stock rule that hides
  the top icons). The lead boxes stay, including during take-control. Each rule is its own constant
  (`TAKE_CONTROL_HIDES`, `OTHER_ALERT_HIDES`).

### comma 4: driver-monitor icon top right, stock AlwaysOnDM rule kept
- Our behavior: the stock driver-monitor icon (60 px, centred on the design's 56 px spot at (414, 8)-(470, 64)) moves
  to the top right. Its visibility is the stock rule: hidden while disengaged unless AlwaysOnDM is on.
- Divergence from the design: the design showed the icon while disengaged regardless of AlwaysOnDM; the stock privacy
  rule is kept.

### comma 4: BogPilot steering arc on the stock torque-bar curve, raised 10 px
- Reference behavior: stock comma 4 torque bar (radius 1200, 12.7 deg span, 22-26 px offset, 14-56 px thickness).
  BogPilot 3X steering arc: driver / openpilot source, angle colours, override tick.
- Our behavior: the BogPilot arc state and colours (`steering_arc.ArcState`, same inputs and rate as the 3X) on the
  stock comma 4 geometry, raised `ARC_RAISE_PX = 10`. Halo widths and the override tick (4 / 2 px) are scaled to the
  small screen. If the arc inputs or paint fail, the stock torque bar is drawn until the next drive. The arc does not
  take the Experimental Mode tap on the comma 4.

### comma 4: thin status border and blind-spot half
- Our behavior: a 3 px border inside the camera view edge, on the stock rounded corner: engaged green `#167F40`,
  override grey `#89928D`, Traffic Mode red while engaged with openpilot longitudinal; none while disengaged. With
  carState `leftBlindspot` / `rightBlindspot` that side's half turns BSM red `#C92231` (alpha F1) with a 5 px edge bar
  under it, under the same rule as the 3X (car reports blind spots, Blind Spot Border or DebugMode; a full-screen or
  critical alert keeps the whole border).
- Divergences: the 3X LKAS-fault flashing border is not drawn on the comma 4; the right-side edge bar mirrors the left
  one (the design only showed the left side).

### comma 4: CEM status badge not drawn
- The 3X CEM status badge (`draw_cem_status`) has no space on the comma 4 layout and is not drawn.

### comma 4: flame tracks unchanged
- The BSM flame tracks (88 mph trigger after the blind-spot fill clears, trail from the passing car) run unchanged in
  the comma 4 model renderer, with the trail starting at the adjacent car's screen point as on the 3X.

- Safety-relevant: none. Display and one existing Param write (personality) only.
- Credits: stock openpilot (comma 4 UI), BogPilot (redesign cluster, arc, border colours, flame tracks, pedal gauge),
  Tinkla/BogGyver (blind-spot border half, Traffic Mode red).
