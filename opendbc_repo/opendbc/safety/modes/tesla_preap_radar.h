#pragma once
// Pre-AP Bosch radar gateway (GTW emulation). Only runs when TESLA_FLAG_PREAP and
// TESLA_FLAG_PREAP_RADAR_EMULATION are both set. Source: NotAutopilot opendbc
// tesla_preap.h @ cc39c7fa (openpilot e99f4dc75), tesla_preap_gtw_emulation.
// Firmware can_send(..., bus 1, skip_tx_hook=true). No host TX, no bus-0 TX,
// no VIN or UDS, no blanket 0-to-1 forward, no Tinkla bus-0 synthetic 0x1A9.
// Behind-nosecone (flag 128) only changes the GTW_carConfig radar_position field,
// and only when emulation (flag 256) is also set.

// Board can_send on the panda; libsafety tests provide a recording stub.
void can_send(CANPacket_t *to_push, uint8_t bus_number, bool skip_tx_hook);
void can_set_checksum(CANPacket_t *to_push);

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

// CRC-8 lookup, polynomial 0x1D. NAP tesla_preap.h:151-167 @ cc39c7fa.
static const int tesla_preap_radar_crc_lookup[256] = {
  0x00, 0x1D, 0x3A, 0x27, 0x74, 0x69, 0x4E, 0x53, 0xE8, 0xF5, 0xD2, 0xCF, 0x9C, 0x81, 0xA6, 0xBB,
  0xCD, 0xD0, 0xF7, 0xEA, 0xB9, 0xA4, 0x83, 0x9E, 0x25, 0x38, 0x1F, 0x02, 0x51, 0x4C, 0x6B, 0x76,
  0x87, 0x9A, 0xBD, 0xA0, 0xF3, 0xEE, 0xC9, 0xD4, 0x6F, 0x72, 0x55, 0x48, 0x1B, 0x06, 0x21, 0x3C,
  0x4A, 0x57, 0x70, 0x6D, 0x3E, 0x23, 0x04, 0x19, 0xA2, 0xBF, 0x98, 0x85, 0xD6, 0xCB, 0xEC, 0xF1,
  0x13, 0x0E, 0x29, 0x34, 0x67, 0x7A, 0x5D, 0x40, 0xFB, 0xE6, 0xC1, 0xDC, 0x8F, 0x92, 0xB5, 0xA8,
  0xDE, 0xC3, 0xE4, 0xF9, 0xAA, 0xB7, 0x90, 0x8D, 0x36, 0x2B, 0x0C, 0x11, 0x42, 0x5F, 0x78, 0x65,
  0x94, 0x89, 0xAE, 0xB3, 0xE0, 0xFD, 0xDA, 0xC7, 0x7C, 0x61, 0x46, 0x5B, 0x08, 0x15, 0x32, 0x2F,
  0x59, 0x44, 0x63, 0x7E, 0x2D, 0x30, 0x17, 0x0A, 0xB1, 0xAC, 0x8B, 0x96, 0xC5, 0xD8, 0xFF, 0xE2,
  0x26, 0x3B, 0x1C, 0x01, 0x52, 0x4F, 0x68, 0x75, 0xCE, 0xD3, 0xF4, 0xE9, 0xBA, 0xA7, 0x80, 0x9D,
  0xEB, 0xF6, 0xD1, 0xCC, 0x9F, 0x82, 0xA5, 0xB8, 0x03, 0x1E, 0x39, 0x24, 0x77, 0x6A, 0x4D, 0x50,
  0xA1, 0xBC, 0x9B, 0x86, 0xD5, 0xC8, 0xEF, 0xF2, 0x49, 0x54, 0x73, 0x6E, 0x3D, 0x20, 0x07, 0x1A,
  0x6C, 0x71, 0x56, 0x4B, 0x18, 0x05, 0x22, 0x3F, 0x84, 0x99, 0xBE, 0xA3, 0xF0, 0xED, 0xCA, 0xD7,
  0x35, 0x28, 0x0F, 0x12, 0x41, 0x5C, 0x7B, 0x66, 0xDD, 0xC0, 0xE7, 0xFA, 0xA9, 0xB4, 0x93, 0x8E,
  0xF8, 0xE5, 0xC2, 0xDF, 0x8C, 0x91, 0xB6, 0xAB, 0x10, 0x0D, 0x2A, 0x37, 0x64, 0x79, 0x5E, 0x43,
  0xB2, 0xAF, 0x88, 0x95, 0xC6, 0xDB, 0xFC, 0xE1, 0x5A, 0x47, 0x60, 0x7D, 0x2E, 0x33, 0x14, 0x09,
  0x7F, 0x62, 0x45, 0x58, 0x0B, 0x16, 0x31, 0x2C, 0x97, 0x8A, 0xAD, 0xB0, 0xE3, 0xFE, 0xD9, 0xC4
};

// NAP tesla_preap.h:170-176 @ cc39c7fa.
static int tesla_preap_radar_compute_crc8(uint32_t lo, uint32_t hi, int msg_len) {
  int crc = 0xFF;
  for (int x = 0; x < msg_len; x++) {
    int v = (x <= 3) ? ((lo >> (x * 8)) & 0xFF) : ((hi >> ((x - 4) * 8)) & 0xFF);
    crc = tesla_preap_radar_crc_lookup[crc ^ v];
  }
  return crc ^ 0xFF;
}

// NAP tesla_preap.h:203-209 @ cc39c7fa. Sum of address bytes + all data bytes except the last.
static uint8_t tesla_preap_radar_byte_sum_checksum(const CANPacket_t *pkt) {
  uint8_t chksum = (uint8_t)(pkt->addr & 0xFFU) + (uint8_t)((pkt->addr >> 8) & 0xFFU);
  int len = GET_LEN(pkt);
  for (int i = 0; i < (len - 1); i++) {
    chksum += pkt->data[i];
  }
  return chksum;
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
  for (int i = 0; i < GET_LEN(src); i++) {
    pkt.data[i] = src->data[i];
  }
  tesla_preap_radar_send(&pkt);
}

// NAP tesla_preap.h:216-316 @ cc39c7fa. Called from tesla_rx_all for every RX.
// Emits at most one rewritten frame per source, plus at most one synthetic on 0x115 and 0x118.
static void tesla_preap_radar_rx_all(const CANPacket_t *to_fwd) {
  if (!tesla_preap || !tesla_preap_radar_emulation) {
    return;
  }
  if (to_fwd->bus != 0U) {
    return;
  }

  const int addr = (int)to_fwd->addr;

  // Group A: simple re-address (NAP :221-230)
  switch (addr) {
    case 0x45:   tesla_preap_radar_readdr(to_fwd, 0x219); break;  // STW_ACTN_RQ
    case 0x108:  tesla_preap_radar_readdr(to_fwd, 0x109); break;  // DI_torque1
    case 0x145:  tesla_preap_radar_readdr(to_fwd, 0x149); break;  // ESP_145h
    case 0x20A:  tesla_preap_radar_readdr(to_fwd, 0x159); break;  // BrakeMessage -> ESP_C
    case 0x308:  tesla_preap_radar_readdr(to_fwd, 0x209); break;  // GTW_odo
    case 0x30A:  tesla_preap_radar_readdr(to_fwd, 0x2D9); break;  // BC_status
    case 0x405:  tesla_preap_radar_readdr(to_fwd, 0x2B9); break;  // VIP_405HS (not DAS_control)
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
    tesla_preap_radar_word_to_bytes(&pkt.data[0], lo);
    tesla_preap_radar_word_to_bytes(&pkt.data[4], hi);
    pkt.data[7] = tesla_preap_radar_byte_sum_checksum(&pkt);
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
      lo = (lo & 0x00C0FFFFU) | (0x0020U << 16);
      hi = (hi & 0x00FFFFF0U) | 0x00000004U;  // force DELPHI sensor ID
      int crc = tesla_preap_radar_compute_crc8(lo, hi, 7);
      hi = hi | ((uint32_t)crc << 24);
    }
    tesla_preap_radar_word_to_bytes(&pkt.data[0], lo);
    tesla_preap_radar_word_to_bytes(&pkt.data[4], hi);
    tesla_preap_radar_send(&pkt);
  }

  // Group C: ESP_115h (0x115) -> 0x129 + synthetic DI_espControl 0x1A9, bus 1 only, len 5 (NAP :270-284)
  if (addr == 0x115) {
    tesla_preap_radar_readdr(to_fwd, 0x129);
    uint32_t hi_src = TESLA_PREAP_RADAR_GET_BYTES_48(to_fwd);
    int counter = ((hi_src & 0xF0) >> 4) & 0x0F;
    uint32_t syn_lo = 0x000C0000U | ((uint32_t)counter << 28);
    int cksm = (0x38 + 0x0C + (counter << 4)) & 0xFF;
    CANPacket_t pkt;
    tesla_preap_radar_pkt_clear(&pkt);
    pkt.addr = 0x1A9;
    pkt.data_len_code = 5;
    tesla_preap_radar_word_to_bytes(&pkt.data[0], syn_lo);
    tesla_preap_radar_word_to_bytes(&pkt.data[4], (uint32_t)cksm);
    tesla_preap_radar_send(&pkt);
  }

  // Group C: DI_torque2 (0x118) -> 0x119 + synthetic ESP_wheelSpeeds 0x169, bus 1 only, len 8 (NAP :287-314)
  if (addr == 0x118) {
    tesla_preap_radar_readdr(to_fwd, 0x119);
    uint32_t lo = TESLA_PREAP_RADAR_GET_BYTES_04(to_fwd);
    int ws_counter = TESLA_PREAP_RADAR_GET_BYTES_48(to_fwd) & 0x0F;
    int raw_speed = (int)((0xFFF0000U & lo) >> 16);
    int speed;
    if (raw_speed == 0xFFF) {
      speed = 0x1FFF;
    } else {
      int mph_x100 = raw_speed * 5 - 2500;
      int kph_x100 = mph_x100 * 1609 / 1000;
      speed = (kph_x100 < 0) ? 0 : ((kph_x100 / 4) & 0x1FFF);
    }
    uint32_t speed_u = (uint32_t)speed;
    uint32_t ws_lo = speed_u | (speed_u << 13) | (speed_u << 26);
    uint32_t ws_hi = ((speed_u >> 6) | (speed_u << 7) | ((uint32_t)ws_counter << 20)) & 0x00FFFFFFU;
    int ws_cksm = 0x76;
    ws_cksm = (ws_cksm + (int)(ws_lo & 0xFF) + (int)((ws_lo >> 8) & 0xFF) + (int)((ws_lo >> 16) & 0xFF) + (int)((ws_lo >> 24) & 0xFF)) & 0xFF;
    ws_cksm = (ws_cksm + (int)(ws_hi & 0xFF) + (int)((ws_hi >> 8) & 0xFF) + (int)((ws_hi >> 16) & 0xFF)) & 0xFF;
    ws_hi = ws_hi | ((uint32_t)ws_cksm << 24);
    CANPacket_t pkt;
    tesla_preap_radar_pkt_clear(&pkt);
    pkt.addr = 0x169;
    pkt.data_len_code = 8;
    tesla_preap_radar_word_to_bytes(&pkt.data[0], ws_lo);
    tesla_preap_radar_word_to_bytes(&pkt.data[4], ws_hi);
    tesla_preap_radar_send(&pkt);
  }
}
