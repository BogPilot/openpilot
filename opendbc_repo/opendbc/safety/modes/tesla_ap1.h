#pragma once
// BogPilot AP1 (legacy Tesla) safety. Selected only when TESLA_FLAG_AP1 is set
// on SAFETY_TESLA. Model 3/Y path in tesla.h is unchanged when the flag is clear.
// Keep angle limits, cancel-only stalk, brake disengage and gas inhibition strict.

// Flag bits for SAFETY_TESLA param. LONG_CONTROL is bit 0 (value 1), matching
// upstream TeslaSafetyFlags.LONG_CONTROL. Do not #define that name here: Model 3/Y
// tesla_init declares a local const with the same identifier under ALLOW_DEBUG.
// AP1 and AP1_STANDSTILL are BogPilot-only; they must not overlap LONG_CONTROL
// or the deprecated DAS_STEERING_3_BIT (bit 1 / value 2).
#define TESLA_FLAG_AP1 8U
#define TESLA_FLAG_AP1_STANDSTILL 16U
// Auto Height in Park (car/tesla_ap1/ride_height.py, was Lower on Park). Set at car start only while Auto Height is on. Pre-AP
// flags 32-256 and the AP2 powertrain bit 512 are separate bits.
#define TESLA_FLAG_AP1_RIDE_HEIGHT 1024U
// Auto Height in Drive at standstill (car/tesla_ap1/ride_height.py HeightOnDrive). Its own bit, set at car start together with
// TESLA_FLAG_AP1_RIDE_HEIGHT while Auto Height is on. The Park bit alone never allows a request in Drive.
#define TESLA_FLAG_AP1_RIDE_HEIGHT_DRIVE 2048U
// Auto Height Very Low (0x308 byte 0 = 0x47), AP1 Model X only: set at car start only for a Model X with Auto Height on. It only
// widens the allowed levels; every other Park / Drive condition, and the Park or Drive bit itself, is still required.
#define TESLA_FLAG_AP1_RIDE_HEIGHT_VERY_LOW 4096U

static bool tesla_ap1 = false;
static bool tesla_ap1_longitudinal = false;
static bool tesla_ap1_stock_aeb = false;
static bool tesla_ap1_standstill = false;
// Last EPAS_sysStatus (0x370): the EPAS is not following angle commands. INHIBITED, FAULT or SNA, or an
// error other than IDLE, HANDS_ON (3) and HIGH_ANGLE_REQ (6), the two codes that stay latched after a
// hand-back. The host stops commanding in this state; the panda drops any ANGLE frame sent into it,
// except for the latched TMP_FAULT and HIGH_ANGLE_RATE_REQ cases in tesla_ap1_tx_hook.
static bool tesla_ap1_epas_refusing = false;
// Last EPAS_sysStatus (0x370) was AVAILABLE or ACTIVE with EAC_ERROR_TMP_FAULT (4). Like codes 3 and 6, the EPAS
// keeps code 4 latched until it is commanded again, so an ANGLE frame is the only thing that clears it.
static bool tesla_ap1_epas_tmp_fault_ready = false;
// Last EPAS_sysStatus (0x370) was AVAILABLE (only; not ACTIVE) with EAC_ERROR_HIGH_ANGLE_RATE_REQ (7). The EPAS
// latches code 7 the same way (recorded after a 0x488 gap: INHIBITED/7, then AVAILABLE/7 for the rest of the drive).
static bool tesla_ap1_epas_rate_req_ready = false;
// Last EPB_epasControl (0x214, bus 0, 10 Hz) said EPB_epasEACAllow == 1, and when it arrived. Watched through
// rx_all, not an RX check: a missing or stale 0x214 never touches controls_allowed, it only keeps codes 4 and 7 blocked.
static bool tesla_ap1_epb_eac_allow = false;
static uint32_t tesla_ap1_epb_eac_allow_ts = 0U;
// Auto Height: the 0x308 ride height request (bus 0). Allowed only with TESLA_FLAG_AP1_RIDE_HEIGHT, in Park (DI_gear from
// DI_torque2 0x118, recent), stopped, never while controls are allowed, byte 0 only 0x41-0x44 (Low, Medium, High, Very High), or
// 0x47 (Very Low) with TESLA_FLAG_AP1_RIDE_HEIGHT_VERY_LOW, bytes 1-7
// equal to the newest touchscreen 0x308 received on bus 0 (recent), at most one frame per 15 ms and at most 150 frames per
// stay in Park (one 2 s, 50 Hz burst is 100 frames). Leaving Park, or an unknown gear, ends the stay.
static bool tesla_ap1_ride_height = false;
static bool tesla_ap1_in_park = false;
static bool tesla_ap1_gear_seen = false;
static uint32_t tesla_ap1_gear_ts = 0U;
static uint8_t tesla_ap1_rh_rx[8] = {0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U};
static bool tesla_ap1_rh_rx_seen = false;
static uint32_t tesla_ap1_rh_rx_ts = 0U;
static bool tesla_ap1_rh_tx_seen = false;
static uint32_t tesla_ap1_rh_tx_ts = 0U;
static uint32_t tesla_ap1_rh_tx_count = 0U;
// Auto Height in Drive: the same 0x308 rule, but in Drive (DI_gear from 0x118, recent) instead of Park, only with
// TESLA_FLAG_AP1_RIDE_HEIGHT_DRIVE, stopped, gas not pressed, never while controls are allowed, and at most 150 frames per stay in
// Drive (its own counter). The same levels 0x41-0x44; bytes 1-7, the screen frame freshness and the 15 ms gap are shared.
static bool tesla_ap1_ride_height_drive = false;
static bool tesla_ap1_ride_height_very_low = false;
static bool tesla_ap1_in_drive = false;
static uint32_t tesla_ap1_rh_drive_tx_count = 0U;

static const LongitudinalLimits TESLA_AP1_LONG_LIMITS = {
  .max_accel = 425,       // 2. m/s^2
  .min_accel = 287,       // -3.52 m/s^2
  .inactive_accel = 375,  // 0. m/s^2
};

// Substitution windows: drop stock DAS from bus 2 only while OP recently TX'd.
static uint32_t tesla_ap1_last_steer_tx_ts = 0;
static uint32_t tesla_ap1_last_long_tx_ts = 0;
static bool tesla_ap1_steer_tx_seen = false;
static bool tesla_ap1_long_tx_seen = false;

#define TESLA_AP1_CLUSTER_LEN 3
static uint32_t tesla_ap1_cluster_tx_ts[TESLA_AP1_CLUSTER_LEN] = {0U, 0U, 0U};
static bool tesla_ap1_cluster_tx_seen[TESLA_AP1_CLUSTER_LEN] = {false, false, false};

static int tesla_ap1_cluster_index(int addr) {
  const int TESLA_AP1_CLUSTER_ADDRS[TESLA_AP1_CLUSTER_LEN] = {0x399, 0x389, 0x239};
  int idx = -1;
  for (int i = 0; i < TESLA_AP1_CLUSTER_LEN; i++) {
    if (TESLA_AP1_CLUSTER_ADDRS[i] == addr) {
      idx = i;
    }
  }
  return idx;
}

static bool tesla_ap1_op_recently_sent(uint32_t last_ts, bool seen, uint32_t timeout_us) {
  bool recent = false;
  if (seen) {
    recent = safety_get_ts_elapsed(microsecond_timer_get(), last_ts) < timeout_us;
  }
  return recent;
}

// Standstill experiment: one 0x2b9 shape accepted while longitudinal is not allowed.
// Raw accel: 0.04 * raw - 15.
static bool tesla_ap1_standby_frame(const CANPacket_t *msg, int raw_accel_min, int raw_accel_max) {
  int set_speed = msg->data[0] | ((msg->data[1] & 0x0FU) << 8);
  int acc_state = msg->data[1] >> 4;
  int aeb_event = msg->data[2] & 0x03U;
  bool ok = (set_speed == 0) && ((acc_state == 0) || (acc_state == 4)) && (aeb_event == 0);
  ok = ok && (raw_accel_max >= TESLA_AP1_LONG_LIMITS.min_accel) && (raw_accel_max <= TESLA_AP1_LONG_LIMITS.inactive_accel);
  ok = ok && (raw_accel_min >= TESLA_AP1_LONG_LIMITS.min_accel) && (raw_accel_min <= TESLA_AP1_LONG_LIMITS.inactive_accel);
  ok = ok && (raw_accel_min <= raw_accel_max);
  return ok;
}

static void tesla_ap1_rx_hook(const CANPacket_t *msg) {
  // EPAS_sysStatus (0x370) bus 0: steering angle
  if (msg_matches(msg, 0x370U, 0U)) {
    const int angle_meas_new = (((msg->data[4] & 0x3FU) << 8) | msg->data[5]) - 8192U;
    update_sample(&angle_meas, angle_meas_new);

    const int epas_eac_status = msg->data[6] >> 5;   // 0 INHIBITED, 1 AVAILABLE, 2 ACTIVE, 3 FAULT, 4 SNA
    const int epas_eac_error = msg->data[2] >> 4;
    const bool epas_status_refuses = (epas_eac_status != 1) && (epas_eac_status != 2);
    const bool epas_error_refuses = (epas_eac_error != 0) && (epas_eac_error != 3) && (epas_eac_error != 6);
    tesla_ap1_epas_refusing = epas_status_refuses || epas_error_refuses;
    // Status and error come from this same frame, so they are always the same age (0x370 is RX-checked at 25 Hz).
    tesla_ap1_epas_tmp_fault_ready = !epas_status_refuses && (epas_eac_error == 4);
    tesla_ap1_epas_rate_req_ready = (epas_eac_status == 1) && (epas_eac_error == 7);

    // While disengaged, openpilot sends no 0x488, so resync desired_angle_last
    // to the measured wheel. Rate tables unchanged once controls_allowed.
    if (!controls_allowed) {
      desired_angle_last = angle_meas_new;
    }
  }

  if (msg->bus == 0U) {
    // DI_torque2 (0x118): vehicle speed
    if (msg->addr == 0x118U) {
      float speed = (((((msg->data[3] & 0x0FU) << 8) | (msg->data[2])) * 0.05) - 25) * 0.447;
      vehicle_moving = SAFETY_ABS(speed) > 0.1;
      UPDATE_VEHICLE_SPEED(speed);

      // DI_gear: bits 12-14 (1 = P). Anything else, SNA and invalid included, is not Park.
      tesla_ap1_in_park = ((msg->data[1] & 0x70U) == 0x10U);
      if (!tesla_ap1_in_park) {
        tesla_ap1_rh_tx_count = 0U;
      }
      // DI_gear 4 = D. Anything else, SNA and invalid included, is not Drive.
      tesla_ap1_in_drive = ((msg->data[1] & 0x70U) == 0x40U);
      if (!tesla_ap1_in_drive) {
        tesla_ap1_rh_drive_tx_count = 0U;
      }
      tesla_ap1_gear_ts = microsecond_timer_get();
      tesla_ap1_gear_seen = true;
    }

    // DI_torque1 (0x108): gas pressed
    if (msg->addr == 0x108U) {
      gas_pressed = (msg->data[6] != 0U);
    }

    // BrakeMessage (0x20a)
    if (msg->addr == 0x20aU) {
      brake_pressed = (((msg->data[0] & 0x0CU) >> 2) != 1U);
    }

    // DI_state (0x368): cruise
    if (msg->addr == 0x368U) {
      int cruise_state = (msg->data[1] >> 4);

      acc_main_on = (cruise_state == 1) ||  // STANDBY
                    (cruise_state == 2) ||  // ENABLED
                    (cruise_state == 3) ||  // STANDSTILL
                    (cruise_state == 4) ||  // OVERRIDE
                    (cruise_state == 6) ||  // PRE_FAULT
                    (cruise_state == 7);    // PRE_CANCEL

      bool cruise_engaged = (cruise_state == 2) ||
                            (cruise_state == 3) ||
                            (cruise_state == 4) ||
                            (cruise_state == 6) ||
                            (cruise_state == 7);
      pcm_cruise_check(cruise_engaged);
    }
  }

  // Stock AEB from DAS_control on bus 2
  if (msg_matches(msg, 0x2b9U, 2U)) {
    if (tesla_ap1_longitudinal) {
      tesla_ap1_stock_aeb = ((msg->data[2] & 0x03U) == 1U);
    }
  }
}

// Every received message (rx_all). EPB_epasControl (0x214) bus 0: EPB_epasEACAllow, bits 2:0 of byte 0
// (1 = EAC allowed). Only the TMP_FAULT / HIGH_ANGLE_RATE_REQ exception in tesla_ap1_tx_hook reads it.
static void tesla_ap1_rx_all_hook(const CANPacket_t *msg) {
  if (msg_matches(msg, 0x214U, 0U, 3U)) {
    tesla_ap1_epb_eac_allow = ((msg->data[0] & 0x07U) == 1U);
    tesla_ap1_epb_eac_allow_ts = microsecond_timer_get();
  }
  // Touchscreen ride height request (0x308, bus 0, 10 Hz): the newest frame, for the Auto Height byte match.
  if (msg_matches(msg, 0x308U, 0U, 8U)) {
    for (int i = 0; i < 8; i++) {
      tesla_ap1_rh_rx[i] = msg->data[i];
    }
    tesla_ap1_rh_rx_seen = true;
    tesla_ap1_rh_rx_ts = microsecond_timer_get();
  }
}

// Auto Height 0x308 TX rule (see the state above).
static bool tesla_ap1_ride_height_tx_ok(const CANPacket_t *msg) {
  const uint32_t TESLA_AP1_GEAR_TIMEOUT_US = 100000U;     // DI_torque2 is 100 Hz
  const uint32_t TESLA_AP1_RH_RX_TIMEOUT_US = 500000U;    // the touchscreen sends 0x308 at 10 Hz
  const uint32_t TESLA_AP1_RH_TX_MIN_GAP_US = 15000U;     // the burst is 50 Hz (20 ms apart)
  const uint32_t TESLA_AP1_RH_TX_MAX_PER_PARK = 150U;      // per stay in Park, and separately per stay in Drive

  bool park_ok = tesla_ap1_ride_height && tesla_ap1_in_park && (tesla_ap1_rh_tx_count < TESLA_AP1_RH_TX_MAX_PER_PARK);
  bool drive_ok = tesla_ap1_ride_height_drive && tesla_ap1_in_drive && !gas_pressed &&
                  (tesla_ap1_rh_drive_tx_count < TESLA_AP1_RH_TX_MAX_PER_PARK);
  bool ok = (park_ok || drive_ok) && !controls_allowed && !vehicle_moving &&
            tesla_ap1_op_recently_sent(tesla_ap1_gear_ts, tesla_ap1_gear_seen, TESLA_AP1_GEAR_TIMEOUT_US) &&
            tesla_ap1_op_recently_sent(tesla_ap1_rh_rx_ts, tesla_ap1_rh_rx_seen, TESLA_AP1_RH_RX_TIMEOUT_US);
  // Low (0x41), Medium (0x42), High (0x43) or Very High (0x44), in Park or Drive, and Very Low (0x47) only with its flag.
  // Idle (0x40) and anything else are refused.
  bool level_ok = ((msg->data[0] >= 0x41U) && (msg->data[0] <= 0x44U)) ||
                  (tesla_ap1_ride_height_very_low && (msg->data[0] == 0x47U));
  if (!level_ok) {
    ok = false;
  }
  for (int i = 1; i < 8; i++) {
    if (msg->data[i] != tesla_ap1_rh_rx[i]) {
      ok = false;
    }
  }
  if (tesla_ap1_op_recently_sent(tesla_ap1_rh_tx_ts, tesla_ap1_rh_tx_seen, TESLA_AP1_RH_TX_MIN_GAP_US)) {
    ok = false;
  }
  return ok;
}

// Legacy Model S vehicle model for the lateral-accel bound (AP1 and Pre-AP): steer ratio 15, wheelbase 2.959 m (CarSpecs in
// car/tesla_ap1/values.py), slip factor as calc_slip_factor() for that car. Must match car/tesla_ap1/lateral_limits.py.
static const AngleSteeringParams TESLA_LEGACY_LAT_ACCEL_PARAMS = {
  .slip_factor = -0.0005666,
  .steer_ratio = 15.,
  .wheelbase = 2.959,
};

static bool tesla_ap1_tx_hook(const CANPacket_t *msg) {
  bool tx = true;
  bool violation = false;
  const int addr = msg->addr;

  // DAS_steeringControl: 2-bit control type (AP1 packing), lookup rate limits
  if (addr == 0x488) {
    int raw_angle_can = ((msg->data[0] & 0x7FU) << 8) | msg->data[1];
    int desired_angle = raw_angle_can - 16384;
    int steer_control_type = msg->data[2] >> 6;
    // AP1 angle rate tables (legacy Mobileye chassis). Not used for Model 3/Y.
    const AngleSteeringLimits TESLA_AP1_STEERING_LIMITS = {
      .max_angle = 3600,  // 360 deg
      .angle_deg_to_can = 10,
      .angle_rate_up_lookup = {
        {2., 7., 17.},
        {8., 4., 2.5}
      },
      .angle_rate_down_lookup = {
        {2., 7., 17.},
        {9., 5., 4.5}
      },
      .frequency = 20U,  // DAS_steeringControl ~20 Hz on AP1
    };
    bool steer_control_enabled = (steer_control_type != 0) &&  // NONE
                                 (steer_control_type != 3);    // DISABLED

    if (steer_angle_cmd_checks(desired_angle, steer_control_enabled, TESLA_AP1_STEERING_LIMITS)) {
      violation = true;
    }
    // Lateral-accel bound and +-360 deg on ANGLE commands (stage 1; the rate tables above are unchanged).
    if (steer_angle_lat_accel_check(desired_angle, steer_control_enabled, controls_allowed, TESLA_AP1_STEERING_LIMITS,
                                    TESLA_LEGACY_LAT_ACCEL_PARAMS)) {
      violation = true;
    }
    // Never send an active steering command into an EPAS that is INHIBITED, FAULT, SNA or in error.
    // One exception: a latched EAC_ERROR_TMP_FAULT (4) while the EPAS is AVAILABLE or ACTIVE, or a latched
    // EAC_ERROR_HIGH_ANGLE_RATE_REQ (7) while the EPAS is AVAILABLE, and the EPB allowed EAC within the last 250 ms
    // (2x the slowest 0x214 gap seen). BogPilot 0.9.7, Tinkla and NAP do not gate the error code at all; this keeps
    // every other code blocked. The rate tables and the lateral-accel bound above still apply to these frames.
    const uint32_t TESLA_AP1_EPB_ALLOW_TIMEOUT_US = 250000U;
    const bool latched_ready = tesla_ap1_epas_tmp_fault_ready || tesla_ap1_epas_rate_req_ready;
    const bool tmp_fault_recovery = latched_ready &&
                                    tesla_ap1_op_recently_sent(tesla_ap1_epb_eac_allow_ts, tesla_ap1_epb_eac_allow,
                                                               TESLA_AP1_EPB_ALLOW_TIMEOUT_US);
    if (steer_control_enabled && tesla_ap1_epas_refusing && !tmp_fault_recovery) {
      violation = true;
    }
  }

  // STW_ACTN_RQ: cancel only
  if (addr == 0x45) {
    int control_lever_status = (msg->data[0] & 0x3FU);
    if (control_lever_status != 1) {
      violation = true;
    }
  }

  // DAS_control chassis longitudinal
  if (addr == 0x2b9) {
    if (tesla_ap1_longitudinal) {
      int aeb_event = msg->data[2] & 0x03U;
      if (aeb_event != 0) {
        violation = true;
      }
      if (tesla_ap1_stock_aeb) {
        violation = true;
      }

      int raw_accel_max = ((msg->data[6] & 0x1FU) << 4) | (msg->data[5] >> 4);
      int raw_accel_min = ((msg->data[5] & 0x0FU) << 5) | (msg->data[4] >> 3);
      bool standby_ok = tesla_ap1_standstill && !get_longitudinal_allowed() &&
                        tesla_ap1_standby_frame(msg, raw_accel_min, raw_accel_max);
      if (!standby_ok) {
        violation |= longitudinal_accel_checks(raw_accel_max, TESLA_AP1_LONG_LIMITS);
        violation |= longitudinal_accel_checks(raw_accel_min, TESLA_AP1_LONG_LIMITS);
      }
    } else {
      violation = true;
    }
  }

  // Hold clear 0x349: all-zero only
  if (addr == 0x349) {
    if ((msg->data[0] | msg->data[1] | msg->data[2] | msg->data[3] |
         msg->data[4] | msg->data[5] | msg->data[6] | msg->data[7]) != 0U) {
      violation = true;
    }
  }

  // AutopilotStatus 0x399: active states 3/4/5 require controls_allowed
  if (addr == 0x399) {
    int autopilot_state = msg->data[0] & 0x0FU;
    if ((autopilot_state >= 3) && (autopilot_state <= 5) && !controls_allowed) {
      violation = true;
    }
  }

  // Auto Height ride height request 0x308
  if (addr == 0x308) {
    if (!tesla_ap1_ride_height_tx_ok(msg)) {
      violation = true;
    }
  }

  if (violation) {
    tx = false;
  }

  if (tx) {
    if (addr == 0x488) {
      tesla_ap1_last_steer_tx_ts = microsecond_timer_get();
      tesla_ap1_steer_tx_seen = true;
    }
    if (addr == 0x2b9) {
      tesla_ap1_last_long_tx_ts = microsecond_timer_get();
      tesla_ap1_long_tx_seen = true;
    }
    if (addr == 0x308) {
      tesla_ap1_rh_tx_ts = microsecond_timer_get();
      tesla_ap1_rh_tx_seen = true;
      if (tesla_ap1_in_drive) {
        tesla_ap1_rh_drive_tx_count += 1U;
      } else {
        tesla_ap1_rh_tx_count += 1U;
      }
    }
    int idx = tesla_ap1_cluster_index(addr);
    if (idx >= 0) {
      tesla_ap1_cluster_tx_ts[idx] = microsecond_timer_get();
      tesla_ap1_cluster_tx_seen[idx] = true;
    }
  }

  return tx;
}

static bool tesla_ap1_fwd_hook(int bus_num, int addr) {
  const uint32_t TESLA_AP1_STEER_SUBSTITUTE_TIMEOUT_US = 100000U;  // 100 ms
  const uint32_t TESLA_AP1_LONG_SUBSTITUTE_TIMEOUT_US = 50000U;    // 50 ms
  const uint32_t TESLA_AP1_CLUSTER_TIMEOUT_US[TESLA_AP1_CLUSTER_LEN] = {750000U, 750000U, 150000U};
  bool block_msg = false;

  if (bus_num == 2) {
    if (addr == 0x488) {
      block_msg = tesla_ap1_op_recently_sent(tesla_ap1_last_steer_tx_ts, tesla_ap1_steer_tx_seen,
                                             TESLA_AP1_STEER_SUBSTITUTE_TIMEOUT_US);
    }

    if (tesla_ap1_longitudinal && (addr == 0x2b9) && !tesla_ap1_stock_aeb) {
      block_msg = tesla_ap1_op_recently_sent(tesla_ap1_last_long_tx_ts, tesla_ap1_long_tx_seen,
                                             TESLA_AP1_LONG_SUBSTITUTE_TIMEOUT_US);
    }

    int idx = tesla_ap1_cluster_index(addr);
    if (idx >= 0) {
      block_msg = tesla_ap1_op_recently_sent(tesla_ap1_cluster_tx_ts[idx], tesla_ap1_cluster_tx_seen[idx],
                                             TESLA_AP1_CLUSTER_TIMEOUT_US[idx]);
    }
  }

  return block_msg;
}

static safety_config tesla_ap1_init_config(uint16_t param) {
  // AP1 enables longitudinal from the flag without the Model 3/Y ALLOW_DEBUG gate.
  tesla_ap1_longitudinal = GET_FLAG(param, 1U);  // TeslaSafetyFlags.LONG_CONTROL
  tesla_ap1_standstill = GET_FLAG(param, TESLA_FLAG_AP1_STANDSTILL);
  tesla_ap1_ride_height = GET_FLAG(param, TESLA_FLAG_AP1_RIDE_HEIGHT);
  tesla_ap1_ride_height_drive = GET_FLAG(param, TESLA_FLAG_AP1_RIDE_HEIGHT_DRIVE);
  tesla_ap1_ride_height_very_low = GET_FLAG(param, TESLA_FLAG_AP1_RIDE_HEIGHT_VERY_LOW);
  tesla_ap1_in_park = false;
  tesla_ap1_in_drive = false;
  tesla_ap1_rh_drive_tx_count = 0U;
  tesla_ap1_gear_seen = false;
  tesla_ap1_gear_ts = 0U;
  for (int i = 0; i < 8; i++) {
    tesla_ap1_rh_rx[i] = 0U;
  }
  tesla_ap1_rh_rx_seen = false;
  tesla_ap1_rh_rx_ts = 0U;
  tesla_ap1_rh_tx_seen = false;
  tesla_ap1_rh_tx_ts = 0U;
  tesla_ap1_rh_tx_count = 0U;

  tesla_ap1_stock_aeb = false;
  tesla_ap1_epas_refusing = false;
  tesla_ap1_epas_tmp_fault_ready = false;
  tesla_ap1_epas_rate_req_ready = false;
  tesla_ap1_epb_eac_allow = false;
  tesla_ap1_epb_eac_allow_ts = 0U;
  tesla_ap1_steer_tx_seen = false;
  tesla_ap1_long_tx_seen = false;
  tesla_ap1_last_steer_tx_ts = 0;
  tesla_ap1_last_long_tx_ts = 0;
  for (int i = 0; i < TESLA_AP1_CLUSTER_LEN; i++) {
    tesla_ap1_cluster_tx_ts[i] = 0U;
    tesla_ap1_cluster_tx_seen[i] = false;
  }

  // Dynamic substitution for steer/long/cluster: check_relay for malfunction
  // detection, disable_static_blocking so fwd_hook can pass stock through
  // until OP is actually transmitting a replacement.
  static const CanMsg TESLA_AP1_TX_MSGS[] = {
    {0x488, 0, 4, .check_relay = true, .disable_static_blocking = true},  // DAS_steeringControl
    {0x45, 0, 8, .check_relay = false},   // STW_ACTN_RQ
    {0x45, 2, 8, .check_relay = false},   // STW_ACTN_RQ
    {0x2b9, 0, 8, .check_relay = true, .disable_static_blocking = true},  // DAS_control
    {0x349, 0, 8, .check_relay = false},  // Hold clear
    {0x399, 0, 8, .check_relay = true, .disable_static_blocking = true},  // AutopilotStatus
    {0x389, 0, 8, .check_relay = true, .disable_static_blocking = true},  // DAS_status2
    {0x239, 0, 8, .check_relay = true, .disable_static_blocking = true},  // DAS_lanes
    {0x308, 0, 8, .check_relay = false},  // Auto Height ride height request (the touchscreen also sends it on bus 0)
  };

  // AP1 chassis RX. No counters/checksums enforced here (stock AP1 frames).
  static RxCheck tesla_ap1_rx_checks[] = {
    {.msg = {{0x2b9, 2, 8, 25U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // DAS_control
    {.msg = {{0x370, 0, 8, 25U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // EPAS_sysStatus
    {.msg = {{0x108, 0, 8, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}}, // DI_torque1
    {.msg = {{0x118, 0, 6, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}}, // DI_torque2
    {.msg = {{0x20a, 0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // BrakeMessage
    {.msg = {{0x368, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // DI_state
    {.msg = {{0x318, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // GTW_carState
  };

  return BUILD_SAFETY_CFG(tesla_ap1_rx_checks, TESLA_AP1_TX_MSGS);
}
