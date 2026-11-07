#ifndef TMAG_PROTO_H
#define TMAG_PROTO_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TMAG_PROTO_VERSION    0x12
#define TMAG_PROTO_FRAME_SIZE 12
#define TMAG_PROTO_SYNC_BYTE  0xAA

typedef enum {
    TMAG_FRAME_DATA = 0x55,
    TMAG_FRAME_STATUS = 0x56,
    TMAG_FRAME_ERROR = 0xEE
} tmag_frame_type_t;

typedef enum {
    TMAG_ERR_NONE = 0x00,
    TMAG_ERR_I2C_NACK = 0x01,
    TMAG_ERR_SENSOR_ID = 0x02,
    TMAG_ERR_CONFIG_FAIL = 0x03,
    TMAG_ERR_I2C_READ = 0x04,
    TMAG_ERR_I2C_TIMEOUT = 0x05,
    TMAG_ERR_NO_CONV = 0x06,
    TMAG_ERR_SENSOR_DIAG = 0x07,
    TMAG_ERR_OVERFLOW = 0x08, /* Reserved; no confirmed sensor overflow condition. */
    TMAG_ERR_TX_OVERFLOW = 0x09
} tmag_err_code_t;

#define TMAG_FLAG_RANGE_MASK   0x03
#define TMAG_FLAG_SENSOR_READY (1U << 2)
#define TMAG_FLAG_CFG_OK       (1U << 3)
#define TMAG_FLAG_TRIGGER_INT  (1U << 4)
#define TMAG_FLAG_INT_PATH_OK  (1U << 5)
#define TMAG_FLAG_CLK_SRC_HSE  (1U << 6)
#define TMAG_FLAG_RATE_X10     (1U << 7)

typedef struct {
    int16_t x_raw;
    int16_t y_raw;
    int16_t z_raw;
    int16_t temp_raw;
} tmag_sample_t;

typedef struct {
    uint8_t flags;
    uint8_t range_code;
    uint16_t sensitivity;
    uint16_t sample_rate_hz;
    uint32_t err_count;
    uint8_t conv_status;
    uint8_t device_status;
} tmag_status_t;

/* Compatibility name: XOR of all bytes, initial value 0; not polynomial CRC-8.
 * NULL is treated as empty input and returns 0. */
uint8_t tmag_crc8(const uint8_t *data, size_t length);

/* out must have room for TMAG_PROTO_FRAME_SIZE bytes. Return 12 on success,
 * or 0 on NULL inputs / invalid status range or rate, leaving out unchanged.
 * Rates 0..255 use Hz; larger rates must be multiples of 10 up to 2550 Hz.
 * Status range and rate bits are derived; all other caller flags survive. */
size_t tmag_encode_data(uint8_t *out, uint8_t seq, const tmag_sample_t *sample);
size_t tmag_encode_status(uint8_t *out, uint8_t seq, const tmag_status_t *status);
size_t tmag_encode_error(uint8_t *out, uint8_t seq, uint8_t err_code,
                         uint8_t i2c_addr, uint8_t reg_addr);

/* Invalid range codes return 0. */
uint16_t tmag_sensitivity_for_range(uint8_t range_code);

#ifdef __cplusplus
}
#endif

#endif
