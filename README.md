# StarPilot

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/firestar5683/StarPilot)
[![Discord](https://img.shields.io/discord/1387432184121393333?label=Discord)](https://firestar.link/discord)
[![Last Updated](https://img.shields.io/github/last-commit/firestar5683/StarPilot/StarPilot)](https://github.com/firestar5683/StarPilot)
[![Wiki](https://img.shields.io/badge/Wiki-StarPilot-blue?logo=wiki)](https://wiki.firestar.link)

**StarPilot** is a custom fork of [comma.ai's openpilot](https://comma.ai/openpilot),
an open source driver assistance system.


Openpilot provides
* Automated Lane Centering
* Adaptive Cruise Control
* Lane Change Assist
* Driver Monitoring *without wheel nags*

StarPilot was formerly a GM targeted fork,
but [has expanded to offer Quality-Of-Life improvements for all](#features)!

StarPilot is built off of [FrogPilot](https://github.com/FrogAi/FrogPilot)
and supports the major features FrogPilot offers.

Ford-specific lateral-control and vehicle-support work includes substantial adaptations from
[BluePilot](https://github.com/BluePilotDev/bluepilot/tree/bp-7.0), principally developed by
[Alan Polk](https://github.com/alan-polk) with additional BluePilot contributors. StarPilot's
implementation has since diverged, but that does not erase its lineage. See [CREDITS.md](CREDITS.md)
for the code-level provenance and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for applicable
upstream notices and terms. BluePilot and its contributors do not maintain or endorse StarPilot;
please direct support requests for this adaptation to the StarPilot project.

Hyundai, Kia, and Genesis angle steering and related vehicle support include substantial adaptations
from [sunnypilot](https://github.com/sunnypilot/sunnypilot/tree/hkg-angle-steering-2025) and its
[opendbc angle-steering branch](https://github.com/sunnypilot/opendbc/tree/hkg-angle-steering-2025).
StarPilot's implementation has diverged significantly; the upstream contributors do not maintain
this adaptation. Detailed code lineage is recorded in [CREDITS.md](CREDITS.md#hyundai-kia-and-genesis-support-adapted-from-sunnypilot).

StarPilot has a vibrant, welcoming community [discord](https://firestar.link/discord).
Stop by to chat or ask questions!

## BogStar: Tesla AP1 Model S (branch `bogstar`)

**BogPilot Tesla AP1 code is still in active development and has not been merged yet. Do not install until documentation has been updated.**

The `bogstar` branch is StarPilot with BogPilot's Tesla AP1 Model S support
(AP1 cars with the stock Mobileye/Bosch autopilot hardware, HW1). It is
experimental and community-maintained. It is not a product, comes with no
warranty, and the driver remains fully responsible for the vehicle at all times.

What the branch adds for AP1 (`TESLA_MODEL_S_HW1`, detected from the brake
booster, radar and EPAS firmware):

* `tesla_ap1` panda safety mode, selected by the AP1 `HAS_AP` safety flag. Stock
  autopilot frames pass through whenever openpilot is not sending its own copy.
  StarPilot's existing pre-AP, legacy and Model 3/Y/S/X Tesla paths are unchanged.
* Lateral control through `DAS_steeringControl` with a short resume hold and a
  soft start after the driver lets go of the wheel.
* openpilot longitudinal (`DAS_control`). The panda only accepts it on a DEBUG
  panda build (the firmware committed in this branch); a release panda keeps
  stock ACC.
* Instrument cluster integration (`AutopilotStatus`, `DAS_status2`, `DAS_lanes`).
* Speed limits read from CAN and shown through StarPilot's dashboard speed limit.
* Holding the cruise stalk pulled for about 2 seconds toggles Experimental Mode
  while engaged; holding it forward for about 2 seconds while disengaged also
  toggles Experimental Mode. The stalk follow-distance setting selects the
  driving personality.
* AP1 set speed with Speed Limit Controller on (BogPilot milestone 3): stalk up or
  down engages at the current speed; a pull engages at the posted limit plus
  offset. Engaged up/down tips change the set by 1 mph (a full tip goes to the next
  or previous 5) and the tipped set stays put across speed-limit zone changes until
  the next pull. Posted limits under 15 mph are ignored and big sudden drops must
  persist for 2 seconds. The cluster set speed follows the planner set.
* Longitudinal smoothing (BogPilot milestone 4): accel slew and a comfort jerk band
  on DAS_control, a standstill hold that relaxes to -1.0 m/s² (no launch thunk), a
  neutral DAS_control while the driver presses the accelerator, a filtered throttle
  cap instead of an on/off cut, and an earlier, gentler regen-sized lead approach
  (comfort brake 1.0 m/s² for the lead cost only; hard braking limits are
  unchanged). Turn the regen comfort brake off with
  `echo 0 > /data/params_bogpilot/RegenComfortBrake` and restart.
* Steering frames stay in counter step with the stock DAS, the EPB "EAC not
  allowed" signal faults lateral, and the panda resyncs its steering-angle rate
  limit to the wheel while disengaged (no rate-limit faults on re-engage). Panda
  limits are unchanged.
* A "BogPilot" startup-alert preset in the StarPilot appearance settings.

The AP1 set-speed layer adds two Python-read fields to `starpilotCarState`
(`resumePressed`, `spdCtrlLvr`).

Credits: the AP1 CAN and safety logic follows the work of
[BogGyver](https://github.com/BogGyver) and the Tinkla project, ported through
[BogPilot](https://github.com/BogPilot). It is built on
[StarPilot](https://github.com/firestar5683/StarPilot) by firestar5683, which is
built on [FrogPilot](https://github.com/FrogAi/FrogPilot) and
[openpilot](https://github.com/commaai/openpilot). Released under the MIT
license, like StarPilot and openpilot (see [LICENSE](LICENSE)). Please send AP1
issues to BogPilot, not to the StarPilot or FrogPilot projects.

## Documentation

Please see [https://wiki.firestar.link](https://wiki.firestar.link) for hardware lists,
installation guides, and software configuration.

## Features

* Full support for Comma C3, C3X, and C4
* Model switcher with all of comma's tinygrad driving models
* Special longitudinal planner tuning for VoACC (visual only, radar-less) vehicles
* Custom-tuned torque controllers for an expanding list of cars.
* Galaxy: StarPilot's portal to configure your comma device using your phone from anywhere.
Download models, change settings, update software, visualize live model outputs for tuning.
* Always On Lateral (full time steering assist)*
* Speed Limit Controller*
* Learning Curve Speed Controller*
* Conditional Experimental Mode (CEM)*
* Driving Profiles*
* Custom themes*
* Alert Volume Controller*
* Comma Pedal Interceptor support*
* Toyota SDSU support*
* ZSS support*
* High quality dashcam recordings*
* Enhanced tuning for CEM (dynamic experimental mode switching)
* And more!

\* [Inherited from FrogPilot](https://github.com/FrogAi/FrogPilot#openpilot-vs-frogpilot)

## GM-only Features

* Increased LKAS fault resiliency
* ASCM_INT and SASCM support
* Custom lateral torque controller, with special tuning for Bolts
* 50% extra torque on 2017 Chevy Bolt
* Improved lateral and longitudinal tuning
* Dashboard cruise control display speed spoofing for vehicles with pedal interceptor
* Extra steering wheel button functionality for vehicles with pedal interceptor
* Optional toggle to boot comma when remote starting your vehicle

## Developer Features

* Native and cross compilation for Windows, Mac, and Ubuntu
* Custom AGNOS to support C3, C3X, and C4
* To run UI on PC:
  * `./c3` for large UI
  * `./c4` for small UI
* `./build` to produce cross compiled binaries for comma devices.
Uses your comma's sysroot/toolchain
* Toggle: "Use Precompiled Binaries" to allow switching between fast boot / editable builds
* Custom long maneuver tests, specifically designed for regen-only vehicles

## Third-Party Notices

* Portions of this software include modified versions of the Material Design Icons provided by Google under the Apache License 2.0. A copy of the license is included in the `LICENSE-MDI` file.
* Ford support includes software adapted from BluePilot's `bp-7.0` branch. The source repository contains both a standard MIT notice and a separate custom SUNNYPILOT LLC notice; StarPilot preserves both in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
* Hyundai, Kia, and Genesis support includes software adapted directly from sunnypilot's HKG angle-steering branch and sunnypilot/opendbc. StarPilot preserves the applicable notices in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

> This project uses software from Haibin Wen and SUNNYPILOT LLC and is licensed under a custom license requiring permission for use.
