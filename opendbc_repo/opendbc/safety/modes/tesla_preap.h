#pragma once
// BogPilot Pre-AP Model S safety. Selected only when TESLA_FLAG_PREAP is set on SAFETY_TESLA and the AP1 flag is clear.
// No new safety-model ordinal: Pre-AP is a flag on SAFETY_TESLA, exactly like AP1, so the signed panda image only needs these
// source lines compiled in (the signed image contains them only once these lines are compiled into it).
//
// Pre-AP has no Autopilot ECU and no harness relay: nothing here uses check_relay, and nothing is forwarded.
// Rate tables are the AP1 tables (same physical car), the lever may only send CANCEL, brake / gear / door / EPAS fault, hands on (level 3) and an EPAS refusal drop controls and need a new pull.
// References: NotAutopilot (NAP) @ e99f4dc75, file opendbc/safety/modes/tesla_preap.h in its opendbc submodule @ cc39c7fa,
// and BogPilot na-preap panda/board/safety/safety_tesla_preap.h @ 568fea947 (MIT, openpilot lineage; keep the notices with
// redistributions); AP1 rate tables as in Tinkla / BogGyver @ 501c7de.
// Stricter than both references on purpose (see DIVERGENCES): the brake is read, steering through the brake needs an armed latch,
// EAC_FAULT drops controls, STW_ACTN_RQ (0x45) may only send CANCEL, DAS_control (0x2b9) is not whitelisted, the pedal command is
// capped at 2500, and the pedal sensor bus is latched to the first bus it is seen on. Optional Bosch radar
// GTW (flags 256/128) is off by default. With flag 256 the GTW stays silent until the host has sent the full 0x560 donor
// config (NAP 604b9c49); 0x560 is consumed here and never put on the car, and is ignored while engaged (stricter than NAP).
// The only UDS path is a read-only F190 allow-list on bus 1 (0x641), disengaged only (NAP 347ac59b / edd064aa).

#define TESLA_FLAG_PREAP 32U
#define TESLA_FLAG_PREAP_PEDAL 64U
#define TESLA_FLAG_PREAP_RADAR_BEHIND_NOSECONE 128U  // NAP TeslaSafetyFlags; only applied with flag 256
#define TESLA_FLAG_PREAP_RADAR_EMULATION 256U         // NAP TeslaSafetyFlags on SafetyModel.tesla

static bool tesla_preap = false;
static bool tesla_preap_pedal = false;
static int tesla_preap_pedal_bus = -1;  // G3: first bus the GAS_SENSOR (0x552) is seen on, as in NAP / BogPilot na-preap

// Bosch radar GTW. tesla_preap_radar_emulation is set only when this is the Pre-AP mode and flag 256 is set.
// Flag 128 without 256 is a no-op (position stays 0, no can_send). epas_type is 0 until a 0x560 record 0 sets it (NAP inits it to 0).
static bool tesla_preap_radar_emulation = false;
static int tesla_preap_radar_position = 0;
static int tesla_preap_radar_epas_type = 0;
// Donor-VIN config from the host (0x560, never on the car). NAP tesla_preap.h:124-130,199-228 @ opendbc 5dbe36d37
// (openpilot naponsp-alpha-prebuilt 7eb09d2a7). Reset on every safety init.
#define TESLA_PREAP_RADAR_VIN_ADDR 0x560U
#define TESLA_PREAP_RADAR_UDS_ADDR 0x641U
#define TESLA_PREAP_RADAR_VIN_LEN 17U
static uint8_t tesla_preap_radar_vin[TESLA_PREAP_RADAR_VIN_LEN];
static uint8_t tesla_preap_radar_vin_complete = 0U;   // bit per 0x560 record 0..2, 7 = complete
static bool tesla_preap_radar_should_send = false;    // 0x560 record 0 data[2] bit 0 (useRadar)
static int tesla_preap_gear = 4;                  // DI_gear, 4 = D
static int tesla_preap_gear_prev = 4;
static bool tesla_preap_doors_open = false;
static bool tesla_preap_lever_engage_prev = false;
static bool tesla_preap_need_fresh_pull = false;  // set by every EPAS drop: a pull held through the drop never re-engages
static bool tesla_preap_brake_msg = false;        // BrakeMessage (0x20a)
static bool tesla_preap_brake_di = false;         // DI_torque2.DI_brakePedal (0x118)
static uint32_t tesla_preap_last_stalk_engage_us = 0U;
// Steer through a brake press. A brake press still drops controls_allowed (the pedal is blocked by it,
// and by the explicit brake rule on 0x551), but steering keeps its own permission, so the driver braking does not also take the wheel
// away. armed = a stalk pull happened and nothing has disarmed it; brake_seen = a brake press happened since that pull. The extra
// permission needs both, so it can only continue a session that a pull started and that a brake press interrupted.
// A gas press does NOT disarm it (a driver on the accelerator after a brake tap silently lost steering for 34 s while openpilot
// still showed engaged). Gas has no bearing on steering, controls_allowed itself rides through gas on this port, and the pedal has its own
// gas rule (get_longitudinal_allowed). Every disarm below has the same cause on the openpilot side, so the two always agree: cancel
// (carstate resets the pull FSM), an EPAS fault, hands on or an EPAS refusal (carstate preap_panda_drop must reset it; G1
// needs the matching carstate change), leaving D (carstate resets it),
// a door (selfdrived doorOpen disengages) and a stale stream (canValid / canError disengages).
static bool tesla_preap_steer_armed = false;
static bool tesla_preap_steer_brake_seen = false;

// Hands high or the EPAS refusing: controls_allowed and the cruise latch are cleared (NAP and BogPilot na-preap do the same),
// so a takeover ends the session and re-engaging needs a new stalk pull. ANGLE is also rejected while this holds.
static bool tesla_preap_epas_blocking = false;

static void tesla_preap_epas_state(const CANPacket_t *msg) {
  const int hands_on_level = msg->data[4] >> 6;     // EPAS_handsOnLevel
  const int eac_status = msg->data[6] >> 5;         // EPAS_eacStatus
  const int eac_error_code = msg->data[2] >> 4;     // EPAS_eacErrorCode
  const bool epas_rejecting = (eac_status == 0) && (eac_error_code >= 6) && (eac_error_code <= 9);
  tesla_preap_epas_blocking = (hands_on_level >= 3) || epas_rejecting;
  // G1: hands on or an EPAS refusal disengage, as in NAP and BogPilot na-preap; re-engaging needs a new stalk pull.
  // EAC_FAULT: permanent, same drop.
  if (tesla_preap_epas_blocking || (eac_status == 3)) {
    controls_allowed = false;
    pcm_cruise_check(false);
    tesla_preap_need_fresh_pull = true;
    tesla_preap_steer_armed = false;
    tesla_preap_steer_brake_seen = false;
  }
}

static bool tesla_preap_door_open(const CANPacket_t *msg) {
  // GTW_carState: 1 = OPEN
  const int d_fl = (msg->data[1] >> 4) & 0x03U;
  const int d_fr = (msg->data[1] >> 6) & 0x03U;
  const int d_rl = (msg->data[2] >> 6) & 0x03U;
  const int d_rr = (msg->data[3] >> 5) & 0x03U;
  const int d_ft = (msg->data[6] >> 2) & 0x03U;
  const int d_tr = (msg->data[5] >> 6) & 0x03U;
  return (d_fl == 1) || (d_fr == 1) || (d_rl == 1) || (d_rr == 1) || (d_ft == 1) || (d_tr == 1);
}

// Steering permission beyond controls_allowed: only a pull-armed session that a brake press interrupted, while the car is in D with the doors
// closed and every monitored stream is fresh (the 1 s age is checked here too, not only in the 1 Hz safety_tick). Never longitudinal. A lost
// prerequisite, an EPAS fault or a cancel disarms it, and only a new pull arms it again. Gas does not (see above). Hands on and an EPAS
// refusal do not disarm it either: they only reject ANGLE while they last.
static bool tesla_preap_steer_allowed(void) {
  bool healthy = tesla_preap && tesla_preap_steer_armed && (tesla_preap_gear == 4) && !tesla_preap_doors_open && !safety_rx_checks_invalid;
  for (int i = 0; i < current_safety_config.rx_checks_len; i++) {
    const RxCheck *check = &current_safety_config.rx_checks[i];
    healthy = healthy && check->status.msg_seen && !check->status.lagging &&
              (safety_get_ts_elapsed(microsecond_timer_get(), check->status.last_timestamp) <= 1000000U);
  }
  if (!healthy) {
    tesla_preap_steer_armed = false;
    tesla_preap_steer_brake_seen = false;
  }
  if (tesla_preap_steer_armed && brake_pressed) {
    tesla_preap_steer_brake_seen = true;
  }
  return controls_allowed || (tesla_preap_steer_armed && tesla_preap_steer_brake_seen);
}

static void tesla_preap_stalk(const CANPacket_t *msg) {
  // STW_ACTN_RQ SpdCtrlLvr_Stat: 2 = pull (engage), 1 = cancel. A rising pull re-arms the engage edge even when controls dropped
  // without the cruise state being cleared; a cancel right after our own pull is the stock echo and is ignored.
  const int lever = msg->data[0] & 0x3FU;
  if (lever == 2) {
    if (tesla_preap_need_fresh_pull && tesla_preap_lever_engage_prev) {
      // pull held through an EPAS drop: ignored until the lever is released and pulled again (rising edge)
    } else if ((tesla_preap_gear == 4) && !tesla_preap_doors_open) {
      tesla_preap_need_fresh_pull = false;
      if (!tesla_preap_lever_engage_prev) {
        cruise_engaged_prev = false;
      }
      pcm_cruise_check(true);
      tesla_preap_last_stalk_engage_us = microsecond_timer_get();
      tesla_preap_steer_armed = true;
      tesla_preap_steer_brake_seen = false;
    } else {
      // not in D or a door is open: pull ignored
    }
  } else if (lever == 1) {
    const uint32_t cancel_echo_window_us = 600000U;
    if (safety_get_ts_elapsed(microsecond_timer_get(), tesla_preap_last_stalk_engage_us) > cancel_echo_window_us) {
      pcm_cruise_check(false);
      tesla_preap_steer_armed = false;
      tesla_preap_steer_brake_seen = false;
    }
  } else {
    // other lever positions neither engage nor cancel
  }
  tesla_preap_lever_engage_prev = (lever == 2);
}

static void tesla_preap_rx_hook(const CANPacket_t *msg) {
  // Comma Pedal GAS_SENSOR (0x552), bus 0 or 2: the interceptor is the gas source when the pedal flag is set
  if (tesla_preap_pedal && (msg->addr == 0x552U)) {
    if (tesla_preap_pedal_bus < 0) {
      tesla_preap_pedal_bus = (int)msg->bus;
    }
    if ((int)msg->bus == tesla_preap_pedal_bus) {   // a second 0x552 source on the other bus never drives gas_pressed
      const int pedal_val = (msg->data[0] << 8) | msg->data[1];
      gas_pressed = (pedal_val > 650);
    }
  }

  if (msg->bus == 0U) {
    if (msg->addr == 0x370U) {
      // EPAS_sysStatus: steering angle (1/10 deg); hands on / EPAS rejecting reject ANGLE, an EPAS fault drops controls
      const int angle_meas_new = (((msg->data[4] & 0x3FU) << 8) | msg->data[5]) - 8192U;
      update_sample(&angle_meas, angle_meas_new);
      tesla_preap_epas_state(msg);
    }

    if (msg->addr == 0x155U) {
      // ESP_B wheel speed, 0.01 kph
      const float speed = ((((msg->data[5] << 8) | msg->data[6]) * 0.01) * 0.277778);
      UPDATE_VEHICLE_SPEED(speed);
      vehicle_moving = speed > 0.139;
    }

    if ((msg->addr == 0x108U) && !tesla_preap_pedal) {
      gas_pressed = (msg->data[6] != 0U);  // DI_torque1 pedal position (the stock pedal is the gas source without the interceptor)
    }

    if (msg->addr == 0x20aU) {
      tesla_preap_brake_msg = (((msg->data[0] & 0x0CU) >> 2) != 1U);  // BrakeMessage.driverBrakeStatus != NOT_PRESSED
      brake_pressed = tesla_preap_brake_msg || tesla_preap_brake_di;
    }

    if (msg->addr == 0x118U) {
      tesla_preap_brake_di = ((msg->data[1] & 0x80U) != 0U);          // DI_torque2.DI_brakePedal
      brake_pressed = tesla_preap_brake_msg || tesla_preap_brake_di;
      tesla_preap_gear = (msg->data[1] >> 4) & 0x07U;                 // DI_gear
      if ((tesla_preap_gear_prev == 4) && (tesla_preap_gear != 4)) {
        controls_allowed = false;
      }
      tesla_preap_gear_prev = tesla_preap_gear;
    }

    if (msg->addr == 0x318U) {
      tesla_preap_doors_open = tesla_preap_door_open(msg);
      if (tesla_preap_doors_open) {
        controls_allowed = false;
      }
    }

    if (msg->addr == 0x45U) {
      tesla_preap_stalk(msg);
    }
  }

  // Observe a lost prerequisite on every frame (the latch must not outlive it), and while steering has no permission at all keep the
  // rate-limit reference on the measured wheel.
  const bool steer_allowed = tesla_preap_steer_allowed();
  if ((msg->bus == 0U) && (msg->addr == 0x370U) && (!steer_allowed || tesla_preap_epas_blocking)) {
    desired_angle_last = angle_meas.values[0];
  }
}

// NAP preap_radar_ready() (tesla_preap.h:178-184): no bus-1 GTW frame until the 0x560 stream is complete and useRadar is set.
static bool tesla_preap_radar_ready(void) {
  return (tesla_preap_radar_vin_complete == 7U) && tesla_preap_radar_should_send;
}

// NAP preap_radar_donor_active() (tesla_preap.h:186-197): 17 spaces (or NULs) means "use this car", no substitution.
static bool tesla_preap_radar_donor_active(void) {
  bool active = false;
  if (tesla_preap_radar_vin_complete == 7U) {
    for (unsigned int i = 0U; i < TESLA_PREAP_RADAR_VIN_LEN; i++) {
      if ((tesla_preap_radar_vin[i] != 0U) && (tesla_preap_radar_vin[i] != (uint8_t)' ')) {
        active = true;
      }
    }
  }
  return active;
}

// NAP preap_apply_radar_vin_msg() (tesla_preap.h:199-228). Records 0..2 only, DLC 8 (TX list). Stricter than NAP:
// ignored without flag 256 and while engaged or armed, so the radar contract cannot change mid-engagement.
// Record 0 also carries the 0x2A9 position (bits 1-2, 0..2) and EPAS type (bits 3-5), as in NAP f00c8cb9. The host sends
// the Radar Donor Type as the position (0 pre-facelift S, 1 facelift S, 2 Model X; NAP NAPRadarPosition) and the Radar EPAS
// Type as the EPAS type (0 Bosch L538 .. 4 Mando VGR66 Gen3, default 0; NAP NAPRadarEpasType); flag 128 (behind nosecone) no longer picks the position.
static void tesla_preap_radar_apply_vin_msg(const CANPacket_t *msg) {
  if (tesla_preap_radar_emulation && !controls_allowed && !tesla_preap_steer_armed && (GET_LEN(msg) == 8U)) {
    const uint8_t rec = msg->data[0];
    if (rec == 0U) {
      const uint8_t cfg = msg->data[2];
      const uint8_t position = (cfg >> 1U) & 0x03U;
      const uint8_t epas_type = (cfg >> 3U) & 0x07U;
      tesla_preap_radar_should_send = (cfg & 0x01U) != 0U;
      tesla_preap_radar_position = (position > 2U) ? 0 : (int)position;
      tesla_preap_radar_epas_type = (int)epas_type;
      tesla_preap_radar_vin[0] = msg->data[5];
      tesla_preap_radar_vin[1] = msg->data[6];
      tesla_preap_radar_vin[2] = msg->data[7];
      tesla_preap_radar_vin_complete |= 1U;
    } else if (rec == 1U) {
      for (unsigned int i = 0U; i < 7U; i++) {
        tesla_preap_radar_vin[3U + i] = msg->data[1U + i];
      }
      tesla_preap_radar_vin_complete |= 2U;
    } else if (rec == 2U) {
      for (unsigned int i = 0U; i < 7U; i++) {
        tesla_preap_radar_vin[10U + i] = msg->data[1U + i];
      }
      tesla_preap_radar_vin_complete |= 4U;
    } else {
      // other records ignored
    }
  }
}

// NAP preap_f190_payload_allowed() / preap_f190_tx_ok() (tesla_preap.h:137-172): exact 8-byte match against 6 frames,
// bus 1, flag 256, disengaged (and not armed). Read-only: no write (0x2E), routine (0x31) or security access (0x27).
static bool tesla_preap_radar_f190_tx_ok(const CANPacket_t *msg) {
  static const uint8_t f190_allowed[6][8] = {
    {0x02U, 0x3EU, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U},  // tester present
    {0x02U, 0x10U, 0x01U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U},  // default session
    {0x02U, 0x10U, 0x03U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U},  // extended session
    {0x03U, 0x22U, 0xF1U, 0x90U, 0x00U, 0x00U, 0x00U, 0x00U},  // read DID F190 (VIN)
    {0x30U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U},  // ISO-TP flow control
    {0x02U, 0x3EU, 0x80U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U},  // tester present, no response
  };
  bool ok = false;
  if (tesla_preap_radar_emulation && !controls_allowed && !tesla_preap_steer_armed && (msg->bus == 1U) && (GET_LEN(msg) == 8U)) {
    for (unsigned int i = 0U; i < 6U; i++) {
      bool match = true;
      for (unsigned int b = 0U; b < 8U; b++) {
        if (msg->data[b] != f190_allowed[i][b]) {
          match = false;
        }
      }
      ok = ok || match;
    }
  }
  return ok;
}

static bool tesla_preap_tx_hook(const CANPacket_t *msg) {
  bool violation = false;
  const int addr = msg->addr;

  if ((uint32_t)addr == TESLA_PREAP_RADAR_VIN_ADDR) {
    // Host-to-panda donor config: consumed, never sent (NAP tesla_preap.h:771-775).
    tesla_preap_radar_apply_vin_msg(msg);
    violation = true;
  }

  if ((uint32_t)addr == TESLA_PREAP_RADAR_UDS_ADDR) {
    // Radar UDS (bus 1 only by the TX list): F190 read sequence only, disengaged only (NAP tesla_preap.h:777-780).
    violation = !tesla_preap_radar_f190_tx_ok(msg);
  }

  if (addr == 0x488) {
    // DAS_steeringControl: AP1 packing, only NONE (0) and ANGLE_CONTROL (1) exist for Pre-AP
    const AngleSteeringLimits TESLA_PREAP_STEERING_LIMITS = {
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
      .frequency = 50U,  // per-command tables, 0x488 is sent at 50 Hz
    };
    const int raw_angle_can = ((msg->data[0] & 0x7FU) << 8) | msg->data[1];
    const int desired_angle = raw_angle_can - 16384;
    const int steer_control_type = msg->data[2] >> 6;
    const bool steer_control_enabled = (steer_control_type == 1);
    const bool lateral_allowed = tesla_preap_steer_allowed();
    if (steer_control_enabled && tesla_preap_epas_blocking) {
      violation = true;   // never ANGLE while hands are high or the EPAS is refusing
    }
    if (steer_angle_cmd_checks_with_lateral_permission(desired_angle, steer_control_enabled, TESLA_PREAP_STEERING_LIMITS, lateral_allowed) ||
        (desired_angle < -TESLA_PREAP_STEERING_LIMITS.max_angle) || (desired_angle > TESLA_PREAP_STEERING_LIMITS.max_angle)) {
      violation = true;
    }
    // Lateral-accel bound (stage 1; the rate tables and the 360 deg check above are unchanged).
    if (steer_angle_lat_accel_check(desired_angle, steer_control_enabled, lateral_allowed, TESLA_PREAP_STEERING_LIMITS,
                                    TESLA_LEGACY_LAT_ACCEL_PARAMS)) {
      violation = true;
    }
    if (steer_control_type > 1) {
      violation = true;
    }
  }

  if (addr == 0x214) {
    // EPB_epasControl: EACAllow 0 or 1 only
    const int eac_allow = msg->data[0] & 0x07U;
    if (eac_allow > 1) {
      violation = true;
    }
  }

  if (addr == 0x45) {
    // STW_ACTN_RQ: cancel only
    if ((msg->data[0] & 0x3FU) != 1U) {
      violation = true;
    }
  }

  if (addr == 0x551) {
    // Comma Pedal GAS_COMMAND: only with the pedal flag; enabled only while longitudinal is allowed; bounded
    const int raw_gas_cmd = (msg->data[0] << 8) | msg->data[1];
    const bool pedal_enable = (msg->data[4] & 0x80U) != 0U;
    const int max_enabled_raw_gas_cmd = 2500;   // ~ 105 %: the planner never asks for more than 90 %
    const int max_disabled_raw_gas_cmd = 500;
    if (!tesla_preap_pedal) {
      violation = true;
    } else if (pedal_enable) {
      // No pedal while the brake is pressed, whatever else is allowed (steering may continue through a brake press, the pedal may not)
      violation |= !get_longitudinal_allowed() || brake_pressed || (raw_gas_cmd > max_enabled_raw_gas_cmd);
    } else {
      violation |= (raw_gas_cmd > max_disabled_raw_gas_cmd);
    }
  }

  return !violation;
}

static safety_config tesla_preap_init_config(uint16_t param) {
  tesla_preap_pedal = GET_FLAG(param, TESLA_FLAG_PREAP_PEDAL);
  // Radar GTW only when flag 256 is set. Flag 128 without 256 is a no-op.
  tesla_preap_radar_emulation = GET_FLAG(param, TESLA_FLAG_PREAP_RADAR_EMULATION);
  // Initial value only: the gateway stays closed until 0x560 record 0 arrives, which sets the position from the host's Radar
  // Donor Type, so flag 128 no longer picks the position the radar sees.
  tesla_preap_radar_position = (tesla_preap_radar_emulation && GET_FLAG(param, TESLA_FLAG_PREAP_RADAR_BEHIND_NOSECONE)) ? 1 : 0;
  tesla_preap_radar_epas_type = 0;
  tesla_preap_radar_vin_complete = 0U;
  tesla_preap_radar_should_send = false;
  for (unsigned int i = 0U; i < TESLA_PREAP_RADAR_VIN_LEN; i++) {
    tesla_preap_radar_vin[i] = (uint8_t)' ';
  }
  tesla_preap_gear = 4;
  tesla_preap_gear_prev = 4;
  tesla_preap_doors_open = false;
  tesla_preap_lever_engage_prev = false;
  tesla_preap_need_fresh_pull = false;
  tesla_preap_brake_msg = false;
  tesla_preap_brake_di = false;
  tesla_preap_last_stalk_engage_us = 0U;
  tesla_preap_steer_armed = false;
  tesla_preap_steer_brake_seen = false;
  tesla_preap_epas_blocking = false;
  tesla_preap_pedal_bus = -1;

  static const CanMsg TESLA_PREAP_TX_MSGS[] = {
    {0x488, 0, 4, .check_relay = false},  // DAS_steeringControl
    {0x214, 0, 3, .check_relay = false},  // EPB_epasControl
    {0x45, 0, 8, .check_relay = false},   // STW_ACTN_RQ (cancel only)
    {0x551, 0, 6, .check_relay = false},  // Comma Pedal GAS_COMMAND, pedal on bus 0
    {0x551, 2, 6, .check_relay = false},  // Comma Pedal GAS_COMMAND, pedal on bus 2
    {0x560, 0, 8, .check_relay = false},  // donor config host->panda: the tx hook consumes it and returns false, never on the car
    {0x641, 1, 8, .check_relay = false},  // radar UDS, F190 read allow-list only, disengaged only
  };

  safety_config ret;
  if (tesla_preap_pedal) {
    static RxCheck tesla_preap_rx_checks_pedal[] = {
      {.msg = {{0x370, 0, 8, 25U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
      {.msg = {{0x108, 0, 8, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
      {.msg = {{0x118, 0, 6, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
      {.msg = {{0x20a, 0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
      {.msg = {{0x368, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
      {.msg = {{0x318, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
      {.msg = {{0x45, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
      {.msg = {{0x155, 0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
      {.msg = {{0x552, 0, 6, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true},
               {0x552, 2, 6, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }}},        // GAS_SENSOR
    };
    ret = BUILD_SAFETY_CFG(tesla_preap_rx_checks_pedal, TESLA_PREAP_TX_MSGS);
  } else {
    static RxCheck tesla_preap_rx_checks[] = {
      {.msg = {{0x370, 0, 8, 25U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},   // EPAS_sysStatus
      {.msg = {{0x108, 0, 8, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // DI_torque1
      {.msg = {{0x118, 0, 6, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},  // DI_torque2
      {.msg = {{0x20a, 0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},   // BrakeMessage
      {.msg = {{0x368, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},   // DI_state
      {.msg = {{0x318, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},   // GTW_carState
      {.msg = {{0x45, 0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},    // STW_ACTN_RQ
      {.msg = {{0x155, 0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},   // ESP_B
    };
    ret = BUILD_SAFETY_CFG(tesla_preap_rx_checks, TESLA_PREAP_TX_MSGS);
  }
  ret.disable_forwarding = true;  // no harness relay on Pre-AP: nothing is ever forwarded
  return ret;
}

