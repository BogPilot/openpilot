#pragma once
// Pre-AP Bosch radar gateway (GTW emulation). Only runs when TESLA_FLAG_PREAP and
// TESLA_FLAG_PREAP_RADAR_EMULATION are both set. Source: NotAutopilot opendbc
// tesla_preap.h @ cc39c7fa (openpilot e99f4dc75), tesla_preap_gtw_emulation.
// Firmware can_send(..., bus 1, skip_tx_hook=true). No bus-0 TX, no blanket 0-to-1 forward,
// no Tinkla bus-0 synthetic 0x1A9. Silent until the host 0x560 donor config is complete (tesla_preap_radar_ready,
// NAP 604b9c49). With a donor VIN set, 0x2B9 VIN records and the 0x2A9 4WD bit follow the donor VIN
// (NAP tesla_preap.h:346-389 @ opendbc 5dbe36d37, openpilot naponsp-alpha-prebuilt 7eb09d2a7).
// Behind-nosecone (flag 128) only changes the GTW_carConfig radar_position field,
// and only when emulation (flag 256) is also set.

// Board builds already declare these in panda/board/drivers/drivers.h (STM32).
// Libsafety tests and the safety MISRA main provide/need the same prototypes.
#if !defined(STM32H7) && !defined(STM32F4)
void can_send(CANPacket_t *to_push, uint8_t bus_number, bool skip_tx_hook);
void can_set_checksum(CANPacket_t *packet);
#endif

#define TESLA_PREAP_RADAR_GET_BYTES_04(msg) ((uint32_t)(msg)->data[0] | ((uint32_t)(msg)->data[1] << 8) | ((uint32_t)(msg)->data[2] << 16) | ((uint32_t)(msg)->data[3] << 24))
#define TESLA_PREAP_RADAR_GET_BYTES_48(msg) ((uint32_t)(msg)->data[4] | ((uint32_t)(msg)->data[5] << 8) | ((uint32_t)(msg)->data[6] << 16) | ((uint32_t)(msg)->data[7] << 24))

static void tesla_preap_radar_word_to_bytes(uint8_t *dst, uint32_t src) {
  dst[0] = (uint8_t)(src & 0xFFU);
  dst[1] = (uint8_t)((src >> 8U) & 0xFFU);
  dst[2] = (uint8_t)((src >> 16U) & 0xFFU);
  dst[3] = (uint8_t)((src >> 24U) & 0xFFU);
}

static void tesla_preap_radar_pkt_clear(CANPacket_t *pkt) {
  pkt->fd = 0U;
  pkt->bus = 1U;
  pkt->data_len_code = 0U;
  pkt->rejected = 0U;
  pkt->returned = 0U;
  pkt->extended = 0U;
  pkt->addr = 0U;
  pkt->checksum = 0U;
  for (unsigned int i = 0U; i < CANPACKET_DATA_SIZE_MAX; i++) {
    pkt->data[i] = 0U;
  }
}

// CRC-8, polynomial 0x1D. NAP tesla_preap.h:151-176 @ cc39c7fa.
// Table is function-local (MISRA 8.9); values are unchanged.
static uint8_t tesla_preap_radar_compute_crc8(uint32_t lo, uint32_t hi, uint32_t msg_len) {
  static const uint8_t tesla_preap_radar_crc_lookup[256] = {
    0x00U, 0x1DU, 0x3AU, 0x27U, 0x74U, 0x69U, 0x4EU, 0x53U, 0xE8U, 0xF5U, 0xD2U, 0xCFU, 0x9CU, 0x81U, 0xA6U, 0xBBU,
    0xCDU, 0xD0U, 0xF7U, 0xEAU, 0xB9U, 0xA4U, 0x83U, 0x9EU, 0x25U, 0x38U, 0x1FU, 0x02U, 0x51U, 0x4CU, 0x6BU, 0x76U,
    0x87U, 0x9AU, 0xBDU, 0xA0U, 0xF3U, 0xEEU, 0xC9U, 0xD4U, 0x6FU, 0x72U, 0x55U, 0x48U, 0x1BU, 0x06U, 0x21U, 0x3CU,
    0x4AU, 0x57U, 0x70U, 0x6DU, 0x3EU, 0x23U, 0x04U, 0x19U, 0xA2U, 0xBFU, 0x98U, 0x85U, 0xD6U, 0xCBU, 0xECU, 0xF1U,
    0x13U, 0x0EU, 0x29U, 0x34U, 0x67U, 0x7AU, 0x5DU, 0x40U, 0xFBU, 0xE6U, 0xC1U, 0xDCU, 0x8FU, 0x92U, 0xB5U, 0xA8U,
    0xDEU, 0xC3U, 0xE4U, 0xF9U, 0xAAU, 0xB7U, 0x90U, 0x8DU, 0x36U, 0x2BU, 0x0CU, 0x11U, 0x42U, 0x5FU, 0x78U, 0x65U,
    0x94U, 0x89U, 0xAEU, 0xB3U, 0xE0U, 0xFDU, 0xDAU, 0xC7U, 0x7CU, 0x61U, 0x46U, 0x5BU, 0x08U, 0x15U, 0x32U, 0x2FU,
    0x59U, 0x44U, 0x63U, 0x7EU, 0x2DU, 0x30U, 0x17U, 0x0AU, 0xB1U, 0xACU, 0x8BU, 0x96U, 0xC5U, 0xD8U, 0xFFU, 0xE2U,
    0x26U, 0x3BU, 0x1CU, 0x01U, 0x52U, 0x4FU, 0x68U, 0x75U, 0xCEU, 0xD3U, 0xF4U, 0xE9U, 0xBAU, 0xA7U, 0x80U, 0x9DU,
    0xEBU, 0xF6U, 0xD1U, 0xCCU, 0x9FU, 0x82U, 0xA5U, 0xB8U, 0x03U, 0x1EU, 0x39U, 0x24U, 0x77U, 0x6AU, 0x4DU, 0x50U,
    0xA1U, 0xBCU, 0x9BU, 0x86U, 0xD5U, 0xC8U, 0xEFU, 0xF2U, 0x49U, 0x54U, 0x73U, 0x6EU, 0x3DU, 0x20U, 0x07U, 0x1AU,
    0x6CU, 0x71U, 0x56U, 0x4BU, 0x18U, 0x05U, 0x22U, 0x3FU, 0x84U, 0x99U, 0xBEU, 0xA3U, 0xF0U, 0xEDU, 0xCAU, 0xD7U,
    0x35U, 0x28U, 0x0FU, 0x12U, 0x41U, 0x5CU, 0x7BU, 0x66U, 0xDDU, 0xC0U, 0xE7U, 0xFAU, 0xA9U, 0xB4U, 0x93U, 0x8EU,
    0xF8U, 0xE5U, 0xC2U, 0xDFU, 0x8CU, 0x91U, 0xB6U, 0xABU, 0x10U, 0x0DU, 0x2AU, 0x37U, 0x64U, 0x79U, 0x5EU, 0x43U,
    0xB2U, 0xAFU, 0x88U, 0x95U, 0xC6U, 0xDBU, 0xFCU, 0xE1U, 0x5AU, 0x47U, 0x60U, 0x7DU, 0x2EU, 0x33U, 0x14U, 0x09U,
    0x7FU, 0x62U, 0x45U, 0x58U, 0x0BU, 0x16U, 0x31U, 0x2CU, 0x97U, 0x8AU, 0xADU, 0xB0U, 0xE3U, 0xFEU, 0xD9U, 0xC4U
  };
  uint8_t crc = 0xFFU;
  for (uint32_t x = 0U; x < msg_len; x++) {
    uint32_t src;
    uint32_t shift;
    if (x <= 3U) {
      src = lo;
      shift = x * 8U;
    } else {
      src = hi;
      shift = (x - 4U) * 8U;
    }
    const uint8_t v = (uint8_t)((src >> shift) & 0xFFU);
    crc = tesla_preap_radar_crc_lookup[crc ^ v];
  }
  return (uint8_t)(crc ^ 0xFFU);
}

static void tesla_preap_radar_send(CANPacket_t *pkt) {
  pkt->bus = 1;
#if defined(STM32H7) || defined(STM32F4)
  can_set_checksum(pkt);
#endif
  can_send(pkt, 1, true);
}

// NAP tesla_preap.h:183-201 @ cc39c7fa. One bus-1 frame per call, same payload and DLC as the source.
static void tesla_preap_radar_readdr(const CANPacket_t *src, uint16_t new_addr) {
  CANPacket_t pkt;
  tesla_preap_radar_pkt_clear(&pkt);
  pkt.extended = src->extended;
  pkt.fd = src->fd;
  pkt.addr = new_addr;
  pkt.data_len_code = src->data_len_code;
  const unsigned int len = (unsigned int)GET_LEN(src);
  for (unsigned int i = 0U; i < len; i++) {
    pkt.data[i] = src->data[i];
  }
  tesla_preap_radar_send(&pkt);
}

// NAP tesla_preap.h:216-316 @ cc39c7fa. Called from tesla_rx_all for every RX.
// Emits at most one rewritten frame per source, plus at most one synthetic on 0x115 and 0x118.
static void tesla_preap_radar_rx_all(const CANPacket_t *to_fwd) {
  if (tesla_preap && tesla_preap_radar_emulation && tesla_preap_radar_ready() && (to_fwd->bus == 0U)) {
    const int addr = (int)to_fwd->addr;

    // Group A: simple re-address (NAP :221-230)
    switch (addr) {
      case 0x45:   tesla_preap_radar_readdr(to_fwd, 0x219); break;  // STW_ACTN_RQ
      case 0x108:  tesla_preap_radar_readdr(to_fwd, 0x109); break;  // DI_torque1
      case 0x145:  tesla_preap_radar_readdr(to_fwd, 0x149); break;  // ESP_145h
      case 0x20A:  tesla_preap_radar_readdr(to_fwd, 0x159); break;  // BrakeMessage -> ESP_C
      case 0x308:  tesla_preap_radar_readdr(to_fwd, 0x209); break;  // GTW_odo
      case 0x30A:  tesla_preap_radar_readdr(to_fwd, 0x2D9); break;  // BC_status
      default: break;
    }

    // Group B: GTW_carConfig (0x398) -> 0x2A9 with bitfield patching (NAP :233-247)
    if (addr == 0x398) {
      CANPacket_t pkt;
      tesla_preap_radar_pkt_clear(&pkt);
      pkt.extended = to_fwd->extended;
      pkt.fd = to_fwd->fd;
      pkt.addr = 0x2A9;
      pkt.data_len_code = to_fwd->data_len_code;
      uint32_t lo = TESLA_PREAP_RADAR_GET_BYTES_04(to_fwd);
      uint32_t hi = TESLA_PREAP_RADAR_GET_BYTES_48(to_fwd);
      lo = (lo & 0xFFFFF33FU) | 0x100U | 0x440U;  // country=US, radar_type=Bosch
      hi = (hi & 0xCFFF0F0FU) | 0x10000000U | ((uint32_t)tesla_preap_radar_position << 4) | ((uint32_t)tesla_preap_radar_epas_type << 12);
      // Bosch xWD is checked against the VIN on 0x2B9: a donor VIN with char 8 '2' or '4' (dual motor) declares 4WD
      // (NAP tesla_preap.h:353-364). No donor: the car's own 0x398 bit is kept.
      if (tesla_preap_radar_donor_active()) {
        const uint8_t drive = tesla_preap_radar_vin[7];
        if ((drive == (uint8_t)'2') || (drive == (uint8_t)'4')) {
          lo |= 0x08U;
        }
      }
      tesla_preap_radar_word_to_bytes(&pkt.data[0], lo);
      tesla_preap_radar_word_to_bytes(&pkt.data[4], hi);
      // No data[7] checksum: Bosch BO_681 "All fixed bytes, no checksum", byte 7 = Msg2A9_Always0x10 (GTW_autopilot=1 set
      // above). NAP a2cdda8e (tesla_preap.h:346-367 @ opendbc 5dbe36d37), BogPilot na-preap c68fda744, Tinkla safety_tesla.h:462-484@501c7de.
      tesla_preap_radar_send(&pkt);
    }

    // VIP_405HS (0x405) -> 0x2B9 VIN feed; mux records 0x10-0x12 carry the donor VIN when one is set
    // (NAP preap_transform_radar_vin_feed, tesla_preap.h:369-389). Not DAS_control; firmware-originated on bus 1 only.
    if (addr == 0x405) {
      CANPacket_t pkt;
      tesla_preap_radar_pkt_clear(&pkt);
      pkt.extended = to_fwd->extended;
      pkt.fd = to_fwd->fd;
      pkt.addr = 0x2B9;
      pkt.data_len_code = to_fwd->data_len_code;
      const unsigned int len = (unsigned int)GET_LEN(to_fwd);
      for (unsigned int i = 0U; i < len; i++) {
        pkt.data[i] = to_fwd->data[i];
      }
      const uint8_t rec = to_fwd->data[0];
      if (tesla_preap_radar_donor_active() && (len == 8U) && ((rec & 0x10U) == 0x10U)) {
        unsigned int first = 0U;
        bool known = true;
        if (rec == 0x10U) {
          first = 0U;
        } else if (rec == 0x11U) {
          first = 3U;
        } else if (rec == 0x12U) {
          first = 10U;
        } else {
          known = false;
        }
        if (known) {
          for (unsigned int i = 1U; i < 8U; i++) {
            pkt.data[i] = 0U;
          }
          // 0x10: VIN[0..2] in bytes 5-7; 0x11: VIN[3..9] in bytes 1-7; 0x12: VIN[10..16] in bytes 1-7
          const unsigned int start = (rec == 0x10U) ? 5U : 1U;
          for (unsigned int i = start; i < 8U; i++) {
            pkt.data[i] = tesla_preap_radar_vin[first + (i - start)];
          }
        }
      }
      tesla_preap_radar_send(&pkt);
    }

    // Group B: STW_ANGLHP_STAT (0x0E) -> 0x199 with SNA replacement (NAP :250-267)
    if (addr == 0x0E) {
      CANPacket_t pkt;
      tesla_preap_radar_pkt_clear(&pkt);
      pkt.extended = to_fwd->extended;
      pkt.fd = to_fwd->fd;
      pkt.addr = 0x199;
      pkt.data_len_code = to_fwd->data_len_code;
      uint32_t lo = TESLA_PREAP_RADAR_GET_BYTES_04(to_fwd);
      uint32_t hi = TESLA_PREAP_RADAR_GET_BYTES_48(to_fwd);
      if (((lo >> 16) & 0xFF3FU) == 0xFF3FU) {
        lo = (lo & 0x00C0FFFFU) | ((uint32_t)0x0020UL << 16);
        hi = (hi & 0x00FFFFF0U) | 0x00000004U;  // force DELPHI sensor ID
        const uint8_t crc = tesla_preap_radar_compute_crc8(lo, hi, 7U);
        hi = hi | ((uint32_t)crc << 24);
      }
      tesla_preap_radar_word_to_bytes(&pkt.data[0], lo);
      tesla_preap_radar_word_to_bytes(&pkt.data[4], hi);
      tesla_preap_radar_send(&pkt);
    }

    // Group C: ESP_115h (0x115) -> 0x129 + synthetic DI_espControl 0x1A9, bus 1 only, len 5 (NAP :270-284)
    if (addr == 0x115) {
      tesla_preap_radar_readdr(to_fwd, 0x129);
      const uint32_t hi_src = TESLA_PREAP_RADAR_GET_BYTES_48(to_fwd);
      const uint32_t counter = ((hi_src & 0xF0U) >> 4) & 0x0FU;
      const uint32_t syn_lo = 0x000C0000U | (counter << 28);
      const uint32_t cksm = (0x38U + 0x0CU + (counter << 4U)) & 0xFFU;
      CANPacket_t pkt;
      tesla_preap_radar_pkt_clear(&pkt);
      pkt.addr = 0x1A9;
      pkt.data_len_code = 5;
      tesla_preap_radar_word_to_bytes(&pkt.data[0], syn_lo);
      tesla_preap_radar_word_to_bytes(&pkt.data[4], cksm);
      tesla_preap_radar_send(&pkt);
    }

    // Group C: DI_torque2 (0x118) -> 0x119 + synthetic ESP_wheelSpeeds 0x169, bus 1 only, len 8 (NAP :287-314)
    if (addr == 0x118) {
      tesla_preap_radar_readdr(to_fwd, 0x119);
      const uint32_t lo = TESLA_PREAP_RADAR_GET_BYTES_04(to_fwd);
      const uint32_t ws_counter = TESLA_PREAP_RADAR_GET_BYTES_48(to_fwd) & 0x0FU;
      const uint32_t raw_speed = (0xFFF0000U & lo) >> 16;
      uint32_t speed_u;
      if (raw_speed == 0xFFFU) {
        speed_u = 0x1FFFU;
      } else {
        const int32_t mph_x100 = ((int32_t)raw_speed * 5) - 2500;
        const int32_t kph_x100 = (mph_x100 * 1609) / 1000;
        if (kph_x100 < 0) {
          speed_u = 0U;
        } else {
          speed_u = ((uint32_t)kph_x100 / 4U) & 0x1FFFU;
        }
      }
      uint32_t ws_lo = speed_u | (speed_u << 13) | (speed_u << 26);
      uint32_t ws_hi = ((speed_u >> 6) | (speed_u << 7) | (ws_counter << 20)) & 0x00FFFFFFU;
      uint32_t ws_cksm = 0x76U;
      ws_cksm = (ws_cksm + (ws_lo & 0xFFU) + ((ws_lo >> 8) & 0xFFU) + ((ws_lo >> 16) & 0xFFU) + ((ws_lo >> 24) & 0xFFU)) & 0xFFU;
      ws_cksm = (ws_cksm + (ws_hi & 0xFFU) + ((ws_hi >> 8) & 0xFFU) + ((ws_hi >> 16) & 0xFFU)) & 0xFFU;
      ws_hi = ws_hi | (ws_cksm << 24);
      CANPacket_t pkt;
      tesla_preap_radar_pkt_clear(&pkt);
      pkt.addr = 0x169;
      pkt.data_len_code = 8;
      tesla_preap_radar_word_to_bytes(&pkt.data[0], ws_lo);
      tesla_preap_radar_word_to_bytes(&pkt.data[4], ws_hi);
      tesla_preap_radar_send(&pkt);
    }
  }
}
