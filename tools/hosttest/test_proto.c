#include "test_harness.h"
#include "tmag_proto.h"

#include <limits.h>
#include <string.h>

static void check_frame(const uint8_t *actual, const uint8_t *expected)
{
    CHECK(memcmp(actual, expected, 12) == 0, "12-byte frame differs from golden");
}

static tmag_status_t base_status(void)
{
    const tmag_status_t status = {0x2C, 0, 885, 100, 0, 1, 0};
    return status;
}

static void test_goldens(void)
{
    static const uint8_t data[] = {
        0xAA, 0x55, 0x01, 0x05, 0xD8, 0x00, 0x2C, 0xFF, 0x1E, 0x44, 0x68, 0x3D
    };
    static const uint8_t status100[] = {
        0xAA, 0x56, 0x42, 0x12, 0x2C, 0x03, 0x75, 0x64, 0x00, 0x01, 0x00, 0x6F
    };
    static const uint8_t status500[] = {
        0xAA, 0x56, 0x42, 0x12, 0xAC, 0x03, 0x75, 0x32, 0x00, 0x01, 0x00, 0xB9
    };
    static const uint8_t status1000[] = {
        0xAA, 0x56, 0x42, 0x12, 0xAC, 0x03, 0x75, 0x64, 0x00, 0x01, 0x00, 0xEF
    };
    static const uint8_t error[] = {
        0xAA, 0xEE, 0x07, 0x01, 0x34, 0x0E, 0, 0, 0, 0, 0, 0x3C
    };
    const tmag_sample_t sample = {1496, 44, -226, 17512};
    uint8_t frame[12];
    tmag_status_t status = base_status();

    CHECK_EQ_U16(tmag_encode_data(frame, 1, &sample), 12);
    check_frame(frame, data);
    CHECK_EQ_U16(tmag_encode_status(frame, 0x42, &status), 12);
    check_frame(frame, status100);
    status.sample_rate_hz = 500;
    CHECK_EQ_U16(tmag_encode_status(frame, 0x42, &status), 12);
    check_frame(frame, status500);
    status.sample_rate_hz = 1000;
    CHECK_EQ_U16(tmag_encode_status(frame, 0x42, &status), 12);
    check_frame(frame, status1000);
    memset(frame, 0xA5, sizeof(frame));
    CHECK_EQ_U16(tmag_encode_error(frame, 7, TMAG_ERR_I2C_NACK, 0x34, 0x0E), 12);
    check_frame(frame, error);
}

static void test_rates_and_flags(void)
{
    static const struct { uint16_t hz; uint8_t encoded; uint8_t scaled; } valid[] = {
        {0, 0, 0}, {1, 1, 0}, {100, 100, 0}, {200, 200, 0}, {255, 255, 0},
        {260, 26, 0x80}, {500, 50, 0x80}, {1000, 100, 0x80}, {2550, 255, 0x80}
    };
    static const uint16_t invalid[] = {256, 259, 2551, 2560, 65535};
    uint8_t frame[12];
    uint8_t sentinel[12];
    tmag_status_t status = base_status();

    for (size_t i = 0; i < sizeof(valid) / sizeof(valid[0]); ++i) {
        for (unsigned hse = 0; hse <= 1; ++hse) {
            /* Supply stale range and rate bits; all other flags must survive. */
            status.flags = (uint8_t)(0xBF | (hse ? 0x40 : 0));
            status.range_code = 2;
            status.sample_rate_hz = valid[i].hz;
            CHECK_EQ_U16(tmag_encode_status(frame, 0xFF, &status), 12);
            CHECK_EQ_U8(frame[4], 0x3E | (hse ? 0x40 : 0) | valid[i].scaled);
            CHECK_EQ_U8(frame[7], valid[i].encoded);
            CHECK_EQ_U8(frame[11], tmag_crc8(frame + 2, 9));
        }
    }
    memset(sentinel, 0xA5, sizeof(sentinel));
    for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        memcpy(frame, sentinel, sizeof(frame));
        status.sample_rate_hz = invalid[i];
        CHECK_EQ_U16(tmag_encode_status(frame, 0, &status), 0);
        CHECK(memcmp(frame, sentinel, sizeof(frame)) == 0,
              "invalid rate %u changed output", (unsigned)invalid[i]);
    }
    /* A previously clear RATE_X10 must also be set from the logical rate. */
    status.flags = TMAG_FLAG_CLK_SRC_HSE;
    status.sample_rate_hz = 1000;
    CHECK_EQ_U16(tmag_encode_status(frame, 0, &status), 12);
    CHECK_EQ_U8(frame[4], 0xC2);
}

static void test_ranges_and_status_fields(void)
{
    static const uint16_t sensitivity[] = {885, 446, 273, 137};
    static const uint8_t invalid_range[] = {4, UINT8_MAX};
    uint8_t frame[12];
    tmag_status_t status = base_status();

    status.flags = 0x83;
    status.sensitivity = 0xABCD;
    status.conv_status = 0xA6;
    status.device_status = 0x15;
    for (uint8_t range = 0; range < 4; ++range) {
        CHECK_EQ_U16(tmag_sensitivity_for_range(range), sensitivity[range]);
        status.range_code = range;
        CHECK_EQ_U16(tmag_encode_status(frame, 0xFF, &status), 12);
        CHECK_EQ_U8(frame[2], 0xFF);
        CHECK_EQ_U8(frame[4], range);
        CHECK_EQ_U8(frame[5], 0xAB);
        CHECK_EQ_U8(frame[6], 0xCD);
        CHECK_EQ_U8(frame[9], 0xA6);
        CHECK_EQ_U8(frame[10], 0x15);
    }
    status.range_code = 0;
    status.err_count = UINT32_MAX;
    CHECK_EQ_U16(tmag_encode_status(frame, 0, &status), 12);
    CHECK_EQ_U8(frame[8], 0xFF);
    status.err_count = 256;
    CHECK_EQ_U16(tmag_encode_status(frame, 0, &status), 12);
    CHECK_EQ_U8(frame[8], 0);
    for (size_t i = 0; i < sizeof(invalid_range) / sizeof(invalid_range[0]); ++i) {
        uint8_t sentinel[12];
        memset(frame, 0xA5, sizeof(frame));
        memcpy(sentinel, frame, sizeof(frame));
        status.range_code = invalid_range[i];
        CHECK_EQ_U16(tmag_sensitivity_for_range(invalid_range[i]), 0);
        CHECK_EQ_U16(tmag_encode_status(frame, 0, &status), 0);
        CHECK(memcmp(frame, sentinel, sizeof(frame)) == 0, "invalid range changed output");
    }
}

static void test_signed_limits_and_checksum(void)
{
    const tmag_sample_t sample = {INT16_MIN, INT16_MAX, -1, 0};
    static const uint8_t expected[] = {
        0xAA, 0x55, 0xFF, 0x80, 0x00, 0x7F, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0xFF
    };
    static const uint8_t legacy[] = {0x01, 0x05, 0xD8, 0x00, 0x2C, 0xFF, 0x1E};
    uint8_t frame[12];
    CHECK_EQ_U16(tmag_encode_data(frame, 0xFF, &sample), 12);
    check_frame(frame, expected);
    CHECK_EQ_U8(tmag_crc8(legacy, sizeof(legacy)), 0x11);
    CHECK_EQ_U8(tmag_crc8(NULL, 0), 0);
    CHECK_EQ_U8(tmag_crc8(NULL, 9), 0);
}

static void test_null_inputs(void)
{
    const tmag_sample_t sample = {0, 0, 0, 0};
    tmag_status_t status = base_status();
    uint8_t frame[12];
    uint8_t sentinel[12];
    memset(frame, 0xA5, sizeof(frame));
    memcpy(sentinel, frame, sizeof(frame));
    CHECK_EQ_U16(tmag_encode_data(NULL, 0, &sample), 0);
    CHECK_EQ_U16(tmag_encode_data(frame, 0, NULL), 0);
    CHECK_EQ_U16(tmag_encode_status(NULL, 0, &status), 0);
    CHECK_EQ_U16(tmag_encode_status(frame, 0, NULL), 0);
    CHECK_EQ_U16(tmag_encode_error(NULL, 0, 0, 0, 0), 0);
    CHECK(memcmp(frame, sentinel, sizeof(frame)) == 0, "null input changed output");
}

int main(void)
{
    test_goldens();
    test_rates_and_flags();
    test_ranges_and_status_fields();
    test_signed_limits_and_checksum();
    test_null_inputs();
    TEST_REPORT();
}
