# Adaptive Accel Near Lead (AP1 and Pre-AP)

Toggle `AdaptiveAccelLead`, Gas / Brake > Longitudinal Tuning, legacy Teslas only (AP1 Model S / X, Pre-AP Model S). OFF by default.
Offroad-only like the rest of Gas / Brake (page lock unchanged). Needs Longitudinal Tuning on.

Credit: NAP / sunnypilot Tesla Pre-AP "Adaptive Accel Limits" (MIT). The follow-limit table and the 1.2x..1.5x blend are NAP's values.

## What it does
Near a tracked lead the final planner accel is capped: `cap = ceiling*(1-s) + follow_limit(v)*s`, where `s` = clip(1 - (r - 1.2)/0.3, 0, 1),
`r` = (lead gap + v_lead^2 / 2*2.5) / (v^2 / 2*2.5 + t_follow*v + 6). `ceiling` = the accel max the cruise path may ask for now (the
Gas / Brake profile max, or the stock limit). Only a positive request is lowered; braking, stop logic, FCW and the MPC are untouched.
Cap code is not called at all when the toggle is off.

`follow_limit` (m/s -> m/s^2): 0:0.3  1.3:0.6  7.5:0.9  15:0.8  25:0.7  30:0.5  40:0.45  (NAP `ACCEL_PREAP_FOLLOW`, unchanged)

## Existing behaviour (before this change)
`Profiles.limits` and `get_cruise_accel` limit only the cruise-speed path by speed and profile. A lead only restores full braking
(`tracking_lead` -> minimum = ACCEL_MIN). Nothing lowers accel as the gap closes.
