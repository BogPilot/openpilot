# AP1 lead side check (phantom brake Option C)

Setting: `AP1LeadSideCheck` (file `/data/params_bogpilot/AP1LeadSideCheck`), **default off**. Vehicle Controls row
"Tesla AP1: Ignore Radar Cars to the Side (Experimental)". Read once when radard starts (next car start).

## What changes
`radard.match_vision_to_track` gains `side_check`. When on and ego speed is 34 mph (15.2 m/s) or more, a radar track can
only be the camera lead's match if its sideways position is within 2.5 m (8.2 ft) of the camera lead, or 2x the camera's
sideways std when larger. If no track passes, there is no radar match and `get_lead` uses the camera lead (still subject
to the AP1 vision-only gate, Option A). Below 34 mph, or with the setting off, the match is stock.

Unchanged: the low-speed radar override, the human lane change adjacent-lead preference (preferred track), the AP1 glitch
filter, the vision-only gate, the lead threshold, the planner and MPC, panda safety.

Cars: AP1 Model S, and AP1 Model X only with openpilot longitudinal (same as the AP1 glitch filter). Pre-AP and every
other car: never.

## Why default off
Replay only (no road test with it on). It changes how the lead is matched, not a threshold. When it falls back to the
camera lead the lead's speed is the camera's estimate, which can be several mph off for a moment.
