"""Tap-to-explain help for BogPilot settings rows (t1017).

Tapping the TEXT area of a settings row opens a scrollable help popup (title, what it does, when to use it,
safety note, default, range). Tapping the switch / buttons on the right of a row still only does its normal
job. Opening or closing help never reads or writes a preference.

All help text lives in the HELP table below, keyed by the row's param key (or a stable page-row id), so it is easy to
edit in one place. Every string goes through tr_noop() and is translated with tr() when the popup is built.

Facts in this table come from the consumers in this tree (planner / controls / opendbc / onroad UI). When a consumer
changes, update the matching entry; test_bogpilot_toggle_help.py checks coverage, ASCII-only text and defaults.

Text rules (the font atlas has ASCII plus a few symbols only): ASCII text, "m/s^2" and "m/s^3" for units, no angle
brackets (the popup renderer treats them as tags).
"""
from __future__ import annotations

from dataclasses import dataclass

from openpilot.system.ui.lib.multilang import tr_noop

POPUP_FONT_SIZE = 42
DEFAULT_LABEL = tr_noop("Default")
RANGE_LABEL = tr_noop("Range")
WHEN_LABEL = tr_noop("When to use it")
SAFETY_LABEL = tr_noop("Safety")
RECOMMENDED_LABEL = tr_noop("Recommended")
CLOSE_LABEL = tr_noop("Close")

# Shared sentences.
_ADOPT = tr_noop("This section stays off, and openpilot drives stock, until you change a setting here.")
_OFFROAD = tr_noop("Can only be changed while the car is off.")


@dataclass(frozen=True)
class HelpEntry:
  title: str
  what: str
  when: str = ""
  note: str = ""          # safety / limitation
  default: str = ""
  range: str = ""
  recommended: str = ""
  default_param: str = ""  # param key whose shipping default the tests compare with `default` (On/Off)


HELP: dict[str, HelpEntry] = {}


def _add(key, title, what, when="", note="", default="", range="", recommended="", default_param=None):
  assert key not in HELP, key
  HELP[key] = HelpEntry(tr_noop(title), tr_noop(what), tr_noop(when) if when else "", tr_noop(note) if note else "",
                        tr_noop(default) if default else "", tr_noop(range) if range else "",
                        tr_noop(recommended) if recommended else "", default_param or "")


# ---------------------------------------------------------------- Alerts and Sounds
_add("GreenLightAlert", "Green Light Alert",
     "Plays a short alert, \"Light turned green\", when you are stopped with no lead car and the driving model predicts that the "
     "car can move off again. It does not read traffic lights: it only follows what the model predicts, so it can be wrong.",
     when="If you often wait at lights and want a nudge when traffic starts moving.",
     note="Always check the road yourself. The alert is lowest priority and is dropped while any stock alert is showing. "
          "It uses the Prompt volume.",
     default="On", default_param="GreenLightAlert")
_add("LeadDepartingAlert", "Lead Departed Alert",
     "Alerts, \"Lead departed\", when you are stopped behind a tracked lead car and it pulls away: it has moved more than "
     "1 m from where it stopped and is moving faster than 1 m/s while you are still stopped.",
     when="If you tend to miss the car in front moving off.",
     note="Lowest priority; dropped while any stock alert is showing. It uses the Prompt volume.",
     default="On", default_param="LeadDepartingAlert")
_add("AlertVolumeControl", "Alert Volume Controller",
     "Lets you set a separate volume for each kind of alert sound. With it off, every alert follows the automatic volume, which "
     "tracks how loud the cabin is. With it on, the rows below set each category: Auto, Muted or a fixed percent.",
     when="If some sounds, such as engage and disengage chimes, are too loud or too quiet for you.",
     note="The safety alert categories (Prompt, Prompt Distracted, Warning Soft and Warning Immediate) can never go below 25 "
          "percent, even if a lower value is saved. Can only be changed while the car is off.",
     default="Off (every alert uses the automatic volume)", default_param="AlertVolumeControl")
_VOL_COMMON = " Auto follows the cabin noise level."
_add("EngageVolume", "Engage Volume", "Volume of the sound played when openpilot engages." + _VOL_COMMON,
     when="Mute it if your car already makes its own engage sound.",
     default="Auto", range="Muted, 1 to 100 percent, or Auto")
_add("DisengageVolume", "Disengage Volume", "Volume of the sound played when openpilot disengages." + _VOL_COMMON,
     when="Mute it if your car already makes its own disengage sound.",
     default="Auto", range="Muted, 1 to 100 percent, or Auto")
_add("RefuseVolume", "Refuse Volume", "Volume of the sound played when openpilot refuses an engage request." + _VOL_COMMON,
     default="Auto", range="Muted, 1 to 100 percent, or Auto")
_add("PromptVolume", "Prompt Volume",
     "Volume of prompt alerts: the low-level sounds for things like a lane departure warning, steering assist unavailable, or a "
     "car detected in the blind spot when a lane change is blocked. The Green Light and Lead Departed alerts use it too."
     + _VOL_COMMON,
     note="Safety alert: cannot go below 25 percent. The Min button sets 25 percent.",
     default="Auto", range="25 to 100 percent, or Auto")
_add("PromptDistractedVolume", "Prompt Distracted Volume",
     "Volume of the driver monitoring prompts, such as Pay Attention and Touch Steering Wheel." + _VOL_COMMON,
     note="Safety alert: cannot go below 25 percent. The Min button sets 25 percent.",
     default="Auto", range="25 to 100 percent, or Auto")
_add("WarningSoftVolume", "Warning Soft Volume",
     "Volume of the warning sound used for forward collision warnings and soft take-control requests." + _VOL_COMMON,
     note="Safety alert: cannot go below 25 percent. The Min button sets 25 percent. Critical alerts also ramp up toward "
          "full volume the longer they sound.",
     default="Auto", range="25 to 100 percent, or Auto")
_add("WarningImmediateVolume", "Warning Immediate Volume",
     "Volume of the urgent warning sound used for immediate take-control requests and the last driver monitoring warnings." + _VOL_COMMON,
     note="Safety alert: cannot go below 25 percent. The Min button sets 25 percent. Critical alerts also ramp up toward "
          "full volume the longer they sound.",
     default="Auto", range="25 to 100 percent, or Auto")
_add("AlertVolumeFloor", "Warning minimum",
     "The warning categories cannot be muted. Prompt, Prompt Distracted, Warning Soft and Warning Immediate stay at 25 percent or "
     "louder. This limit is enforced where the sound is played, so a lower saved value is ignored.",
     default="25 percent", range="25 to 100 percent")

# ---------------------------------------------------------------- Vehicle
_add("DisableOpenpilotLongitudinal", "Disable openpilot Longitudinal Control",
     "Uses the car's own adaptive cruise control for speed and following distance instead of openpilot's gas and brake control. "
     "Steering stays with openpilot.",
     when="If you prefer the car's stock cruise behavior.",
     note="Takes effect the next time the car starts, and asks you to confirm before turning on. Features that need openpilot "
          "longitudinal control, such as the Gas / Brake rows, stop applying. Can only be changed while the car is off.",
     default="Off", default_param="DisableOpenpilotLongitudinal")
_add("EnableICIntegration", "Tesla AP1: Dash Cluster Integration",
     "Shows openpilot information on the Tesla instrument cluster. Turning it off stops all cluster messages, so the cluster stays "
     "completely stock.",
     when="Turn it off if you want the dash to look exactly as Tesla made it.",
     note="Takes effect immediately. Model S only. " + _OFFROAD,
     default="On")
_add("RegenComfortBrake", "Tesla AP1: Earlier, Gentler Regen Stops",
     "The Model S AP1 brake pedal is friction only, and regen is limited to about 1 to 1.5 m/s^2. With this on, openpilot starts "
     "slowing for a lead earlier and uses regen-sized braking instead of the stock 2.5 m/s^2 comfort braking.",
     when="If approaches to a slower lead feel late or need friction brakes.",
     note="Emergency braking limits and the stopped distance are unchanged, so collision braking still has full authority. "
          "Needs openpilot longitudinal control. Takes effect the next time the planner starts, normally the next drive.",
     default="On")
_add("CarSelection", "Car Selection",
     "Picks the car openpilot should assume when automatic detection finds no car. Auto is the normal setting. The Tesla AP1 "
     "Model S and Model X entries are fallbacks for bench or bring-up use.",
     when="Only if openpilot does not recognize your car on its own.",
     note="A car that is positively detected always wins over this choice. Tesla AP1 Model X is steering only (the car's own "
          "cruise control stays in charge) and has not been verified on a real car. Takes effect the next time the car starts. "
          + _OFFROAD,
     default="Auto")
_add("CarSelection.current", "Current selection",
     "Shows what is saved: Auto, or a fallback car. \"(fallback)\" or \"(forced)\" means a car is saved and is used only if "
     "automatic detection finds none.")

# ---------------------------------------------------------------- Stalk Controls
_add("twist_follow", "Stalk Twist Following Distance",
     "Uses the twist detent of the AP1 distance stalk to set the following time. Off uses the normal driving profile. It does not "
     "change engaging, cancelling or the stalk's speed steps.",
     when="If you like to change following distance with the stalk.",
     note="Only for Tesla AP1. " + _OFFROAD,
     default="On")
_add("experimental_pull", "Long Pull: Experimental Mode",
     "While openpilot is engaged, holding the stalk toward you flips Experimental Mode once. The pull that engages openpilot "
     "never flips modes, and stock resume and set-speed behavior is unchanged.",
     note="Needs openpilot longitudinal control. The hold time is set in the Experimental Pull Hold row. " + _OFFROAD,
     default="On")
_add("experimental_push", "Long Push: Experimental Mode",
     "While openpilot is disengaged, holding the stalk away from you flips Experimental Mode once. A push that starts while "
     "engaged still cancels immediately and never flips modes on that hold.",
     note="Needs openpilot longitudinal control. The hold time is set in the Experimental Push Hold row. " + _OFFROAD,
     default="On")
_add("pull_hold_s", "Experimental Pull Hold",
     "How long you hold the stalk toward you before Experimental Mode flips. Longer is harder to trigger by accident.",
     note="Only Experimental Mode timing changes. Normal engagement and cancel timing stay fixed. A damaged or invalid saved "
          "value turns the gesture off rather than making it shorter.",
     default="1.23 s", range="1.10 to 5.00 seconds, in 0.01 second steps")
_add("push_hold_s", "Experimental Push Hold",
     "How long you hold the stalk away from you before Experimental Mode flips. Longer is harder to trigger by accident.",
     note="Only Experimental Mode timing changes. Normal engagement and cancel timing stay fixed. A damaged or invalid saved "
          "value turns the gesture off rather than making it shorter.",
     default="1.23 s", range="1.10 to 5.00 seconds, in 0.01 second steps")
_add("standard_engage_cancel_fixed", "Standard Stalk Engagement / Cancel",
     "Shows that normal engage and cancel on the stalk are fixed. No timing here can be changed, and the pre-AP double pull is "
     "not supported by this build.")

# ---------------------------------------------------------------- Lane Changes
_BSM_NOTE = ("A lane change, nudged or automatic, is blocked while the blind-spot monitor reports the side occupied. If the "
             "blind-spot data is missing, stale or invalid (Tesla AP1), the side counts as occupied.")
_add("LaneChanges", "Lane Changes",
     "Master switch for lane changes with the turn signal. Off turns lane changes off. The settings below only apply while this "
     "is on.",
     note="Off disables lane changes entirely: the turn signal alone will not move the car. Until you change a row on this "
          "page, the stock behavior applies (signal, then a nudge on the wheel). " + _BSM_NOTE,
     default="On", default_param="LaneChanges")
_add("NudgelessLaneChange", "Automatic Lane Changes",
     "Changes lanes by itself after you turn on the signal, with no nudge on the wheel, once the Lane Change Delay has passed.",
     when="If you are comfortable with openpilot starting the move once it judges the lane is clear.",
     note="Only starts when steering is active, you are above the minimum speed, the blind-spot monitor reports the side clear "
          "and you are not steering against the move. If blind-spot data is missing, stale or invalid (Tesla AP1), the side "
          "counts as occupied and the change is blocked. You are still responsible for checking the lane.",
     default="Off", recommended="Off until you have tried it somewhere safe", default_param="NudgelessLaneChange")
_add("LaneChangeTime", "Lane Change Delay",
     "How long the turn signal must be on before an automatic lane change starts.",
     note="Applies to Automatic Lane Changes only.",
     default="1.0 s", range="0 to 5 seconds, in 0.1 steps")
_add("MinimumLaneChangeSpeed", "Minimum Lane Change Speed",
     "The lowest speed at which a lane change is allowed.",
     note="A built-in floor of 20 mph (32.2 km/h) always applies, so lower values do not go below that.",
     default="20 mph (32 km/h)", range="0 to 99 mph (0 to 150 km/h)")
_add("LaneDetectionWidth", "Minimum Lane Width",
     "Blocks automatic lane changes into a lane narrower than this width. The width comes from the driving model's lane lines "
     "and road edge; if it cannot be measured, the change is blocked.",
     note="Applies to Automatic Lane Changes only. 0 turns this extra check off.",
     default="0 (off)", range="0 to 15 feet (0 to 5 m)")
_add("OneLaneChange", "One Lane Change Per Signal",
     "After an automatic lane change completes, another one does not start until the turn signal has been switched off and on "
     "again.",
     default="On", default_param="OneLaneChange")

# ---------------------------------------------------------------- Gas / Brake (openpilot longitudinal control only)
_GB = "Needs openpilot longitudinal control and can only be changed while the car is off."
_add("AdvancedLongitudinalTune", "Advanced Longitudinal Tuning",
     "Opens fine tuning of the actuator delay, the strongest acceleration, and how the car brakes to a stop. " + _ADOPT,
     note=_GB + " Stock safety limits still apply.",
     default="Off")
_add("LongitudinalActuatorDelay", "Actuator Delay",
     "The time between openpilot's throttle or brake command and the car's response. Raise it if the car feels slow to react, "
     "lower it if it feels too eager or overshoots.",
     note="Until you change it, the car's own value is used. " + _GB,
     default="The car's own value", range="0 to 1 second, in 0.01 steps")
_add("MaxDesiredAcceleration", "Maximum Acceleration",
     "Limits the strongest acceleration openpilot can command.",
     when="Lower it for gentler launches.",
     note=_GB,
     default="4.0 m/s^2", range="0.1 to 4.0 m/s^2, in 0.1 steps")
_add("StopAccel", "Stop Acceleration",
     "How hard openpilot brakes to hold a stop. More negative brakes harder.",
     note="Never softer than -0.5 m/s^2, so the car always holds a stop. Out-of-range saved values are clamped. Until you change "
          "this row, the car's own value is used. " + _GB,
     default="The car's own value", range="-4.0 to -0.5 m/s^2, in 0.01 steps")
_add("StoppingDecelRate", "Stopping Rate",
     "How fast the stopping brake ramps in as the car comes to a stop. Lower is gentler.",
     note="Never below 0.1 m/s^3, because a near-zero rate would ramp braking far too slowly. Out-of-range saved values are "
          "clamped. Until you change this row, the stock rate is used. " + _GB,
     default="1.0 m/s^3", range="0.1 to 1.0 m/s^3, in 0.01 steps")
_add("LongitudinalTune", "Longitudinal Tuning",
     "Opens the acceleration and deceleration profiles and Human-Like Acceleration. " + _ADOPT,
     note=_GB,
     default="Off")
_add("AccelerationProfile", "Acceleration Profile",
     "How quickly openpilot speeds up. Standard is the stock limits, Eco is gentle, Sport is firmer, and Sport+ allows the "
     "highest acceleration, up to 4 m/s^2 at low speed.",
     note=_GB,
     default="Sport", range="Standard, Eco, Sport or Sport+")
_add("DecelerationProfile", "Deceleration Profile",
     "How gently openpilot slows down. Standard is the stock limit. Eco allows half of the normal braking and Eco+ a quarter, "
     "so the car coasts more.",
     note="When following a lead car, full braking is always restored, so a gentler profile never weakens braking behind a "
          "lead. " + _GB,
     default="Eco", range="Standard, Eco or Eco+")
_add("HumanAcceleration", "Human-Like Acceleration",
     "Eases the throttle at low set speeds and as you approach the set speed, instead of accelerating at the full limit.",
     note="Only limits acceleration. Braking is not affected. " + _GB,
     default="On", default_param="HumanAcceleration")
_add("ConditionalExperimental", "Conditional Experimental Mode",
     "Switches Experimental Mode on automatically when the conditions you choose below are met, and back off when they are "
     "not. " + _ADOPT,
     note="Pressing the gas or brake pedal resets it. Needs openpilot longitudinal control. " + _OFFROAD,
     default="Off")
_add("CESpeed", "Below (no lead)",
     "Switches to Experimental Mode when you drive below this speed and there is no lead car (above 1 m/s).",
     when="Helps the model handle slow, stop-and-go driving.",
     default="0 (off)", range="0 to 99 mph (0 to 150 km/h)")
_add("CESpeedLead", "Below, With Lead",
     "Switches to Experimental Mode when you drive below this speed while following a lead car.",
     default="0 (off)", range="0 to 99 mph (0 to 150 km/h)")
_add("CECurves", "Curve Detected Ahead",
     "Switches to Experimental Mode when a curve is detected ahead and you are driving faster than about 5 m/s, so the model "
     "can pick a suitable speed.",
     default="Off", default_param="CECurves")
_add("CECurvesLead", "Curve Detected Ahead, With Lead",
     "Also uses the curve condition while you are following a lead car. Without it, curves are ignored when following a lead.",
     default="Off", default_param="CECurvesLead")
_add("CEStopLights", "\"Detected\" Stop Lights/Signs",
     "Switches to Experimental Mode when the driving model predicts a stop and there is no lead car. openpilot does not detect "
     "traffic lights or stop signs, so it may stop when there is no clear reason.",
     note="Hidden when the Predicted Stop In row is shown. The model's stop prediction is not traffic-light recognition.",
     default="On", default_param="CEStopLights")
_add("CELead", "Lead Detected Ahead",
     "Switches to Experimental Mode when the lead car is much slower than you (more than 5 m/s, about 11 mph) or is stopped "
     "(under 1 m/s). This build uses the radar's lead track.",
     default="Off", default_param="CELead")
_add("CESlowerLead", "Slower Lead",
     "Use the condition for a lead that is more than 5 m/s slower than you.",
     default="Off", default_param="CESlowerLead")
_add("CEStoppedLead", "Stopped Lead",
     "Use the condition for a lead that is stopped, moving under 1 m/s.",
     default="Off", default_param="CEStoppedLead")
_add("CEModelStopTime", "Predicted Stop In",
     "Switches to Experimental Mode when the driving model predicts the car will stop within this many seconds and there is no "
     "lead car. This is usually the model seeing a red light or stop sign ahead.",
     note="openpilot does not detect traffic lights or stop signs; in Experimental Mode the model makes end-to-end decisions "
          "and may stop without a clear reason.",
     default="8 seconds", range="0 to 9 seconds (0 is off)")
_add("CESignalSpeed", "Turn Signal Below",
     "Switches to Experimental Mode when you use a turn signal below this speed, so the model can choose a suitable speed for "
     "turns.",
     default="55 mph", range="0 to 99 mph (0 to 150 km/h; 0 is off)")
_add("CESignalLaneDetection", "Not For Detected Lanes",
     "Skips the turn signal condition when a lane wide enough for a lane change is detected on the signalled side, so ordinary "
     "lane changes do not switch modes.",
     default="On", default_param="CESignalLaneDetection")
_add("ShowCEMStatus", "Status Widget",
     "Shows on the driving screen which condition switched Experimental Mode on.",
     default="On", default_param="ShowCEMStatus")
_add("QOLLongitudinal", "Quality of Life",
     "Opens extra stopping options: Force Stop, Increase Stopped Distance and manual weather offsets.",
     note=_GB,
     default="On", default_param="QOLLongitudinal")
_add("ForceStops", "Force Stop at \"Detected\" Stop Lights/Signs",
     "When the driving model has predicted a stop for about 1 second and there is no lead car, openpilot lowers its cruise "
     "target so the car comes to a stop.",
     note="The model does not detect traffic lights or stop signs and may stop without a clear reason. Pressing the "
          "accelerator or an acceleration button overrides it, and it then waits 10 seconds before it can try again. " + _GB,
     default="Off", default_param="ForceStops")
_add("IncreasedStoppedDistance", "Increase Stopped Distance by",
     "Stops the car farther behind a lead car by treating the lead as that much closer. It never makes a present lead's "
     "distance smaller than 0.5 m.",
     note="Applies only to a lead that is present. " + _GB,
     default="0", range="0 to 10 feet (0 to 3 m)")
_add("WeatherPresets", "Weather Condition Offsets",
     "Lets you apply extra stopped distance for a weather condition you pick by hand. There is no automatic weather lookup, no "
     "location upload and no API key.",
     note="In this build only the stopped distance offsets take effect. " + _GB,
     default="Off", default_param="WeatherPresets")
_add("WeatherPresets.page", "Weather Condition Offsets",
     "Opens the manual weather condition and the per-condition offsets.")
_add("BogPilotManualWeather", "Manual Weather Condition",
     "Which condition the offsets use: Clear, Low visibility, Rain, Storm or Snow. Clear turns the offsets off. The choice stays "
     "on this device until you change it.",
     note=_GB,
     default="Clear")
for _cond, _name in (("LowVisibility", "Low Visibility"), ("Rain", "Rain"), ("RainStorm", "Rainstorms"), ("Snow", "Snow")):
  _add("weather." + _cond, _name,
       "Opens the offsets used when the manual weather condition is " + _name.lower() + ".")
  _add("IncreasedStoppedDistance" + _cond, "Increase Stopped Distance by (" + _name + ")",
       "Extra distance to stop behind a lead car while the manual weather condition is " + _name.lower() + ". Added to the "
       "regular Increase Stopped Distance setting.",
       note=_GB,
       default="0", range="0 to 10 feet (0 to 3 m)")

# ---------------------------------------------------------------- Steering Tuning
_ST = "Offroad only; applies next drive. Stock safety limits are unchanged."
_add("AdvancedLateralTune", "Advanced Lateral Tuning",
     "Unlocks manual steering values: actuator delay, steer ratio and, on torque-controlled cars, friction and lateral "
     "acceleration. Values you do not set keep the car's or the learned value.",
     note="Needs a previously detected car. " + _ST,
     default="Off", default_param="AdvancedLateralTune")
_add("SteerDelay", "Actuator Delay (steering)",
     "Seconds between a steering command and the car's response. If you never set it, the auto-learned value is kept.",
     note="Stays inside the learner's own limits. " + _ST,
     default="Auto-learned (starts at the car's delay plus 0.2 s)", range="0.15 to 0.65 seconds, in 0.01 steps")
_add("SteerRatio", "Steer Ratio",
     "The ratio of steering wheel angle to road wheel angle. Reset returns to the auto-learned value.",
     note=_ST,
     default="Auto-learned", range="0.5 to 1.5 times the car's own value, in 0.01 steps")
_add("SteerFriction", "Friction",
     "Torque-controlled cars only. Compensates for steering friction.",
     note="Needs Force Auto-Tune Off on cars that have live tuning. " + _ST,
     default="The car's own value", range="0 to 0.5, in 0.01 steps")
_add("SteerLatAccel", "Lateral Acceleration",
     "Torque-controlled cars only. Maps steering torque to turning response.",
     note="Needs Force Auto-Tune Off on cars that have live tuning. " + _ST,
     default="The car's own value", range="0.75 to 1.25 times the car's own value, in 0.01 steps")
_add("ForceAutoTuneOff", "Force Auto-Tune Off",
     "For torque cars that already tune themselves live: use the Friction and Lateral Acceleration values you set instead of "
     "the live ones.",
     note="Only shown for torque cars with live tuning. " + _ST,
     default="Off", default_param="ForceAutoTuneOff")
_add("ForceAutoTune", "Force Auto-Tune On",
     "For torque cars without built-in live tuning: learn Friction and Lateral Acceleration live while driving. The usual "
     "validity checks still apply.",
     note="Only shown for torque cars without live tuning. " + _ST,
     default="Off", default_param="ForceAutoTune")
_add("QOLLateral", "Quality of Life (steering)",
     "Opens the steering comfort options: Pause Steering Below and Turn Signal Only.",
     note=_ST,
     default="On", default_param="QOLLateral")
_add("PauseLateralSpeed", "Pause Steering Below",
     "Below this speed openpilot does not steer, and you steer yourself. 0 turns it off.",
     note="This only ever stops steering; it never adds steering. Be ready to steer below the set speed. Uses the speed units "
          "you have chosen. " + _ST,
     default="0 (off)", range="0 to 99 mph (0 to 150 km/h)")
_add("PauseLateralOnSignal", "Turn Signal Only",
     "Only pause steering below the speed while a turn signal is on. Without it, steering pauses below the speed at all times.",
     note="Has no effect while Pause Steering Below is 0. " + _ST,
     default="Off", default_param="PauseLateralOnSignal")

# ---------------------------------------------------------------- Driving Model
_add("driving_model.status", "Driving Model",
     "Shows which driving model is in use. Only the Default (stock) model ships with BogPilot. Models added later appear on "
     "this page.",
     note="A model is only used if it passes a hash check and the 0.11.2 compatibility check. If one fails, the stock model "
          "is used instead and an alert tells you why.")
_add("driving_model.default", "Default (stock) model",
     "The stock openpilot driving model. It is always listed first, it is the default, and it is what the car uses whenever "
     "another model is missing or fails its checks.",
     when="Pick it to go back to stock after trying another model.",
     default="Selected")
_add("driving_model.entry", "Installed model",
     "A model installed on this device. Its hashes and compatibility with 0.11.2 are checked before it can be selected. "
     "\"Not usable\" means a check failed and it cannot be selected.",
     note="A switch only takes effect when the car is off, from the next drive. It is checked again at start, and the stock "
          "model is used if it fails.")

# ---------------------------------------------------------------- Visuals
_add("AdjacentLeadsUI", "Adjacent Lead Speed Boxes",
     "Shows boxes with the speed of radar-tracked cars in the lanes beside you while openpilot is engaged.",
     note="Needs a car with radar.",
     default="On", default_param="AdjacentLeadsUI")
_add("BlindSpotPath", "Blind Spot Lane Fill",
     "Tints the lane beside you red while the car's blind spot monitor reports a vehicle there.",
     note="Only on cars that report blind spot data (Tesla AP1). Needs Driving Screen Widgets.",
     default="On", default_param="BlindSpotPath")
_add("BlindSpotMetrics", "Blind Spot Border",
     "Turns the matching half of the screen border red while the blind spot monitor reports a vehicle.",
     note="Needs Status Border. Only on cars that report blind spot data.",
     default="On", default_param="BlindSpotMetrics")
_add("BSMFlameTracks", "Bog to the Future",
     "Draws two burning tire tracks down the lane beside you, for 3 seconds, behind a car that passes you faster than 88 mph "
     "(about 142 km/h). Display only: it never steers, brakes or changes how the car drives.",
     when="It fires when the blind spot lane fill on that side switches off, with a radar-tracked car in that lane going over "
          "88 mph. So it needs a car that reports blind spot data (Tesla AP1), the Blind Spot Lane Fill on, and a radar "
          "that tracks the car in the next lane. On most drives it never shows.",
     note="Display only, no effect on control. Needs Blind Spot Lane Fill and Driving Screen Widgets.",
     default="On", default_param="BSMFlameTracks")
_add("OnroadDistanceButton", "Driving Personality Button",
     "Shows a button in the driver-side corner that shows and changes the driving personality.",
     note="Needs Quality of Life Visuals and openpilot longitudinal control.",
     default="Off", default_param="OnroadDistanceButton")
_add("PedalsOnUI", "Pedals on Screen",
     "Shows gas and brake pedal icons that light up with the car's acceleration. Shows measured acceleration, not pedal "
     "position or commanded braking.",
     note="Needs Driving Screen Widgets and openpilot longitudinal control.",
     default="Off", default_param="PedalsOnUI")
_add("ScreenRecorder", "Screen Recorder Button",
     "Shows a button on the driving screen that starts and stops a screen recording of what the UI draws.",
     note="Recordings are saved on the device in 5 minute segments. Recording will not start, or move on to a new segment, with "
          "under 1 GiB free. Nothing is recorded until you press the button.",
     default="On", default_param="ScreenRecorder")
_add("DriverCamera", "Show Driver Camera When In Reverse",
     "Shows the driver camera feed while the car is in reverse, after the car has been in reverse for half a second, and returns "
     "to the road view when you leave reverse.",
     note="Needs Quality of Life Visuals. Alerts still draw on top of the camera view.",
     default="Off", default_param="DriverCamera")
_add("QOLVisuals", "Quality of Life Visuals",
     "Parent switch for the reverse camera and the driving personality button. When off, both stay off.",
     default="On", default_param="QOLVisuals")
_add("CustomUI", "Driving Screen Widgets",
     "Parent switch for the blind spot lane fill and the pedals on screen. When off, those stay hidden.",
     default="On", default_param="CustomUI")
_add("BorderMetrics", "Status Border",
     "Parent switch for status colors on the screen border. The Blind Spot Border needs it.",
     default="On", default_param="BorderMetrics")
_add("DynamicPedalsOnUI", "Dynamic Pedals",
     "When Pedals on Screen is on, each pedal icon's strength follows the car's measured acceleration: the gas pedal grows with "
     "acceleration, and the brake grows with deceleration and is full at a standstill. Off hides the pedal overlay.",
     default="On", default_param="DynamicPedalsOnUI")
_add("SwapSpeedGraph", "Accel Graph on Top",
     "Puts the acceleration graph above the speed row in the top-left corner of the driving screen. Display only.",
     default="On", default_param="SwapSpeedGraph")
_add("Fahrenheit", "Temperature in Fahrenheit",
     "Shows the sidebar temperature in Fahrenheit instead of Celsius.",
     note="Separate from the Metric Units setting.",
     default="Off", default_param="Fahrenheit")
_add("NumericalTemp", "Numerical Temperature",
     "Shows the sidebar temperature as a number while the car is off, instead of only the GOOD or HIGH label. While driving, the "
     "sidebar still shows the label.",
     default="On", default_param="NumericalTemp")
_add("ShowCPU", "Show CPU in Sidebar",
     "Shows the CPU usage metric in the sidebar while the car is off.",
     default="On", default_param="ShowCPU")
_add("ShowMemoryUsage", "Show Memory in Sidebar",
     "Shows the memory (RAM) usage metric in the sidebar.",
     default="On", default_param="ShowMemoryUsage")
_add("NavigationUI", "Navigation Widgets",
     "Parent switch for the posted speed limit tile on the driving screen.",
     default="On", default_param="NavigationUI")
_add("ShowSpeedLimits", "Show Speed Limits",
     "Shows the posted speed limit tile. The limit comes from the speed limit the Tesla dashboard reports, not from maps or "
     "the camera, and only a limit the dash reports as valid and current is used.",
     note="Needs Navigation Widgets. It only displays the limit and never changes the car's speed.",
     default="On", default_param="ShowSpeedLimits")

# ---------------------------------------------------------------- Device Controls
_add("DeviceManagement", "Device Settings",
     "Master switch for the shutdown timer and the low-voltage cutoff. Off keeps stock power protection.",
     note="Cannot make the device stay on longer or run the battery lower than stock allows. " + _OFFROAD,
     default="Stock behavior")
_add("DeviceShutdown", "Device Shutdown Timer",
     "How long the device stays on after the car is turned off before it powers down.",
     note="Never longer than the stock 30 hours. Needs Device Settings on. Applies at the next power check. " + _OFFROAD,
     default="30 hours (stock)", range="5 minutes, 15 / 30 / 45 minutes, then 1 to 30 hours")
_add("LowVoltageShutdown", "Low-Voltage Cutoff",
     "The car battery voltage below which the device shuts down to protect the battery. Higher shuts down earlier.",
     note="Never lower than the stock 11.8 V. Needs Device Settings on. " + _OFFROAD,
     default="11.8 V (stock)", range="11.8 to 12.5 V, in 0.1 steps")
_add("ScreenManagement", "Screen Settings",
     "Master switch for screen brightness, timeout and standby. Off keeps stock display behavior.",
     note=_OFFROAD,
     default="Stock behavior")
_add("ScreenBrightness", "Screen Brightness (Offroad)",
     "Screen brightness while the car is off. Auto uses the stock automatic brightness.",
     note="Needs Screen Settings on. " + _OFFROAD,
     default="Auto", range="1 to 100 percent, or Auto")
_add("ScreenBrightnessOnroad", "Screen Brightness (Onroad)",
     "Screen brightness while driving. Auto uses the stock automatic brightness.",
     note="Alerts raise the screen to at least 30 percent so they stay visible. Needs Screen Settings on. " + _OFFROAD,
     default="Auto", range="0 to 100 percent, or Auto")
_add("ScreenTimeout", "Screen Timeout (Offroad)",
     "How long the screen stays on after your last touch while the car is off.",
     note="Needs Screen Settings on. " + _OFFROAD,
     default="30 seconds", range="5 to 60 seconds, in 5 second steps")
_add("ScreenTimeoutOnroad", "Screen Timeout (Onroad)",
     "How long the screen stays on after your last touch while driving.",
     note="Needs Screen Settings on. " + _OFFROAD,
     default="10 seconds (stock)", range="5 to 60 seconds, in 5 second steps")
_add("StandbyMode", "Standby Mode",
     "Lets the screen go to sleep after the timeout even while the car is on. Alerts and engagement changes wake it.",
     when="If you want a dark screen while driving.",
     note="Needs Screen Settings on. " + _OFFROAD,
     default="Off", default_param="StandbyMode")
_add("ScreenRecorderControl", "Screen Recorder",
     "Starts or stops a screen recording of what the UI draws. Recordings are saved on the device in 5 minute segments.",
     note="Refuses to start with under 1 GiB free. " + _OFFROAD)

# ---------------------------------------------------------------- Utilities
_add("DebugMode", "Debug Mode",
     "Shows BogPilot developer metrics on the next drive. It is not a permanent setting: it clears itself on the following "
     "offroad transition.",
     when="Only when you are troubleshooting.",
     note=_OFFROAD,
     default="Off", recommended="Off")
_add("BogPilotDefaultsReset", "Reset BogPilot Settings to Defaults",
     "Restores BogPilot's shipping defaults. A local backup is written first, and the reset is refused if the backup fails. "
     "Vehicle identity, calibration and cloud credentials are kept. No reboot.",
     note="Driving preferences change. Tuning sections such as Gas / Brake and Lane Changes go back to stock behavior until you "
          "change a setting in them again. " + _OFFROAD)
_add("DoToggleResetStock", "Reset Toggles to Stock openpilot",
     "Queues a reset of the openpilot toggles to stock values for the next time openpilot restarts. A backup is written first. "
     "Nothing changes right now and the device does not reboot.",
     note="Driving preferences change at the next restart. " + _OFFROAD)
_add("ClearCaches", "Clear Caches",
     "Deletes the download and model caches and the soft API cache. Settings backups, device identity and the operating system "
     "are never touched.",
     note=_OFFROAD)
_add("LocalDebugReport", "Save Debug Report Locally",
     "Writes a diagnostics file on this device with a few non-secret settings, the version and the names of error logs. Nothing "
     "is uploaded and the dongle ID and VIN are left out.",
     note=_OFFROAD)

# ---------------------------------------------------------------- Data
_add("data:Delete Driving Data", "Delete Driving Data",
     "Deletes the local driving data and footage stored on this device. Drives you have marked as preserved are kept.",
     when="To free space.",
     note="Cannot be undone. Asks you to confirm. " + _OFFROAD)
_add("data:Delete Error Logs", "Delete Error Logs",
     "Deletes the error logs stored on this device.",
     note="Cannot be undone. Asks you to confirm. " + _OFFROAD)
_add("data:Screen Recordings", "Screen Recordings",
     "Delete, delete all or rename the screen recordings saved on this device.",
     note="Recording must be stopped. Management is refused while a recording lock or partial file exists. " + _OFFROAD)
_add("data:Storage Use", "Storage Use",
     "Shows how much space driving data, error logs and screen recordings use. Read only.")
_add("data:Toggle Backups", "Toggle Backups",
     "Back up, restore or delete saved copies of your BogPilot feature toggles. Only audited, non-secret preferences are saved, "
     "and nothing leaves the device.",
     note="A backup only restores when the installed software, schema, platform and vehicle match exactly. " + _OFFROAD)
_add("data:Toggle Backups:BACKUP", "Back Up Toggles",
     "Saves a copy of your current feature toggles on this device.",
     note=_OFFROAD)
_add("data:Toggle Backups:DELETE", "Delete a Toggle Backup",
     "Deletes one compatible toggle backup that you pick.",
     note="Cannot be undone. " + _OFFROAD)
_add("data:Toggle Backups:DELETE ALL", "Delete All Toggle Backups",
     "Deletes every validated toggle backup. Older, system or executable archives are kept.",
     note="Cannot be undone. " + _OFFROAD)
_add("data:Toggle Backups:RESTORE", "Restore a Toggle Backup",
     "Lets you pick a backup and shows a preview of the changes first. Nothing changes until you apply the preview.",
     note=_OFFROAD)
_add("data:Toggle Backups.scope", "Scope",
     "Which preferences a toggle backup covers. Security, calibration, identity, driver monitoring and cloud keys are excluded, "
     "and nothing is uploaded.")
_add("data:Apply Preview", "Apply Preview",
     "Applies only the listed, compatible preference changes after writing a backup of your current settings. No restart or "
     "reboot is done.",
     note="Driving behavior preferences may change. " + _OFFROAD)
_add("data:BogPilot Stats", "BogPilot Stats",
     "View or reset the usage statistics BogPilot has collected on this device.",
     note="Stats stay local. Resetting keeps driving logs and recordings. " + _OFFROAD)
_add("data:BogPilot Stats:RESET", "Reset BogPilot Stats",
     "Clears the collected BogPilot statistics. Driving logs and recordings are kept.",
     note="Cannot be undone. Asks you to confirm. " + _OFFROAD)
_add("data:BogPilot Stats:EXPORT", "Export BogPilot Stats",
     "Writes a local JSON copy of the BogPilot statistics. It never uploads anything, and an existing file is not overwritten.",
     note="Asks you to confirm. " + _OFFROAD)
_add("data:View Stats", "View Stats", "Shows the saved BogPilot statistics. Read only.")
_add("data:Screen Recordings:DELETE", "Delete a Screen Recording",
     "Deletes one screen recording that you pick.",
     note="Cannot be undone. Recording must be stopped. " + _OFFROAD)
_add("data:Screen Recordings:DELETE ALL", "Delete All Screen Recordings",
     "Deletes all completed screen recordings on this device.",
     note="Cannot be undone. Recording must be stopped. " + _OFFROAD)
_add("data:Screen Recordings:RENAME", "Rename a Screen Recording",
     "Renames one screen recording. An existing file is never overwritten.",
     note="Recording must be stopped. " + _OFFROAD)

# Rows that deliberately have NO help popup (they keep the stock inline description, or have nothing to explain).
SKIPPED: dict[str, str] = {
  "Reset Steering row buttons (Reset Actuator Delay / Steer Ratio / Friction / Lateral Acceleration)":
    "action buttons named by the value they reset; the value row above carries the help",
  "-0.01 / +0.01 and -1 / +1 stepper rows": "no text area (the whole row is the buttons)",
  "Weather IncreaseFollowing / ReduceAcceleration / ReduceLateralAcceleration rows": "hidden: no consumer in this build",
  "CENavigation, CENavigationIntersections, CENavigationTurns, CENavigationLead rows": "hidden: no navigation producer in this build",
  "HumanLaneChanges and TurnDesires": "row items exist but are not registered on any page in this build",
  "Alert Volume Controller: Storage row": "informational text about the file store; no choice to explain",
  "Vehicle Info rows": "read-only CarParams readouts",
  "Disable Logging, High-Quality Recording, Raise Temperature Limits, Offroad Screensaver, Flash Panda, Force Drive State, "
  "BogPilot Backups": "unavailable placeholders; their inline description already says why they are unavailable",
  "Status rows, Total local data, per-category Storage Use rows, Preview Changes rows, Protected rows, Baseline, "
  "Affected keys": "live readouts, not settings",
  "BACK header rows and the Gas / Brake, Steering and Device 'Back' rows": "navigation",
  "Stock Toggles, Device, Software and Developer pages (stock openpilot)":
    "stock rows already expand their own description when you tap the title; left unchanged",
  "MICI layout": "BogPilot settings pages are TICI layout only in this tree",
}

# Registered param keys that deliberately have no help entry (key -> reason). Checked by the coverage test.
SKIPPED_KEYS: dict[str, str] = {
  "CENavigation": "hidden: no navigation producer in this build",
  "CENavigationIntersections": "hidden: no navigation producer in this build",
  "CENavigationTurns": "hidden: no navigation producer in this build",
  "CENavigationLead": "hidden: no navigation producer in this build",
  "HumanLaneChanges": "not registered on any page in this build",
  "TurnDesires": "not registered on any page in this build",
}

# Row titles (text only rows) that deliberately have no help popup. Checked by the native page-walk test.
SKIPPED_TITLES: frozenset[str] = frozenset({
  "Status", "Back", "BACK", "Storage", "Total local data", "Baseline", "Affected keys",
  # Steering Tuning reset buttons: named by the value they reset; the value row above carries the help.
  "Reset Actuator Delay", "Reset Steer Ratio", "Reset Friction", "Reset Lateral Acceleration",
  # Unavailable placeholders: their inline description already says why they are unavailable.
  "Flash Panda", "Force Drive State", "BogPilot Backups", "Disable Logging", "High-Quality Recording",
  "Raise Temperature Limits", "Offroad Screensaver",
})


# ---------------------------------------------------------------- Main menu rows (0.9.7 layout)
_add("menu.tuning_level", "Tuning Level",
     "Chooses how many settings the BogPilot menu shows. Minimal shows the basics, Standard adds the common options, Advanced "
     "adds the fine tuning, and Developer shows every setting. A setting that is hidden keeps its value; only the menu row is "
     "hidden, and a setting above your level reads as its default.",
     when="Pick Minimal or Standard for a simpler menu. Pick Developer to see everything.",
     note="Developer shows settings that change how the car drives. The level can only be changed while the car is off.",
     default="Developer, until you pick a level; your choice is then saved")
_add("menu.alerts_sounds", "Alerts and Sounds",
     "The alert volume controller and the BogPilot alerts.")
_add("menu.driving", "Driving Controls",
     "Choose the driving model, tune gas and brake, and adjust steering and lane changes.")
_add("menu.navigation", "Navigation",
     "The navigation widgets shown on the driving screen, such as the posted speed limit tile.")
_add("menu.system", "System Settings",
     "Local data and statistics, device and screen controls, and utilities such as resetting settings to the BogPilot defaults.")
_add("menu.theme", "Theme and Appearance",
     "The driving screen visuals: blind spot warnings, widgets, sidebar metrics and Bog to the Future.")
_add("menu.vehicle", "Vehicle Settings",
     "Pick the car, change vehicle controls, set up the stalk controls and see vehicle info.")


# Row ids that appear on a page more than once under different titles map to the same entry here.
ALIASES: dict[str, str] = {
  "group:advanced": "AdvancedLongitudinalTune",
  "group:conditional": "ConditionalExperimental",
  "group:profiles": "LongitudinalTune",
  "group:qol": "QOLLongitudinal",
  "qol": "QOLLongitudinal",
  "longitudinal": "LongitudinalTune",
  "weather": "WeatherPresets.page",
  "system:Device Settings": "DeviceManagement",
  "system:Screen Settings": "ScreenManagement",
  "driving_model": "driving_model.entry",
}


def resolve(key: str) -> HelpEntry | None:
  return HELP.get(ALIASES.get(key, key))


# ---------------------------------------------------------------------------------------------------------------------
# Text building (pure, no raylib)
# ---------------------------------------------------------------------------------------------------------------------
def _clean(text: str) -> str:
  # The popup renderer reads angle brackets as tags; entries must never contain them, but never let one through.
  return text.replace("<", "(").replace(">", ")")


def help_html(entry: HelpEntry, translate=None, extra: str = "") -> str:
  """HTML (tags the HtmlRenderer understands) for one popup."""
  t = translate if translate is not None else (lambda s: s)
  parts = ["<h2>" + _clean(t(entry.title)) + "</h2>", "<p>" + _clean(t(entry.what)) + "</p>"]
  if extra:
    parts.append("<p>" + _clean(extra) + "</p>")

  def section(label, body):
    if body:
      parts.append("<h4>" + _clean(t(label)) + "</h4>")
      parts.append("<p>" + _clean(t(body)) + "</p>")

  section(WHEN_LABEL, entry.when)
  section(SAFETY_LABEL, entry.note)
  section(RECOMMENDED_LABEL, entry.recommended)
  section(DEFAULT_LABEL, entry.default)
  section(RANGE_LABEL, entry.range)
  return "".join(parts)


def help_plain(entry: HelpEntry, translate=None) -> str:
  t = translate if translate is not None else (lambda s: s)
  bits = [t(entry.title), t(entry.what)]
  for label, body in ((WHEN_LABEL, entry.when), (SAFETY_LABEL, entry.note), (RECOMMENDED_LABEL, entry.recommended),
                      (DEFAULT_LABEL, entry.default), (RANGE_LABEL, entry.range)):
    if body:
      bits.append(t(label) + ": " + t(body))
  return "\n".join(bits)


# ---------------------------------------------------------------------------------------------------------------------
# Popup + wiring
# ---------------------------------------------------------------------------------------------------------------------
def create_help_dialog(entry: HelpEntry, extra: str = ""):
  """Scrollable popup with one Close button. Built lazily so this module imports without raylib."""
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.html_render import HtmlRenderer, ElementType
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  html = help_html(entry, tr, extra)

  class HelpDialog(ConfirmDialog):
    """ConfirmDialog (rich, single button) with left-aligned text. Close, Enter and Escape all just pop it."""
    def __init__(self):
      super().__init__(html, tr(CLOSE_LABEL), cancel_text="", rich=True)
      self.entry = entry
      self.html = html
      self.closed = False
      self._html_renderer = HtmlRenderer(text=html, text_size={ElementType.P: POPUP_FONT_SIZE})
      self._scroller = Scroller([self._html_renderer], line_separator=False, spacing=0)

    def _confirm_button_callback(self):
      self.closed = True
      super()._confirm_button_callback()

    def _cancel_button_callback(self):
      self.closed = True
      super()._cancel_button_callback()

  return HelpDialog()


def attach_help_first(item, *keys: str, extra=None):
  """attach_help with fallbacks: the first key that has an entry wins."""
  for key in keys:
    if resolve(key) is not None:
      return attach_help(item, key, extra)
  return item


def open_help(key: str, extra: str = ""):
  """Open the popup for `key`. Reads and writes nothing."""
  from openpilot.system.ui.lib.application import gui_app
  entry = resolve(key)
  if entry is None:
    return None
  dialog = create_help_dialog(entry, extra)
  gui_app.push_widget(dialog)
  return dialog


def _gate(item, key: str):
  """Tuning Level: hide the row while the chosen level is below the level the row needs. Rows with no level always show."""
  if not hasattr(item, "set_level_gate"):
    return
  from openpilot.selfdrive.ui.bogpilot import tuning_level
  if tuning_level.row_level(key) is not None:
    item.set_level_gate(lambda k=key: tuning_level.row_visible(k))


def attach_help(item, key: str, extra=None):
  """Make a ListItem open the help for `key` when its text area is tapped. The switch / buttons are untouched.

  extra: optional callable returning live text (for example a model's hash line) shown under the help.
  Unknown keys leave the row alone, so a row without an entry keeps the stock inline description.
  """
  _gate(item, key)
  if resolve(key) is None or not hasattr(item, "set_help_callback"):
    return item  # unknown key, or a stand-in row that is not a ListItem: leave it alone
  item.set_help_callback(lambda: open_help(key, extra() if callable(extra) else (extra or "")))
  item.help_key = key
  return item
