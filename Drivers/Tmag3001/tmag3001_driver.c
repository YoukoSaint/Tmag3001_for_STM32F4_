/**
 * @file    tmag3001_driver.c
 * @brief   TMAG3001 3D Hall Effect Sensor Driver Implementation
 * @details Based on Texas Instruments TMAG3001 Datasheet (ZHCSR44C / SLYS053)
 * @date    2026-04-09
 */

#include "tmag3001_driver.h"
#include <math.h>

/* ======================== Private Constants ======================== */

// Sensitivity (LSB/mT) from datasheet Table 6-2
// Index 0 = RANGE_40mT, Index 1 = RANGE_80mT
static const float SENSITIVITY_TABLE[] = {
    885.0f,     // ±40mT (A1) — 885 LSB/mT
    446.0f      // ±80mT (A1) — 446 LSB/mT
};

// Temperature conversion constants (datasheet Section 6.3.8)
#define TADC_T0     17512.0f    // ADC count at 25°C
#define TADC_RES    58.2f       // LSB/°C
#define TSENS_T0    25.0f       // Reference temperature °C

/* ======================== Register Access ======================== */

HAL_StatusTypeDef TMAG3001_ReadRegister(TMAG3001_Handle_t *dev, uint8_t reg, uint8_t *data)
{
    return HAL_I2C_Mem_Read(dev->hi2c,
                            dev->i2c_addr << 1,
                            reg,
                            I2C_MEMADD_SIZE_8BIT,
                            data,
                            1,
                            100);
}

HAL_StatusTypeDef TMAG3001_WriteRegister(TMAG3001_Handle_t *dev, uint8_t reg, uint8_t data)
{
    return HAL_I2C_Mem_Write(dev->hi2c,
                             dev->i2c_addr << 1,
                             reg,
                             I2C_MEMADD_SIZE_8BIT,
                             &data,
                             1,
                             100);
}

static HAL_StatusTypeDef TMAG3001_ReadMultiple(TMAG3001_Handle_t *dev, uint8_t reg, uint8_t *data, uint16_t len)
{
    return HAL_I2C_Mem_Read(dev->hi2c,
                            dev->i2c_addr << 1,
                            reg,
                            I2C_MEMADD_SIZE_8BIT,
                            data,
                            len,
                            200);
}

/* ======================== Initialization ======================== */

HAL_StatusTypeDef TMAG3001_Init(TMAG3001_Handle_t *dev, I2C_HandleTypeDef *hi2c)
{
    HAL_StatusTypeDef status;
    uint8_t manuf_lsb, manuf_msb;

    dev->hi2c = hi2c;
    dev->i2c_addr = TMAG3001_I2C_ADDR_7BIT;
    dev->range = TMAG3001_RANGE_40mT;
    dev->mode = TMAG3001_MODE_STANDBY;
    dev->avg = TMAG3001_AVG_1X;

    // Verify manufacturer ID to confirm I2C communication
    status = TMAG3001_ReadRegister(dev, TMAG3001_REG_MANUF_ID_LSB, &manuf_lsb);
    if (status != HAL_OK) return status;

    status = TMAG3001_ReadRegister(dev, TMAG3001_REG_MANUF_ID_MSB, &manuf_msb);
    if (status != HAL_OK) return status;

    if (manuf_lsb != TMAG3001_MANUF_ID_LSB_VAL || manuf_msb != TMAG3001_MANUF_ID_MSB_VAL) {
        return HAL_ERROR;  // Not a TMAG3001
    }

    HAL_Delay(5);
    return HAL_OK;
}

/* ======================== Configuration ======================== */

HAL_StatusTypeDef TMAG3001_Configure(TMAG3001_Handle_t *dev, TMAG3001_Config_t *config)
{
    HAL_StatusTypeDef status;
    uint8_t reg_val;

    // Device_Config_1 (0x00): Conv_AVG[4:2], I2C_RD=0 (standard read)
    reg_val = (config->avg & 0x07) << 2;
    status = TMAG3001_WriteRegister(dev, TMAG3001_REG_DEVICE_CONFIG_1, reg_val);
    if (status != HAL_OK) return status;

    // Device_Config_2 (0x01): Operating_Mode[1:0]
    reg_val = config->mode & 0x03;
    status = TMAG3001_WriteRegister(dev, TMAG3001_REG_DEVICE_CONFIG_2, reg_val);
    if (status != HAL_OK) return status;

    // Sensor_Config_1 (0x02): MAG_CH_EN[7:4]
    reg_val = config->channels & 0xF0;
    status = TMAG3001_WriteRegister(dev, TMAG3001_REG_SENSOR_CONFIG_1, reg_val);
    if (status != HAL_OK) return status;

    // Sensor_Config_2 (0x03): X_Y_Range[1], Z_Range[0]
    reg_val = 0;
    if (config->range == TMAG3001_RANGE_80mT) {
        reg_val = 0x03;  // X_Y_Range=1, Z_Range=1
    }
    status = TMAG3001_WriteRegister(dev, TMAG3001_REG_SENSOR_CONFIG_2, reg_val);
    if (status != HAL_OK) return status;

    // Update handle
    dev->range = config->range;
    dev->mode = config->mode;
    dev->avg = config->avg;

    return HAL_OK;
}

/* ======================== Data Acquisition ======================== */

HAL_StatusTypeDef TMAG3001_ReadMagData(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data)
{
    HAL_StatusTypeDef status;
    uint8_t buffer[6];  // X_MSB, X_LSB, Y_MSB, Y_LSB, Z_MSB, Z_LSB
    int16_t x_raw, y_raw, z_raw;

    // Read X, Y, Z results (0x12 - 0x17, 6 consecutive bytes)
    status = TMAG3001_ReadMultiple(dev, TMAG3001_REG_X_RESULT_MSB, buffer, 6);
    if (status != HAL_OK) return status;

    x_raw = (int16_t)((buffer[0] << 8) | buffer[1]);
    y_raw = (int16_t)((buffer[2] << 8) | buffer[3]);
    z_raw = (int16_t)((buffer[4] << 8) | buffer[5]);

    data->x_mT = TMAG3001_CountsToMagnetic(x_raw, dev->range);
    data->y_mT = TMAG3001_CountsToMagnetic(y_raw, dev->range);
    data->z_mT = TMAG3001_CountsToMagnetic(z_raw, dev->range);

    return HAL_OK;
}

HAL_StatusTypeDef TMAG3001_ReadAll(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data)
{
    HAL_StatusTypeDef status;
    uint8_t cs = 0;

    /* In continuous mode the conversion finishes every ~322 us. We poll
     * CONV_STATUS but cap the wait at ~2 ms so a single slow cycle doesn't
     * stall the whole 100 ms main loop. */
    for (int i = 0; i < 5; i++) {
        status = TMAG3001_ReadRegister(dev, TMAG3001_REG_CONV_STATUS, &cs);
        if (status == HAL_OK && (cs & 0x01)) break;
    }
    data->conv_status = cs;

    /* Read magnetic data — multi-byte read (6 bytes from 0x12) is the
     * documented protocol and is faster than 6 single-byte reads. */
    uint8_t buf6[6];
    status = TMAG3001_ReadMultiple(dev, TMAG3001_REG_X_RESULT_MSB, buf6, 6);
    if (status != HAL_OK) return status;
    int16_t x_raw = (int16_t)((buf6[0] << 8) | buf6[1]);
    int16_t y_raw = (int16_t)((buf6[2] << 8) | buf6[3]);
    int16_t z_raw = (int16_t)((buf6[4] << 8) | buf6[5]);
    data->x_mT = TMAG3001_CountsToMagnetic(x_raw, dev->range);
    data->y_mT = TMAG3001_CountsToMagnetic(y_raw, dev->range);
    data->z_mT = TMAG3001_CountsToMagnetic(z_raw, dev->range);

    /* Temperature: 2 bytes from 0x10 */
    uint8_t buf2[2];
    status = TMAG3001_ReadMultiple(dev, TMAG3001_REG_T_RESULT_MSB, buf2, 2);
    if (status != HAL_OK) return status;
    int16_t temp_raw = (int16_t)((buf2[0] << 8) | buf2[1]);
    data->temperature_C = TMAG3001_CountsToTemperature(temp_raw);

    return HAL_OK;
}

HAL_StatusTypeDef TMAG3001_ReadStatus(TMAG3001_Handle_t *dev, uint8_t *status)
{
    return TMAG3001_ReadRegister(dev, TMAG3001_REG_CONV_STATUS, status);
}

HAL_StatusTypeDef TMAG3001_ReadDeviceID(TMAG3001_Handle_t *dev, uint8_t *id)
{
    return TMAG3001_ReadRegister(dev, TMAG3001_REG_DEVICE_ID, id);
}

/* ======================== Conversion Utilities ======================== */

float TMAG3001_CountsToMagnetic(int16_t counts, TMAG3001_MagneticRange range)
{
    float sensitivity = SENSITIVITY_TABLE[range];
    return (float)counts / sensitivity;
}

float TMAG3001_CountsToTemperature(int16_t counts)
{
    // T(°C) = (Temp_Result - TADC_T0) / TADC_RES + TSENS_T0
    return ((float)counts - TADC_T0) / TADC_RES + TSENS_T0;
}
