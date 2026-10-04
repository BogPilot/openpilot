// Shared Model 3/Y and non-AP1 table. Not an AP1 limit. AP1 uses
// TESLA_AP1_STEERING_LIMITS, from Tinkla earlytesla-panda
// board/safety/safety_tesla.h (TESLA_LOOKUP_ANGLE_RATE_UP / _DOWN).
const SteeringLimits TESLA_STEERING_LIMITS = {
  .angle_deg_to_can = 10,
  .angle_rate_up_lookup = {
    {0., 5., 15.},
    {10., 1.6, .3}
  },
  .angle_rate_down_lookup = {
    {0., 5., 15.},
    {10., 7.0, .8}
  },
};

// AP1 only. Tinkla TESLA_LOOKUP_ANGLE_RATE_UP speeds {2., 7., 17.} rates {8., 4., 2.5};
// TESLA_LOOKUP_ANGLE_RATE_DOWN speeds {2., 7., 17.} rates {9., 5., 4.5}; TESLA_DEG_TO_CAN 10.
// Selected only when TESLA_FLAG_AP1 is set. The shared table above is not for AP1.
const SteeringLimits TESLA_AP1_STEERING_LIMITS = {
  .angle_deg_to_can = 10,
  .angle_rate_up_lookup = {
    {2., 7., 17.},
    {8., 4., 2.5}
  },
  .angle_rate_down_lookup = {
    {2., 7., 17.},
    {9., 5., 4.5}
  },
};

const LongitudinalLimits TESLA_LONG_LIMITS = {
  .max_accel = 425,       // 2. m/s^2
  .min_accel = 287,       // -3.52 m/s^2  // TODO: limit to -3.48
  .inactive_accel = 375,  // 0. m/s^2
};


const int TESLA_FLAG_POWERTRAIN = 1;
const int TESLA_FLAG_LONGITUDINAL_CONTROL = 2;
const int TESLA_FLAG_RAVEN = 4;
// Bit 3, value 8. Selects TESLA_AP1_STEERING_LIMITS. Does not overlap
// POWERTRAIN (1), LONGITUDINAL_CONTROL (2), or RAVEN (4). Set with
// LONGITUDINAL_CONTROL for CAR.TESLA_AP1_MODELS (flags 10) so chassis
// DAS_control is allowed. Does not set POWERTRAIN and does not require 0x2bf.
// tesla_tx_hook uses 0x2b9 when the powertrain flag is unset, and 0x2bf only
// when it is set.
const int TESLA_FLAG_AP1 = 8;

const CanMsg TESLA_TX_MSGS[] = {
  {0x488, 0, 4},  // DAS_steeringControl
  {0x45, 0, 8},   // STW_ACTN_RQ
  {0x45, 2, 8},   // STW_ACTN_RQ
  {0x2b9, 0, 8},  // DAS_control
};

// AP1 only. 0x349 is Tinkla DAS warning matrix 3. The tx hook allows only
// the all-zero clear (DAS_gas_to_resume, bit 1 of byte 0, held at 0).
// Not added to TESLA_TX_MSGS, so Model 3/Y and non-AP1 cannot send it.
const CanMsg TESLA_AP1_TX_MSGS[] = {
  {0x488, 0, 4},  // DAS_steeringControl
  {0x45, 0, 8},   // STW_ACTN_RQ
  {0x45, 2, 8},   // STW_ACTN_RQ
  {0x2b9, 0, 8},  // DAS_control
  {0x349, 0, 8},  // Hold clear
};

const CanMsg TESLA_PT_TX_MSGS[] = {
  {0x2bf, 0, 8},  // DAS_control
};

RxCheck tesla_rx_checks[] = {
  {.msg = {{0x2b9, 2, 8, .frequency = 25U}, { 0 }, { 0 }}},   // DAS_control
  {.msg = {{0x370, 0, 8, .frequency = 25U}, { 0 }, { 0 }}},   // EPAS_sysStatus
  {.msg = {{0x108, 0, 8, .frequency = 100U}, { 0 }, { 0 }}},  // DI_torque1
  {.msg = {{0x118, 0, 6, .frequency = 100U}, { 0 }, { 0 }}},  // DI_torque2
  {.msg = {{0x20a, 0, 8, .frequency = 50U}, { 0 }, { 0 }}},   // BrakeMessage
  {.msg = {{0x368, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},   // DI_state
  {.msg = {{0x318, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},   // GTW_carState
};

RxCheck tesla_raven_rx_checks[] = {
  {.msg = {{0x2b9, 2, 8, .frequency = 25U}, { 0 }, { 0 }}},   // DAS_control
  {.msg = {{0x131, 2, 8, .frequency = 100U}, { 0 }, { 0 }}},  // EPAS3P_sysStatus
  {.msg = {{0x108, 0, 8, .frequency = 100U}, { 0 }, { 0 }}},  // DI_torque1
  {.msg = {{0x118, 0, 6, .frequency = 100U}, { 0 }, { 0 }}},  // DI_torque2
  {.msg = {{0x20a, 0, 8, .frequency = 50U}, { 0 }, { 0 }}},   // BrakeMessage
  {.msg = {{0x368, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},   // DI_state
  {.msg = {{0x318, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},   // GTW_carState
};

RxCheck tesla_pt_rx_checks[] = {
  {.msg = {{0x106, 0, 8, .frequency = 100U}, { 0 }, { 0 }}},  // DI_torque1
  {.msg = {{0x116, 0, 6, .frequency = 100U}, { 0 }, { 0 }}},  // DI_torque2
  {.msg = {{0x1f8, 0, 8, .frequency = 50U}, { 0 }, { 0 }}},   // BrakeMessage
  {.msg = {{0x2bf, 2, 8, .frequency = 25U}, { 0 }, { 0 }}},   // DAS_control
  {.msg = {{0x256, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},   // DI_state
};

bool tesla_longitudinal = false;
bool tesla_powertrain = false;  // Are we the second panda intercepting the powertrain bus?
bool tesla_raven = false;
bool tesla_ap1 = false;

bool tesla_stock_aeb = false;

// Tinkla-style substitution window: drop a stock DAS frame from bus 2 only
// while openpilot has recently transmitted its own replacement on bus 0.
// Periods match TESLA_AP_FWD_MODDED (0x488 ~20 Hz, 0x2b9 ~40 Hz); timeout is 2x.
// Without a recent OP TX, stock frames are forwarded. Do not block for the
// whole time Tesla safety mode is active.
const uint32_t TESLA_STEER_SUBSTITUTE_TIMEOUT_US = 100000U;  // 100 ms
const uint32_t TESLA_LONG_SUBSTITUTE_TIMEOUT_US = 50000U;    // 50 ms
uint32_t tesla_last_steer_tx_ts = 0;
uint32_t tesla_last_long_tx_ts = 0;
bool tesla_steer_tx_seen = false;
bool tesla_long_tx_seen = false;

static bool tesla_op_recently_sent(uint32_t last_ts, bool seen, uint32_t timeout_us) {
  if (!seen) {
    return false;
  }
  return get_ts_elapsed(microsecond_timer_get(), last_ts) < timeout_us;
}

static void tesla_rx_hook(const CANPacket_t *to_push) {
  int bus = GET_BUS(to_push);
  int addr = GET_ADDR(to_push);

  if (!tesla_powertrain) {
    if((!tesla_raven && (addr == 0x370) && (bus == 0)) || (tesla_raven && (addr == 0x131) && (bus == 2))) {
      // Steering angle: (0.1 * val) - 819.2 in deg.
      // Store it 1/10 deg to match steering request
      int angle_meas_new = (((GET_BYTE(to_push, 4) & 0x3FU) << 8) | GET_BYTE(to_push, 5)) - 8192U;
      update_sample(&angle_meas, angle_meas_new);
    }
  }

  if(bus == 0) {
    if(addr == (tesla_powertrain ? 0x116 : 0x118)) {
      // Vehicle speed: ((0.05 * val) - 25) * MPH_TO_MPS
      float speed = (((((GET_BYTE(to_push, 3) & 0x0FU) << 8) | (GET_BYTE(to_push, 2))) * 0.05) - 25) * 0.447;
      vehicle_moving = ABS(speed) > 0.1;
      UPDATE_VEHICLE_SPEED(speed);
    }

    if(addr == (tesla_powertrain ? 0x106 : 0x108)) {
      // Gas pressed
      gas_pressed = (GET_BYTE(to_push, 6) != 0U);
    }

    if(addr == (tesla_powertrain ? 0x1f8 : 0x20a)) {
      // Brake pressed
      brake_pressed = (((GET_BYTE(to_push, 0) & 0x0CU) >> 2) != 1U);
    }

    if(addr == (tesla_powertrain ? 0x256 : 0x368)) {
      // Cruise state
      int cruise_state = (GET_BYTE(to_push, 1) >> 4);

      acc_main_on = (cruise_state == 1) ||  // STANDBY
        (cruise_state == 2) ||  // ENABLED
        (cruise_state == 3) ||  // STANDSTILL
        (cruise_state == 4) ||  // OVERRIDE
        (cruise_state == 6) ||  // PRE_FAULT
        (cruise_state == 7);    // PRE_CANCEL

      bool cruise_engaged = (cruise_state == 2) ||  // ENABLED
                            (cruise_state == 3) ||  // STANDSTILL
                            (cruise_state == 4) ||  // OVERRIDE
                            (cruise_state == 6) ||  // PRE_FAULT
                            (cruise_state == 7);    // PRE_CANCEL
      pcm_cruise_check(cruise_engaged);
    }
  }

  if (bus == 2) {
    int das_control_addr = (tesla_powertrain ? 0x2bf : 0x2b9);
    if (tesla_longitudinal && (addr == das_control_addr)) {
      // "AEB_ACTIVE"
      tesla_stock_aeb = ((GET_BYTE(to_push, 2) & 0x03U) == 1U);
    }
  }

  if (tesla_powertrain) {
    // 0x2bf: DAS_control should not be received on bus 0
    generic_rx_checks((addr == 0x2bf) && (bus == 0));
  } else {
    // 0x488: DAS_steeringControl should not be received on bus 0
    generic_rx_checks((addr == 0x488) && (bus == 0));
  }

}


static bool tesla_tx_hook(const CANPacket_t *to_send) {
  bool tx = true;
  int addr = GET_ADDR(to_send);
  bool violation = false;

  if(!tesla_powertrain && (addr == 0x488)) {
    // Steering control: (0.1 * val) - 1638.35 in deg.
    // We use 1/10 deg as a unit here
    int raw_angle_can = (((GET_BYTE(to_send, 0) & 0x7FU) << 8) | GET_BYTE(to_send, 1));
    int desired_angle = raw_angle_can - 16384;
    int steer_control_type = GET_BYTE(to_send, 2) >> 6;
    bool steer_control_enabled = (steer_control_type != 0) &&  // NONE
                                 (steer_control_type != 3);    // DISABLED

    // AP1 flag picks the Tinkla table. Otherwise the shared non-AP1 table.
    // 0x2bf is not part of this choice.
    const SteeringLimits limits = tesla_ap1 ? TESLA_AP1_STEERING_LIMITS : TESLA_STEERING_LIMITS;
    if (steer_angle_cmd_checks(desired_angle, steer_control_enabled, limits)) {
      violation = true;
    }
  }

  if (!tesla_powertrain && (addr == 0x45)) {
    // No button other than cancel can be sent by us
    int control_lever_status = (GET_BYTE(to_send, 0) & 0x3FU);
    if (control_lever_status != 1) {
      violation = true;
    }
  }

  // Unset powertrain flag: chassis DAS_control is 0x2b9, not 0x2bf.
  if(addr == (tesla_powertrain ? 0x2bf : 0x2b9)) {
    // DAS_control: longitudinal control message
    if (tesla_longitudinal) {
      // No AEB events may be sent by openpilot
      int aeb_event = GET_BYTE(to_send, 2) & 0x03U;
      if (aeb_event != 0) {
        violation = true;
      }

      // Don't send messages when the stock AEB system is active
      if (tesla_stock_aeb) {
        violation = true;
      }

      // Don't allow any acceleration limits above the safety limits
      int raw_accel_max = ((GET_BYTE(to_send, 6) & 0x1FU) << 4) | (GET_BYTE(to_send, 5) >> 4);
      int raw_accel_min = ((GET_BYTE(to_send, 5) & 0x0FU) << 5) | (GET_BYTE(to_send, 4) >> 3);
      violation |= longitudinal_accel_checks(raw_accel_max, TESLA_LONG_LIMITS);
      violation |= longitudinal_accel_checks(raw_accel_min, TESLA_LONG_LIMITS);
    } else {
      violation = true;
    }
  }

  // AP1 Hold clear. Reject any warning bit. Tinkla packs DAS_gas_to_resume
  // as (DAS_gas_to_resume << 1) in byte 0 of 0x349.
  if (tesla_ap1 && (addr == 0x349)) {
    if ((GET_BYTE(to_send, 0) | GET_BYTE(to_send, 1) | GET_BYTE(to_send, 2) | GET_BYTE(to_send, 3) |
         GET_BYTE(to_send, 4) | GET_BYTE(to_send, 5) | GET_BYTE(to_send, 6) | GET_BYTE(to_send, 7)) != 0U) {
      violation = true;
    }
  }

  if (violation) {
    tx = false;
  }

  // Record allowed OP transmits so fwd_hook can drop matching stock copies
  // only while a replacement is actually being sent (Tinkla FWD_MODDED idea).
  if (tx) {
    if (!tesla_powertrain && (addr == 0x488)) {
      tesla_last_steer_tx_ts = microsecond_timer_get();
      tesla_steer_tx_seen = true;
    }
    if (addr == (tesla_powertrain ? 0x2bf : 0x2b9)) {
      tesla_last_long_tx_ts = microsecond_timer_get();
      tesla_long_tx_seen = true;
    }
  }

  return tx;
}

static int tesla_fwd_hook(int bus_num, int addr) {
  int bus_fwd = -1;

  if(bus_num == 0) {
    // Chassis/PT to autopilot
    bus_fwd = 2;
  }

  if(bus_num == 2) {
    // Autopilot to chassis/PT
    int das_control_addr = (tesla_powertrain ? 0x2bf : 0x2b9);

    // Interceptor: stock DAS frames keep flowing unless OP is substituting.
    // Unconditional block of 0x488 / flag-gated block of 0x2b9 killed stock
    // Autopilot and AEB at boot (rlog 2026-10-04: stock bus-2 copies left
    // bus 0 ~0.1s after safety param 10).
    bool block_msg = false;
    if (!tesla_powertrain && (addr == 0x488)) {
      block_msg = tesla_op_recently_sent(tesla_last_steer_tx_ts, tesla_steer_tx_seen,
                                         TESLA_STEER_SUBSTITUTE_TIMEOUT_US);
    }

    if (tesla_longitudinal && (addr == das_control_addr) && !tesla_stock_aeb) {
      block_msg = tesla_op_recently_sent(tesla_last_long_tx_ts, tesla_long_tx_seen,
                                         TESLA_LONG_SUBSTITUTE_TIMEOUT_US);
    }

    if(!block_msg) {
      bus_fwd = 0;
    }
  }

  return bus_fwd;
}

static safety_config tesla_init(uint16_t param) {
  tesla_powertrain = GET_FLAG(param, TESLA_FLAG_POWERTRAIN);
  tesla_longitudinal = GET_FLAG(param, TESLA_FLAG_LONGITUDINAL_CONTROL);
  tesla_raven = GET_FLAG(param, TESLA_FLAG_RAVEN);
  tesla_ap1 = GET_FLAG(param, TESLA_FLAG_AP1);

  tesla_stock_aeb = false;
  tesla_steer_tx_seen = false;
  tesla_long_tx_seen = false;
  tesla_last_steer_tx_ts = 0;
  tesla_last_long_tx_ts = 0;

  safety_config ret;
  if (tesla_powertrain) {
    ret = BUILD_SAFETY_CFG(tesla_pt_rx_checks, TESLA_PT_TX_MSGS);
  } else if (tesla_raven) {
    ret = BUILD_SAFETY_CFG(tesla_raven_rx_checks, TESLA_TX_MSGS);
  } else if (tesla_ap1) {
    ret = BUILD_SAFETY_CFG(tesla_rx_checks, TESLA_AP1_TX_MSGS);
  } else {
    ret = BUILD_SAFETY_CFG(tesla_rx_checks, TESLA_TX_MSGS);
  }
  return ret;
}

const safety_hooks tesla_hooks = {
  .init = tesla_init,
  .rx = tesla_rx_hook,
  .tx = tesla_tx_hook,
  .fwd = tesla_fwd_hook,
};
