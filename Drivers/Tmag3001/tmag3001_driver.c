/** TMAG3001 A1 register driver. All I2C calls have a bounded 20 ms timeout. */
#include "tmag3001_driver.h"
#include <math.h>
#include <stddef.h>

#define TMAG3001_TIMEOUT_MS 20U

static int valid_device(const TMAG3001_Handle_t *dev)
{
    return dev != NULL && dev->hi2c != NULL &&
           dev->i2c_addr >= 0x34U && dev->i2c_addr <= 0x37U;
}

static HAL_StatusTypeDef read_multiple(TMAG3001_Handle_t *dev, uint8_t reg,
                                      uint8_t *data, uint16_t len)
{
    if (!valid_device(dev) || data == NULL || len == 0U) return HAL_ERROR;
    return HAL_I2C_Mem_Read(dev->hi2c, (uint16_t)(dev->i2c_addr << 1), reg,
                            I2C_MEMADD_SIZE_8BIT, data, len, TMAG3001_TIMEOUT_MS);
}

HAL_StatusTypeDef TMAG3001_ReadRegister(TMAG3001_Handle_t *dev, uint8_t reg, uint8_t *data)
{
    return read_multiple(dev, reg, data, 1U);
}

HAL_StatusTypeDef TMAG3001_WriteRegister(TMAG3001_Handle_t *dev, uint8_t reg, uint8_t data)
{
    if (!valid_device(dev)) return HAL_ERROR;
    /* Public raw writes can change configuration behind the acquisition cache. */
    if (reg <= TMAG3001_REG_I2C_ADDRESS) dev->config_valid = 0U;
    return HAL_I2C_Mem_Write(dev->hi2c, (uint16_t)(dev->i2c_addr << 1), reg,
                             I2C_MEMADD_SIZE_8BIT, &data, 1U, TMAG3001_TIMEOUT_MS);
}

HAL_StatusTypeDef TMAG3001_InitAtAddress(TMAG3001_Handle_t *dev,
                                      I2C_HandleTypeDef *hi2c, uint8_t addr)
{
    uint8_t lsb, msb, id;
    HAL_StatusTypeDef status;
    if (dev == NULL) return HAL_ERROR;
    *dev = (TMAG3001_Handle_t){0};
    dev->hi2c = hi2c;
    dev->i2c_addr = addr;
    dev->range = TMAG3001_RANGE_40mT;
    dev->mode = TMAG3001_MODE_STANDBY;
    dev->avg = TMAG3001_AVG_1X;
    if (!valid_device(dev)) return HAL_ERROR;
    status = TMAG3001_ReadRegister(dev, TMAG3001_REG_MANUF_ID_LSB, &lsb);
    if (status != HAL_OK) return status;
    status = TMAG3001_ReadRegister(dev, TMAG3001_REG_MANUF_ID_MSB, &msb);
    if (status != HAL_OK) return status;
    if (lsb != TMAG3001_MANUF_ID_LSB_VAL || msb != TMAG3001_MANUF_ID_MSB_VAL)
        return HAL_ERROR;
    status = TMAG3001_ReadDeviceID(dev, &id);
    if (status != HAL_OK) return status;
    /* VERSION[3:2] = 00 identifies the supported A1 sensitivity ranges. */
    return (id & 0x0cU) == 0U ? HAL_OK : HAL_ERROR;
}

HAL_StatusTypeDef TMAG3001_Init(TMAG3001_Handle_t *dev, I2C_HandleTypeDef *hi2c)
{
    return TMAG3001_InitAtAddress(dev, hi2c, TMAG3001_I2C_ADDR_7BIT);
}

static int valid_config(const TMAG3001_Config_t *c)
{
    return c != NULL &&
           (c->range == TMAG3001_RANGE_40mT || c->range == TMAG3001_RANGE_80mT) &&
           (unsigned)c->avg <= (unsigned)TMAG3001_AVG_32X &&
           (unsigned)c->mode <= (unsigned)TMAG3001_MODE_WAKEUP &&
           (unsigned)c->channels <= (unsigned)TMAG3001_CH_XYZ &&
           ((unsigned)c->channels & 0x0fU) == 0U;
}

static HAL_StatusTypeDef configure(TMAG3001_Handle_t *dev,
                                  const TMAG3001_Config_t *c, int acquisition)
{
    static const uint8_t regs[] = {0x00, 0x01, 0x02, 0x03, 0x08};
    uint8_t values[5], actual;
    HAL_StatusTypeDef status;
    if (dev != NULL) dev->config_valid = 0U;
    if (!valid_device(dev) || !valid_config(c)) return HAL_ERROR;
    /* Short circuit keeps legacy callers' uninitialized enable_int untouched. */
    if (acquisition && (c->mode != TMAG3001_MODE_STANDBY || c->enable_int > 1U))
        return HAL_ERROR;
    values[0] = (uint8_t)((unsigned)c->avg << 2);
    values[1] = (uint8_t)c->mode;
    values[2] = (uint8_t)c->channels;
    values[3] = (uint8_t)((acquisition ? 0x80U : 0U) |
                (c->range == TMAG3001_RANGE_80mT ? 3U : 0U));
    values[4] = acquisition && c->enable_int ? 0x86U : 0U;
    size_t count = acquisition ? 5U : 4U;
    for (size_t i = 0; i < count; ++i) {
        status = TMAG3001_WriteRegister(dev, regs[i], values[i]);
        if (status != HAL_OK) return status;
    }
    if (acquisition) {
        for (size_t i = 0; i < count; ++i) {
            status = TMAG3001_ReadRegister(dev, regs[i], &actual);
            if (status != HAL_OK) return status;
            if (actual != values[i]) return HAL_ERROR;
        }
    }
    dev->range = c->range;
    dev->mode = c->mode;
    dev->avg = c->avg;
    dev->device_config_1 = values[0];
    dev->config_valid = (uint8_t)acquisition;
    return HAL_OK;
}

HAL_StatusTypeDef TMAG3001_Configure(TMAG3001_Handle_t *dev, TMAG3001_Config_t *config)
{
    return configure(dev, config, 0);
}

HAL_StatusTypeDef TMAG3001_ConfigureForAcq(TMAG3001_Handle_t *dev,
                                        const TMAG3001_Config_t *config)
{
    return configure(dev, config, 1);
}

HAL_StatusTypeDef TMAG3001_TriggerConversion(TMAG3001_Handle_t *dev)
{
    if (!valid_device(dev) || !dev->config_valid) return HAL_ERROR;
    /* T is control-byte bit 7, not DEVICE_CONFIG_2 operating-mode data. */
    return TMAG3001_WriteRegister(dev, 0x80U | TMAG3001_REG_DEVICE_CONFIG_1,
                                 dev->device_config_1);
}

static int16_t signed_be(const uint8_t *bytes)
{
    uint16_t bits = (uint16_t)(((uint16_t)bytes[0] << 8) | bytes[1]);
    /* Avoid implementation-defined unsigned-to-signed overflow conversion. */
    return (int16_t)((int32_t)bits - (bits >= 0x8000U ? 65536 : 0));
}

static void magnetic(TMAG3001_Data_t *data, const uint8_t *bytes,
                     TMAG3001_MagneticRange range)
{
    data->x_raw = signed_be(bytes);
    data->y_raw = signed_be(bytes + 2);
    data->z_raw = signed_be(bytes + 4);
    data->x_mT = TMAG3001_CountsToMagnetic(data->x_raw, range);
    data->y_mT = TMAG3001_CountsToMagnetic(data->y_raw, range);
    data->z_mT = TMAG3001_CountsToMagnetic(data->z_raw, range);
}

HAL_StatusTypeDef TMAG3001_ReadSample(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data)
{
    uint8_t bytes[9];
    if (!valid_device(dev) || data == NULL ||
        (dev->range != TMAG3001_RANGE_40mT && dev->range != TMAG3001_RANGE_80mT))
        return HAL_ERROR;
    HAL_StatusTypeDef status = read_multiple(dev, TMAG3001_REG_T_RESULT_MSB, bytes, 9U);
    if (status != HAL_OK) return status;
    TMAG3001_Data_t sample = {0};
    magnetic(&sample, bytes + 2, dev->range);
    sample.temp_raw = signed_be(bytes);
    sample.temperature_C = TMAG3001_CountsToTemperature(sample.temp_raw);
    sample.conv_status = bytes[8];
    *data = sample;
    return HAL_OK;
}

HAL_StatusTypeDef TMAG3001_ReadAll(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data)
{
    return TMAG3001_ReadSample(dev, data);
}

HAL_StatusTypeDef TMAG3001_ReadMagData(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data)
{
    uint8_t bytes[6];
    if (!valid_device(dev) || data == NULL ||
        (dev->range != TMAG3001_RANGE_40mT && dev->range != TMAG3001_RANGE_80mT))
        return HAL_ERROR;
    HAL_StatusTypeDef status = read_multiple(dev, TMAG3001_REG_X_RESULT_MSB, bytes, 6U);
    if (status != HAL_OK) return status;
    magnetic(data, bytes, dev->range);
    return HAL_OK;
}

HAL_StatusTypeDef TMAG3001_ReadStatus(TMAG3001_Handle_t *dev, uint8_t *status)
{
    return TMAG3001_ReadRegister(dev, TMAG3001_REG_CONV_STATUS, status);
}

HAL_StatusTypeDef TMAG3001_ReadDeviceStatus(TMAG3001_Handle_t *dev, uint8_t *status)
{
    return TMAG3001_ReadRegister(dev, TMAG3001_REG_DEVICE_STATUS, status);
}

HAL_StatusTypeDef TMAG3001_ReadDeviceID(TMAG3001_Handle_t *dev, uint8_t *id)
{
    return TMAG3001_ReadRegister(dev, TMAG3001_REG_DEVICE_ID, id);
}

float TMAG3001_CountsToMagnetic(int16_t counts, TMAG3001_MagneticRange range)
{
    static const float sensitivity[] = {885.0f, 446.0f};
    if (range != TMAG3001_RANGE_40mT && range != TMAG3001_RANGE_80mT) return NAN;
    return (float)counts / sensitivity[(unsigned)range];
}

float TMAG3001_CountsToTemperature(int16_t counts)
{
    return ((float)counts - 17512.0f) / 58.2f + 25.0f;
}
