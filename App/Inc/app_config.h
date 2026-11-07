#ifndef APP_CONFIG_H
#define APP_CONFIG_H
#ifndef APP_USE_INT
#define APP_USE_INT 0
#endif
#if APP_USE_INT != 0 && APP_USE_INT != 1
#error "APP_USE_INT must be 0 or 1"
#endif
#ifndef APP_CONV_POLL_INTERVAL_MS
#define APP_CONV_POLL_INTERVAL_MS 1U
#endif
#ifndef APP_CONV_TIMEOUT_MS
#define APP_CONV_TIMEOUT_MS 5U
#endif
#if APP_CONV_POLL_INTERVAL_MS <= 0 || APP_CONV_TIMEOUT_MS <= 0 || APP_CONV_POLL_INTERVAL_MS > APP_CONV_TIMEOUT_MS
#error "Conversion poll interval and timeout must be positive; interval must not exceed timeout"
#endif
#ifndef APP_SAMPLE_RATE_HZ
#define APP_SAMPLE_RATE_HZ 100U
#endif
#if APP_SAMPLE_RATE_HZ <= 0 || APP_SAMPLE_RATE_HZ > 1000
#error "APP_SAMPLE_RATE_HZ must be in 1..1000 Hz"
#elif 1000 % APP_SAMPLE_RATE_HZ != 0
#error "APP_SAMPLE_RATE_HZ must divide 1000 ms exactly"
#endif
#ifndef APP_RANGE_CODE
#define APP_RANGE_CODE 0U
#endif
#if APP_RANGE_CODE != 0 && APP_RANGE_CODE != 1
#error "Only TMAG3001 A1 ranges 0 and 1 are supported"
#endif
#define APP_SAMPLE_PERIOD_MS (1000U / APP_SAMPLE_RATE_HZ)
#ifndef APP_I2C_FIRST_ADDRESS
#define APP_I2C_FIRST_ADDRESS 0x34U
#endif
#ifndef APP_I2C_LAST_ADDRESS
#define APP_I2C_LAST_ADDRESS 0x37U
#endif
#ifndef APP_I2C_TIMEOUT_MS
#define APP_I2C_TIMEOUT_MS 20U
#endif
#ifndef APP_INT_TIMEOUT_MS
#define APP_INT_TIMEOUT_MS 5U
#endif
#ifndef APP_HEARTBEAT_MS
#define APP_HEARTBEAT_MS 1000U
#endif
#ifndef APP_RETRY_MS
#define APP_RETRY_MS 1000U
#endif
#ifndef APP_UART_BAUD
#define APP_UART_BAUD 115200U
#endif
#ifndef APP_I2C_CLOCK_HZ
#define APP_I2C_CLOCK_HZ 100000U
#endif
#ifndef APP_TX_RING_SIZE
#define APP_TX_RING_SIZE 16U
#endif
#endif
