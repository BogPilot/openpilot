# BogPilot for legacy Tesla Model S / X (openpilot 0.11.2 base)

Branch: `bogpilot-tesla` (openpilot 0.11.2 base, comma 3X on AGNOS 19.9). Release tag: `bogpilot-tesla-c3x-0.11.2`.

BogPilot is a community fork. It is not a comma product. You are always responsible for driving: keep your hands on the
wheel and your eyes on the road, and be ready to take over at any time.

> [!IMPORTANT]
> **`bogpilot-tesla` is currently comma 3X only.** Install URL for comma 3X: `installer.comma.ai/BogPilot/bogpilot-tesla`
>
> **On a comma 3, do not install `bogpilot-tesla`.** comma does not officially support AGNOS 19.9 on comma 3 hardware.
> If you have a comma 3 and a Model S AP1, use the `bogpilot-tesla-0.9.7` branch (AGNOS 10.1, which runs on the comma 3):
> `installer.comma.ai/BogPilot/bogpilot-tesla-0.9.7`
>
> A 0.11.0 / AGNOS 17.2 LTS version will be backported from 0.11.2 once the full legacy Tesla integration is complete in v0.11.2.

[![BogPilot on a legacy Model S (replay, signs and plates blurred).](docs/media/bogpilot_ui_replay_poster.png)](https://github.com/user-attachments/assets/bd31ac4c-b7e6-4b28-ac7b-2f897dcfb026)

*BogPilot on a legacy Model S (replay, signs and plates blurred). Click the picture for the video.*

## Supported cars

| Car | Platform | Lateral | Longitudinal | Tested on a car? |
|---|---|---|---|---|
| Model S, Pre-Autopilot (2012-14) | `TESLA_PREAP_MODELS` | yes, through the Pre-AP safety flag | only with a Comma Pedal | No: no Pre-AP logs exist yet |
| Model S, Autopilot 1 (2014-16) | `TESLA_AP1_MODELS` | yes | openpilot long | **Yes**: the only drive-tested car (see "Testing status") |
| Model X, Autopilot 1 (2016) | `TESLA_AP1_MODELX` | yes | stock cruise only, lateral-only | No engaged logs yet |
| Model S / X, Autopilot 2 | none | - | - | **Not supported yet**: planned for a future release once we have AP2 rlogs |

Car detection: AP1 cars have no firmware-version rows, so they are picked by their CAN signature or by the
CarModel / ForceFingerprint setting. Pre-AP is picked by CarModel / ForceFingerprint, or detected from a Comma Pedal
with no Mobileye on bus 2.

### Testing status (be honest with yourself before you drive)
- AP1 Model S: drive-tested by the maintainer on earlier builds of this line and bench-driven on this build; the maintainer
  reports everything working on this build. No other driver or car has tested it.
- AP1 Model X and Pre-AP Model S: no engaged drive logs. The driver-override numbers were chosen from AP1 Model S
  driving and are unproven on those cars.
- Panda safety changes since commit `a4296aee`, the bench-driven build: the optional Pre-AP Bosch radar gateway
  (`opendbc_repo/opendbc/safety/modes/tesla_preap_radar.h`, with small hooks in `tesla.h` and `tesla_preap.h`; off unless
  safety flag 256 is set) and its tests, one added Pre-AP pedal/brake test, and the panda source identity check
  (`panda/build_identity.py`). The AP1 safety path is unchanged. The radar gateway has no drive logs.

## Install

Requirements: comma 3X on AGNOS 19.9, a harness for your car.

1. On the comma 3X setup screen, choose custom software and enter the installer URL for this branch:
   `installer.comma.ai/BogPilot/bogpilot-tesla`
2. After install, confirm Settings > Software shows branch `bogpilot-tesla` and the device is on AGNOS 19.9.
3. Connect the harness and the car. Vehicle settings appear once the car is detected.

Note: the previous 0.9.7 / AGNOS 10.1 line is preserved on branch `bogpilot-tesla-0.9.7`. It has no shared history
with this tree. Do not install it on a comma 3X that is already on AGNOS 19.9.

## Features and defaults

### Camera View (default: Auto)
- Choices: **Auto**, **Standard**, **Wide**. Help text (BogPilot 0.9.7 wording): "Select the active camera view.
  This is purely a visual change and doesn't impact how openpilot drives!"
- Auto is stock openpilot 0.11.2 switching: in Experimental Mode with a wide stream, wide below 11 mph, narrow above
  22 mph, otherwise narrow. Standard always shows the narrow road camera; Wide always the wide one.
- The old "Driver" choice is gone; a saved Driver value reads as Auto. The cabin camera still shows in reverse.
- Registered default 0 (Auto). BogPilot > Appearance, under Quality of Life Visuals (default On).

### Accel / decel bars (Pedals on Screen; default: **On**)
- Two vertical bars replace the 0.9.7 pedal icons: decel on the left, accel on the right. They show when openpilot
  longitudinal is active, Driving Screen Widgets is on (default On), Pedals on Screen is on (default **On**) and Dynamic
  Pedals is on (default On). All three are under BogPilot > Appearance.
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
- FrogPilot by FrogAi (James) and contributors (MIT); BogPilot forks FrogPilot's work.
- Eric Brown (nworb-cire): imported OPGM / FrogPilot 0.9.7 history.
- BogPilot 0.9.7 (`bogpilot-tesla-0.9.7`), Tinkla / BogGyver openpilot and NotAutopilot (NAP) are the Tesla references.
- mapd map data by pfeiferj (MIT).
- Beta tester **IRIT-able** (GitHub, fork `github.com/IRIT-able/bogpilot-openpilot`) found and fixed, on Nov 5 2026, the same
  Pre-AP problems that BogPilot's Pre-AP work fixes: the Comma Pedal sensor bit layout (GAS_SENSOR state and counter nibbles),
  engaging only on a stalk pull, and re-arming on a new pull. Thank you. The Pre-AP code in this repository is BogPilot's own;
  no code from that fork was copied.

Lineage: BogPilot is forked from FrogPilot's work (FrogAi and contributors, MIT), which is itself a fork of openpilot (MIT, Comma.ai, Inc.), and adds Tesla support. Thank you to the FrogPilot team for their brilliant work. Legacy Tesla (AP1 and Pre-AP) CAN definitions and panda safety come from BogPilot 0.9.7, Tinkla / BogGyver and NotAutopilot (NAP), credited in docs/tesla/DIVERGENCES.md and docs/tesla/PREAP_PORT.md. BogPilot is not a comma product and does not use the openpilot trademark as a product name for modified safety builds.

<details>
<summary>MIT Licensed</summary>

openpilot is released under the MIT license. Some parts of the software are released under other licenses as specified.

Any user of this software shall indemnify and hold harmless Comma.ai, Inc. and its directors, officers, employees, agents, stockholders, affiliates, subcontractors and customers from and against all allegations, claims, actions, suits, demands, damages, liabilities, obligations, losses, settlements, judgments, costs and expenses (including without limitation attorneys’ fees and costs) which arise out of, relate to or result from any use of this software by user.

**THIS IS ALPHA QUALITY SOFTWARE FOR RESEARCH PURPOSES ONLY. THIS IS NOT A PRODUCT.
YOU ARE RESPONSIBLE FOR COMPLYING WITH LOCAL LAWS AND REGULATIONS.
NO WARRANTY EXPRESSED OR IMPLIED.**
</details>
