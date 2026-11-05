"""NAP-style Pre-AP VirtualDAS and pedal long constants.

Credit: NAP-style / Tinkla pedal profiles reduced for feedforward architecture.
"""

# Pre-AP pedal accel envelopes, mapped to openpilot Driving Personality toggle.
ACCEL_PREAP_BP = [0.0, 1.3, 7.5, 15.0, 25.0, 30.0, 40.0]  # m/s
ACCEL_PREAP_PROFILES = {
  0: [0.3, 0.8, 1.1, 1.0, 0.85, 0.7, 0.6],  # aggressive
  1: [0.3, 0.7, 1.0, 0.9, 0.8, 0.6, 0.5],  # standard
  2: [0.3, 0.6, 0.9, 0.8, 0.7, 0.5, 0.45],  # relaxed
}
ACCEL_PREAP_FOLLOW = [0.3, 0.6, 0.9, 0.8, 0.7, 0.5, 0.45]

PEDAL_LONG_K_BP = [0.0, 3.0, 6.0, 35.0]
PEDAL_LONG_KP_V = [0.0, 0.0, 0.0, 0.0]
PEDAL_LONG_KI_V = [0.0, 0.0, 0.0, 0.0]

VDAS_INNER_K_BP = [0.0, 5.0, 35.0]
VDAS_INNER_KP_V = [0.0, 0.0, 0.0]
VDAS_INNER_KI_V = [0.3, 0.2, 0.15]

VDAS_FUTURE_T_BP = [2.0, 5.0]
VDAS_FUTURE_T_V = [0.30, 0.55]
VDAS_AEGO_FILTER_RC = 0.25
VDAS_ACCEL_JERK_MAX = 1.0  # m/s^3
VDAS_DECEL_JERK_MAX = 2.5  # m/s^3
VDAS_ACCEL_SNAP_MAX = 4.0  # m/s^4
VDAS_ZERO_TORQUE_TRANSITION_WIDTH = 0.25  # m/s^2 each side of zero
VDAS_EGO_JERK_MAX = 5.0  # m/s^3

PEDAL_DI_MIN = -5.0
PEDAL_DI_ZERO = 0.0
PEDAL_DI_PRESSED = 2.0
ACCEL_MAX = 2.5  # m/s^2
REGEN_MAX = -1.5  # m/s^2

PEDAL_BP = [0., 5., 12., 20., 30., 40.]
PEDAL_MAX_VALUES = [50., 58., 66., 74., 82., 90.]

PEDAL_RAMP_RATE_UP = 5.0    # DI/step @ 50Hz
PEDAL_RAMP_RATE_DOWN = 2.5  # DI/step @ 50Hz
ACCEL_DEADBAND = 0.15  # m/s^2
PEDAL_HYST_GAP = 1.0  # DI units

ENGAGE_GRACE_FRAMES = 50  # 0.5s at 100Hz
ENGAGE_GRACE_PEDAL_RAMP_RATE_UP = 0.9  # DI/update at 50Hz
