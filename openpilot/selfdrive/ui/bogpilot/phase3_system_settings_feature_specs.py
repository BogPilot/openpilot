"""Frozen nonsecret feature preference scope, derived from active-toggle audit.

Archival eligibility is NOT a claim that every registered feature has an active
consumer. No credentials, identifiers, calibration, action/status flags, vehicle
fingerprint overrides, cloud integration, DM or safety activation keys are included.
Source: own current registry + safe_feature_whitelist audit @ aee7f1bd9.
"""
import json

FEATURE_SPECS = json.loads(r'''{
  "AP1StandstillEngage": {
    "declared_default": null,
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "AP1StandstillEngage",
    "type": "BOOL"
  },
  "AccelerationPath": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Acceleration Path",
    "type": "BOOL"
  },
  "AccelerationProfile": {
    "declared_default": "2",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Acceleration Profile",
    "type": "INT"
  },
  "AdjacentLeadsUI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Adjacent Leads Tracking",
    "type": "BOOL"
  },
  "AdjacentPath": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Adjacent Lanes",
    "type": "BOOL"
  },
  "AdjacentPathMetrics": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Adjacent Lane Metrics",
    "type": "BOOL"
  },
  "AdvancedCustomUI": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Advanced UI Controls",
    "type": "BOOL"
  },
  "AdvancedLateralTune": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Advanced Lateral Tuning",
    "type": "BOOL"
  },
  "AdvancedLongitudinalTune": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Advanced Longitudinal Tuning",
    "type": "BOOL"
  },
  "AggressiveFollow": {
    "declared_default": "1.25",
    "max": 3,
    "min": 1,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Following Distance",
    "type": "FLOAT"
  },
  "AggressiveJerkAcceleration": {
    "declared_default": "50",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Acceleration Smoothness",
    "type": "FLOAT"
  },
  "AggressiveJerkDanger": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Safety Gap Bias",
    "type": "FLOAT"
  },
  "AggressiveJerkDeceleration": {
    "declared_default": "50",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Braking Smoothness",
    "type": "FLOAT"
  },
  "AggressiveJerkSpeed": {
    "declared_default": "50",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed-Up Response",
    "type": "FLOAT"
  },
  "AggressiveJerkSpeedDecrease": {
    "declared_default": "50",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Slowdown Response",
    "type": "FLOAT"
  },
  "AggressivePersonalityProfile": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Aggressive",
    "type": "BOOL"
  },
  "AlertVolumeControl": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Alert Volume Controller",
    "type": "BOOL"
  },
  "AlwaysOnLateral": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Always On Lateral",
    "type": "BOOL"
  },
  "AlwaysOnLateralLKAS": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Enable With LKAS",
    "type": "BOOL"
  },
  "AlwaysOnLateralMain": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Enable With Cruise Control",
    "type": "BOOL"
  },
  "BSMFlameTracks": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "BSMFlameTracks",
    "type": "BOOL"
  },
  "BigMap": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Larger Map Display",
    "type": "BOOL"
  },
  "BlindSpotMetrics": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Border Metrics",
    "type": "BOOL"
  },
  "BlindSpotPath": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Blind Spot Path",
    "type": "BOOL"
  },
  "BorderMetrics": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Border Metrics",
    "type": "BOOL"
  },
  "CECurves": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Curve Detected Ahead",
    "type": "BOOL"
  },
  "CECurvesLead": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Curve Detected Ahead",
    "type": "BOOL"
  },
  "CELead": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Lead Detected Ahead",
    "type": "BOOL"
  },
  "CENavigation": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Navigation-Based",
    "type": "BOOL"
  },
  "CENavigationIntersections": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Navigation-Based",
    "type": "BOOL"
  },
  "CENavigationLead": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Navigation-Based",
    "type": "BOOL"
  },
  "CENavigationTurns": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Navigation-Based",
    "type": "BOOL"
  },
  "CESignalLaneDetection": {
    "declared_default": "1",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Turn Signal Below",
    "type": "BOOL"
  },
  "CESignalSpeed": {
    "declared_default": "55",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Turn Signal Below",
    "type": "INT"
  },
  "CESlowerLead": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Lead Detected Ahead",
    "type": "BOOL"
  },
  "CESpeed": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Below",
    "type": "INT"
  },
  "CESpeedLead": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "With Lead",
    "type": "INT"
  },
  "CEStopLights": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "\"Detected\" Stop Lights/Signs",
    "type": "BOOL"
  },
  "CEStoppedLead": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Lead Detected Ahead",
    "type": "BOOL"
  },
  "CameraView": {
    "declared_default": "3",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Camera View",
    "type": "INT"
  },
  "ClusterOffset": {
    "declared_default": "1.015",
    "max": 1.05,
    "min": 1.0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.001,
    "title": "Dashboard Speed Offset",
    "type": "FLOAT"
  },
  "Compass": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Compass",
    "type": "BOOL"
  },
  "ConditionalExperimental": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Conditional Experimental Mode",
    "type": "BOOL"
  },
  "ConfidenceBall": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "ConfidenceBall",
    "type": "BOOL"
  },
  "CurveSpeedController": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Curve Speed Controller",
    "type": "BOOL"
  },
  "CustomAlerts": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "BogPilot Alerts",
    "type": "BOOL"
  },
  "CustomCruise": {
    "declared_default": "1",
    "max": 99,
    "min": 1,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Cruise Interval",
    "type": "INT"
  },
  "CustomCruiseLong": {
    "declared_default": "5",
    "max": 99,
    "min": 1,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Cruise Interval (Hold)",
    "type": "INT"
  },
  "CustomPersonalities": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Driving Personalities",
    "type": "BOOL"
  },
  "CustomUI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Driving Screen Widgets",
    "type": "BOOL"
  },
  "DecelerationProfile": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Deceleration Profile",
    "type": "INT"
  },
  "DeveloperHUD": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "DeveloperHUD",
    "type": "BOOL"
  },
  "DeveloperMetrics": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Developer Metrics",
    "type": "BOOL"
  },
  "DeveloperSidebar": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Developer Sidebar",
    "type": "BOOL"
  },
  "DeveloperSidebarMetric1": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Metric #1",
    "type": "INT"
  },
  "DeveloperSidebarMetric2": {
    "declared_default": "2",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Metric #2",
    "type": "INT"
  },
  "DeveloperSidebarMetric3": {
    "declared_default": "3",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Metric #3",
    "type": "INT"
  },
  "DeveloperSidebarMetric4": {
    "declared_default": "4",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Metric #4",
    "type": "INT"
  },
  "DeveloperSidebarMetric5": {
    "declared_default": "5",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Metric #5",
    "type": "INT"
  },
  "DeveloperSidebarMetric6": {
    "declared_default": "6",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Metric #6",
    "type": "INT"
  },
  "DeveloperSidebarMetric7": {
    "declared_default": "7",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Metric #7",
    "type": "INT"
  },
  "DeveloperUI": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Developer UI",
    "type": "BOOL"
  },
  "DeveloperWidgets": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Developer Widgets",
    "type": "BOOL"
  },
  "DeviceManagement": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Device Settings",
    "type": "BOOL"
  },
  "DeviceShutdown": {
    "declared_default": "9",
    "max": 33,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Device Shutdown Timer",
    "type": "INT"
  },
  "DisableOpenpilotLongitudinal": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Disable openpilot Longitudinal Control",
    "type": "BOOL"
  },
  "DisengageOnAccelerator": {
    "declared_default": null,
    "max": null,
    "min": null,
    "source": "explicit_stock_switch_whitelist",
    "step": null,
    "title": "Disengage on Accelerator Pedal",
    "type": "BOOL"
  },
  "DisengageVolume": {
    "declared_default": "101",
    "max": 101,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Disengage Volume",
    "type": "INT"
  },
  "DriverCamera": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Show Driver Camera When In Reverse",
    "type": "BOOL"
  },
  "DynamicPathWidth": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Dynamic Path Width",
    "type": "BOOL"
  },
  "DynamicPedalsOnUI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Gas / Brake Pedal Indicators",
    "type": "BOOL"
  },
  "EnableICIntegration": {
    "declared_default": null,
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "Instrument cluster integration",
    "type": "BOOL"
  },
  "EngageVolume": {
    "declared_default": "101",
    "max": 101,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Engage Volume",
    "type": "INT"
  },
  "ExperimentalGMTune": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "FrogsGoMoo's Experimental Tune",
    "type": "BOOL"
  },
  "ExperimentalMode": {
    "declared_default": null,
    "max": null,
    "min": null,
    "source": "explicit_stock_switch_whitelist",
    "step": null,
    "title": "Experimental Mode",
    "type": "BOOL"
  },
  "FPSCounter": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "FPS Display",
    "type": "BOOL"
  },
  "Fahrenheit": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Numerical Temperature Gauge",
    "type": "BOOL"
  },
  "ForceAutoTune": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Force Auto-Tune On",
    "type": "BOOL"
  },
  "ForceAutoTuneOff": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Force Auto-Tune Off",
    "type": "BOOL"
  },
  "ForceMPHDashboard": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Force MPH from Dashboard",
    "type": "BOOL"
  },
  "ForceStops": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Force Stop at \"Detected\" Stop Lights/Signs",
    "type": "BOOL"
  },
  "ForceTorqueController": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Force Torque Controller",
    "type": "BOOL"
  },
  "FrogsGoMoosTweak": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "FrogsGoMoo's Personal Tweaks",
    "type": "BOOL"
  },
  "FullMap": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Larger Map Display",
    "type": "BOOL"
  },
  "GreenLightAlert": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Green Light Alert",
    "type": "BOOL"
  },
  "HideAccelGraph": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "Hide Accel Graph",
    "type": "BOOL"
  },
  "HideAlerts": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Hide Non-Critical Alerts",
    "type": "BOOL"
  },
  "HideLeadMarker": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Hide Lead Marker",
    "type": "BOOL"
  },
  "HideMap": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Hide Map Settings Button",
    "type": "BOOL"
  },
  "HideMapIcon": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Hide Map Settings Button",
    "type": "BOOL"
  },
  "HideMaxSpeed": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Hide Max Speed",
    "type": "BOOL"
  },
  "HideSpeed": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Hide Current Speed",
    "type": "BOOL"
  },
  "HideSpeedLimit": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Hide Speed Limits",
    "type": "BOOL"
  },
  "HigherBitrate": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "High-Quality Recording",
    "type": "BOOL"
  },
  "HolidayThemes": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Holiday Themes",
    "type": "BOOL"
  },
  "HondaAltTune": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Gentle Following",
    "type": "BOOL"
  },
  "HondaLowSpeedPedal": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Responsive Pedal at Low Speeds",
    "type": "BOOL"
  },
  "HondaMaxBrake": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Increased Braking Force",
    "type": "BOOL"
  },
  "HumanAcceleration": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Human-Like Acceleration",
    "type": "BOOL"
  },
  "HumanFollowing": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Human-Like Following",
    "type": "BOOL"
  },
  "HumanLaneChanges": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Human-Like Lane Changes",
    "type": "BOOL"
  },
  "IncreaseFollowingLowVisibility": {
    "declared_default": "0",
    "max": 3,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Increase Following Distance by:",
    "type": "FLOAT"
  },
  "IncreaseFollowingRain": {
    "declared_default": "0",
    "max": 3,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Increase Following Distance by:",
    "type": "FLOAT"
  },
  "IncreaseFollowingRainStorm": {
    "declared_default": "0",
    "max": 3,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Increase Following Distance by:",
    "type": "FLOAT"
  },
  "IncreaseFollowingSnow": {
    "declared_default": "0",
    "max": 3,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Increase Following Distance by:",
    "type": "FLOAT"
  },
  "IsLdwEnabled": {
    "declared_default": null,
    "max": null,
    "min": null,
    "source": "explicit_stock_switch_whitelist",
    "step": null,
    "title": "Enable Lane Departure Warnings",
    "type": "BOOL"
  },
  "IsMetric": {
    "declared_default": null,
    "max": null,
    "min": null,
    "source": "explicit_stock_switch_whitelist",
    "step": null,
    "title": "Use Metric System",
    "type": "BOOL"
  },
  "LKASButtonControl": {
    "declared_default": "5",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "LKAS Button",
    "type": "INT"
  },
  "LaneChanges": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Lane Changes",
    "type": "BOOL"
  },
  "LaneDetectionWidth": {
    "declared_default": "0",
    "max": 15,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.1,
    "title": "Minimum Lane Width",
    "type": "FLOAT"
  },
  "LaneLinesWidth": {
    "declared_default": "4",
    "max": 24,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Lane Lines Width",
    "type": "INT"
  },
  "LateralTune": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Lateral Tuning",
    "type": "BOOL"
  },
  "LeadDepartingAlert": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Lead Departing Alert",
    "type": "BOOL"
  },
  "LeadDetectionThreshold": {
    "declared_default": "35",
    "max": 50,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Lead Detection Sensitivity",
    "type": "INT"
  },
  "LiveYOLO": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "LiveYOLO",
    "type": "BOOL"
  },
  "LockDoors": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Automatically Lock/Unlock Doors",
    "type": "BOOL"
  },
  "LongPitch": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Smooth Pedal Response on Hills",
    "type": "BOOL"
  },
  "LongitudinalActuatorDelay": {
    "declared_default": "",
    "max": 1,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Actuator Delay",
    "type": "FLOAT"
  },
  "LongitudinalTune": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Longitudinal Tuning",
    "type": "BOOL"
  },
  "LoudBlindspotAlert": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Loud \"Car Detected in Blindspot\" Alert",
    "type": "BOOL"
  },
  "LowVoltageShutdown": {
    "declared_default": "11.8",
    "max": 12.5,
    "min": 11.8,
    "source": "BOGPILOT_PARAMS",
    "step": 0.1,
    "title": "Low-Voltage Cutoff",
    "type": "FLOAT"
  },
  "MapAcceleration": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Map Accel/Decel to Gears",
    "type": "BOOL"
  },
  "MapDeceleration": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Map Accel/Decel to Gears",
    "type": "BOOL"
  },
  "MapGears": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Map Accel/Decel to Gears",
    "type": "BOOL"
  },
  "MapStyle": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Map Style",
    "type": "INT"
  },
  "MaxDesiredAcceleration": {
    "declared_default": "4.0",
    "max": 4.0,
    "min": 0.1,
    "source": "BOGPILOT_PARAMS",
    "step": 0.1,
    "title": "Maximum Acceleration",
    "type": "FLOAT"
  },
  "MinimumLaneChangeSpeed": {
    "declared_default": "20.0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Minimum Lane Change Speed",
    "type": "FLOAT"
  },
  "ModelRandomizer": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Model Randomizer",
    "type": "BOOL"
  },
  "ModelUI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Model UI",
    "type": "BOOL"
  },
  "NNFF": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Neural Network Feedforward (NNFF)",
    "type": "BOOL"
  },
  "NNFFLite": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Neural Network Feedforward (NNFF) Lite",
    "type": "BOOL"
  },
  "NavSettingLeftSide": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Show Map on Left Side of UI",
    "type": "BOOL"
  },
  "NavigationUI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Navigation Widgets",
    "type": "BOOL"
  },
  "NewLongAPI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "comma's New Longitudinal API",
    "type": "BOOL"
  },
  "NoLogging": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Disable Logging",
    "type": "BOOL"
  },
  "NudgelessLaneChange": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Automatic Lane Changes",
    "type": "BOOL"
  },
  "NumericalTemp": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Numerical Temperature Gauge",
    "type": "BOOL"
  },
  "OccViz": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "OccViz",
    "type": "BOOL"
  },
  "OffroadScreensaver": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "OffroadScreensaver",
    "type": "BOOL"
  },
  "Offset1": {
    "declared_default": "5",
    "max": 99,
    "min": -99,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed Offset (0\u201324 mph)",
    "type": "INT"
  },
  "Offset2": {
    "declared_default": "5",
    "max": 99,
    "min": -99,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed Offset (25\u201334 mph)",
    "type": "INT"
  },
  "Offset3": {
    "declared_default": "5",
    "max": 99,
    "min": -99,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed Offset (35\u201344 mph)",
    "type": "INT"
  },
  "Offset4": {
    "declared_default": "5",
    "max": 99,
    "min": -99,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed Offset (45\u201354 mph)",
    "type": "INT"
  },
  "Offset5": {
    "declared_default": "10",
    "max": 99,
    "min": -99,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed Offset (55\u201364 mph)",
    "type": "INT"
  },
  "Offset6": {
    "declared_default": "10",
    "max": 99,
    "min": -99,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed Offset (65\u201374 mph)",
    "type": "INT"
  },
  "Offset7": {
    "declared_default": "10",
    "max": 99,
    "min": -99,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed Offset (75\u201399 mph)",
    "type": "INT"
  },
  "OneLaneChange": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "One Lane Change Per Signal",
    "type": "BOOL"
  },
  "PathEdgeWidth": {
    "declared_default": "20",
    "max": 100,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Path Edges Width",
    "type": "INT"
  },
  "PathWidth": {
    "declared_default": "6.1",
    "max": 10,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.1,
    "title": "Path Width",
    "type": "FLOAT"
  },
  "PauseAOLOnBrake": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Pause on Brake Press Below",
    "type": "INT"
  },
  "PauseLateralOnSignal": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Turn Signal Only",
    "type": "BOOL"
  },
  "PauseLateralSpeed": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Pause Steering Below",
    "type": "INT"
  },
  "PedalsOnUI": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Gas / Brake Pedal Indicators",
    "type": "BOOL"
  },
  "PersonalizeOpenpilot": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Custom Themes",
    "type": "BOOL"
  },
  "PreferredSchedule": {
    "declared_default": "2",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Automatically Update Maps",
    "type": "INT"
  },
  "PromptDistractedVolume": {
    "declared_default": "101",
    "max": 101,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Prompt Distracted Volume",
    "type": "INT"
  },
  "PromptVolume": {
    "declared_default": "101",
    "max": 101,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Prompt Volume",
    "type": "INT"
  },
  "QOLLateral": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Quality of Life",
    "type": "BOOL"
  },
  "QOLLongitudinal": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Quality of Life",
    "type": "BOOL"
  },
  "QOLVisuals": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Quality of Life",
    "type": "BOOL"
  },
  "RadarTracksUI": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Radar Tracks",
    "type": "BOOL"
  },
  "RainbowPath": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Rainbow Path",
    "type": "BOOL"
  },
  "RandomThemes": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Random Themes",
    "type": "BOOL"
  },
  "RedesignUI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "RedesignUI",
    "type": "BOOL"
  },
  "ReduceAccelerationLowVisibility": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Reduce Acceleration by:",
    "type": "INT"
  },
  "ReduceAccelerationRain": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Reduce Acceleration by:",
    "type": "INT"
  },
  "ReduceAccelerationRainStorm": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Reduce Acceleration by:",
    "type": "INT"
  },
  "ReduceAccelerationSnow": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Reduce Acceleration by:",
    "type": "INT"
  },
  "ReduceLateralAccelerationLowVisibility": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Reduce Speed in Curves by:",
    "type": "INT"
  },
  "ReduceLateralAccelerationRain": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Reduce Speed in Curves by:",
    "type": "INT"
  },
  "ReduceLateralAccelerationRainStorm": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Reduce Speed in Curves by:",
    "type": "INT"
  },
  "ReduceLateralAccelerationSnow": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Reduce Speed in Curves by:",
    "type": "INT"
  },
  "RefuseVolume": {
    "declared_default": "101",
    "max": 101,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Refuse Volume",
    "type": "INT"
  },
  "RegenAwareStop": {
    "declared_default": null,
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "RegenAwareStop",
    "type": "BOOL"
  },
  "RegenComfortBrake": {
    "declared_default": null,
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "Regen comfort braking",
    "type": "BOOL"
  },
  "RelaxedFollow": {
    "declared_default": "1.75",
    "max": 3,
    "min": 1,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Following Distance",
    "type": "FLOAT"
  },
  "RelaxedJerkAcceleration": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Acceleration Smoothness",
    "type": "FLOAT"
  },
  "RelaxedJerkDanger": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Safety Gap Bias",
    "type": "FLOAT"
  },
  "RelaxedJerkDeceleration": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Braking Smoothness",
    "type": "FLOAT"
  },
  "RelaxedJerkSpeed": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed-Up Response",
    "type": "FLOAT"
  },
  "RelaxedJerkSpeedDecrease": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Slowdown Response",
    "type": "FLOAT"
  },
  "RelaxedPersonalityProfile": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Relaxed",
    "type": "BOOL"
  },
  "ReverseCruise": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Reverse Cruise Increase",
    "type": "BOOL"
  },
  "RoadEdgesWidth": {
    "declared_default": "2",
    "max": 24,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Road Edges Width",
    "type": "INT"
  },
  "RoadNameUI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Road Name",
    "type": "BOOL"
  },
  "RotatingWheel": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Rotating Steering Wheel",
    "type": "BOOL"
  },
  "SLCConfirmation": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Confirm New Speed Limits",
    "type": "BOOL"
  },
  "SLCConfirmationHigher": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Confirm New Speed Limits",
    "type": "BOOL"
  },
  "SLCConfirmationLower": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Confirm New Speed Limits",
    "type": "BOOL"
  },
  "SLCFallback": {
    "declared_default": "2",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Fallback Speed",
    "type": "INT"
  },
  "SLCLookaheadHigher": {
    "declared_default": "0",
    "max": 30,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Higher Limit Lookahead Time",
    "type": "INT"
  },
  "SLCLookaheadLower": {
    "declared_default": "0",
    "max": 30,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Lower Limit Lookahead Time",
    "type": "INT"
  },
  "SLCMapboxFiller": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Use Mapbox as Fallback",
    "type": "BOOL"
  },
  "SLCOverride": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Override Speed",
    "type": "INT"
  },
  "SNGHack": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Stop-and-Go Hack",
    "type": "BOOL"
  },
  "ScreenBrightness": {
    "declared_default": "101",
    "max": 101,
    "min": 1,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Screen Brightness (Offroad)",
    "type": "INT"
  },
  "ScreenBrightnessOnroad": {
    "declared_default": "101",
    "max": 101,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Screen Brightness (Onroad)",
    "type": "INT"
  },
  "ScreenManagement": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Screen Settings",
    "type": "BOOL"
  },
  "ScreenRecorder": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Screen Recorder",
    "type": "BOOL"
  },
  "ScreenTimeout": {
    "max": 60,
    "min": 5,
    "source": "BOGPILOT_PARAMS",
    "step": 5,
    "title": "Screen Timeout (Offroad)",
    "type": "INT"
  },
  "ScreenTimeoutOnroad": {
    "max": 60,
    "min": 5,
    "source": "BOGPILOT_PARAMS",
    "step": 5,
    "title": "Screen Timeout (Onroad)",
    "type": "INT"
  },
  "SetSpeedLimit": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Match Speed Limit on Engage",
    "type": "BOOL"
  },
  "SetSpeedOffset": {
    "declared_default": "0",
    "max": 99,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Offset Set Speed by:",
    "type": "INT"
  },
  "ShowCEMStatus": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Status Widget",
    "type": "BOOL"
  },
  "ShowCPU": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Sidebar Metrics",
    "type": "BOOL"
  },
  "ShowCSCStatus": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Status Widget",
    "type": "BOOL"
  },
  "ShowGPU": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Sidebar Metrics",
    "type": "BOOL"
  },
  "ShowIP": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Sidebar Metrics",
    "type": "BOOL"
  },
  "ShowMemoryUsage": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Sidebar Metrics",
    "type": "BOOL"
  },
  "ShowSLCOffset": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Show Speed Limit Offset",
    "type": "BOOL"
  },
  "ShowSpeedLimits": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Show Speed Limits",
    "type": "BOOL"
  },
  "ShowSteering": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Border Metrics",
    "type": "BOOL"
  },
  "ShowStoppingPoint": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Model Stopping Point",
    "type": "BOOL"
  },
  "ShowStoppingPointMetrics": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Model Stopping Point",
    "type": "BOOL"
  },
  "ShowStorageLeft": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Sidebar Metrics",
    "type": "BOOL"
  },
  "ShowStorageUsed": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Sidebar Metrics",
    "type": "BOOL"
  },
  "SignalMetrics": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Border Metrics",
    "type": "BOOL"
  },
  "SpeedLimitChangedAlert": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Speed Limit Changed Alert",
    "type": "BOOL"
  },
  "SpeedLimitController": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Speed Limit Controller",
    "type": "BOOL"
  },
  "SpeedLimitFiller": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Speed Limit Filler",
    "type": "BOOL"
  },
  "SpeedLimitSources": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Show Speed Limit Sources",
    "type": "BOOL"
  },
  "StandardFollow": {
    "declared_default": "1.45",
    "max": 3,
    "min": 1,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Following Distance",
    "type": "FLOAT"
  },
  "StandardJerkAcceleration": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Acceleration Smoothness",
    "type": "FLOAT"
  },
  "StandardJerkDanger": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Safety Gap Bias",
    "type": "FLOAT"
  },
  "StandardJerkDeceleration": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Braking Smoothness",
    "type": "FLOAT"
  },
  "StandardJerkSpeed": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Speed-Up Response",
    "type": "FLOAT"
  },
  "StandardJerkSpeedDecrease": {
    "declared_default": "100",
    "max": 200,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Slowdown Response",
    "type": "FLOAT"
  },
  "StandardPersonalityProfile": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Standard",
    "type": "BOOL"
  },
  "StandbyMode": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Standby Mode",
    "type": "BOOL"
  },
  "StartAccel": {
    "declared_default": "",
    "max": 4,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Start Acceleration",
    "type": "FLOAT"
  },
  "StaticPedalsOnUI": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Gas / Brake Pedal Indicators",
    "type": "BOOL"
  },
  "SteerDelay": {
    "declared_default": "",
    "max": 1,
    "min": 0.01,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Actuator Delay",
    "type": "FLOAT"
  },
  "SteerFriction": {
    "declared_default": "",
    "max": 1,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Friction",
    "type": "FLOAT"
  },
  "SteerKP": {
    "declared_default": "",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Kp Factor",
    "type": "FLOAT"
  },
  "SteerLatAccel": {
    "declared_default": "",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Lateral Acceleration",
    "type": "FLOAT"
  },
  "SteerRatio": {
    "declared_default": "",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Steer Ratio",
    "type": "FLOAT"
  },
  "StopAccel": {
    "declared_default": "",
    "max": 0,
    "min": -4,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Stop Acceleration",
    "type": "FLOAT"
  },
  "StoppingDecelRate": {
    "declared_default": "",
    "max": 1,
    "min": 0.001,
    "source": "BOGPILOT_PARAMS",
    "step": 0.001,
    "title": "Stopping Rate",
    "type": "FLOAT"
  },
  "SubaruSNG": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Stop and Go",
    "type": "BOOL"
  },
  "SwapSpeedGraph": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "FILE_TOGGLES",
    "step": null,
    "title": "Accel Graph on Top",
    "type": "BOOL"
  },
  "TacoTune": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "\"Taco Bell Run\" Turn Speed Hack",
    "type": "BOOL"
  },
  "TacoTuneHacks": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "\"Taco Bell Run\" Torque Hack",
    "type": "BOOL"
  },
  "ToyotaDoors": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Automatically Lock/Unlock Doors",
    "type": "BOOL"
  },
  "TuningLevel": {
    "declared_default": "0",
    "max": 3,
    "min": 0,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Tuning Level",
    "type": "INT"
  },
  "TurnDesires": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Force Turn Desires Below Lane Change Speed",
    "type": "BOOL"
  },
  "UnlimitedLength": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "\"Unlimited\" Road UI",
    "type": "BOOL"
  },
  "UnlockDoors": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Automatically Lock/Unlock Doors",
    "type": "BOOL"
  },
  "UseSI": {
    "declared_default": "1",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Use International System of Units",
    "type": "BOOL"
  },
  "UseVienna": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Use Vienna-Style Speed Signs",
    "type": "BOOL"
  },
  "VEgoStarting": {
    "declared_default": "",
    "max": 1,
    "min": 0.01,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Start Speed",
    "type": "FLOAT"
  },
  "VEgoStopping": {
    "declared_default": "",
    "max": 1,
    "min": 0.01,
    "source": "BOGPILOT_PARAMS",
    "step": 0.01,
    "title": "Stop Speed",
    "type": "FLOAT"
  },
  "VoltSNG": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Stop-and-Go Hack",
    "type": "BOOL"
  },
  "WarningImmediateVolume": {
    "declared_default": "101",
    "max": 101,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Warning Immediate Volume",
    "type": "INT"
  },
  "WarningSoftVolume": {
    "declared_default": "101",
    "max": 101,
    "min": 25,
    "source": "BOGPILOT_PARAMS",
    "step": 1,
    "title": "Warning Soft Volume",
    "type": "INT"
  },
  "WeatherPresets": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Weather Condition Offsets",
    "type": "BOOL"
  },
  "WheelSpeed": {
    "declared_default": "0",
    "max": null,
    "min": null,
    "source": "BOGPILOT_PARAMS",
    "step": null,
    "title": "Use Wheel Speed",
    "type": "BOOL"
  }
}''')
PROTECTED_EXCLUSIONS = json.loads(r'''{
  "AdbEnabled": "protected security policy",
  "AlwaysOnDM": "protected driver-monitoring policy",
  "AutomaticUpdates": "network/code installation policy",
  "AutomaticallyDownloadModels": "network/model installation policy",
  "CalibratedLateralAcceleration": "calibration",
  "CalibrationParams": "protected calibration",
  "CarParams": "protected car identity/configuration",
  "CarParamsPersistent": "protected car identity/configuration",
  "DebugMode": "transient not persistent preference",
  "DisableOnroadUploads": "removed cloud integration",
  "DoToggleReset": "protected action flag",
  "DoToggleResetStock": "protected action flag",
  "DongleId": "protected account/device identity",
  "ExperimentalLongitudinalEnabled": "protected safety activation",
  "ForceFingerprint": "vehicle identification",
  "GoatScream": "explicitly skipped feature",
  "HevcStream": "removed streaming",
  "HighQualityRecordingConsent": "action consent never archived/restored",
  "IncreaseThermalLimits": "unapproved thermal policy",
  "LiveParametersV2": "protected learned calibration",
  "LocalLoggingDisableConsent": "action consent never archived/restored",
  "NoUploads": "removed cloud integration",
  "OpenpilotEnabledToggle": "protected master safety choice",
  "RecordFront": "protected driver-camera privacy preference",
  "RemoteUIStream": "removed streaming",
  "SecOCKey": "protected key material",
  "ShowUploadRate": "removed cloud presentation",
  "SshEnabled": "protected security policy",
  "ToyotaDSUBypass": "protected safety bypass"
}''')

COMPAT_SOURCE_FILES = ('openpilot/common/bogpilot_alert_volumes.py', 'openpilot/common/bogpilot_ap1_profile.py', 'openpilot/common/bogpilot_onroad_toggles.py', 'openpilot/common/bogpilot_params.py', 'openpilot/common/bogpilot_settings.py', 'openpilot/common/bogpilot_shipping_defaults.py', 'openpilot/common/bogpilot_store.py', 'openpilot/common/bogpilot_toggles.py', 'openpilot/selfdrive/car/ap1_runtime.py', 'openpilot/selfdrive/car/card.py', 'openpilot/selfdrive/controls/lib/ap1_curve_speed.py', 'openpilot/selfdrive/controls/lib/ap1_planning.py', 'openpilot/selfdrive/controls/lib/bogpilot_csc.py', 'openpilot/selfdrive/controls/lib/bogpilot_radar.py', 'openpilot/selfdrive/monitoring/dmonitoringd.py', 'openpilot/selfdrive/selfdrived/selfdrived.py', 'openpilot/selfdrive/test/helpers.py', 'openpilot/selfdrive/test/process_replay/process_replay.py', 'openpilot/selfdrive/ui/bogpilot/alert_volumes.py', 'openpilot/selfdrive/ui/bogpilot/frogpilot_defaults.py', 'openpilot/selfdrive/ui/bogpilot/offroad_stats.py', 'openpilot/selfdrive/ui/bogpilot/phase3_system_settings_backend.py', 'openpilot/selfdrive/ui/bogpilot/phase3_system_settings_feature_specs.py', 'openpilot/selfdrive/ui/bogpilot/phase3_system_settings_features.py', 'openpilot/selfdrive/ui/bogpilot/toggle_metadata.py', 'openpilot/selfdrive/ui/bogpilot/vehicle_settings.py', 'openpilot/selfdrive/ui/layouts/onboarding.py', 'openpilot/selfdrive/ui/layouts/settings/bogpilot.py', 'openpilot/selfdrive/ui/layouts/settings/bogpilot_visuals.py', 'openpilot/selfdrive/ui/layouts/settings/developer.py', 'openpilot/selfdrive/ui/layouts/settings/toggles.py', 'openpilot/selfdrive/ui/layouts/sidebar.py', 'openpilot/selfdrive/ui/mici/layouts/home.py', 'openpilot/selfdrive/ui/mici/layouts/onboarding.py', 'openpilot/selfdrive/ui/mici/layouts/settings/developer.py', 'openpilot/selfdrive/ui/mici/layouts/settings/toggles.py', 'openpilot/selfdrive/ui/onroad/bogpilot/bogpilot_hud.py', 'openpilot/selfdrive/ui/onroad/bogpilot/bogpilot_model.py', 'openpilot/selfdrive/ui/onroad/bogpilot/bsm_state.py', 'openpilot/selfdrive/ui/onroad/bogpilot/cluster_layout.py', 'openpilot/selfdrive/ui/onroad/bogpilot/file_toggles.py', 'openpilot/selfdrive/ui/onroad/bogpilot/flame_tracks_logic.py', 'openpilot/selfdrive/ui/onroad/bogpilot/hud_compose.py', 'openpilot/selfdrive/ui/onroad/bogpilot/pedals.py', 'openpilot/selfdrive/ui/onroad/bogpilot/speed_limit_display.py', 'openpilot/selfdrive/ui/onroad/exp_button.py', 'openpilot/selfdrive/ui/soundd.py', 'openpilot/selfdrive/ui/ui_state.py', 'openpilot/selfdrive/ui/widgets/bogpilot_stats.py', 'openpilot/selfdrive/ui/widgets/exp_mode_button.py', 'openpilot/system/bogpilot/toggle_reset.py', 'openpilot/system/hardware/power_monitoring.py', 'openpilot/system/loggerd/loggerd.h', 'openpilot/system/manager/manager.py', 'openpilot/system/manager/process_config.py', 'openpilot/tools/bogpilot/rc_startup_gate.py')
