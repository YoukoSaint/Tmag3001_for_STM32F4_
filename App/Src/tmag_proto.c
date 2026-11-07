#include "tmag_proto.h"

uint8_t tmag_crc8(const uint8_t *data, size_t length)
{
    uint8_t checksum = 0;
    if (data == NULL) {
        return 0;
    }
    for (size_t i = 0; i < length; ++i) {
        checksum ^= data[i];
    }
    return checksum;
}

static void write_be16(uint8_t *out, uint16_t value)
{
    out[0] = (uint8_t)(value >> 8);
    out[1] = (uint8_t)value;
}

size_t tmag_encode_data(uint8_t *out, uint8_t seq, const tmag_sample_t *sample)
{
    if (out == NULL || sample == NULL) {
        return 0;
    }

    out[0] = TMAG_PROTO_SYNC_BYTE;
    out[1] = TMAG_FRAME_DATA;
    out[2] = seq;
    /* Unsigned conversion preserves the two's-complement wire bit pattern. */
    write_be16(out + 3, (uint16_t)sample->x_raw);
    write_be16(out + 5, (uint16_t)sample->y_raw);
    write_be16(out + 7, (uint16_t)sample->z_raw);
    write_be16(out + 9, (uint16_t)sample->temp_raw);
    out[11] = tmag_crc8(out + 2, 9);
    return TMAG_PROTO_FRAME_SIZE;
}

size_t tmag_encode_status(uint8_t *out, uint8_t seq, const tmag_status_t *status)
{
    uint8_t encoded_rate;
    uint8_t rate_flag = 0;
    uint8_t flags;

    if (out == NULL || status == NULL || status->range_code > 3) {
        return 0;
    }
    /* Validate the logical uint16 rate before narrowing or writing any output. */
    if (status->sample_rate_hz <= 255) {
        encoded_rate = (uint8_t)status->sample_rate_hz;
    } else if (status->sample_rate_hz <= 2550 && status->sample_rate_hz % 10 == 0) {
        encoded_rate = (uint8_t)(status->sample_rate_hz / 10);
        rate_flag = TMAG_FLAG_RATE_X10;
    } else {
        return 0;
    }
    flags = (uint8_t)((status->flags &
                      (uint8_t)~(TMAG_FLAG_RANGE_MASK | TMAG_FLAG_RATE_X10)) |
                     status->range_code | rate_flag);

    out[0] = TMAG_PROTO_SYNC_BYTE;
    out[1] = TMAG_FRAME_STATUS;
    out[2] = seq;
    out[3] = TMAG_PROTO_VERSION;
    out[4] = flags;
    write_be16(out + 5, status->sensitivity);
    out[7] = encoded_rate;
    out[8] = (uint8_t)status->err_count;
    out[9] = status->conv_status;
    out[10] = status->device_status;
    out[11] = tmag_crc8(out + 2, 9);
    return TMAG_PROTO_FRAME_SIZE;
}

size_t tmag_encode_error(uint8_t *out, uint8_t seq, uint8_t err_code,
                         uint8_t i2c_addr, uint8_t reg_addr)
{
    if (out == NULL) {
        return 0;
    }
    out[0] = TMAG_PROTO_SYNC_BYTE;
    out[1] = TMAG_FRAME_ERROR;
    out[2] = seq;
    out[3] = err_code;
    out[4] = i2c_addr;
    out[5] = reg_addr;
    for (size_t i = 6; i <= 10; ++i) {
        out[i] = 0;
    }
    out[11] = tmag_crc8(out + 2, 9);
    return TMAG_PROTO_FRAME_SIZE;
}

uint16_t tmag_sensitivity_for_range(uint8_t range_code)
{
    static const uint16_t sensitivity[] = {885, 446, 273, 137};
    if (range_code >= sizeof(sensitivity) / sizeof(sensitivity[0])) {
        return 0;
    }
    return sensitivity[range_code];
}
