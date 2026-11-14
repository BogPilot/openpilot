# BogPilot for legacy Tesla Model S / X (openpilot 0.11.2 base)

Branch: `bogpilot-tesla` (openpilot 0.11.2 base, comma 3X on AGNOS 19.9).

BogPilot is a community fork. It is not a comma product. You are always responsible for driving: keep your hands on the
wheel and your eyes on the road, and be ready to take over at any time.

## Supported cars

| Car | Platform | Lateral | Longitudinal | Tested on a car? |
|---|---|---|---|---|
| Model S, Autopilot 1 (2014-16) | `TESLA_AP1_MODELS` | yes | openpilot long | **Yes**: the only drive-tested car (see "Testing status") |
| Model X, Autopilot 1 (2016) | `TESLA_AP1_MODELX` | yes | stock cruise only, lateral-only | No engaged logs yet |
| Model S, Pre-Autopilot (2012-14) | `TESLA_PREAP_MODELS` | yes, through the Pre-AP safety flag | only with a Comma Pedal | No: no Pre-AP logs exist yet |
| Model S / X, Autopilot 2 | none | - | - | **Not supported**: AP2 is not a platform in this tree |

Car detection: AP1 cars have no firmware-version rows, so they are picked by their CAN signature or by the
CarModel / ForceFingerprint setting. Pre-AP is picked by CarModel / ForceFingerprint, or detected from a Comma Pedal
with no Mobileye on bus 2.

### Testing status (be honest with yourself before you drive)
- AP1 Model S: drive-tested by the maintainer on earlier builds of this line and bench-driven on this build; the maintainer
  reports everything working on this build. No other driver or car has tested it.
- AP1 Model X and Pre-AP Model S: no engaged drive logs. The driver-override numbers were chosen from AP1 Model S
  driving and are unproven on those cars.
- Panda safety code is unchanged from the previously reviewed build of this line.

## Install

Requirements: comma 3X on AGNOS 19.9, a harness for your car.

1. On the comma 3X setup screen, choose custom software and enter the installer URL for this branch:
   `installer.comma.ai/BogPilot/bogpilot-tesla`
2. After install, confirm Settings > Software shows branch `bogpilot-tesla` and the device is on AGNOS 19.9.
3. Connect the harness and the car. Vehicle settings appear once the car is detected.

Note: until this release is published, the `bogpilot-tesla` branch holds the older 0.9.7 / AGNOS 10.1 line, which has
no shared history with this tree. Do not install the old branch on a comma 3X that is already on AGNOS 19.9.

## Features and defaults

### Camera View (default: Auto)
- Choices: **Auto**, **Standard**, **Wide**. Help text (BogPilot 0.9.7 wording): "Select the active camera view.
  This is purely a visual change and doesn't impact how openpilot drives!"
- Auto is stock openpilot 0.11.2 switching: in Experimental Mode with a wide stream, wide below 11 mph, narrow above
  22 mph, otherwise narrow. Standard always shows the narrow road camera; Wide always the wide one.
- The old "Driver" choice is gone; a saved Driver value reads as Auto. The cabin camera still shows in reverse.
- Registered default 0 (Auto). Settings > Visuals, under Quality of Life Visuals (default On).

### Accel / decel bars (Pedals on Screen; default: **On**)
- Two vertical bars replace the 0.9.7 pedal icons: decel on the left, accel on the right. They show when openpilot
  longitudinal is active, Driving Screen Widgets is on (default On) and Pedals on Screen is on (default **On**).
- AP1 decel bar: total braking decel on one scale. **2.0 m/s² fills 50 %**, 3.5 m/s² fills 100 %.
- Colours:
  - regen (you, or nobody, braking with regen): **blue**; OP regen decel: dusty blue;
  - your brake press: **red** when friction does most of the braking, violet when regen does most;
  - OP applying the brake booster (AP1): **muted lavender** while regen has the majority, **rose** when friction has it;
  - accel: green for your pedal, sage for an OP accel request.
- The OP brake colour clears at most 0.25 s (plus one frame) after OP stops braking. Display only.
- Pre-AP and other cars keep the two-half layout (regen half, brake press from 50 %).

### Confidence ball (default: On, left edge)
- A small ball on the edge of the driving screen whose height follows the driving model's confidence.
- Engaged: green / orange / red. Overriding: consistent white ball with grey shade. **Disengaged: slate grey at high confidence fading to white
  at low confidence**, shaded top to bottom like stock, so it never looks like openpilot is active.
- Display only; no control path reads it. Side: Left (default) or Right.

### Override Sensitivity (default: 2)
- How hard you must push the wheel to take over steering, levels 1 to 5.
- Fire torque = 2.0 Nm × scale: **1 = 2.5 Nm, 2 = 2.25 Nm (default), 3 = 2.0 Nm, 4 = 1.75 Nm, 5 = 1.5 Nm**.
- The EPAS hands-on flag always counts as a takeover; panda steering limits do not change with this setting.
- AP1 Model S / X and Pre-AP Model S only.

### Stalk hold for Experimental Mode (default: 1.23 s)
- With openpilot longitudinal, a long stalk **pull** while engaged, or a long **push** while disengaged, flips
  Experimental Mode once (Chill <-> Experimental). Default hold 1.23 s, adjustable 1.10 to 5.00 s in 0.01 s steps.
- The engaging pull and an engaged cancel push never flip modes; normal engage and cancel timing is fixed.

### Bog to the Future (default: On; display only)
- Draws two burning tire tracks for 3 seconds down the lane beside you behind a car that passes faster than **88 mph**.
- Needs blind spot data (Tesla AP1), Blind Spot Lane Fill on, and a radar track of that car. Never steers or brakes.

### Blind spot monitoring (BSM) display (AP1)
- Blind Spot Lane Fill (default On): tints the lane beside you red while the car reports a vehicle there.
- Blind Spot Border (default On): turns that half of the screen border red.
- Only cars that report blind spot data (Tesla AP1).

### AP1 / legacy Tesla longitudinal tuning ported from 0.9.7
On AP1 Model S / X and Pre-AP Model S, a one-time start-up write applies the profiles the maintainer drove on 0.9.7,
without overwriting any setting you already changed:
- Acceleration **Sport** (max 3.0 / 2.5 / 2.0 / 1.5 / 1.0 / 0.8 / 0.6 m/s² at 0 / 11 / 22 / 34 / 45 / 56 / 89 mph);
- Deceleration **Eco+** (coasts more, brakes as softly as possible);
- Human-Like Acceleration on, Human Following on, custom personalities (follow 1.25 / 1.45 / 2.0 s).
- Turning Longitudinal Tuning off (or Reset to stock) returns to the stock cruise limit.

## Privacy
BogPilot does not register with comma servers and does not upload driving data to comma by default.

## Credits
- comma.ai openpilot (MIT).
- BogPilot 0.9.7 (`bogpilot-tesla`), Tinkla / BogGyver openpilot and NotAutopilot (NAP) are the Tesla references.
- mapd map data by pfeiferj (MIT).
- Beta tester **IRIT-able** (GitHub, fork `github.com/IRIT-able/bogpilot-openpilot`) found and fixed, on Nov 5 2026, the same
  Pre-AP problems that BogPilot's Pre-AP work fixes: the Comma Pedal sensor bit layout (GAS_SENSOR state and counter nibbles),
  engaging only on a stalk pull, and re-arming on a new pull. Thank you. The Pre-AP code in this repository is BogPilot's own;
  no code from that fork was copied.

Lineage: BogPilot is forked from FrogPilot's work (FrogAi and contributors, MIT), which is itself a fork of openpilot (MIT, Comma.ai, Inc.), and adds Tesla support. Thank you to the FrogPilot team for their brilliant work. Pre-AP signal reference values may come from an upstream legacy port (data values only). BogPilot is not a comma product and does not use the openpilot trademark as a product name for modified safety builds.

<details>
<summary>MIT Licensed</summary>

openpilot is released under the MIT license. Some parts of the software are released under other licenses as specified.

Any user of this software shall indemnify and hold harmless Comma.ai, Inc. and its directors, officers, employees, agents, stockholders, affiliates, subcontractors and customers from and against all allegations, claims, actions, suits, demands, damages, liabilities, obligations, losses, settlements, judgments, costs and expenses (including without limitation attorneys’ fees and costs) which arise out of, relate to or result from any use of this software by user.

**THIS IS ALPHA QUALITY SOFTWARE FOR RESEARCH PURPOSES ONLY. THIS IS NOT A PRODUCT.
YOU ARE RESPONSIBLE FOR COMPLYING WITH LOCAL LAWS AND REGULATIONS.
NO WARRANTY EXPRESSED OR IMPLIED.**
</details>
