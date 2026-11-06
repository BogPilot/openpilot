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

static bool tesla_ap1 = false;
static bool tesla_ap1_standstill = false;

// AP1 angle rate tables (legacy Mobileye chassis). Not used for Model 3/Y.
static const AngleSteeringLimits TESLA_AP1_STEERING_LIMITS = {
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

static const LongitudinalLimits TESLA_AP1_LONG_LIMITS = {
  .max_accel = 425,       // 2. m/s^2
  .min_accel = 287,       // -3.52 m/s^2
  .inactive_accel = 375,  // 0. m/s^2
};

// Substitution windows: drop stock DAS from bus 2 only while OP recently TX'd.
static const uint32_t TESLA_AP1_STEER_SUBSTITUTE_TIMEOUT_US = 100000U;  // 100 ms
static const uint32_t TESLA_AP1_LONG_SUBSTITUTE_TIMEOUT_US = 50000U;    // 50 ms
static uint32_t tesla_ap1_last_steer_tx_ts = 0;
static uint32_t tesla_ap1_last_long_tx_ts = 0;
static bool tesla_ap1_steer_tx_seen = false;
static bool tesla_ap1_long_tx_seen = false;

#define TESLA_AP1_CLUSTER_LEN 3
static const int TESLA_AP1_CLUSTER_ADDRS[TESLA_AP1_CLUSTER_LEN] = {0x399, 0x389, 0x239};
static const uint32_t TESLA_AP1_CLUSTER_TIMEOUT_US[TESLA_AP1_CLUSTER_LEN] = {750000U, 750000U, 150000U};
static uint32_t tesla_ap1_cluster_tx_ts[TESLA_AP1_CLUSTER_LEN] = {0U, 0U, 0U};
static bool tesla_ap1_cluster_tx_seen[TESLA_AP1_CLUSTER_LEN] = {false, false, false};

static int tesla_ap1_cluster_index(int addr) {
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
    if (tesla_longitudinal) {
      tesla_stock_aeb = ((msg->data[2] & 0x03U) == 1U);
    }
  }
}

static bool tesla_ap1_tx_hook(const CANPacket_t *msg) {
  bool tx = true;
  bool violation = false;
  const int addr = msg->addr;

  // DAS_steeringControl: 2-bit control type (AP1 packing), lookup rate limits
  if (addr == 0x488) {
    int raw_angle_can = ((msg->data[0] & 0x7FU) << 8) | msg->data[1];
    int desired_angle = raw_angle_can - 16384;
    int steer_control_type = msg->data[2] >> 6;
    bool steer_control_enabled = (steer_control_type != 0) &&  // NONE
                                 (steer_control_type != 3);    // DISABLED

    if (steer_angle_cmd_checks(desired_angle, steer_control_enabled, TESLA_AP1_STEERING_LIMITS)) {
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
    if (tesla_longitudinal) {
      int aeb_event = msg->data[2] & 0x03U;
      if (aeb_event != 0) {
        violation = true;
      }
      if (tesla_stock_aeb) {
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
    int idx = tesla_ap1_cluster_index(addr);
    if (idx >= 0) {
      tesla_ap1_cluster_tx_ts[idx] = microsecond_timer_get();
      tesla_ap1_cluster_tx_seen[idx] = true;
    }
  }

  return tx;
}

static bool tesla_ap1_fwd_hook(int bus_num, int addr) {
  bool block_msg = false;

  if (bus_num == 2) {
    if (addr == 0x488) {
      block_msg = tesla_ap1_op_recently_sent(tesla_ap1_last_steer_tx_ts, tesla_ap1_steer_tx_seen,
                                             TESLA_AP1_STEER_SUBSTITUTE_TIMEOUT_US);
    }

    if (tesla_longitudinal && (addr == 0x2b9) && !tesla_stock_aeb) {
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
  tesla_longitudinal = GET_FLAG(param, 1U);  // TeslaSafetyFlags.LONG_CONTROL
  tesla_ap1_standstill = GET_FLAG(param, TESLA_FLAG_AP1_STANDSTILL);

  tesla_stock_aeb = false;
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
