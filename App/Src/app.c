#include "app.h"
#include "app_config.h"
#include "tmag3001_driver.h"
#include "tmag_proto.h"
#include <string.h>

static UART_HandleTypeDef *tx_uart;
static I2C_HandleTypeDef *sensor_i2c;
static TMAG3001_Handle_t sensor;
static tmag_status_t health;
static uint8_t seq;
static volatile uint8_t armed, irq_pending;
static uint32_t armed_at, nominal_at, retry_at, heartbeat_at;
static uint8_t last_flags;
static uint8_t ring[APP_TX_RING_SIZE][TMAG_PROTO_FRAME_SIZE];
/* count includes the DMA-owned tail: it may not be reused before completion. */
static volatile unsigned head, tail, count;
static volatile uint8_t tx_active, tx_recover;
static uint8_t overflow_pending, tx_fault_seen;
static uint32_t tx_fault_at;

static uint32_t lock(void)
{
    uint32_t previous = __get_PRIMASK();
    __disable_irq();
    return previous;
}
static void unlock(uint32_t previous) { __set_PRIMASK(previous); }

static void add_errors(uint32_t amount)
{
    uint32_t key = lock();
    health.err_count += amount;
    unlock(key);
}

static void tx_fault(void)
{
    uint32_t now = HAL_GetTick();
    if (!tx_fault_seen || (uint32_t)(now - tx_fault_at) >= APP_HEARTBEAT_MS) {
        add_errors(1U);
        tx_fault_seen = 1U;
        tx_fault_at = now;
    }
}
/* Called with interrupts masked. HAL's DMA start does not wait for completion. */
static void pump_locked(void)
{
    if (!tx_active && !tx_recover && count && tx_uart != NULL) {
        tx_active = 1U;
        if (HAL_UART_Transmit_DMA(tx_uart, ring[tail], TMAG_PROTO_FRAME_SIZE) != HAL_OK) {
            tx_active = 0U;
            tx_fault();
        }
    }
}
static int enqueue(const uint8_t *frame)
{
    uint32_t key = lock();
    if (count == APP_TX_RING_SIZE) {
        add_errors(1U);
        overflow_pending = 1U;
        unlock(key);
        return 0;
    }
    memcpy(ring[head], frame, TMAG_PROTO_FRAME_SIZE);
    head = (head + 1U) % APP_TX_RING_SIZE;
    count++;
    pump_locked();
    unlock(key);
    return 1;
}
static void error_frame(uint8_t code, uint8_t reg)
{
    uint8_t frame[TMAG_PROTO_FRAME_SIZE];
    if (code != TMAG_ERR_NONE) add_errors(1U);
    if (tmag_encode_error(frame, seq++, code, sensor.i2c_addr, reg) == TMAG_PROTO_FRAME_SIZE)
        (void)enqueue(frame);
}
static void status_frame(void)
{
    uint8_t frame[TMAG_PROTO_FRAME_SIZE];
    if (tmag_encode_status(frame, seq++, &health) == TMAG_PROTO_FRAME_SIZE)
        (void)enqueue(frame);
    last_flags = health.flags;
    heartbeat_at = HAL_GetTick();
}
static uint8_t bus_error(HAL_StatusTypeDef result)
{
    return result == HAL_TIMEOUT ? TMAG_ERR_I2C_TIMEOUT : TMAG_ERR_I2C_READ;
}
static void disarm(void)
{
    uint32_t key = lock();
    armed = 0U;
    irq_pending = 0U;
    unlock(key);
}
static void degrade(HAL_StatusTypeDef result, uint8_t reg)
{
    disarm();
    health.flags &= (uint8_t)~(TMAG_FLAG_SENSOR_READY | TMAG_FLAG_CFG_OK | TMAG_FLAG_INT_PATH_OK);
    sensor.config_valid = 0U;
    retry_at = HAL_GetTick();
    error_frame(bus_error(result), reg);
}
/* InitAtAddress's HAL_ERROR can mean either ID mismatch or a failed bus read.
 * Only successful explicit ID reads provide evidence for SENSOR_ID. */
static uint8_t init_error(HAL_StatusTypeDef initial)
{
    uint8_t lo, hi, id;
    HAL_StatusTypeDef result;
    if (initial == HAL_TIMEOUT) return TMAG_ERR_I2C_TIMEOUT;
    result = TMAG3001_ReadRegister(&sensor, TMAG3001_REG_MANUF_ID_LSB, &lo);
    if (result != HAL_OK) return bus_error(result);
    result = TMAG3001_ReadRegister(&sensor, TMAG3001_REG_MANUF_ID_MSB, &hi);
    if (result != HAL_OK) return bus_error(result);
    result = TMAG3001_ReadDeviceID(&sensor, &id);
    if (result != HAL_OK) return bus_error(result);
    return lo != TMAG3001_MANUF_ID_LSB_VAL || hi != TMAG3001_MANUF_ID_MSB_VAL ||
           (id & 0x0cU) ? TMAG_ERR_SENSOR_ID : TMAG_ERR_I2C_READ;
}
static void connect_sensor(void)
{
    HAL_StatusTypeDef result = HAL_ERROR;
    uint8_t addr, scan_timed_out = 0U;
    const TMAG3001_Config_t config = {
        .range = APP_RANGE_CODE == 0U ? TMAG3001_RANGE_40mT : TMAG3001_RANGE_80mT,
        .mode = TMAG3001_MODE_STANDBY, .avg = TMAG3001_AVG_1X,
        .channels = TMAG3001_CH_XYZ, .enable_int = 1U
    };
    for (addr = APP_I2C_FIRST_ADDRESS; addr <= APP_I2C_LAST_ADDRESS; ++addr) {
        result = HAL_I2C_IsDeviceReady(sensor_i2c, (uint16_t)addr << 1, 1U, APP_I2C_TIMEOUT_MS);
        if (result == HAL_OK) break;
        if (result == HAL_TIMEOUT) scan_timed_out = 1U;
    }
    if (addr > APP_I2C_LAST_ADDRESS) {
        sensor.i2c_addr = 0U;
        error_frame(scan_timed_out ? TMAG_ERR_I2C_TIMEOUT : TMAG_ERR_I2C_NACK, 0U);
    } else {
        result = TMAG3001_InitAtAddress(&sensor, sensor_i2c, addr);
        if (result != HAL_OK) {
            error_frame(init_error(result), TMAG3001_REG_DEVICE_ID);
        } else {
            result = TMAG3001_ConfigureForAcq(&sensor, &config);
            if (result != HAL_OK || !sensor.config_valid) {
                error_frame(result == HAL_TIMEOUT ? TMAG_ERR_I2C_TIMEOUT : TMAG_ERR_CONFIG_FAIL,
                            TMAG3001_REG_DEVICE_CONFIG_1);
            } else {
                result = TMAG3001_ReadDeviceStatus(&sensor, &health.device_status);
                if (result != HAL_OK) {
                    error_frame(bus_error(result), TMAG3001_REG_DEVICE_STATUS);
                } else {
                    health.flags |= TMAG_FLAG_SENSOR_READY | TMAG_FLAG_CFG_OK;
                    nominal_at = HAL_GetTick();
                    error_frame(TMAG_ERR_NONE, 0U);
                }
            }
        }
    }
    retry_at = HAL_GetTick();
}
static void collect_sample(uint8_t from_irq)
{
    TMAG3001_Data_t sample;
    HAL_StatusTypeDef result = TMAG3001_ReadSample(&sensor, &sample);
    disarm();
    if (result != HAL_OK) {
        degrade(result, TMAG3001_REG_T_RESULT_MSB);
        return;
    }
    health.conv_status = sample.conv_status;
    result = TMAG3001_ReadDeviceStatus(&sensor, &health.device_status);
    if (result != HAL_OK) {
        degrade(result, TMAG3001_REG_DEVICE_STATUS);
        return;
    }
    if ((sample.conv_status & 2U) || (health.device_status & 0x06U)) {
        health.flags &= (uint8_t)~TMAG_FLAG_INT_PATH_OK;
        error_frame(TMAG_ERR_SENSOR_DIAG, TMAG3001_REG_DEVICE_STATUS);
    } else if (!(sample.conv_status & TMAG3001_CONV_STATUS_COMPLETE)) {
        health.flags &= (uint8_t)~TMAG_FLAG_INT_PATH_OK;
        error_frame(TMAG_ERR_NO_CONV, TMAG3001_REG_CONV_STATUS);
    } else {
        uint8_t frame[TMAG_PROTO_FRAME_SIZE];
        const tmag_sample_t raw = { sample.x_raw, sample.y_raw, sample.z_raw, sample.temp_raw };
        if (from_irq) health.flags |= TMAG_FLAG_INT_PATH_OK;
        else health.flags &= (uint8_t)~TMAG_FLAG_INT_PATH_OK;
        if (tmag_encode_data(frame, seq++, &raw) == TMAG_PROTO_FRAME_SIZE)
            (void)enqueue(frame);
    }
}
void App_Init(UART_HandleTypeDef *uart, I2C_HandleTypeDef *i2c)
{
    tx_uart = uart;
    sensor_i2c = i2c;
    memset(&sensor, 0, sizeof(sensor));
    memset(&health, 0, sizeof(health));
    head = tail = count = 0U;
    tx_active = tx_recover = armed = irq_pending = 0U;
    seq = overflow_pending = tx_fault_seen = 0U;
    health.range_code = APP_RANGE_CODE;
    health.sensitivity = tmag_sensitivity_for_range(APP_RANGE_CODE);
    health.sample_rate_hz = APP_SAMPLE_RATE_HZ;
    health.flags = TMAG_FLAG_TRIGGER_INT | (App_ClockFromHSE() ? TMAG_FLAG_CLK_SRC_HSE : 0U);
    connect_sensor();
    status_frame();
}
void App_OnSensorInt(void)
{
    if (armed) irq_pending = 1U;
}
void App_Process(void)
{
    uint32_t now = HAL_GetTick();
    if (tx_recover) {
        /* Keep the tail owned until HAL confirms TX/DMA have stopped. Completion
         * callbacks are ignored during recovery; the same queued frame retries. */
        if (HAL_UART_AbortTransmit(tx_uart) == HAL_OK) {
            uint32_t key = lock();
            tx_active = tx_recover = 0U;
            unlock(key);
        } else tx_fault();
    }
    {
        uint32_t key = lock();
        pump_locked();
        unlock(key);
    }
    if (overflow_pending && count < APP_TX_RING_SIZE) {
        overflow_pending = 0U;
        /* Drops already incremented err_count: don't count the notification again. */
        uint8_t frame[TMAG_PROTO_FRAME_SIZE];
        if (tmag_encode_error(frame, seq++, TMAG_ERR_TX_OVERFLOW, sensor.i2c_addr, 0U) == TMAG_PROTO_FRAME_SIZE)
            (void)enqueue(frame);
    }
    if (!(health.flags & TMAG_FLAG_SENSOR_READY)) {
        if ((uint32_t)(now - retry_at) >= APP_RETRY_MS) connect_sensor();
    } else {
        if (armed) {
            if (irq_pending) collect_sample(1U);
            else if ((uint32_t)(now - armed_at) >= APP_INT_TIMEOUT_MS) {
                HAL_StatusTypeDef result;
                health.flags &= (uint8_t)~TMAG_FLAG_INT_PATH_OK;
                result = TMAG3001_ReadStatus(&sensor, &health.conv_status);
                if (result != HAL_OK) degrade(result, TMAG3001_REG_CONV_STATUS);
                else if (health.conv_status & TMAG3001_CONV_STATUS_COMPLETE) collect_sample(0U);
                else {
                    disarm();
                    error_frame((health.conv_status & 2U) ? TMAG_ERR_SENSOR_DIAG : TMAG_ERR_NO_CONV,
                                TMAG3001_REG_CONV_STATUS);
                }
            }
        }
        now = HAL_GetTick();
        if ((health.flags & TMAG_FLAG_SENSOR_READY) && (uint32_t)(now - nominal_at) >= APP_SAMPLE_PERIOD_MS) {
            uint32_t slots = (uint32_t)(now - nominal_at) / APP_SAMPLE_PERIOD_MS;
            nominal_at += slots * APP_SAMPLE_PERIOD_MS;
            /* Missed nominal slots are observable through the cumulative counter.
             * Never burst conversions to catch up after a slow I2C transaction. */
            add_errors(slots - (armed ? 0U : 1U));
            if (!armed) {
                uint32_t key = lock();
                irq_pending = 0U;
                armed_at = HAL_GetTick();
                armed = 1U; /* EXTI may fire inside the trigger I2C write. */
                unlock(key);
                HAL_StatusTypeDef result = TMAG3001_TriggerConversion(&sensor);
                if (result != HAL_OK) degrade(result, TMAG3001_REG_DEVICE_CONFIG_1);
            }
        }
    }
    if (health.flags != last_flags || (uint32_t)(HAL_GetTick() - heartbeat_at) >= APP_HEARTBEAT_MS)
        status_frame();
}
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *uart)
{
    uint32_t key = lock();
    if (uart == tx_uart && tx_active && !tx_recover) {
        tail = (tail + 1U) % APP_TX_RING_SIZE;
        count--;
        tx_active = 0U;
        pump_locked();
    }
    unlock(key);
}
void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart)
{
    uint32_t key = lock();
    if (uart == tx_uart) {
        tx_fault();
        if (tx_active) tx_recover = 1U;
    }
    unlock(key);
}
