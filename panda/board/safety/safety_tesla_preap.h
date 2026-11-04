#pragma once

// =============================================================================
// SAFETY_TESLA_PREAP — Pre-Autopilot Tesla Model S (BogPilot)
// =============================================================================
//
// Adapted from NotAutopilot's opendbc safety/modes/tesla_preap.h for BogPilot's
// FrogPilot 0.9.7 panda API. Credit: NotAutopilot (nap-release / tesla_preap).
// Spiritual predecessor: Tinkla (BogGyver) Pre-AP safety tables.
//
// This mode is COMPLETELY SEPARATE from safety_tesla.h (SAFETY_TESLA / AP1).
// Selecting SAFETY_TESLA_PREAP never changes TESLA_AP1_TX_MSGS or tesla_hooks.
//
// Pre-AP has no Autopilot ECU and no harness relay. generic_rx_checks is called
// with stock_ecu_detected=false (same idea as Tinkla "PreAP has no relay").
//
// Full NAP chassis→radar GTW readdr (rx_all) is NOT ported — BogPilot 0.9.7
// safety_hooks has no rx_all. When PREAP_FLAG_RADAR_EMULATION is set, a tight
// TX whitelist allows Python dummy-VIN / GTW helper frames on the radar bus.
// Default off. Pedal + steer + stalk + EPAS gating are ported. See PREAP_NA.md.
//
// License: MIT (Comma.ai / openpilot lineage); keep notices with redistributions.
// =============================================================================

const int PREAP_FLAG_ENABLE_PEDAL = 1;
const int PREAP_FLAG_RADAR_EMULATION = 2;       // allow radar-bus helper TX (default off)
const int PREAP_FLAG_RADAR_BEHIND_NOSECONE = 4;  // mount hint for userspace (TX limits same)

// Same physical car as AP1 Model S. Rate tables match TESLA_AP1_STEERING_LIMITS
// so Pre-AP does not invent a looser steer envelope than AP1.
const SteeringLimits TESLA_PREAP_STEERING_LIMITS = {
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

static bool preap_enable_pedal = false;
static bool preap_radar_emulation = false;
static int preap_pedal_can = -1;
static int preap_gear = 4;
static int preap_gear_prev = 4;
static bool preap_doors_open = false;
static uint32_t preap_last_stalk_engage_us = 0;
#define PREAP_CANCEL_ECHO_WINDOW_US 600000U

// Narrow TX surface from NotAutopilot tesla_preap (no HUD spam, no iBooster).
const CanMsg TESLA_PREAP_TX_MSGS[] = {
  {0x488, 0, 4},  // DAS_steeringControl
  {0x2b9, 0, 8},  // DAS_control
  {0x214, 0, 3},  // EPB_epasControl
  {0x551, 0, 6},  // Pedal GAS_COMMAND bus 0
  {0x551, 2, 6},  // Pedal GAS_COMMAND bus 2
  {0x45,  0, 8},  // STW_ACTN_RQ stalk spoof
};

// Extra TX when PREAP_FLAG_RADAR_EMULATION is on (radar bus = 1). Tight set.
const CanMsg TESLA_PREAP_TX_MSGS_WITH_RADAR[] = {
  {0x488, 0, 4},
  {0x2b9, 0, 8},
  {0x214, 0, 3},
  {0x551, 0, 6},
  {0x551, 2, 6},
  {0x45,  0, 8},
  {0x560, 1, 8},  // VIN_VIP dummy (Python)
  {0x2A9, 1, 8},  // GTW_carConfig helper
  {0x199, 1, 8},  // STW_ANGLHP helper
};

RxCheck tesla_preap_rx_checks[] = {
  {.msg = {{0x370, 0, 8, .frequency = 25U}, { 0 }, { 0 }}},   // EPAS_sysStatus
  {.msg = {{0x108, 0, 8, .frequency = 100U}, { 0 }, { 0 }}},  // DI_torque1
  {.msg = {{0x118, 0, 6, .frequency = 100U}, { 0 }, { 0 }}},  // DI_torque2
  {.msg = {{0x20a, 0, 8, .frequency = 50U}, { 0 }, { 0 }}},   // BrakeMessage
  {.msg = {{0x368, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},   // DI_state
  {.msg = {{0x318, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},   // GTW_carState
  {.msg = {{0x45,  0, 8, .frequency = 10U}, { 0 }, { 0 }}},   // STW_ACTN_RQ
  {.msg = {{0x155, 0, 8, .frequency = 50U}, { 0 }, { 0 }}},   // ESP_B
};

RxCheck tesla_preap_rx_checks_with_pedal[] = {
  {.msg = {{0x370, 0, 8, .frequency = 25U}, { 0 }, { 0 }}},
  {.msg = {{0x108, 0, 8, .frequency = 100U}, { 0 }, { 0 }}},
  {.msg = {{0x118, 0, 6, .frequency = 100U}, { 0 }, { 0 }}},
  {.msg = {{0x20a, 0, 8, .frequency = 50U}, { 0 }, { 0 }}},
  {.msg = {{0x368, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},
  {.msg = {{0x318, 0, 8, .frequency = 10U}, { 0 }, { 0 }}},
  {.msg = {{0x45,  0, 8, .frequency = 10U}, { 0 }, { 0 }}},
  {.msg = {{0x155, 0, 8, .frequency = 50U}, { 0 }, { 0 }}},
  {.msg = {{0x552, 0, 6, .frequency = 50U},
           {0x552, 2, 6, .frequency = 50U}, { 0 }}},  // GAS_SENSOR
};

static void tesla_preap_rx_hook(const CANPacket_t *msg) {
  // Pedal sensor may be on bus 0 or 2.
  if (preap_enable_pedal && (msg->addr == 0x552U)) {
    int pedal_val = (GET_BYTE(msg, 0) << 8) | GET_BYTE(msg, 1);
    gas_pressed = (pedal_val > 650);
    if (preap_pedal_can == -1) {
      preap_pedal_can = msg->bus;
    }
    return;
  }

  if (msg->bus != 0U) {
    return;
  }

  if (msg->addr == 0x370U) {
    int angle_meas_new = (((GET_BYTE(msg, 4) & 0x3FU) << 8) | GET_BYTE(msg, 5)) - 8192;
    update_sample(&angle_meas, angle_meas_new);

    int hands_on_level = GET_BYTE(msg, 4) >> 6;
    int eac_status = GET_BYTE(msg, 6) >> 5;
    int eac_error_code = GET_BYTE(msg, 2) >> 4;
    bool epas_rejecting = (eac_status == 0) && (eac_error_code >= 6) && (eac_error_code <= 9);
    if ((hands_on_level >= 3) || epas_rejecting) {
      controls_allowed = false;
      pcm_cruise_check(false);
    }
  }

  if (msg->addr == 0x155U) {
    // ESP_B speed: same scaling NotAutopilot uses (0.01 kph).
    float speed = ((((GET_BYTE(msg, 5) << 8) | GET_BYTE(msg, 6)) * 0.01f) * 0.277778f);
    UPDATE_VEHICLE_SPEED(speed);
    vehicle_moving = speed > 0.139f;  // ~0.5 kph
  }

  if (msg->addr == 0x108U) {
    if (!preap_enable_pedal) {
      gas_pressed = (GET_BYTE(msg, 6) != 0U);
    }
  }

  // Pre-AP: brake does not clear controls_allowed here (software layer handles
  // brake → steering-only). Force false so generic_rx_checks does not drop us.
  if (msg->addr == 0x20aU) {
    brake_pressed = false;
  }

  if (msg->addr == 0x118U) {
    preap_gear = (GET_BYTE(msg, 1) >> 4) & 0x07;
    if ((preap_gear_prev == 4) && (preap_gear != 4)) {
      controls_allowed = false;
    }
    preap_gear_prev = preap_gear;
  }

  if (msg->addr == 0x318U) {
    int d_fl = (GET_BYTE(msg, 1) >> 4) & 0x03;
    int d_fr = (GET_BYTE(msg, 1) >> 6) & 0x03;
    int d_rl = (GET_BYTE(msg, 2) >> 6) & 0x03;
    int d_rr = (GET_BYTE(msg, 3) >> 5) & 0x03;
    int d_ft = (GET_BYTE(msg, 6) >> 2) & 0x03;
    int d_tr = (GET_BYTE(msg, 5) >> 6) & 0x03;
    preap_doors_open = (d_fl == 1) || (d_fr == 1) || (d_rl == 1) || (d_rr == 1) || (d_ft == 1) || (d_tr == 1);
    if (preap_doors_open) {
      controls_allowed = false;
    }
  }

  if (msg->addr == 0x45U) {
    int lever = GET_BYTE(msg, 0) & 0x3FU;
    if (lever == 2) {  // pull = enable
      if ((preap_gear == 4) && !preap_doors_open) {
        pcm_cruise_check(true);
        preap_last_stalk_engage_us = microsecond_timer_get();
      }
    } else if (lever == 1) {  // push = cancel, with echo filter
      uint32_t elapsed = get_ts_elapsed(microsecond_timer_get(), preap_last_stalk_engage_us);
      if (elapsed > PREAP_CANCEL_ECHO_WINDOW_US) {
        pcm_cruise_check(false);
      }
    }
  }

  // No harness relay on Pre-AP.
  generic_rx_checks(false);
}

static bool tesla_preap_tx_hook(const CANPacket_t *msg) {
  bool tx = true;
  bool violation = false;

  if (msg->addr == 0x488U) {
    int raw_angle_can = ((GET_BYTE(msg, 0) & 0x7FU) << 8) | GET_BYTE(msg, 1);
    int desired_angle = raw_angle_can - 16384;
    int steer_control_type = GET_BYTE(msg, 2) >> 6;
    bool steer_control_enabled = (steer_control_type == 1);
    if (steer_angle_cmd_checks(desired_angle, steer_control_enabled, TESLA_PREAP_STEERING_LIMITS)) {
      violation = true;
    }
    if ((steer_control_type != 0) && (steer_control_type != 1)) {
      violation = true;
    }
  }

  if (msg->addr == 0x214U) {
    int epas_control_type = GET_BYTE(msg, 0) & 0x07U;
    if (epas_control_type > 1) {
      violation = true;
    }
  }

  if (msg->addr == 0x2b9U) {
    int aeb_event = GET_BYTE(msg, 2) & 0x03U;
    if (aeb_event != 0) {
      violation = true;
    }
  }

  // Radar helper TX — only when emulation flag is on (default off).
  if ((msg->addr == 0x560U) || (msg->addr == 0x2A9U) || (msg->addr == 0x199U)) {
    if (!preap_radar_emulation || (msg->bus != 1U)) {
      violation = true;
    }
  }

  // Pedal GAS_COMMAND — NotAutopilot ENABLE/passthrough rules.
  if (msg->addr == 0x551U) {
    if (!preap_enable_pedal) {
      violation = true;
    } else {
      bool pedal_enable = (GET_BYTE(msg, 4) & 0x80U) != 0U;
      int raw_gas_cmd = (GET_BYTE(msg, 0) << 8) | GET_BYTE(msg, 1);
      if (pedal_enable) {
        if (!get_longitudinal_allowed()) {
          violation = true;
        }
      } else if (raw_gas_cmd > 500) {
        violation = true;
      }
    }
  }

  if (violation) {
    tx = false;
  }
  return tx;
}

static int tesla_preap_fwd_hook(int bus_num, int addr) {
  // Pre-AP has no AP ECU on bus 2. Do not forward 0↔2 (NAP: return true to
  // block; BogPilot fwd returns destination bus or -1 to drop).
  (void)bus_num;
  (void)addr;
  return -1;
}

static safety_config tesla_preap_init(uint16_t param) {
  preap_enable_pedal = GET_FLAG(param, PREAP_FLAG_ENABLE_PEDAL);
  preap_radar_emulation = GET_FLAG(param, PREAP_FLAG_RADAR_EMULATION);
  // Behind-nosecone is a userspace mount hint; TX whitelist is the same either way.
  (void)GET_FLAG(param, PREAP_FLAG_RADAR_BEHIND_NOSECONE);

  preap_gear = 4;
  preap_gear_prev = 4;
  preap_doors_open = false;
  preap_pedal_can = -1;
  preap_last_stalk_engage_us = 0;

  if (preap_radar_emulation) {
    if (preap_enable_pedal) {
      return BUILD_SAFETY_CFG(tesla_preap_rx_checks_with_pedal, TESLA_PREAP_TX_MSGS_WITH_RADAR);
    }
    return BUILD_SAFETY_CFG(tesla_preap_rx_checks, TESLA_PREAP_TX_MSGS_WITH_RADAR);
  }
  if (preap_enable_pedal) {
    return BUILD_SAFETY_CFG(tesla_preap_rx_checks_with_pedal, TESLA_PREAP_TX_MSGS);
  }
  return BUILD_SAFETY_CFG(tesla_preap_rx_checks, TESLA_PREAP_TX_MSGS);
}

const safety_hooks tesla_preap_hooks = {
  .init = tesla_preap_init,
  .rx = tesla_preap_rx_hook,
  .tx = tesla_preap_tx_hook,
  .fwd = tesla_preap_fwd_hook,
};
